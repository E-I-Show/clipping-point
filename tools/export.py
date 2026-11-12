"""配布物を作る。clipping_point/ → dist/clipping_point.pyxapp → dist/clipping_point.html。

  python3 tools/export.py

dist/ を作業場所にして `pyxel package` と `pyxel app2html` を回し、できた中身と大きさを検査する。
終了コード：0＝合格、1＝検査で問題あり、2＝ビルドの道具が回り切れない。
検査：要るファイル（main.py）がある。入ってはいけないもの（テスト、文書、道具、試験用データ、__pycache__）が無い。
知らない種類のファイルが無い。HTML内のデータが .pyxapp と一致する。HTMLが上限（tools/budgets.json）の内。
定義データ：出荷物の中の data/ の下のファイルの一覧が、ソースの木の clipping_point/data/ と同じ（data_files）。
表の定義（cp_core/datadefs.py の TABLES）が求めるファイルが、出荷物にある（無ければ missing）。1ファイル1表の表は <表>.json、
1ファイル1項目の表は <表>/ の直下に .json が1つ以上。一覧が同じ、だけだと、ソースから消したときに、両方に無くて通ってしまう。
"""
import base64
import fnmatch
import re
import sys
import zipfile

import data_reference
from _common import APP, DIST, FAIL, INCOMPLETE, OK, finish, load_budgets, run, show_tail

NAME = APP.name  # pyxel package は、対象ディレクトリの名前を .pyxapp の名前にする
MUST_HAVE = (f"{NAME}/main.py",)  # 入口。直下に無いとパッケージをimportできない
DATA_DIR = data_reference.DATA_DIR.name  # 出荷物の中の、定義データの置き場の名（data）
# 入ってはいけないディレクトリ名（パスのどこかにあれば不合格）。
FORBIDDEN_DIRS = frozenset({"tests", "testpacks", "docs", "tools", "spikes", "out", "dist", "__pycache__"})
# 入ってはいけないファイル名の形（テスト、文書、キャッシュ）。
FORBIDDEN_FILES = ("test_*.py", "*_test.py", "conftest.py", "*.md", "*.pyc", "count_floor.txt")
# 出荷物に入ってよいファイルの種類。初期版は画像や3Dのモデルのファイルを持たない。足すときはここに足す。
SHIP_SUFFIXES = (".py", ".json")
STARTUP_MARKER = ".pyxapp_startup_script"  # pyxel package が自分で足す、入口の名前を書いたファイル
KINDS = ("missing", "outside", "forbidden", "unknown_type", "data_files", "payload", "size")  # 検査の種類。最後の1行の failed= に出る語


def inspect_names(names: list) -> list:
    """アーカイブの中のパスの一覧を調べ、問題の一覧を返す。"""
    problems = []
    for must in MUST_HAVE:
        if must not in names:
            problems.append(("missing", f"要るファイルが入っていない：{must}"))
    for name in names:
        parts = name.split("/")
        base = parts[-1]
        if parts[0] != NAME:
            problems.append(("outside", f"{NAME}/ の外のパスが入っている：{name}"))
        elif len(parts) == 2 and base == STARTUP_MARKER:
            continue
        elif FORBIDDEN_DIRS & set(parts[1:-1]) or any(fnmatch.fnmatch(base, pattern) for pattern in FORBIDDEN_FILES):
            problems.append(("forbidden", f"入ってはいけないものが入っている：{name}"))
        elif not base.endswith(SHIP_SUFFIXES):
            problems.append(("unknown_type", f"知らない種類のファイルが入っている：{name}"))
    return problems


def source_data_files(app_dir=APP) -> list:
    """ソースの木の、定義データの置き場の下の全部のファイル。出荷物の根からの相対の名（data/cars.json の形）。"""
    base = app_dir / DATA_DIR
    return sorted(path.relative_to(app_dir).as_posix() for path in base.rglob("*") if path.is_file() and "__pycache__" not in path.parts)


def inspect_data(names: list, source_files: list, tables: dict) -> list:
    """アーカイブの中の定義データを調べ、問題の一覧を返す。

    names は、アーカイブの中のパスの一覧。source_files は、ソースの木の定義データ（source_data_files() の形）。
    tables は、表の定義（cp_core/datadefs.py の TABLES）。表の名とファイルの形だけを引く。
    """
    prefix, base = f"{NAME}/", f"{DATA_DIR}/"
    shipped = sorted(name[len(prefix):] for name in names if name.startswith(prefix + base))
    problems = []
    for name in sorted(set(source_files) - set(shipped)):
        problems.append(("data_files", f"ソースの定義データが、出荷物に入っていない：{name}"))
    for name in sorted(set(shipped) - set(source_files)):
        problems.append(("data_files", f"出荷物に、ソースの木に無い定義データが入っている：{name}"))
    suffix = data_reference.datadefs.SUFFIX
    for table_name, table in tables.items():
        if table.layout == data_reference.datadefs.ONE_TABLE:
            wanted = f"{base}{table_name}{suffix}"
            if wanted not in shipped:
                problems.append(("missing", f"表の定義が求める定義データが入っていない：{wanted}"))
        else:
            folder = f"{base}{table_name}/"
            if not any(name.startswith(folder) and name.endswith(suffix) and "/" not in name[len(folder):] for name in shipped):
                problems.append(("missing", f"表の定義が求める定義データが、1つも入っていない：{folder}*{suffix}"))
    return problems


def payload_matches(html_text: str, pyxapp_bytes: bytes) -> bool:
    """HTMLに埋め込まれたデータが、.pyxapp のバイト列と同じか。データが見つからなければ False。"""
    payload = re.search(r'base64: "([A-Za-z0-9+/=]+)"', html_text)
    return bool(payload) and base64.b64decode(payload.group(1)) == pyxapp_bytes


def main() -> int:
    budgets = load_budgets()
    DIST.mkdir(parents=True, exist_ok=True)
    pyxapp, html = DIST / f"{NAME}.pyxapp", DIST / f"{NAME}.html"
    pyxapp.unlink(missing_ok=True)
    html.unlink(missing_ok=True)
    steps = (
        ("package", [sys.executable, "-m", "pyxel", "package", APP, APP / "main.py"]),
        ("app2html", [sys.executable, "-m", "pyxel", "app2html", pyxapp.name]),
    )
    for step, cmd in steps:
        code, out, err = run(cmd, cwd=DIST)  # どちらも、作業ディレクトリに出力を書く
        if code != 0:
            show_tail(out, err)
            return finish("export", INCOMPLETE, f"reason=pyxel_{step}_failed exit={code}")
    if not pyxapp.is_file() or not html.is_file():
        return finish("export", INCOMPLETE, "reason=output_missing")

    with zipfile.ZipFile(pyxapp) as zf:
        names = zf.namelist()
    problems = inspect_names(names)
    problems += inspect_data(names, source_data_files(), data_reference.datadefs.TABLES)
    if not payload_matches(html.read_text(encoding="utf-8"), pyxapp.read_bytes()):
        problems.append(("payload", "HTML内のデータが .pyxapp と一致しない"))
    html_bytes, pyxapp_bytes = html.stat().st_size, pyxapp.stat().st_size
    limit = budgets["html_max_bytes"]
    if html_bytes > limit:
        problems.append(("size", f"HTMLが {html_bytes} バイト（上限 {limit} バイト）"))
    for _, message in problems:
        print(f"  export: {message}")
    summary = (
        f"files={len(names)} pyxapp_bytes={pyxapp_bytes} html_bytes={html_bytes} html_max_bytes={limit} "
        f"checks={len(KINDS)} problems={len(problems)}"
    )
    if problems:
        summary += " failed=" + ",".join(sorted({kind for kind, _ in problems}))
    return finish("export", FAIL if problems else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
