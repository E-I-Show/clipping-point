"""定義データの参照。道具が、定義データのファイルを自分で読んで、表ごとの項目の数を数える。結果の data の確かめも、ここに置く。

tools/run.py と tools/web_smoke.py、tools/export.py が使う。同じ計算を2か所に書かない。pyxel は読み込まない。
数えるのは、道具の側の、別の読み方（標準のJSONの読みと、ファイルの一覧）。アプリの読み込み（cp_core/datadefs.py の
load_game_data）は通さない。アプリの申告（結果の data の tables）だけに頼らないため。表の定義からは、表の名とファイルの形だけを引く。
  1ファイル1表    <表>.json の、表の並びの中の id の数
  1ファイル1項目  <表>/ の直下の .json の数
試験用データを重ねたときは、同じ名（id、ファイルの名）を1つに数える（差し替えは増えず、新しい名は増える）。
"""
import json
import sys
from pathlib import Path

from _common import APP, ROOT

if str(APP) not in sys.path:
    sys.path.append(str(APP))  # cp_core と cp_app を読む。後ろに足す（標準ライブラリの名前を隠さないように）

from cp_app import data_files  # noqa: E402 - pyxel を読み込まないモジュール
from cp_core import datadefs, storage  # noqa: E402

DATA_DIR = APP / "data"  # 出荷する定義データの置き場
PACKS_ROOT = ROOT / datadefs.PACKS_DIR  # 試験用データの根
DATA_CHECKS = ("data_tables", "data_warnings", "data_pack", "data_namespace")  # 結果の data の確かめの名


def pack_names(packs_root=PACKS_ROOT) -> list:
    """試験用データの根の直下の、ディレクトリの名（整列した順）。根が無ければ、空。"""
    root = Path(packs_root)
    return sorted(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def count_entries(data_dir=DATA_DIR, pack_dir=None, tables=None) -> dict:
    """道具が、定義データのファイルを自分で読んで数えた、表ごとの項目の数。読めないファイルがあれば ValueError。

    pack_dir は、重ねる試験用データの置き場。無ければ None。tables は、表の定義（既定は、実物の表の定義）。
    """
    tables = datadefs.TABLES if tables is None else tables
    counts = {}
    for name, table in tables.items():
        keys = []
        for directory in (data_dir, pack_dir):
            if directory is None:
                continue
            if table.layout == datadefs.ONE_TABLE:
                path = Path(directory) / f"{name}{datadefs.SUFFIX}"
                if not path.is_file():
                    continue
                try:
                    keys += [str(entry[datadefs.ID_KEY]) for entry in json.loads(path.read_text(encoding="utf-8"))[name]]
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
            else:
                keys += [path.stem for path in sorted((Path(directory) / name).glob(f"*{datadefs.SUFFIX}")) if path.is_file()]
        counts[name] = len(set(keys))
    return counts


def expected_tables(pack=None, data_dir=DATA_DIR, packs_root=PACKS_ROOT) -> tuple:
    """道具が数えた、表ごとの項目の数。返すのは (数の辞書, 数えられなかった理由)。数えられなければ、辞書は None。"""
    try:
        return count_entries(data_dir, None if pack is None else Path(packs_root) / pack), ""
    except ValueError as exc:
        return None, str(exc)


def data_checks(result: dict, want_tables, want_pack, why: str = "") -> list:
    """結果の data の確かめ。返すのは [(名前, 合っているか, 合わないときの文)]。

    want_tables は、道具が数えた、表ごとの項目の数（数えられなかったら None。合格にしない）。
    want_pack は、渡した試験用データの名（渡していなければ None）。保存の名前空間は、渡していれば pack_<名>、いなければ main。
    """
    seen = result.get("data") if isinstance(result.get("data"), dict) else {}
    tables, warnings = seen.get("tables"), seen.get("warnings")
    counted = isinstance(tables, dict) and all(type(count) is int for count in tables.values())
    want_namespace = storage.DEFAULT_NAMESPACE if want_pack is None else datadefs.PACK_NAMESPACE_PREFIX + want_pack
    return [
        (
            "data_tables",
            want_tables is not None and counted and tables == want_tables,
            f"表ごとの件数が {tables!r}（道具が、定義データのファイルを自分で読んで数えた件数は {want_tables!r}）{why}",
        ),
        ("data_warnings", type(warnings) is int and warnings == 0, f"定義データの警告が {warnings!r} 件（0件のはず）"),
        (
            "data_pack",
            "pack" in seen and seen["pack"] == want_pack and type(seen["pack"]) is type(want_pack),
            f"重ねた試験用データの名が {seen.get('pack')!r}（{want_pack!r} のはず）",
        ),
        (
            "data_namespace",
            seen.get("namespace") == want_namespace,
            f"設定を読んだ保存の口の名前空間が {seen.get('namespace')!r}（{want_namespace!r} のはず。"
            f"試験用データを重ねている間は {datadefs.PACK_NAMESPACE_PREFIX}<名>）",
        ),
    ]


def pack_or_reason(name: str, packs_root=PACKS_ROOT) -> str:
    """試験用データ（名）が、重ねられる形で置いてあるか。返すのは、使えない理由（使えれば、空の文字列）。

    見るのは、アプリと同じ所（cp_app/data_files.py の read_pack。名の字、置き場、ファイルが1つ以上）。
    """
    try:
        data_files.read_pack(name, packs_root)
    except ValueError as exc:
        return str(exc)
    return ""
