"""道具 check（tools/check.py）の、data の節の関数（data_sets）のテスト。一時の置き場（tmp_path）と、作り物の表の定義で回す。

道具を別プロセスで回すこと（実物の定義データを壊すと、`check --only data` が1になること）は、道具 selftest-break が見る。
ここでは、節の関数が、調べた組の数と、問題の一覧を、決めたとおりに返すことを見る。
  件数は、調べた組の数（読み込み検査まで届いた組。問題があった組も数える）。全部の組に問題があっても、0にならない
  （0だと、道具 check は「何も調べていない」の2にする。問題があるのだから、1のはず）。
  出荷するデータの警告は、問題として数える。実物の表の定義には、参照が無いので、警告は、作り物の表の定義で起こす。
読み込み検査そのものは tests/test_datadefs.py、ファイルを読む所は tests/test_data_files.py。
"""
import json

import check
from conftest import ROOT
from cp_core.datadefs import ONE_ENTRY, ONE_TABLE, Ident, Label, Ref, TableDef

# 作り物の表の定義。車が、音を参照する。参照されていない音は、警告になる。
TABLES = {
    "sounds": TableDef(ONE_TABLE, {"id": Ident(), "name": Label(14)}),
    "cars": TableDef(ONE_TABLE, {"id": Ident(), "name": Label(14), "sound": Ref("sounds")}),
    "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "name": Label(14)}),
}
SOUND = {"id": "eng_na", "name": "ENGINE"}
CAR = {"id": "kazane", "name": "KAZANE", "sound": "eng_na"}
TRACK = {"id": "test_loop", "name": "TEST LOOP"}


def write(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value), encoding="utf-8")


def places(tmp_path, sounds=None, cars=None, packs=None) -> tuple:
    """一時の置き場と、試験用データの根を作る。packs は {名: {相対の名: 中身}}。返すのは (置き場, 試験用データの根)。"""
    data, root = tmp_path / "data", tmp_path / "testpacks"
    write(data / "sounds.json", {"sounds": [SOUND] if sounds is None else sounds})
    write(data / "cars.json", {"cars": [CAR] if cars is None else cars})
    write(data / "tracks" / "test_loop.json", TRACK)
    for name, files in (packs or {}).items():
        (root / name).mkdir(parents=True, exist_ok=True)
        for rel, value in files.items():
            write(root / name / rel, value)
    return data, root


def test_check_tool_clean_data_counts_the_shipped_set_and_every_pack(tmp_path):
    more = {"cars.json": {"cars": [{"id": "wide", "name": "W" * 14, "sound": "eng_na"}]}}
    data, root = places(tmp_path, packs={"extreme": more, "other": {"tracks/extra.json": {"id": "extra", "name": "EXTRA"}}})
    assert check.data_sets(data, root, TABLES) == (3, [])  # 出荷するデータと、試験用データ2つ


def test_check_tool_no_pack_directory_still_counts_the_shipped_set(tmp_path):
    # 試験用データは、あるだけ調べる。0個でもよい（根が無くても、空でも）。
    data, root = places(tmp_path)
    assert not root.exists()
    assert check.data_sets(data, root, TABLES) == (1, [])
    root.mkdir()
    assert check.data_sets(data, root, TABLES) == (1, [])


def test_check_tool_warning_in_the_shipped_data_is_counted_as_a_problem(tmp_path):
    # どこからも参照されていない定義。読み込みは通る（警告）。道具 check は、問題に数える。
    data, root = places(tmp_path, sounds=[SOUND, {"id": "sfx_unused", "name": "UNUSED"}])
    assert check.data_sets(data, root, TABLES) == (1, ["(shipped) warning: sounds.sfx_unused: defined but never referenced"])


def test_check_tool_warning_only_in_a_pack_set_is_not_counted(tmp_path):
    # 試験用データが足した、参照されていない定義は、問題に数えない（警告0件を見張るのは、出荷するデータ）。
    pack = {"sounds.json": {"sounds": [{"id": "sfx_trial", "name": "TRIAL"}]}}
    data, root = places(tmp_path, packs={"trial": pack})
    assert check.data_sets(data, root, TABLES) == (2, [])


def test_check_tool_problems_of_the_shipped_data_are_listed_once(tmp_path):
    # 出荷するデータの問題は、出荷するデータの組で1度だけ挙げる（試験用データを重ねた組で、同じ行を繰り返さない）。
    cars = [{**CAR, "nmae": "X"}, {"id": "second", "name": "K" * 15, "sound": "nobody"}]
    data, root = places(tmp_path, cars=cars, packs={"extreme": {"tracks/extra.json": {"id": "extra", "name": "EXTRA"}}})
    assert check.data_sets(data, root, TABLES) == (2, [
        "(shipped) cars.json:cars[0].nmae: unknown key",
        f"(shipped) cars.json:cars[1].name: '{'K' * 15}' is 15 characters (at most 14)",
        "(shipped) cars.json:cars[1].sound: no sounds with id 'nobody'",
    ])


def test_check_tool_problems_of_a_pack_are_listed_under_its_name(tmp_path):
    bad = {"cars.json": {"cars": [{"id": "kazane", "name": "カザネ", "sound": "eng_na"}]}, "notes.txt": "x"}
    data, root = places(tmp_path, packs={"broken": bad, "fine": {"tracks/extra.json": {"id": "extra", "name": "EXTRA"}}})
    assert check.data_sets(data, root, TABLES) == (3, [
        "(broken) testpacks/broken/notes.txt: unknown file (no table reads this name)",
        "(broken) testpacks/broken/cars.json:cars[0].name: 'カザネ' has characters outside printable ASCII",
    ])


def test_check_tool_count_is_the_number_of_sets_even_when_every_set_has_problems(tmp_path):
    # 全部の組に問題がある。件数は、調べた組の数（2）。0にしない（0だと、道具 check は、1でなく2を返してしまう）。
    pack = {"cars.json": {"cars": [{"id": "wide", "name": "W" * 15, "sound": "eng_na"}]}}
    data, root = places(tmp_path, cars=[{**CAR, "nmae": "X"}], packs={"extreme": pack})
    count, problems = check.data_sets(data, root, TABLES)
    assert count == 2
    assert problems == [
        "(shipped) cars.json:cars[0].nmae: unknown key",
        f"(extreme) testpacks/extreme/cars.json:cars[0].name: '{'W' * 15}' is 15 characters (at most 14)",
    ]
    # 置き場そのものが無くても、出荷するデータの組は、読み込み検査まで届く（表のファイルが無い、という問題になる）。
    count, problems = check.data_sets(tmp_path / "no_such_data", tmp_path / "no_such_packs", TABLES)
    assert count == 1 and problems == ["(shipped) sounds.json: missing file", "(shipped) cars.json: missing file", "(shipped) tracks/: no entry files"]


def test_check_tool_pack_that_cannot_be_overlaid_is_a_problem_and_not_a_set(tmp_path):
    # 空の置き場、名の字が違う置き場、根の直下のファイル。黙って飛ばさない。読み込み検査まで届かないので、組には数えない。
    data, root = places(tmp_path, packs={"fine": {"tracks/extra.json": {"id": "extra", "name": "EXTRA"}}})
    (root / "empty" / "tracks").mkdir(parents=True)
    write(root / "Bad Name" / "cars.json", {"cars": [CAR]})
    write(root / "readme.txt", "x")
    count, problems = check.data_sets(data, root, TABLES)
    assert count == 2  # 出荷するデータと、fine
    assert len(problems) == 3
    assert problems[0].startswith("testpacks/Bad Name: 重ねられない：") and "bad test pack name" in problems[0]
    assert problems[1].startswith("testpacks/empty: 重ねられない：") and "has no files" in problems[1]
    assert problems[2].startswith("testpacks/readme.txt: 試験用データの置き場（ディレクトリ）でない")


def test_check_tool_real_data_section_passes_and_counts_the_real_sets():
    # いまのリポジトリ。出荷するデータと、testpacks/ の下の全部の試験用データ。
    packs = sorted(path.name for path in (ROOT / "testpacks").iterdir() if path.is_dir())
    assert "extreme" in packs
    assert check.data() == (1 + len(packs), [])
    assert check.SECTIONS["data"] is check.data and list(check.SECTIONS)[-1] == "data"
