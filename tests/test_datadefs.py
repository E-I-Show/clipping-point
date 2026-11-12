"""定義データの読み込み検査と、試験用データの重ね方（cp_core.datadefs）のテスト。pyxel は読み込まない。

読み込み検査は、ファイルに触れない（受けるのは「相対の名 → 文」の辞書）。ファイルを読むのは、実物の定義データを
辞書にする所（real_sources）だけ。実物の表の定義は、参照、並び、入れ子の項目を、まだ持たない。それらは、作り物の表の定義
（FAKE_TABLES）で確かめる。
壊した場合は、どれも DataError になること（ほかの例外にならない）と、問題の行が、狙ったファイルと場所を指すことを見る。
表を足す、項目を足すときは、ここの BROKEN に、その表とその鍵の、壊した場合を足す（足さないと、末尾の節の見張りのテストが落ちる）。
見張りは、入れ子の項目、並びの中の項目、省ける項目の中まで開いて、鍵の道（engine.idle_rpm など）の全部に、壊した場合を求める。
壊した場合の札（どの鍵を壊したか）は、並ぶはずの行の場所と照らす（書いた人の申告のままにしない）。
ファイルを読む所は tests/test_data_files.py、道具 check の data の節は tests/test_check_tool.py。
"""
import json
import re

import pytest

from conftest import ROOT
from cp_core import datadefs, profile, storage
from cp_core.datadefs import (
    ONE_ENTRY,
    ONE_TABLE,
    TABLES,
    Bool,
    DataError,
    Enum,
    GameData,
    Ident,
    Int,
    Label,
    ListOf,
    Num,
    Obj,
    Opt,
    Ref,
    TableDef,
    load_game_data,
)

DATA = ROOT / "clipping_point" / "data"
CARS, LOOP = "cars.json", "tracks/test_loop.json"  # 実物の定義データのファイル


def real_sources() -> dict:
    """実物の定義データ。「相対の名 → 文」の辞書。"""
    return {path.relative_to(DATA).as_posix(): path.read_text(encoding="utf-8") for path in sorted(DATA.rglob("*")) if path.is_file()}


def edited(name: str, change, sources=None) -> dict:
    """定義データのファイル1つを、JSONとして読んで、change で書き換えたもの。元の辞書は変えない。"""
    sources = dict(real_sources() if sources is None else sources)
    doc = json.loads(sources[name])
    change(doc)
    sources[name] = json.dumps(doc)
    return sources


def with_text(name: str, text, sources=None) -> dict:
    """定義データのファイル1つを、文のまま置き換えたもの（足すこともできる）。"""
    return {**(real_sources() if sources is None else sources), name: text}


def problems_of(sources: dict, pack=None, tables=TABLES) -> list:
    """読み込み検査が並べた問題の行。DataError のほかの例外は、そのまま外へ出る（テストが落ちる）。"""
    with pytest.raises(DataError) as info:
        load_game_data(sources, pack, tables)
    return list(info.value.problems)


# --- 実物の定義データ ---
def test_datadefs_shipped_data_loads_with_no_warnings():
    data = load_game_data(real_sources())
    assert type(data) is GameData
    assert data.warnings == ()  # 出荷するデータは、警告0件
    assert data.counts() == {"cars": 1, "tracks": 1}
    assert data.ids("cars") == ("kazane",) and data.ids("tracks") == ("test_loop",)
    assert data.entry("cars", "kazane") == {"id": "kazane", "name": "KAZANE", "data_version": 1}
    assert data.entry("tracks", "test_loop") == {"id": "test_loop", "name": "TEST LOOP", "data_version": 1}
    assert data.pack is None and data.save_namespace == "main" == storage.DEFAULT_NAMESPACE


def test_datadefs_shipped_files_carry_their_notes_and_the_notes_are_not_handed_out():
    # 根拠の薄い値は、同じファイルの頭の _notes に「仮の値：<根拠>。<合わせる時>」と書く。注は、使う側へ渡らない。
    for name, text in real_sources().items():
        notes = json.loads(text)["_notes"]
        assert notes and all(note.startswith("仮の値：") for note in notes.values()), name
    data = load_game_data(real_sources())
    for table in TABLES:
        for ident in data.ids(table):
            assert not [key for key in data.entry(table, ident) if key.startswith("_")]


def test_datadefs_real_table_definitions_are_the_two_minimal_tables():
    assert list(TABLES) == ["cars", "tracks"]
    assert TABLES["cars"].layout == ONE_TABLE and TABLES["tracks"].layout == ONE_ENTRY
    for table in TABLES.values():
        assert list(table.fields) == ["id", "name", "data_version"]
        assert type(table.fields["id"]) is Ident and type(table.fields["name"]) is Label
        assert table.fields["name"].max_len == datadefs.NAME_MAX == 14  # 車名もコース名も、14字まで
        assert (table.fields["data_version"].low, table.fields["data_version"].high) == (1, None)  # データの版は、1以上の整数


# --- 実物の定義データを、1か所ずつ壊す。{名前: (表, 札, 壊したファイルの辞書, 並ぶはずの問題の行)} ---
# 札は、壊した鍵の道（頭の階の鍵は name、入れ子の中の鍵は engine.idle_rpm、並びの中の項目の鍵は engine.curve.rpm）。
# どの鍵でもない所を壊した件（知らない鍵、空の表）は None。札は、並ぶはずの行の場所と照らされる（下の見張り）。
def car(**values):
    return edited(CARS, lambda doc: doc["cars"][0].update(values))


def loop(**values):
    return edited(LOOP, lambda doc: doc.update(values))


BROKEN = {
    "cars unknown key": ("cars", None, car(nmae="KAZANE"), ["cars.json:cars[0].nmae: unknown key"]),
    "cars missing key": ("cars", "name", edited(CARS, lambda doc: doc["cars"][0].pop("name")), ["cars.json:cars[0].name: missing"]),
    "cars bool where int": ("cars", "data_version", car(data_version=True), ["cars.json:cars[0].data_version: expected an integer, got bool"]),
    "cars string where int": ("cars", "data_version", car(data_version="1"), ["cars.json:cars[0].data_version: expected an integer, got str"]),
    "cars float where int": ("cars", "data_version", car(data_version=1.0), ["cars.json:cars[0].data_version: expected an integer, got float"]),
    "cars out of range": ("cars", "data_version", car(data_version=0), ["cars.json:cars[0].data_version: 0 is outside 1.."]),
    "cars non-ascii label": ("cars", "name", car(name="カザネ"), ["cars.json:cars[0].name: 'カザネ' has characters outside printable ASCII"]),
    "cars label too long": ("cars", "name", car(name="K" * 15), [f"cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)"]),
    "cars empty label": ("cars", "name", car(name=""), ["cars.json:cars[0].name: expected a non-empty text, got ''"]),
    "cars bad id": ("cars", "id", car(id="Kazane RS"), ["cars.json:cars[0].id: 'Kazane RS' is not an id (lowercase ASCII, digits, _)"]),
    "cars duplicate id": (
        "cars", "id", edited(CARS, lambda doc: doc["cars"].append(dict(doc["cars"][0]))), ["cars.json:cars[1].id: duplicate id 'kazane'"],
    ),
    "cars empty table": ("cars", None, edited(CARS, lambda doc: doc["cars"].clear()), ["cars.json:cars: no entries"]),
    "tracks unknown key": ("tracks", None, loop(lenght_m=1800), ["tracks/test_loop.json:lenght_m: unknown key"]),
    "tracks missing key": (
        "tracks", "data_version", edited(LOOP, lambda doc: doc.pop("data_version")), ["tracks/test_loop.json:data_version: missing"],
    ),
    "tracks bool where int": ("tracks", "data_version", loop(data_version=False), ["tracks/test_loop.json:data_version: expected an integer, got bool"]),
    "tracks out of range": ("tracks", "data_version", loop(data_version=-3), ["tracks/test_loop.json:data_version: -3 is outside 1.."]),
    "tracks non-ascii label": ("tracks", "name", loop(name="テスト"), ["tracks/test_loop.json:name: 'テスト' has characters outside printable ASCII"]),
    "tracks label too long": ("tracks", "name", loop(name="TEST LOOP LONG!"), ["tracks/test_loop.json:name: 'TEST LOOP LONG!' is 15 characters (at most 14)"]),
    "tracks file name differs from id": (
        "tracks", "id", loop(id="other_loop"), ["tracks/test_loop.json:id: 'other_loop' does not match the file name 'test_loop'"],
    ),
    "tracks bad id": (
        "tracks", "id", {CARS: real_sources()[CARS], "tracks/Test Loop.json": json.dumps({"id": "Test Loop", "name": "TEST LOOP", "data_version": 1})},
        ["tracks/Test Loop.json:id: 'Test Loop' is not an id (lowercase ASCII, digits, _)"],
    ),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_datadefs_broken_shipped_data_is_rejected_with_the_file_and_the_place(case):
    _, _, sources, want = BROKEN[case]
    assert problems_of(sources) == want


def test_datadefs_the_longest_name_and_the_first_data_version_pass():
    data = load_game_data(car(name="K" * 14, data_version=1))
    assert data.entry("cars", "kazane")["name"] == "K" * 14
    assert load_game_data(car(name="A b-1!", data_version=10 ** 12)).entry("cars", "kazane")["data_version"] == 10 ** 12


def test_datadefs_three_planted_problems_are_all_listed():
    # 最初の1件で止めず、全部を並べる。ファイルをまたいでも、同じ。
    sources = edited(CARS, lambda doc: doc["cars"][0].update(nmae="X", name="K" * 15))
    sources = edited(LOOP, lambda doc: doc.update(data_version=0), sources)
    assert problems_of(sources) == [
        "cars.json:cars[0].nmae: unknown key",
        f"cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)",
        "tracks/test_loop.json:data_version: 0 is outside 1..",
    ]


def test_datadefs_error_text_has_the_count_and_every_line():
    with pytest.raises(DataError) as info:
        load_game_data(edited(CARS, lambda doc: doc["cars"][0].update(nmae="X", data_version=0)))
    assert isinstance(info.value, ValueError) and type(info.value.problems) is tuple
    assert str(info.value) == "2 data problem(s):\n  cars.json:cars[0].nmae: unknown key\n  cars.json:cars[0].data_version: 0 is outside 1.."


# --- JSONの読み。重複した鍵、NaN、Infinity、読めない文、読めなかったファイル ---
@pytest.mark.parametrize(
    "name, text, want",
    [
        (CARS, '{"cars": [{"id": "kazane", "name": "A", "name": "KAZANE", "data_version": 1}]}', "cars.json: duplicate key 'name'"),
        (CARS, '{"cars": [], "cars": [{"id": "kazane", "name": "KAZANE", "data_version": 1}]}', "cars.json: duplicate key 'cars'"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "data_version": NaN}', "tracks/test_loop.json: NaN is not accepted (not a JSON number)"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "data_version": Infinity}', "tracks/test_loop.json: Infinity is not accepted (not a JSON number)"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "_note": -Infinity, "data_version": 1}', "tracks/test_loop.json: -Infinity is not accepted (not a JSON number)"),
    ],
)
def test_datadefs_duplicate_keys_and_nan_are_problems_of_the_file(name, text, want):
    # 標準の読み方は、重複した鍵を後勝ちで黙って通し、NaN も通す。注の中の NaN も、JSONの文としては受けない。
    assert problems_of(with_text(name, text)) == [want]


SECOND_CAR_BROKEN = '{"id": "second", "nmae": "X", "data_version": 0}'  # 知らない鍵、足りない鍵、範囲の外
SECOND_CAR_LINES = ["cars.json:cars[1].nmae: unknown key", "cars.json:cars[1].name: missing", "cars.json:cars[1].data_version: 0 is outside 1.."]


@pytest.mark.parametrize(
    "first, want",
    [
        pytest.param('{"id": "kazane", "name": "A", "name": "KAZANE", "data_version": 1}', "cars.json: duplicate key 'name'", id="duplicate_key"),
        pytest.param(
            '{"id": "kazane", "name": "KAZANE", "_trial": NaN, "data_version": 1}', "cars.json: NaN is not accepted (not a JSON number)",
            id="nan_in_a_note",
        ),
        pytest.param(
            '{"id": "kazane", "name": "KAZANE", "data_version": Infinity}', "cars.json: Infinity is not accepted (not a JSON number)",
            id="infinity",
        ),
    ],
)
def test_datadefs_file_with_a_duplicate_key_or_nan_is_handled_like_a_file_that_is_not_json(first, want):
    # 決め：重複した鍵か、NaN・無限大のあるファイルは、JSONが読めないファイルと同じ扱い。そのファイルの項目は、検査へ渡さない。
    # 1つ目の項目に重複した鍵（か NaN）、2つ目の項目に、ほかの問題。並ぶのは、JSONの文を読む所の行だけ。
    # 後勝ちの値で検査を続ける形にはしない（誤った値を検査して、原因と違う行が並ぶ）。
    text = f'{{"cars": [{first}, {SECOND_CAR_BROKEN}]}}'
    assert problems_of(with_text(CARS, text)) == [want]
    # 対：1つ目の項目が読める文なら、2つ目の項目の問題は、全部並ぶ（2つ目の項目の問題が、見本に実際にあること）。
    plain = f'{{"cars": [{json.dumps(ENTRY)}, {SECOND_CAR_BROKEN}]}}'
    assert problems_of(with_text(CARS, plain)) == SECOND_CAR_LINES
    # JSONでないファイルも、同じ形（そのファイルの行が1つだけ）。
    cut = problems_of(with_text(CARS, plain[:-1]))
    assert len(cut) == 1 and cut[0].startswith("cars.json: cannot read: not JSON")
    # ほかのファイルの問題は、一緒に並ぶ。
    both = edited(LOOP, lambda doc: doc.update(data_version=0), with_text(CARS, text))
    assert problems_of(both) == [want, "tracks/test_loop.json:data_version: 0 is outside 1.."]
    # 試験用データの側でも、同じ。
    assert problems_of(real_sources(), ("p", {CARS: text})) == [f"testpacks/p/{want}"]


def test_datadefs_references_to_a_file_that_handed_no_entry_are_listed_as_missing():
    # 参照される側の表のファイルが、項目を検査へ渡さなかった（重複した鍵、JSONでない）。その表への参照は、どれも
    # 「無い id への参照」として並ぶ。どちらの場合も、同じ形（重複した鍵のファイルを、読めないファイルと同じに扱う）。
    refs = ["cars.json:cars[0].sound: no sounds with id 'eng_na'"]
    sources = fake_sources()
    sources["sounds.json"] = '{"sounds": [{"id": "eng_na", "kind": "engine", "kind": "engine"}]}'
    assert problems_of(sources, tables=FAKE_TABLES) == ["sounds.json: duplicate key 'kind'", *refs]
    sources["sounds.json"] = '{"sounds": [{"id": "eng_na", "kind": "engine"}'
    got = problems_of(sources, tables=FAKE_TABLES)
    assert len(got) == 2 and got[0].startswith("sounds.json: cannot read: not JSON") and got[1:] == refs


@pytest.mark.parametrize(
    "text",
    [
        "", "{", '{"cars": [}', "{'cars': []}", '{"cars": [1,]}',
        # BOMつきの文。見えない字（U+FEFF）は、ソースに直に置かず、名前のエスケープで書く（書き直しや整形で消えると、"{}" になって、
        # 狙いと違う理由で落ちる）。
        pytest.param("\N{BYTE ORDER MARK}{}", id="bom"),
        pytest.param("[" * 100000 + "]" * 100000, id="nested_too_deep"),
    ],
)
def test_datadefs_text_that_is_not_json_is_a_problem_of_the_file(text):
    # JSONでない文と、入れ子が深すぎる文。どちらも、そのファイルの問題（ほかの例外にしない）。
    got = problems_of(with_text(CARS, text))
    assert len(got) == 1 and got[0].startswith("cars.json: cannot read: ")


@pytest.mark.parametrize("value", [None, b'{"cars": []}', 5, ["x"]])
def test_datadefs_file_that_could_not_be_read_is_a_problem_of_the_file(value):
    # 読めなかったファイルは、読む所（cp_app/data_files.py）が、値を None にして渡す。文字列でなければ、どれも問題。
    assert problems_of(with_text(CARS, value)) == ["cars.json: cannot read the file"]
    assert problems_of(with_text(LOOP, value)) == ["tracks/test_loop.json: cannot read the file"]


def test_datadefs_number_too_big_for_a_float_is_not_a_number():
    # 1e999 は、標準の読み方で無限大になる（NaN と違い、JSONの文を読む所では止まらない）。数の規則が受けない。
    tables = {"cars": TableDef(ONE_TABLE, {"id": Ident(), "mass": Num(500, 2500)})}
    assert problems_of({"cars.json": '{"cars": [{"id": "a", "mass": 1e999}]}'}, tables=tables) == ["cars.json:cars[0].mass: inf is not a finite number"]


# --- 知らないファイル、2つの形に当たらない名、無いファイル ---
@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",  # .json でない
        "sounds.json",  # 表の定義に無い名
        "tracks.json",  # 1ファイル1項目の表を、1ファイル1表の形で置いた
        "cars/kazane.json",  # 1ファイル1表の表を、1ファイル1項目の形で置いた
        "tracks/deep/test_loop.json",  # 深い階
        "tracks/readme.md",
        "tracks/.json",
        "sounds/engine.json",  # 知らないディレクトリ
        "CARS.JSON",
    ],
)
def test_datadefs_file_that_no_table_reads_is_a_problem(name):
    # 拾わない名を、黙って無視しない。中身は読まない（JSONでなくても、読めなくても、問題は1つ）。
    for text in ("{}", "not json", None):
        assert problems_of(with_text(name, text)) == [f"{name}: unknown file (no table reads this name)"]


def test_datadefs_missing_table_files_are_problems():
    sources = real_sources()
    assert problems_of({name: text for name, text in sources.items() if name != CARS}) == ["cars.json: missing file"]
    assert problems_of({CARS: sources[CARS]}) == ["tracks/: no entry files"]
    assert problems_of({}) == ["cars.json: missing file", "tracks/: no entry files"]


# --- ファイルの頭の形の誤り。2つの形のそれぞれで ---
ENTRY = {"id": "kazane", "name": "KAZANE", "data_version": 1}


@pytest.mark.parametrize(
    "doc, want",
    [
        ([ENTRY], ['cars.json: the file must be {"cars": [...]}, got list']),
        ("cars", ['cars.json: the file must be {"cars": [...]}, got str']),
        (None, ['cars.json: the file must be {"cars": [...]}, got NoneType']),
        ({}, ['cars.json:cars: missing (the file must be {"cars": [...]})']),
        ({"car": [ENTRY]}, ["cars.json:car: unknown key at the top level (only 'cars' and notes)", 'cars.json:cars: missing (the file must be {"cars": [...]})']),
        ({"cars": [ENTRY], "extra": 1, "more": 2}, ["cars.json:extra: unknown key at the top level (only 'cars' and notes)", "cars.json:more: unknown key at the top level (only 'cars' and notes)"]),
        ({"cars": {"kazane": ENTRY}}, ["cars.json:cars: expected a list of entries, got dict"]),
        ({"cars": None}, ["cars.json:cars: expected a list of entries, got NoneType"]),
        ({"cars": [ENTRY, 5, "x", [ENTRY]]}, [
            "cars.json:cars[1]: expected an entry (an object), got int",
            "cars.json:cars[2]: expected an entry (an object), got str",
            "cars.json:cars[3]: expected an entry (an object), got list",
        ]),
        ({"cars": [{"name": "KAZANE", "data_version": 1}]}, ["cars.json:cars[0].id: missing"]),
        ({"cars": [{**ENTRY, "id": 7}]}, ["cars.json:cars[0].id: expected a string id, got int"]),
        ({"cars": [{**ENTRY, "id": None}]}, ["cars.json:cars[0].id: expected a string id, got NoneType"]),
        # id が無い項目も、ほかの鍵は照らす（全部を並べる）。
        ({"cars": [{"name": "", "nmae": 1}]}, ["cars.json:cars[0].id: missing", "cars.json:cars[0].nmae: unknown key", "cars.json:cars[0].name: expected a non-empty text, got ''", "cars.json:cars[0].data_version: missing"]),
    ],
)
def test_datadefs_one_table_file_with_a_wrong_head_is_a_problem_of_the_file(doc, want):
    assert problems_of(with_text(CARS, json.dumps(doc))) == want


@pytest.mark.parametrize(
    "doc, want",
    [
        ([{"id": "test_loop", "name": "TEST LOOP", "data_version": 1}], ["tracks/test_loop.json: the file must be one entry (an object), got list"]),
        ("test_loop", ["tracks/test_loop.json: the file must be one entry (an object), got str"]),
        (3, ["tracks/test_loop.json: the file must be one entry (an object), got int"]),
        ({"name": "TEST LOOP", "data_version": 1}, ["tracks/test_loop.json:id: missing"]),
        ({"id": ["test_loop"], "name": "TEST LOOP", "data_version": 1}, ["tracks/test_loop.json:id: expected a string id, got list"]),
        ({}, ["tracks/test_loop.json:id: missing", "tracks/test_loop.json:name: missing", "tracks/test_loop.json:data_version: missing"]),
        # 1ファイル1表の形（{"tracks": […]}）で置いた。
        ({"tracks": [{"id": "test_loop", "name": "TEST LOOP", "data_version": 1}]}, [
            "tracks/test_loop.json:id: missing", "tracks/test_loop.json:tracks: unknown key",
            "tracks/test_loop.json:name: missing", "tracks/test_loop.json:data_version: missing",
        ]),
    ],
)
def test_datadefs_one_entry_file_with_a_wrong_head_is_a_problem_of_the_file(doc, want):
    assert problems_of(with_text(LOOP, json.dumps(doc))) == want


WEIRD = [None, True, False, 0, 1, -1, 1.5, "", "x", [], [None], [[]], {}, {"id": None}, {"id": []}, {"id": {}}, {"cars": 1}, {"_": 1}]


def test_datadefs_strange_values_anywhere_never_raise_anything_but_data_error():
    # 変な値を、ファイルの頭、表の値、項目、id、ほかの鍵に置く。DataError のほかの例外（KeyError、TypeError）にならない。
    for value in WEIRD:
        for sources in (
            with_text(CARS, json.dumps(value)),
            with_text(CARS, json.dumps({"cars": value})),
            with_text(CARS, json.dumps({"cars": [value]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "id": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "name": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "extra": value}]})),
            with_text(LOOP, json.dumps(value)),
            with_text(LOOP, json.dumps({"id": value, "name": "TEST LOOP", "data_version": 1})),
            with_text(LOOP, json.dumps({"id": "test_loop", "name": "TEST LOOP", "data_version": value})),
        ):
            try:
                load_game_data(sources)
            except DataError as exc:
                assert exc.problems
            # 試験用データの側に置いても、同じ。
            try:
                load_game_data(real_sources(), ("p", sources))
            except DataError as exc:
                assert exc.problems and all(line.startswith(("testpacks/p/", "cars.json", "tracks/")) for line in exc.problems)


# --- 規則の部品。1つずつ ---
@pytest.mark.parametrize(
    "rule, good, bad",
    [
        (Int(1, 5), [1, 3, 5], [0, 6, True, False, 1.0, "1", None, [1]]),
        (Int(0), [0, 10 ** 30], [-1, True, 0.0, "0"]),
        (Num(0.5, 2.5), [1, 2, 0.5, 2.5, 1.25], [0, 3, 0.49, True, "1.5", None, float("nan"), float("inf"), float("-inf"), 10 ** 400]),
        (Bool(), [True, False], [0, 1, "true", None]),
        (Enum("FF", "FR"), ["FF", "FR"], ["RR", "ff", "", 1, None, ["FF"]]),
        (Ident(), ["kazane", "a", "test_loop", "x_1", "9lives"], ["", "Kazane", "a b", "a-b", "a.b", "é", 5, None, ["a"]]),
        (Label(14), ["KAZANE", "A", "K" * 14, "A b-1!~"], ["", "K" * 15, "カザネ", "A\tB", "A\nB", "é", "\x7f", 5, None, ["A"]]),
        (Ref("cars"), ["kazane", ""], [5, None, ["kazane"], True]),
        (ListOf(Int(0), 1, 3), [[1], [1, 2, 3], ["not checked here"]], [[], [1, 2, 3, 4], "abc", (1,), None, {"0": 1}]),
        (Obj({"a": Int(0)}), [{}, {"a": "not checked here"}], [[], "x", None, 5]),
    ],
)
def test_datadefs_rule_part_accepts_and_rejects(rule, good, bad):
    # 規則の部品は、値を受けて、問題の文（無ければ None）を返す。並びと入れ子の項目は、自分の階だけを見る（中は、読み込み検査が照らす）。
    for value in good:
        assert rule.check(value) is None, value
    for value in bad:
        message = rule.check(value)
        assert type(message) is str and message, value


# --- 作り物の表の定義。参照、並び、入れ子の項目、省ける項目、列挙、数、真偽 ---
FAKE_TABLES = {
    "sounds": TableDef(ONE_TABLE, {"id": Ident(), "kind": Enum("engine", "sfx"), "base_hz": Opt(Num(20, 2000))}),
    "cars": TableDef(ONE_TABLE, {
        "id": Ident(),
        "name": Label(14),
        "turbo": Bool(),
        "sound": Ref("sounds"),
        "gears": ListOf(Num(0.5, 5.0), 2, 4),
        "engine": Obj({"idle_rpm": Int(500, 2000), "curve": ListOf(Obj({"rpm": Int(0, 9000), "torque": Num(0, 500)}), 1, 4)}),
        "extras": Opt(ListOf(Ref("sounds"), 0, 3)),
    }),
    "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "name": Label(14), "cars": ListOf(Ref("cars"), 1, 3)}),
}
FAKE_CAR = {
    "id": "kazane", "name": "KAZANE", "turbo": False, "sound": "eng_na", "gears": [3.2, 1.9, 1.0],
    "engine": {"idle_rpm": 900, "curve": [{"rpm": 1000, "torque": 120.5}, {"rpm": 6000, "torque": 160}]},
}
FAKE_SOUNDS = [{"id": "eng_na", "kind": "engine", "base_hz": 110}]
FAKE_TRACK = {"id": "test_loop", "name": "TEST LOOP", "cars": ["kazane"]}


def fake_sources(car=None, sounds=None, track=None, cars=None) -> dict:
    """作り物の表の定義に合う、定義データ。car は、車の項目に重ねる値。"""
    rows = [{**FAKE_CAR, **(car or {})}] if cars is None else cars
    return {
        "sounds.json": json.dumps({"sounds": FAKE_SOUNDS if sounds is None else sounds}),
        "cars.json": json.dumps({"cars": rows}),
        "tracks/test_loop.json": json.dumps({**FAKE_TRACK, **(track or {})}),
    }


def test_datadefs_fake_tables_load_and_keep_the_nested_values():
    data = load_game_data(fake_sources(), tables=FAKE_TABLES)
    assert data.warnings == () and data.counts() == {"sounds": 1, "cars": 1, "tracks": 1}
    assert data.entry("cars", "kazane") == FAKE_CAR
    assert data.entry("tracks", "test_loop") == FAKE_TRACK


@pytest.mark.parametrize(
    "car, want",
    [
        ({"turbo": 1}, ["cars.json:cars[0].turbo: expected true or false, got int"]),
        ({"sound": "eng_v8"}, ["cars.json:cars[0].sound: no sounds with id 'eng_v8'"]),  # 無い参照
        ({"sound": 5}, ["cars.json:cars[0].sound: expected an id of sounds, got int"]),
        ({"extras": ["eng_na", "nobody", "also_nobody"]}, [  # 並びの中の、無い参照。2つとも並ぶ
            "cars.json:cars[0].extras[1]: no sounds with id 'nobody'", "cars.json:cars[0].extras[2]: no sounds with id 'also_nobody'",
        ]),
        ({"extras": None}, ["cars.json:cars[0].extras: expected a list, got NoneType"]),  # 省ける項目でも、null は受けない
        ({"gears": [3.2]}, ["cars.json:cars[0].gears: expected a list of 2..4 items, got 1"]),  # 並びの長さ
        ({"gears": [3.2, 1.9, 1.4, 1.0, 0.8]}, ["cars.json:cars[0].gears: expected a list of 2..4 items, got 5"]),
        ({"gears": [3.2, "1.9", 9.0, True]}, [  # 並びの中は、最初の1件で止めない
            "cars.json:cars[0].gears[1]: expected a number, got str",
            "cars.json:cars[0].gears[2]: 9.0 is outside 0.5..5.0",
            "cars.json:cars[0].gears[3]: expected a number, got bool",
        ]),
        ({"gears": "3.2 1.9"}, ["cars.json:cars[0].gears: expected a list, got str"]),
        # 入れ子の中の誤り。鍵の道が付く。
        ({"engine": {"idle_rpm": 100, "curve": [{"rpm": 1000, "torque": 120.5}]}}, ["cars.json:cars[0].engine.idle_rpm: 100 is outside 500..2000"]),
        ({"engine": {"idle_rpm": 900, "curve": [{"rpm": 1000, "torque": 120.5}, {"rpm": -1, "torque": "x", "trq": 1}]}}, [
            "cars.json:cars[0].engine.curve[1].trq: unknown key",
            "cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000",
            "cars.json:cars[0].engine.curve[1].torque: expected a number, got str",
        ]),
        ({"engine": {"idle_rpm": 900}}, ["cars.json:cars[0].engine.curve: missing"]),
        ({"engine": {"idle_rpm": 900, "curve": [5]}}, ["cars.json:cars[0].engine.curve[0]: expected an object, got int"]),
        ({"engine": [900]}, ["cars.json:cars[0].engine: expected an object, got list"]),
    ],
)
def test_datadefs_fake_broken_values_are_rejected_with_the_key_path(car, want):
    assert problems_of(fake_sources(car), tables=FAKE_TABLES) == want


def test_datadefs_value_outside_the_enumeration_and_optional_keys():
    assert problems_of(fake_sources(sounds=[{"id": "eng_na", "kind": "bgm"}]), tables=FAKE_TABLES) == [
        "sounds.json:sounds[0].kind: 'bgm' is not one of ['engine', 'sfx']"
    ]
    # 省ける項目は、無くてもよい。あれば、規則で照らす。
    assert load_game_data(fake_sources(sounds=[{"id": "eng_na", "kind": "engine"}]), tables=FAKE_TABLES).entry("sounds", "eng_na") == {"id": "eng_na", "kind": "engine"}
    assert problems_of(fake_sources(sounds=[{"id": "eng_na", "kind": "engine", "base_hz": 5}]), tables=FAKE_TABLES) == [
        "sounds.json:sounds[0].base_hz: 5 is outside 20..2000"
    ]


def test_datadefs_references_are_checked_after_every_table_is_read():
    # 参照の先の表（sounds）が、参照する側の表（cars）より後ろに定義されていても、同じに読める（表を読む順に頼らない）。
    backwards = {name: FAKE_TABLES[name] for name in ("tracks", "cars", "sounds")}
    data = load_game_data(fake_sources(), tables=backwards)
    assert data.counts() == {"tracks": 1, "cars": 1, "sounds": 1} and data.warnings == ()
    # 1ファイル1項目の表からの、並びの中の参照。
    assert problems_of(fake_sources(track={"cars": ["kazane", "nobody"]}), tables=backwards) == ["tracks/test_loop.json:cars[1]: no cars with id 'nobody'"]


def test_datadefs_unreferenced_definition_is_a_warning_not_a_problem():
    # 参照される側の表（sounds と cars）で、どこからも参照されていない定義は、警告。読み込みは通る。
    sounds = [*FAKE_SOUNDS, {"id": "sfx_unused", "kind": "sfx"}, {"id": "sfx_other", "kind": "sfx"}]
    cars = [FAKE_CAR, {**FAKE_CAR, "id": "spare", "extras": ["sfx_other"]}]
    data = load_game_data(fake_sources(sounds=sounds, cars=cars), tables=FAKE_TABLES)
    assert data.warnings == ("sounds.sfx_unused: defined but never referenced", "cars.spare: defined but never referenced")
    assert data.counts() == {"sounds": 3, "cars": 2, "tracks": 1}
    # 参照されない側の表（tracks）の定義は、警告にならない。実物の表の定義には、参照が無いので、警告は出ない。
    assert load_game_data(fake_sources(), tables=FAKE_TABLES).warnings == ()


def test_datadefs_note_keys_pass_at_every_level_and_are_not_handed_out():
    car = {
        **FAKE_CAR, "_note": "placeholder", "_checked": {"by": "nobody", "_deep": [1, 2]},
        "engine": {
            "idle_rpm": 900, "_note": "idle",
            "curve": [{"rpm": 1000, "torque": 120.5, "_source": ["bench", {"_x": 1}]}, {"rpm": 6000, "torque": 160}],
        },
    }
    sources = {
        "sounds.json": json.dumps({"_notes": {"sounds": "仮の値：…"}, "_more": [1], "sounds": FAKE_SOUNDS}),
        "cars.json": json.dumps({"_notes": "text", "cars": [car]}),
        "tracks/test_loop.json": json.dumps({**FAKE_TRACK, "_notes": {"test_loop": "仮の値：…"}}),
    }
    data = load_game_data(sources, tables=FAKE_TABLES)

    def keys_of(value) -> list:
        if type(value) is dict:
            return [*value, *(key for item in value.values() for key in keys_of(item))]
        return [key for item in value for key in keys_of(item)] if type(value) is list else []

    for table in FAKE_TABLES:
        for ident in data.ids(table):
            assert not [key for key in keys_of(data.entry(table, ident)) if key.startswith("_")], (table, ident)
    assert data.entry("cars", "kazane") == FAKE_CAR and data.entry("tracks", "test_loop") == FAKE_TRACK


def test_datadefs_wrong_table_definitions_are_value_errors_not_data_errors():
    # 表の定義そのものの誤りは、データの問題ではない。
    for tables in (
        {"cars": TableDef("one_per_line", {"id": Ident()})},
        {"cars": TableDef(ONE_TABLE, {"name": Label(14)})},
        {"cars": TableDef(ONE_TABLE, {"id": Label(14)})},
        {"cars": TableDef(ONE_TABLE, {"id": Ident(), "sound": Ref("sounds")})},
        {"cars": TableDef(ONE_TABLE, {"id": Ident(), "engine": Obj({"sounds": ListOf(Ref("sounds"), 0, 2)})})},
    ):
        with pytest.raises(ValueError) as info:
            load_game_data({}, tables=tables)
        assert not isinstance(info.value, DataError)


# --- 読み込んだ定義 ---
def test_datadefs_ids_come_in_file_order_and_missing_names_are_key_errors():
    cars = [{**FAKE_CAR, "id": "zeta"}, {**FAKE_CAR, "id": "alpha"}, {**FAKE_CAR, "id": "kazane"}]
    data = load_game_data(fake_sources(cars=cars), tables=FAKE_TABLES)
    assert data.ids("cars") == ("zeta", "alpha", "kazane") and type(data.ids("cars")) is tuple  # 整列しない。ファイルの順
    for table, ident in (("cars", "nobody"), ("nothing", "kazane"), ("cars", None)):
        with pytest.raises(KeyError):
            data.entry(table, ident)
    with pytest.raises(KeyError):
        data.ids("nothing")


def test_datadefs_entry_is_a_fresh_copy_down_to_the_nested_lists():
    # 引いた値の、奥の並びと辞書を書き換えても、次に引いた値が変わらない（浅い複製では、奥が同じ物になる）。
    data = load_game_data(fake_sources(), tables=FAKE_TABLES)
    first = data.entry("cars", "kazane")
    first["name"] = "CHANGED"
    first["gears"].append(0.1)
    first["engine"]["idle_rpm"] = 0
    first["engine"]["curve"][0]["rpm"] = -5
    first["engine"]["curve"].clear()
    second = data.entry("cars", "kazane")
    assert second == FAKE_CAR
    third = data.entry("cars", "kazane")
    assert second is not third and second["gears"] is not third["gears"]
    assert second["engine"] is not third["engine"] and second["engine"]["curve"][0] is not third["engine"]["curve"][0]
    counts = data.counts()
    counts["cars"] = 99
    assert data.counts()["cars"] == 1


def test_datadefs_loading_does_not_change_the_sources():
    sources, pack_files = real_sources(), {CARS: json.dumps({"cars": [{"id": "kazane", "name": "OTHER", "data_version": 2}]})}
    before, pack_before = dict(sources), dict(pack_files)
    load_game_data(sources, ("p", pack_files))
    assert sources == before and pack_files == pack_before


# --- 問題の行の順 ---
def test_datadefs_problem_lines_come_in_the_same_order_every_time():
    # 辞書へ入れた順と、JSONの中の鍵の順を変えても、問題の行は、同じ順で並ぶ（集合を回した順に頼らない）。
    car = {"zz": 1, "id": "kazane", "aa": 2, "data_version": 0, "name": "", "mm": 3}
    track = {"data_version": "1", "zz": 1, "name": "カ", "aa": 2, "id": "test_loop"}
    names = ["notes.txt", CARS, "zz.json", LOOP, "aa.json"]
    texts = {
        CARS: {"cars": [car, dict(reversed(car.items()))]}, LOOP: track, "notes.txt": {}, "zz.json": {}, "aa.json": {},
    }
    want = [
        "aa.json: unknown file (no table reads this name)",
        "notes.txt: unknown file (no table reads this name)",
        "zz.json: unknown file (no table reads this name)",
        "cars.json:cars[1].id: duplicate id 'kazane'",
        "cars.json:cars[0].aa: unknown key",
        "cars.json:cars[0].mm: unknown key",
        "cars.json:cars[0].zz: unknown key",
        "cars.json:cars[0].name: expected a non-empty text, got ''",
        "cars.json:cars[0].data_version: 0 is outside 1..",
        "tracks/test_loop.json:aa: unknown key",
        "tracks/test_loop.json:zz: unknown key",
        "tracks/test_loop.json:name: 'カ' has characters outside printable ASCII",
        "tracks/test_loop.json:data_version: expected an integer, got str",
        "cars.json:cars[1].aa: unknown key",
        "cars.json:cars[1].mm: unknown key",
        "cars.json:cars[1].zz: unknown key",
        "cars.json:cars[1].name: expected a non-empty text, got ''",
        "cars.json:cars[1].data_version: 0 is outside 1..",
    ]
    for order in (names, list(reversed(names)), sorted(names), names[2:] + names[:2]):
        sources = {name: json.dumps(texts[name]) for name in order}
        assert problems_of(sources) == want
    assert problems_of({name: json.dumps(texts[name], sort_keys=True) for name in names}) == want


# --- 試験用データの重ね方 ---
PACK_CARS = {"cars": [{"id": "kazane", "name": "KAZANE RS TEST", "data_version": 3}, {"id": "wide_test_car", "name": "W" * 14, "data_version": 1}]}


def test_datadefs_pack_replaces_the_same_id_and_appends_a_new_id():
    sources = real_sources()
    data = load_game_data(sources, ("extreme", {CARS: json.dumps(PACK_CARS)}))
    assert data.pack == "extreme" and data.warnings == ()
    assert data.ids("cars") == ("kazane", "wide_test_car")  # 同じ id は、元の位置で差し替え。新しい id は、末尾
    assert data.entry("cars", "kazane") == {"id": "kazane", "name": "KAZANE RS TEST", "data_version": 3}
    assert data.entry("cars", "wide_test_car")["name"] == "W" * 14
    assert data.counts() == {"cars": 2, "tracks": 1}  # 重ねなかった表は、そのまま
    # 元のデータは変わらない。
    plain = load_game_data(sources)
    assert plain.pack is None and plain.ids("cars") == ("kazane",) and plain.entry("cars", "kazane")["name"] == "KAZANE"


def test_datadefs_pack_keeps_the_position_of_a_replaced_entry():
    cars = [{**FAKE_CAR, "id": "first"}, {**FAKE_CAR, "id": "kazane"}, {**FAKE_CAR, "id": "last"}]
    pack = {"cars.json": json.dumps({"cars": [{**FAKE_CAR, "id": "new_one"}, {**FAKE_CAR, "id": "kazane", "name": "REPLACED"}]})}
    data = load_game_data(fake_sources(cars=cars), ("p", pack), FAKE_TABLES)
    assert data.ids("cars") == ("first", "kazane", "last", "new_one")
    assert data.entry("cars", "kazane")["name"] == "REPLACED" and data.entry("cars", "first")["name"] == "KAZANE"


def test_datadefs_pack_of_one_entry_files_replaces_the_same_name_and_adds_a_new_name():
    pack = {
        LOOP: json.dumps({"id": "test_loop", "name": "REPLACED LOOP", "data_version": 9}),
        "tracks/wide_test_loop.json": json.dumps({"id": "wide_test_loop", "name": "M" * 14, "data_version": 1}),
        "tracks/another_loop.json": json.dumps({"id": "another_loop", "name": "ANOTHER", "data_version": 1}),
    }
    data = load_game_data(real_sources(), ("extreme", pack))
    assert data.ids("tracks") == ("test_loop", "another_loop", "wide_test_loop")  # 元の順のあとに、新しい名（名を整列した順）
    assert data.entry("tracks", "test_loop") == {"id": "test_loop", "name": "REPLACED LOOP", "data_version": 9}
    assert data.counts() == {"cars": 1, "tracks": 3}
    assert load_game_data(real_sources()).entry("tracks", "test_loop")["name"] == "TEST LOOP"


def test_datadefs_the_overlaid_result_goes_through_the_same_checks():
    # 重ねた結果を、同じ読み込み検査に通す。試験用データの中の問題は、頭に testpacks/<名>/ が付く。
    bad = {"cars": [{"id": "kazane", "name": "K" * 15, "data_version": 1}, {"id": "new_car", "nmae": "X", "data_version": True}]}
    assert problems_of(real_sources(), ("extreme", {CARS: json.dumps(bad)})) == [
        f"testpacks/extreme/cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)",
        "testpacks/extreme/cars.json:cars[1].nmae: unknown key",
        "testpacks/extreme/cars.json:cars[1].name: missing",
        "testpacks/extreme/cars.json:cars[1].data_version: expected an integer, got bool",
    ]
    assert problems_of(real_sources(), ("extreme", {LOOP: json.dumps({"id": "other", "name": "X", "data_version": 1})})) == [
        "testpacks/extreme/tracks/test_loop.json:id: 'other' does not match the file name 'test_loop'"
    ]
    # 参照も、重ねた結果で照らす。試験用データが足した定義への参照は通り、無い定義への参照は落ちる。
    more_sounds = {"sounds.json": json.dumps({"sounds": [{"id": "eng_turbo", "kind": "engine"}]})}
    turbo = {"cars.json": json.dumps({"cars": [{**FAKE_CAR, "sound": "eng_turbo", "extras": ["eng_na"]}]})}
    assert load_game_data(fake_sources(), ("p", {**more_sounds, **turbo}), FAKE_TABLES).entry("cars", "kazane")["sound"] == "eng_turbo"
    assert problems_of(fake_sources(), ("p", turbo), FAKE_TABLES) == ["testpacks/p/cars.json:cars[0].sound: no sounds with id 'eng_turbo'"]
    # 出荷するデータの、差し替えられた項目の問題は、重ねた結果には無い。差し替えられなかった項目の問題は、残る。
    broken = edited(CARS, lambda doc: doc["cars"][0].update(nmae="X"))
    assert load_game_data(broken, ("extreme", {CARS: json.dumps(PACK_CARS)})).ids("cars") == ("kazane", "wide_test_car")
    only_new = {CARS: json.dumps({"cars": [PACK_CARS["cars"][1]]})}
    assert problems_of(broken, ("extreme", only_new)) == ["cars.json:cars[0].nmae: unknown key"]


@pytest.mark.parametrize(
    "files, want",
    [
        # ファイルの頭の形が合わないファイルは、重ねない。問題は、そのファイルの1行だけ（突き合わせの途中で、別の例外にならない）。
        ({CARS: json.dumps([PACK_CARS["cars"][0]])}, ['testpacks/p/cars.json: the file must be {"cars": [...]}, got list']),
        ({CARS: json.dumps({"cars": {"kazane": {}}})}, ["testpacks/p/cars.json:cars: expected a list of entries, got dict"]),
        ({CARS: json.dumps({"cars": []})}, ["testpacks/p/cars.json:cars: no entries"]),
        ({CARS: json.dumps({"cars": [PACK_CARS["cars"][0], 5]})}, ["testpacks/p/cars.json:cars[1]: expected an entry (an object), got int"]),
        ({CARS: json.dumps({"cars": [{"name": "X", "data_version": 1}]})}, ["testpacks/p/cars.json:cars[0].id: missing"]),
        ({CARS: json.dumps({"cars": [{"id": 5, "name": "", "data_version": 1}]})}, [
            "testpacks/p/cars.json:cars[0].id: expected a string id, got int", "testpacks/p/cars.json:cars[0].name: expected a non-empty text, got ''",
        ]),
        ({LOOP: json.dumps(["test_loop"])}, ["testpacks/p/tracks/test_loop.json: the file must be one entry (an object), got list"]),
        ({LOOP: json.dumps({"name": "X", "data_version": 1})}, ["testpacks/p/tracks/test_loop.json:id: missing"]),
        ({CARS: "{"}, None),
        ({CARS: None}, ["testpacks/p/cars.json: cannot read the file"]),
        ({CARS: '{"cars": [], "cars": []}'}, ["testpacks/p/cars.json: duplicate key 'cars'"]),
        # 同じファイルの中の、id の重複。
        ({CARS: json.dumps({"cars": [PACK_CARS["cars"][1], PACK_CARS["cars"][1]]})}, ["testpacks/p/cars.json:cars[1].id: duplicate id 'wide_test_car'"]),
        # 2つの形に当たらない名。「重ねたつもりで、重なっていない」まま通さない。
        ({"notes.txt": "x"}, ["testpacks/p/notes.txt: unknown file (no table reads this name)", "testpacks/p/: no table files (nothing would be overlaid)"]),
        ({"tracks.json": "{}", CARS: json.dumps(PACK_CARS)}, ["testpacks/p/tracks.json: unknown file (no table reads this name)"]),
        ({"cars/kazane.json": "{}", "tracks/deep/x.json": "{}", CARS: json.dumps(PACK_CARS)}, [
            "testpacks/p/cars/kazane.json: unknown file (no table reads this name)", "testpacks/p/tracks/deep/x.json: unknown file (no table reads this name)",
        ]),
        # 表のファイルが1つも無い。
        ({}, ["testpacks/p/: no table files (nothing would be overlaid)"]),
    ],
)
def test_datadefs_pack_file_with_a_wrong_shape_is_not_overlaid_and_is_a_problem(files, want):
    got = problems_of(real_sources(), ("p", files))
    if want is None:
        assert len(got) == 1 and got[0].startswith("testpacks/p/cars.json: cannot read: ")
    else:
        assert got == want


@pytest.mark.parametrize("name", ["", "Extreme", "extreme pack", "a-b", "a.b", "a/b", "..", "é", "a" * 44, None, 5, ["extreme"]])
def test_datadefs_bad_pack_name_is_a_value_error(name):
    with pytest.raises(ValueError) as info:
        load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
    assert not isinstance(info.value, DataError)
    with pytest.raises(ValueError):
        datadefs.check_pack_name(name)


# --- 保存の名前空間 ---
def test_datadefs_save_namespace_is_main_or_pack_and_the_name():
    assert load_game_data(real_sources()).save_namespace == "main"
    for name in ("extreme", "x_1", "9", "a" * 43):
        data = load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
        assert data.pack == name == datadefs.check_pack_name(name)
        assert data.save_namespace == f"pack_{name}"
        # 保存の口が、名前空間として受ける（48字まで。「.」を含まない）。
        assert storage.SaveStore(storage.MemoryBackend(), data.save_namespace).namespace == f"pack_{name}"
    assert datadefs.PACK_NAME_MAX == 43 and len(datadefs.PACK_NAMESPACE_PREFIX) + datadefs.PACK_NAME_MAX == storage.KEY_MAX
    assert datadefs.PACK_NAMESPACE_PREFIX == "pack_" and datadefs.PACKS_DIR == "testpacks"


def test_datadefs_pack_named_like_a_namespace_in_use_does_not_share_that_namespace():
    # 名が、ふつうの保存の名前空間（main）や、保存の往復の名前空間（selfcheck）と同じ試験用データを、実際に重ねる。
    # 保存の名前空間は、どちらとも重ならない（頭の pack_ が無いと、名 main の試験用データが、ふだんの保存に触れる）。
    in_use = {storage.DEFAULT_NAMESPACE, profile.SELFCHECK_NAMESPACE}
    assert in_use == {"main", "selfcheck"}
    for name in sorted(in_use):
        data = load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
        assert data.pack == name
        assert data.save_namespace not in in_use, name
        # 保存の口が受ける名前空間でも、重ならない。
        assert storage.SaveStore(storage.MemoryBackend(), data.save_namespace).namespace not in in_use, name


# --- 表を足す、項目を足すときの手順の見張り ---
def key_paths(fields: dict, prefix: str = "") -> list:
    """鍵ごとの規則の、鍵の道の全部（定義の順）。入れ子の項目、並びの中の項目、省ける項目の中も開く。

    {"engine": Obj({"idle_rpm": …, "curve": ListOf(Obj({"rpm": …}), …)})} なら、engine、engine.idle_rpm、engine.curve、engine.curve.rpm。
    """
    found = []
    for key, rule in fields.items():
        path = f"{prefix}{key}"
        found.append(path)
        while isinstance(rule, (Opt, ListOf)):  # 省ける項目と並びは、中の規則まで開く
            rule = rule.inner if isinstance(rule, Opt) else rule.item
        if isinstance(rule, Obj):
            found += key_paths(rule.fields, f"{path}.")
    return found


def key_path_of(line: str, table: str, tables: dict) -> str:
    """問題の行の場所を、項目の中の鍵の道にする。並びの中の番号と、1ファイル1表の頭（表の名と、項目の番号）は落とす。

    「cars.json:cars[0].engine.curve[1].rpm: …」は engine.curve.rpm、「tracks/test_loop.json:name: …」は name。
    項目の中を指さない行（ファイルの問題、表の問題）は、空の文字列。
    """
    where = line.split(": ", 1)[0].partition(":")[2]
    if tables[table].layout == ONE_TABLE:
        head = re.match(rf"{re.escape(table)}\[\d+\](\.|$)", where)
        if head is None:
            return ""
        where = where[head.end():]
    return re.sub(r"\[\d+\]", "", where)


def broken_case_problems(tables: dict, broken: dict) -> list:
    """壊した場合の表（{名前: (表, 札, 壊したファイルの辞書, 並ぶはずの問題の行)}）を、表の定義と照らす。返すのは、足りない所と、札の食い違い。

    - 表ごとに、どの鍵でもない所を壊した件（札が None。知らない鍵か、空の表）が、1つ以上ある。
    - 表の、鍵の道の全部（key_paths。入れ子の奥まで）に、その鍵の道を札にした件が、1つ以上ある。
    - 札は、書いた人の申告のままにしない。並ぶはずの行は1つ以上あり、その場所（key_path_of）は、どれも、札と同じ鍵の道。
      札が None の件の行は、表のどの鍵の道も指さない。
    """
    problems = []
    for name, table in tables.items():
        paths = key_paths(table.fields)
        cases = {case: (tag, want) for case, (case_table, tag, _, want) in broken.items() if case_table == name}
        tags = {tag for tag, _ in cases.values()}
        if None not in tags:
            problems.append(f"{name}: 知らない鍵か、空の表の、壊した場合が無い")
        problems += [f"{name}: 壊した場合の無い鍵：{path}" for path in paths if path not in tags]
        for case in sorted(cases):
            tag, want = cases[case]
            places = [key_path_of(line, name, tables) for line in want]
            if not places:
                problems.append(f"{case}: 並ぶはずの行が無い")
            if tag is None:
                problems += [f"{case}: 札は None、行の場所は、鍵 {place}" for place in places if place in paths]
                continue
            if tag not in paths:
                problems.append(f"{case}: 札 {tag} は、表 {name} の鍵の道に無い")
            problems += [f"{case}: 札は {tag}、行の場所は {place or '項目の外'}" for place in places if place != tag]
    problems += [f"{case}: 表の定義に無い表：{value[0]}" for case, value in sorted(broken.items()) if value[0] not in tables]
    return problems


def test_datadefs_every_real_table_has_its_files_and_every_key_has_a_broken_case():
    sources = real_sources()
    for name, table in TABLES.items():
        if table.layout == ONE_TABLE:
            assert f"{name}.json" in sources, name
        else:
            assert [source for source in sources if source.startswith(f"{name}/")], name
    # 鍵は、入れ子の奥まで見る（鍵の道ごとに、壊した場合が要る）。札は、並ぶはずの行の場所と照らす。
    assert broken_case_problems(TABLES, BROKEN) == []
    assert {case_table for case_table, _, _, _ in BROKEN.values()} == set(TABLES)
    assert all(datadefs._classify(name, TABLES) is not None for name in sources)  # 実物の置き場に、知らないファイルが無い


# 見張りそのものの確かめ。実物の表の定義は、まだ入れ子を持たないので、作り物の表の定義（入れ子の項目、並びの中の項目、
# 省ける項目の中の項目。2つのファイルの形）で、見張りが、奥の鍵と、札の食い違いを拾うことを見る。
GUARD_TABLES = {
    "cars": TableDef(ONE_TABLE, {
        "id": Ident(),
        "engine": Obj({"idle_rpm": Int(500, 2000), "curve": ListOf(Obj({"rpm": Int(0, 9000)}), 1, 4)}),
        "tune": Opt(Obj({"boost": Num(0, 2)})),
    }),
    "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "gates": Opt(ListOf(Obj({"x": Num(-100, 100)}), 1, 3))}),
}
GUARD_CAR = {"id": "kazane", "engine": {"idle_rpm": 900, "curve": [{"rpm": 1000}]}, "tune": {"boost": 1}}
GUARD_TRACK = {"id": "test_loop", "gates": [{"x": 0}, {"x": 5}]}


def guard_case(table: str, tag, car=None, track=None) -> tuple:
    """作り物の表の定義の、壊した場合1つ。並ぶはずの行は、実際に読み込み検査を通して作る（行の形を、手で書かない）。"""
    sources = {
        "cars.json": json.dumps({"cars": [{**GUARD_CAR, **(car or {})}]}),
        "tracks/test_loop.json": json.dumps({**GUARD_TRACK, **(track or {})}),
    }
    return table, tag, sources, problems_of(sources, tables=GUARD_TABLES)


def guard_cases() -> dict:
    """作り物の表の定義の、鍵の道の全部に1件ずつと、表ごとに、知らない鍵の件。"""
    engine = GUARD_CAR["engine"]
    return {
        "cars unknown key": guard_case("cars", None, car={"nmae": 1}),
        "cars id": guard_case("cars", "id", car={"id": "Bad Id"}),
        "cars engine": guard_case("cars", "engine", car={"engine": [900]}),
        "cars idle": guard_case("cars", "engine.idle_rpm", car={"engine": {**engine, "idle_rpm": 100}}),
        "cars curve": guard_case("cars", "engine.curve", car={"engine": {**engine, "curve": []}}),
        "cars rpm": guard_case("cars", "engine.curve.rpm", car={"engine": {**engine, "curve": [{"rpm": 1000}, {"rpm": -1}]}}),
        "cars tune": guard_case("cars", "tune", car={"tune": 5}),
        "cars boost": guard_case("cars", "tune.boost", car={"tune": {"boost": 9}}),
        "tracks unknown key": guard_case("tracks", None, track={"lenght_m": 1}),
        "tracks id": guard_case("tracks", "id", track={"id": "other"}),
        "tracks gates": guard_case("tracks", "gates", track={"gates": "x"}),
        "tracks gate x": guard_case("tracks", "gates.x", track={"gates": [{"x": 0}, {"x": 999}]}),
    }


def test_datadefs_broken_case_guard_collects_the_key_paths_down_to_the_nested_keys():
    assert key_paths(GUARD_TABLES["cars"].fields) == ["id", "engine", "engine.idle_rpm", "engine.curve", "engine.curve.rpm", "tune", "tune.boost"]
    assert key_paths(GUARD_TABLES["tracks"].fields) == ["id", "gates", "gates.x"]
    assert key_paths(FAKE_TABLES["cars"].fields) == [
        "id", "name", "turbo", "sound", "gears", "engine", "engine.idle_rpm", "engine.curve", "engine.curve.rpm", "engine.curve.torque", "extras",
    ]
    assert key_paths(TABLES["cars"].fields) == ["id", "name", "data_version"]  # 実物は、まだ頭の階だけ
    # 問題の行の場所を、鍵の道にする。
    assert key_path_of("cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000", "cars", GUARD_TABLES) == "engine.curve.rpm"
    assert key_path_of("testpacks/p/cars.json:cars[12].id: duplicate id 'kazane'", "cars", GUARD_TABLES) == "id"
    assert key_path_of("tracks/test_loop.json:gates[1].x: 999 is outside -100..100", "tracks", GUARD_TABLES) == "gates.x"
    assert key_path_of("tracks/Test Loop.json:id: 'Test Loop' is not an id (lowercase ASCII, digits, _)", "tracks", GUARD_TABLES) == "id"
    for line in ("cars.json: duplicate key 'name'", "cars.json:cars: no entries", "cars.json:car: unknown key at the top level (only 'cars' and notes)"):
        assert key_path_of(line, "cars", GUARD_TABLES) == "", line


def test_datadefs_broken_case_guard_wants_a_case_for_every_key_path():
    full = guard_cases()
    # 並ぶはずの行は、1件ずつ、狙った鍵の道を指している（見本が、空振りでないこと）。
    assert full["cars rpm"][3] == ["cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000"]
    assert full["tracks gate x"][3] == ["tracks/test_loop.json:gates[1].x: 999 is outside -100..100"]
    assert all(len(want) == 1 for _, _, _, want in full.values())
    assert broken_case_problems(GUARD_TABLES, full) == []
    # 件を1つ抜くと、その鍵の道が挙がる。入れ子の中の鍵も、並びの中の項目の鍵も、省ける項目の中の鍵も、同じ
    # （頭の階の鍵 engine の件が残っていても、engine.idle_rpm の件が無ければ、通さない）。
    for case, (table, tag, _, _) in full.items():
        rest = {name: value for name, value in full.items() if name != case}
        missing = f"{table}: 知らない鍵か、空の表の、壊した場合が無い" if tag is None else f"{table}: 壊した場合の無い鍵：{tag}"
        assert broken_case_problems(GUARD_TABLES, rest) == [missing], case
    # 壊した場合の表が、表の定義に無い表を指す。
    stray = {**full, "sounds unknown key": ("sounds", None, {}, ["sounds.json:sounds[0].nmae: unknown key"])}
    assert broken_case_problems(GUARD_TABLES, stray) == ["sounds unknown key: 表の定義に無い表：sounds"]


def test_datadefs_broken_case_guard_checks_the_tag_against_the_place_of_the_lines():
    full = guard_cases()
    unknown_key, idle = full["cars unknown key"][3], full["cars idle"][3]

    def with_case(tag, want, name="cars idle") -> list:
        return broken_case_problems(GUARD_TABLES, {**full, name: ("cars", tag, {}, want)})

    # 札の申告が、行の場所と違う。知らない鍵を壊した件に、鍵の札を付けても、通らない。
    assert with_case("engine.idle_rpm", unknown_key) == ["cars idle: 札は engine.idle_rpm、行の場所は nmae"]
    # 頭の階の鍵の札で、入れ子の中の鍵の件を兼ねられない（逆も）。
    assert with_case("engine", idle, "cars engine") == ["cars engine: 札は engine、行の場所は engine.idle_rpm"]
    assert with_case("engine.idle_rpm", full["cars engine"][3]) == ["cars idle: 札は engine.idle_rpm、行の場所は engine"]
    # 行が2つあれば、どちらも、札の鍵の道を指す。
    assert with_case("engine.idle_rpm", [*idle, *unknown_key]) == ["cars idle: 札は engine.idle_rpm、行の場所は nmae"]
    # 項目の中を指さない行（ファイルの問題）。
    assert with_case("engine.idle_rpm", ["cars.json: duplicate key 'idle_rpm'"]) == ["cars idle: 札は engine.idle_rpm、行の場所は 項目の外"]
    # 並ぶはずの行が無い件は、札を確かめられない。
    assert with_case("engine.idle_rpm", []) == ["cars idle: 並ぶはずの行が無い"]
    # 札が None の件の行が、表の鍵を指している（鍵を壊した件を、知らない鍵の件として数えない）。
    assert with_case(None, idle, "cars unknown key") == ["cars unknown key: 札は None、行の場所は、鍵 engine.idle_rpm"]
    # 表に無い鍵の札。
    assert with_case("mass", ["cars.json:cars[0].mass: unknown key"], "cars mass") == ["cars mass: 札 mass は、表 cars の鍵の道に無い"]
    # レビューの見本：mass を壊していないのに、札だけ mass。
    assert with_case("mass", unknown_key, "cars mass") == ["cars mass: 札 mass は、表 cars の鍵の道に無い", "cars mass: 札は mass、行の場所は nmae"]
