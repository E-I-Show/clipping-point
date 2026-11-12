"""道具が、定義データのファイルを自分で読んで数える所と、結果の data の確かめ（tools/data_reference.py）のテスト。

一時の置き場（tmp_path）で回す。Pyxelは使わない。道具 run と web-smoke の probe の筋書きが、この関数を使う。
アプリを別プロセスで回すこと（重ねる口を読まない、保存の口へ名前空間を渡さない、で落ちること）は、道具 selftest-break が見る。
ここでは、数え方が、アプリの読み込み（cp_core.datadefs）と別の読み方でも、同じ数になること、
結果の data の確かめが、合っている場合に通り、合わない場合に、その名で落ちることを見る。
"""
import json

import pytest

import data_reference
from conftest import ROOT
from cp_app import data_files
from cp_core.datadefs import ONE_ENTRY, ONE_TABLE, Ident, TableDef

TABLES = {"cars": TableDef(ONE_TABLE, {"id": Ident()}), "tracks": TableDef(ONE_ENTRY, {"id": Ident()})}
GOOD = {"tables": {"cars": 1, "tracks": 1}, "warnings": 0, "pack": None, "namespace": "main"}
PACKED = {"tables": {"cars": 2, "tracks": 2}, "warnings": 0, "pack": "extreme", "namespace": "pack_extreme"}


def write(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value), encoding="utf-8")


def places(tmp_path) -> tuple:
    """一時の置き場（車2台、コース2本）と、試験用データ（車1台を差し替え、1台を足す。コース1本を差し替え、1本を足す）。"""
    data, pack = tmp_path / "data", tmp_path / "testpacks" / "extreme"
    write(data / "cars.json", {"_notes": "x", "cars": [{"id": "kazane"}, {"id": "second"}]})
    write(data / "tracks" / "test_loop.json", {"id": "test_loop"})
    write(data / "tracks" / "other_loop.json", {"id": "other_loop"})
    write(pack / "cars.json", {"cars": [{"id": "kazane"}, {"id": "wide"}]})
    write(pack / "tracks" / "test_loop.json", {"id": "test_loop"})
    write(pack / "tracks" / "wide_loop.json", {"id": "wide_loop"})
    return data, pack


def failed(checks) -> list:
    return [name for name, ok, _ in checks if not ok]


def data_failed(seen, want_tables=None, want_pack=None) -> list:
    """結果の data が seen のときに、落ちる確かめの名。"""
    want_tables = {"cars": 1, "tracks": 1} if want_tables is None else want_tables
    return failed(data_reference.data_checks({"data": seen}, want_tables, want_pack))


# --- 道具が自分で数える ---
def test_data_reference_counts_the_entries_of_both_file_shapes(tmp_path):
    data, pack = places(tmp_path)
    assert data_reference.count_entries(data, None, TABLES) == {"cars": 2, "tracks": 2}
    # 試験用データを重ねると、差し替えは増えず、新しい名だけ増える。
    assert data_reference.count_entries(data, pack, TABLES) == {"cars": 3, "tracks": 3}
    assert data_reference.count_entries(str(data), str(pack), TABLES) == {"cars": 3, "tracks": 3}


def test_data_reference_counts_only_the_files_a_table_reads(tmp_path):
    data, _ = places(tmp_path)
    write(data / "notes.txt", "x")
    write(data / "tracks" / "readme.md", "x")
    write(data / "tracks" / "deep" / "x.json", {"id": "x"})  # 深い階は、数えない
    assert data_reference.count_entries(data, None, TABLES) == {"cars": 2, "tracks": 2}
    # 無いファイルは、0件。
    assert data_reference.count_entries(tmp_path / "no_such_data", None, TABLES) == {"cars": 0, "tracks": 0}


@pytest.mark.parametrize("content", [b"{", b"[1]", b'{"cars": 5}', b'{"cars": [5]}', b'{"cars": [{"name": "X"}]}', b'{"car": []}', b"\xff\xfe"])
def test_data_reference_file_it_cannot_count_is_a_value_error_and_no_count(tmp_path, content):
    # JSONでない、形が違う、id が無い、UTF-8でない。どれも、数えられない（0件として数えない）。
    data, _ = places(tmp_path)
    (data / "cars.json").write_bytes(content)
    with pytest.raises(ValueError):
        data_reference.count_entries(data, None, TABLES)
    tables, why = data_reference.expected_tables(None, data, tmp_path / "testpacks")
    assert tables is None and "cars.json" in why
    # 数えられなかったら、表ごとの件数の確かめは、合格にしない（アプリの申告が、どんな値でも）。
    assert failed(data_reference.data_checks({"data": GOOD}, None, None, "（数えられなかった）")) == ["data_tables"]


def test_data_reference_real_counts_agree_with_the_loader_of_the_app():
    # 道具の数え方（標準のJSONの読みと、ファイルの一覧）と、アプリの読み込み（読み込み検査と重ね方）が、実物で同じ数になる。
    tables, why = data_reference.expected_tables()
    assert why == "" and tables == data_files.load({}, None).counts() == {"cars": 1, "tracks": 1, "assists": 1}
    for name in data_reference.pack_names():
        tables, why = data_reference.expected_tables(name)
        assert why == "" and tables == data_files.load({data_files.PACK_ENV: name}, None).counts(), name
    assert data_reference.expected_tables("extreme")[0] == {"cars": 2, "tracks": 2, "assists": 1}  # 重ねなかった表（操作補正）は、そのまま
    assert data_reference.DATA_DIR == ROOT / "clipping_point" / "data" and data_reference.PACKS_ROOT == ROOT / "testpacks"
    assert "extreme" in data_reference.pack_names() and data_reference.pack_names(ROOT / "no_such_packs") == []


# --- 結果の data の確かめ ---
def test_data_reference_good_result_passes_every_check():
    checks = data_reference.data_checks({"data": GOOD}, {"cars": 1, "tracks": 1}, None)
    assert [name for name, _, _ in checks] == list(data_reference.DATA_CHECKS) == ["data_tables", "data_warnings", "data_pack", "data_namespace"]
    assert failed(checks) == [] and all(type(message) is str and message for _, _, message in checks)
    assert failed(data_reference.data_checks({"data": PACKED}, {"cars": 2, "tracks": 2}, "extreme")) == []


@pytest.mark.parametrize(
    "seen, names",
    [
        ({**GOOD, "tables": {"cars": 2, "tracks": 1}}, ["data_tables"]),
        ({**GOOD, "tables": {"cars": 1}}, ["data_tables"]),  # 表が1つ足りない
        ({**GOOD, "tables": {"cars": 1, "tracks": 1, "sounds": 0}}, ["data_tables"]),
        ({**GOOD, "tables": {"cars": 0, "tracks": 0}}, ["data_tables"]),  # 定義データを読まずに、空の定義で起動した
        ({**GOOD, "tables": {"cars": True, "tracks": True}}, ["data_tables"]),  # 真偽の値は、件数でない
        ({**GOOD, "tables": {"cars": 1.0, "tracks": 1.0}}, ["data_tables"]),
        ({**GOOD, "tables": None}, ["data_tables"]),
        ({**GOOD, "tables": [1, 1]}, ["data_tables"]),
        ({**GOOD, "warnings": 1}, ["data_warnings"]),
        ({**GOOD, "warnings": None}, ["data_warnings"]),
        ({**GOOD, "warnings": False}, ["data_warnings"]),  # 真偽の値は、件数でない
        ({**GOOD, "warnings": []}, ["data_warnings"]),
        ({**GOOD, "pack": "extreme"}, ["data_pack"]),  # 渡していないのに、重ねている
        ({**GOOD, "pack": ""}, ["data_pack"]),
        ({**GOOD, "pack": False}, ["data_pack"]),
        ({**GOOD, "namespace": "pack_extreme"}, ["data_namespace"]),
        ({**GOOD, "namespace": "selfcheck"}, ["data_namespace"]),
        ({**GOOD, "namespace": None}, ["data_namespace"]),
        ({key: value for key, value in GOOD.items() if key != "pack"}, ["data_pack"]),  # 項目が無い（null と取り違えない）
        ({}, list(data_reference.DATA_CHECKS)),
        (None, list(data_reference.DATA_CHECKS)),
        ("data", list(data_reference.DATA_CHECKS)),
    ],
)
def test_data_reference_each_deviation_of_a_plain_result_fails_under_its_own_name(seen, names):
    assert data_failed(seen) == names


def test_data_reference_result_without_the_data_item_fails_every_check():
    # 古い形の結果（data が無い）。何も見ずに通さない。
    assert failed(data_reference.data_checks({"ticks": 120}, {"cars": 1, "tracks": 1}, None)) == list(data_reference.DATA_CHECKS)


@pytest.mark.parametrize(
    "seen, names",
    [
        # 重ねる口を読まない。重ねていない結果が返る。
        (GOOD, ["data_tables", "data_pack", "data_namespace"]),
        # 重ねたのに、アプリが、設定を読む保存の口へ、名前空間を渡さない。名前空間だけが main になる。
        ({**PACKED, "namespace": "main"}, ["data_namespace"]),
        ({**PACKED, "namespace": "pack_other"}, ["data_namespace"]),
        ({**PACKED, "pack": "other"}, ["data_pack"]),
        ({**PACKED, "pack": None}, ["data_pack"]),
        ({**PACKED, "tables": {"cars": 1, "tracks": 1}}, ["data_tables"]),
        # 重ねた結果の警告も、0件を求める（道具 check の data の節も、重ねた組の警告を問題に数える。tests/test_check_tool.py）。
        ({**PACKED, "warnings": 2}, ["data_warnings"]),
    ],
)
def test_data_reference_each_deviation_of_a_pack_result_fails_under_its_own_name(seen, names):
    assert data_failed(seen, {"cars": 2, "tracks": 2}, "extreme") == names


# --- 試験用データが、重ねられる形で置いてあるか（道具 run の --pack が、アプリを回す前に見る） ---
def test_data_reference_pack_that_can_be_overlaid_has_no_reason(tmp_path):
    _, pack = places(tmp_path)
    assert data_reference.pack_or_reason("extreme", pack.parent) == ""
    assert data_reference.pack_or_reason("extreme") == ""  # 実物


def test_data_reference_missing_empty_or_badly_named_pack_has_a_reason(tmp_path):
    _, pack = places(tmp_path)
    root = pack.parent
    (root / "empty" / "tracks").mkdir(parents=True)  # 置き場はあるが、ファイルが1つも無い
    for name in ("nosuch", "empty", "Bad Name", "", "../extreme"):
        assert data_reference.pack_or_reason(name, root), name
    assert data_reference.pack_or_reason("extreme", tmp_path / "no_such_root")
    assert data_reference.pack_or_reason("no_such_pack_zz")  # 実物の根に、無い名
