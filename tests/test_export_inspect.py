"""配布物の検査（tools/export.py の inspect_names、inspect_data、payload_matches）のテスト。Pyxelは回さない。

ビルドを通した検査は `python3 tools/export.py` が見る。ここでは、ビルドでは作りにくい形
（外のパス、入口が無い、データが1バイト違う、定義データが出荷物に無い）を、検査の関数に直に与える。
"""
import base64

import pytest

import export
from cp_core.datadefs import ONE_ENTRY, ONE_TABLE, TABLES, Ident, TableDef

GOOD = ["clipping_point/main.py", "clipping_point/cp_core/sim.py", "clipping_point/.pyxapp_startup_script"]
# 定義データ。ソースの木の一覧（出荷物の根からの相対の名）と、それが入った出荷物。表の定義は、2つの形を1つずつ。
DATA_TABLES = {"cars": TableDef(ONE_TABLE, {"id": Ident()}), "tracks": TableDef(ONE_ENTRY, {"id": Ident()})}
SOURCE_DATA = ["data/cars.json", "data/tracks/test_loop.json"]
GOOD_WITH_DATA = GOOD + [f"clipping_point/{name}" for name in SOURCE_DATA]


def kinds(names) -> list:
    return sorted({kind for kind, _ in export.inspect_names(names)})


def html_with(data: bytes) -> str:
    return '<script>launchPyxel({ command: "play", base64: "' + base64.b64encode(data).decode("ascii") + '" });</script>'


def test_export_clean_archive_has_no_problems():
    assert export.inspect_names(GOOD) == []


def test_export_missing_entry_script_is_reported():
    assert kinds(["clipping_point/cp_core/sim.py"]) == ["missing"]


def test_export_path_outside_the_app_directory_is_reported():
    assert kinds(GOOD + ["other/readme.py"]) == ["outside"]


@pytest.mark.parametrize("name", [
    "clipping_point/tests/test_zz.py",
    "clipping_point/cp_core/test_sim.py",
    "clipping_point/cp_core/conftest.py",
    "clipping_point/README.md",
    "clipping_point/tools/check.py",
    "clipping_point/cp_core/__pycache__/sim.cpython-313.pyc",
])
def test_export_forbidden_files_are_reported(name):
    assert kinds(GOOD + [name]) == ["forbidden"]


def test_export_unknown_file_type_is_reported():
    assert kinds(GOOD + ["clipping_point/data/notes.txt"]) == ["unknown_type"]


def test_export_every_reported_kind_is_listed():
    seen = kinds(["other/x.py", "clipping_point/README.md", "clipping_point/data/notes.txt"])
    assert seen == ["forbidden", "missing", "outside", "unknown_type"]
    assert set(seen) <= set(export.KINDS)
    assert {"payload", "size"} <= set(export.KINDS)


# --- 定義データ ---
def data_kinds(names, source=None, tables=None) -> list:
    return sorted(kind for kind, _ in export.inspect_data(names, SOURCE_DATA if source is None else source, DATA_TABLES if tables is None else tables))


def test_export_archive_with_the_same_data_files_as_the_source_has_no_problems():
    assert export.inspect_data(GOOD_WITH_DATA, SOURCE_DATA, DATA_TABLES) == []
    assert export.inspect_names(GOOD_WITH_DATA) == []
    # 1ファイル1項目の表は、1つ以上あればよい（2つ目も、ソースと同じなら通る）。
    more = ["data/tracks/other_loop.json"]
    assert export.inspect_data(GOOD_WITH_DATA + [f"clipping_point/{more[0]}"], SOURCE_DATA + more, DATA_TABLES) == []


def test_export_data_file_of_the_source_that_is_not_shipped_is_reported():
    without_cars = [name for name in GOOD_WITH_DATA if name != "clipping_point/data/cars.json"]
    assert data_kinds(without_cars) == ["data_files", "missing"]  # 一覧が違い、表の定義が求めるファイルも無い
    extra_source = SOURCE_DATA + ["data/tracks/other_loop.json"]
    assert data_kinds(GOOD_WITH_DATA, extra_source) == ["data_files"]  # ソースにあるコースが、出荷物に入っていない


def test_export_shipped_data_file_that_is_not_in_the_source_is_reported():
    assert data_kinds(GOOD_WITH_DATA + ["clipping_point/data/tracks/stale_loop.json"]) == ["data_files"]
    assert data_kinds(GOOD_WITH_DATA + ["clipping_point/data/old.json"]) == ["data_files"]


def test_export_data_file_deleted_from_the_source_is_missing_even_though_the_lists_agree():
    # ソースから消すと、出荷物にも入らない。一覧は同じ（両方に無い）なので、表の定義が求めるファイルで落とす。
    without_cars = [name for name in GOOD_WITH_DATA if name != "clipping_point/data/cars.json"]
    assert data_kinds(without_cars, ["data/tracks/test_loop.json"]) == ["missing"]
    without_tracks = [name for name in GOOD_WITH_DATA if not name.startswith("clipping_point/data/tracks/")]
    assert data_kinds(without_tracks, ["data/cars.json"]) == ["missing"]
    assert data_kinds(GOOD, []) == ["missing", "missing"]  # 定義データが、丸ごと無い
    messages = [message for _, message in export.inspect_data(GOOD, [], DATA_TABLES)]
    assert "data/cars.json" in messages[0] and "data/tracks/" in messages[1]


def test_export_entry_file_in_a_deeper_directory_or_of_another_type_does_not_count_for_its_table():
    # 1ファイル1項目の表のファイルは、<表>/ の直下の .json だけ。深い階と、ほかの種類は、数えない。
    for name in ("data/tracks/deep/test_loop.json", "data/tracks/readme.txt", "data/tracks.json", "data/trackside/a.json"):
        names = GOOD + ["clipping_point/data/cars.json", f"clipping_point/{name}"]
        assert data_kinds(names, ["data/cars.json", name]) == ["missing"], name
    # 1ファイル1表の表のファイルは、<表>.json だけ。
    names = GOOD + ["clipping_point/data/cars/kazane.json", "clipping_point/data/tracks/test_loop.json"]
    assert data_kinds(names, ["data/cars/kazane.json", "data/tracks/test_loop.json"]) == ["missing"]


def test_export_data_outside_the_data_directory_is_not_compared():
    # data/ の外のファイル（コード）は、定義データの一覧に入れない。
    assert export.inspect_data(GOOD_WITH_DATA + ["clipping_point/cp_core/datadefs.py", "clipping_point/database/x.json"], SOURCE_DATA, DATA_TABLES) == []


def test_export_real_source_data_files_satisfy_the_real_table_definitions():
    # いまのリポジトリ。ソースの木の定義データが、そのまま出荷物に入れば、実物の表の定義が求めるファイルがそろう。
    source = export.source_data_files()
    assert source == sorted(source) and "data/cars.json" in source and all(name.startswith("data/") for name in source)
    assert export.inspect_data(GOOD + [f"clipping_point/{name}" for name in source], source, TABLES) == []
    assert export.DATA_DIR == "data" and "data_files" in export.KINDS and "missing" in export.KINDS
    assert "testpacks" in export.FORBIDDEN_DIRS  # 試験用データは、出荷物に入らない
    assert kinds(GOOD + ["clipping_point/testpacks/extreme/cars.json"]) == ["forbidden"]


def test_export_payload_matches_the_same_bytes():
    assert export.payload_matches(html_with(b"PK\x03\x04abc"), b"PK\x03\x04abc")


def test_export_payload_one_byte_off_is_rejected():
    assert not export.payload_matches(html_with(b"PK\x03\x04abc"), b"PK\x03\x04abd")


def test_export_payload_not_found_is_rejected():
    assert not export.payload_matches("<html></html>", b"abc")
