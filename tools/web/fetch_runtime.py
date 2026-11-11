"""ランタイムの写しを .cache/pyxel_web/ に取得し、tools/web/SHA256SUMS と照合して、組み立てる。

  python3 tools/web/fetch_runtime.py           足りない分だけ取得し、照合し、組み立てる
  python3 tools/web/fetch_runtime.py --check   照合だけ。取得も組み立てもしない

取得元は次の2つだけ。kitao.dev（本番の配信元）と cdn.jsdelivr.net には触れない。
  raw.githubusercontent.com/kitao/pyxel/v3.0.1/wasm/        Pyxelの側（pyxel.js、wheel、画像）
  registry.npmjs.org/pyodide/-/pyodide-314.0.7.tgz          Pyodideの芯
置き場（どれもgitの外）：
  .cache/pyxel_web/vendor/   取得したままのファイル。SHA256SUMS の左のパスと同じ並び
  .cache/pyxel_web/mirror/   ブラウザ版が要求するURLと同じ並びに組み立てたもの（kitao.dev/pyxel/…）。
                             ブラウザの実行役（tools/web/webrun.js）が、ランタイムへの要求をここへ差し替える
終了コード：0＝そろっていて照合が通った、1＝照合が合わない、
2＝取得できない・書き込めない（--check では、足りない）。どの場合も、最後の1行を出す。
既にそろっていて照合が通れば、取得し直さない（ネットワークに触れない）。
置き場と取得の関数は main() の引数で替えられる。テストが、一時の置き場と偽の取得で、ネットワークなしに通すため。
"""
import argparse
import hashlib
import http.client
import io
import os
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zlib
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    # tools/_common.py を読む。後ろに足す（tools/ の test.py などが、標準ライブラリの名前を隠さないように）。
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from _common import FAIL, INCOMPLETE, OK, ROOT, TOOLS, finish  # noqa: E402

PYXEL_VERSION = "3.0.1"
PYODIDE_VERSION = "314.0.7"
WEB_PYTHON = "3.14"  # Pyodide 314 が載せているPythonの版の頭。tools/web_smoke.py が照らす
SUMS = TOOLS / "web" / "SHA256SUMS"
CACHE = ROOT / ".cache" / "pyxel_web"
VENDOR = CACHE / "vendor"
MIRROR = CACHE / "mirror"
PYXEL_DIR = "pyxel_wasm_orig/"  # SHA256SUMS の中の、Pyxelの側のファイルの頭
PYODIDE_DIR = "pyodide_npm/package/"  # 同じく、Pyodideのtgzから取り出すファイルの頭
PYODIDE_TGZ = f"pyodide_npm/pyodide-{PYODIDE_VERSION}.tgz"
PYXEL_URL = f"https://raw.githubusercontent.com/kitao/pyxel/v{PYXEL_VERSION}/wasm/"
PYODIDE_URL = f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE_VERSION}.tgz"
MIRROR_HOST = "kitao.dev"  # ブラウザ版のHTMLが、ランタイムを要求する先
MIRROR_PYXEL = f"{MIRROR_HOST}/pyxel/{PYXEL_VERSION}/"
MIRROR_PYODIDE = f"{MIRROR_HOST}/pyxel/pyodide/v{PYODIDE_VERSION}/"
FETCH_TIMEOUT_S = 180


class FetchError(Exception):
    """取得できなかった（ネットワーク、取得元の応答、tgzの中身）。"""


def read_sums(path: Path = SUMS) -> dict:
    """照合用の一覧を読む。返すのは {vendor/ からの相対パス: SHA-256}。1行も読めなければ ValueError。"""
    sums = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        if len(digest) != 64 or not rel or rel.startswith(("/", "..")) or "/../" in rel:
            raise ValueError(f"{path}: 読めない行：{line!r}")
        sums[rel] = digest
    if not sums:
        raise ValueError(f"{path}: 1行も無い")
    return sums


def mirror_rel(rel: str):
    """vendor/ の中のパスを、mirror/ の中のパスに直す。組み立てに使わないファイル（tgz）は None。"""
    if rel.startswith(PYXEL_DIR):
        return MIRROR_PYXEL + rel[len(PYXEL_DIR):]
    if rel.startswith(PYODIDE_DIR):
        return MIRROR_PYODIDE + rel[len(PYODIDE_DIR):]
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_files(base: Path, wanted: dict) -> tuple:
    """base の下を {相対パス: SHA-256} と照らす。返すのは (無いファイルの一覧, 合わないファイルの一覧)。"""
    missing, mismatched = [], []
    for rel, digest in wanted.items():
        path = Path(base) / rel
        if not path.is_file():
            missing.append(rel)
        elif sha256_of(path) != digest:
            mismatched.append(rel)
    return missing, mismatched


def mirror_wanted(sums: dict) -> dict:
    """組み立てたランタイムの写し（mirror/）にあるはずのファイル。{mirror/ からの相対パス: SHA-256}。"""
    return {mirror_rel(rel): digest for rel, digest in sums.items() if mirror_rel(rel)}


def check_mirror(sums: dict, mirror: Path = MIRROR) -> tuple:
    """組み立てたランタイムの写し（mirror/）を照らす。tools/web_smoke.py が、開く前に毎回呼ぶ。"""
    return check_files(mirror, mirror_wanted(sums))


def download(url: str) -> bytes:
    """URLの中身を取得する。取得できなければ FetchError。"""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as response:  # noqa: S310 - 取得元は上の2つの定数だけ
            return response.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        # HTTPException は OSError の子ではない。途中で接続が切れると、read() が IncompleteRead（HTTPException の子）を出す。
        raise FetchError(f"{url}: {type(exc).__name__}: {exc}") from exc


def store(path: Path, data: bytes) -> None:
    """一時ファイルに書いてから差し替える。途中で止まっても、半端なファイルを残さない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def unpack_members(tgz_bytes: bytes, members: list) -> dict:
    """Pyodideのtgzから、members のファイルを取り出す。返すのは {vendor/ からの相対パス: バイト列}。読めなければ FetchError。"""
    found = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tgz_bytes), mode="r:gz") as tar:
            for rel in members:
                # 名前を決め打ちで読む。tgzの中のパスをそのまま展開しない。
                member = tar.extractfile("package/" + rel[len(PYODIDE_DIR):])
                if member is None:
                    raise FetchError(f"{PYODIDE_TGZ}: {rel} がファイルでない")
                found[rel] = member.read()
    except (tarfile.TarError, KeyError, OSError, EOFError, zlib.error) as exc:
        # 途中で切れたtgzは、tarfile が包まない EOFError や zlib.error を出す。
        raise FetchError(f"{PYODIDE_TGZ}: {type(exc).__name__}: {exc}") from exc
    return found


def fetch_vendor(sums: dict, redo: list, vendor: Path = VENDOR, downloader=download) -> int:
    """redo に挙がったファイルを取得し直す。返すのは、取得したファイルの数。取得できなければ FetchError。"""
    vendor = Path(vendor)
    fetched = 0
    for rel in redo:
        if rel.startswith(PYXEL_DIR):
            store(vendor / rel, downloader(PYXEL_URL + rel[len(PYXEL_DIR):]))
            fetched += 1
    members = [rel for rel in redo if rel.startswith(PYODIDE_DIR)]
    tgz = vendor / PYODIDE_TGZ
    if PYODIDE_TGZ in redo or (members and not tgz.is_file()):
        store(tgz, downloader(PYODIDE_URL))
        fetched += 1
        members = [rel for rel in sums if rel.startswith(PYODIDE_DIR)]  # tgzを取り直したら、中身も取り出し直す
    if members:
        for rel, data in unpack_members(tgz.read_bytes(), members).items():
            store(vendor / rel, data)
    return fetched


def build_mirror(sums: dict, vendor: Path = VENDOR, mirror: Path = MIRROR) -> None:
    """照合の通った vendor/ から、mirror/ を作り直す。"""
    vendor, mirror = Path(vendor), Path(mirror)
    shutil.rmtree(mirror, ignore_errors=True)
    for rel in sums:
        target = mirror_rel(rel)
        if target:
            (mirror / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(vendor / rel, mirror / target)


def report(kind: str, names: list) -> None:
    for name in names:
        print(f"  fetch_runtime: {kind}：{name}")


def main(argv=None, sums_path: Path = SUMS, vendor: Path = VENDOR, mirror: Path = MIRROR, downloader=download) -> int:
    ap = argparse.ArgumentParser(description="ランタイムの写しを取得し、照合し、組み立てる")
    ap.add_argument("--check", action="store_true", help="照合だけ。取得も組み立てもしない")
    args = ap.parse_args(argv)
    try:
        sums = read_sums(sums_path)
    except (OSError, ValueError) as exc:
        print(f"  fetch_runtime: {exc}")
        return finish("fetch_runtime", INCOMPLETE, "files=0 reason=no_sums")
    head = f"files={len(sums)} mirror_files={len(mirror_wanted(sums))}"

    fetched = 0
    try:
        where = "vendor"
        missing, mismatched = check_files(vendor, sums)
        if (missing or mismatched) and not args.check:
            fetched = fetch_vendor(sums, missing + mismatched, vendor, downloader)
            missing, mismatched = check_files(vendor, sums)
        if not missing and not mismatched:
            where = "mirror"
            missing, mismatched = check_mirror(sums, mirror)
            if (missing or mismatched) and not args.check:
                build_mirror(sums, vendor, mirror)
                missing, mismatched = check_mirror(sums, mirror)
        size = sum(path.stat().st_size for base in (vendor, mirror) for path in Path(base).rglob("*") if path.is_file())
    except FetchError as exc:
        print(f"  fetch_runtime: 取得できない：{exc}")
        return finish("fetch_runtime", INCOMPLETE, f"{head} reason=fetch_failed")
    except OSError as exc:
        print(f"  fetch_runtime: 置き場を読み書きできない：{type(exc).__name__}: {exc}")
        return finish("fetch_runtime", INCOMPLETE, f"{head} reason=io_error")
    report(f"{where}/ に無い", missing)
    report(f"{where}/ のハッシュ値が一覧と合わない", mismatched)
    if mismatched:
        return finish("fetch_runtime", FAIL, f"{head} fetched={fetched} mismatched={len(mismatched)} missing={len(missing)} reason=checksum_mismatch")
    if missing:
        return finish("fetch_runtime", INCOMPLETE, f"{head} fetched={fetched} missing={len(missing)} reason=missing")
    return finish("fetch_runtime", OK, f"{head} fetched={fetched} cache_bytes={size} mismatched=0 missing=0")


if __name__ == "__main__":
    sys.exit(main())
