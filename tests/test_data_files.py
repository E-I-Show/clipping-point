"""定義データのファイルを読む所（cp_app.data_files）のテスト。一時の置き場（tmp_path）の中だけで書く。pyxel は読み込まない。

読み込み検査そのものは tests/test_datadefs.py。ここでは、置き場の下のファイルを、名を挙げて読む所、試験用データの置き場を
読む所、環境の辞書と js で分かれる所、実物の置き場（clipping_point/data/ と testpacks/）が読めることを見る。
アプリ（cp_app/app.py）が、読み込んだ定義の保存の名前空間を、設定を読む保存の口へ渡していることは、ソースを読んで見る
（守りのテスト。pyxel を読み込まない）。実物のアプリでの確かめは、道具 run（`python3 tools/run.py --pack extreme`）。
"""
import ast
import json
import os

import pytest

from conftest import ROOT
from cp_app import data_files
from cp_app.data_files import PACK_ENV, load, read_pack, read_sources
from cp_core import datadefs
from cp_core.datadefs import DataError
from test_datadefs import real_assist, real_camera, real_car, real_loop, real_palette
from test_screens import APP_PY, app_method, is_attribute_of, is_self_attribute, self_attribute_values

# 一時の置き場に置く項目。実物の項目を読んで作る（鍵が増えても、見本が、足りない鍵の問題を出さない）。
CAR, TRACK, ASSIST, CAMERA, PALETTE = real_car(), real_loop(), real_assist(), real_camera(), real_palette()
PACKS = ROOT / "testpacks"
ONE_OF_EACH = {"cars": 1, "tracks": 1, "assists": 1, "cameras": 1, "palettes": 1}  # 出荷するデータの、表ごとの件数
# 表のファイルが1つも無いときに並ぶ行（表の定義の順）。
ALL_MISSING = ["cars.json: missing file", "tracks/: no entry files", "assists.json: missing file", "cameras.json: missing file", "palettes.json: missing file"]


def write(path, value) -> None:
    """ファイルを1つ置く。value が文字列ならそのまま、バイト列ならバイト列のまま、ほかはJSONにして書く。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if type(value) is bytes:
        path.write_bytes(value)
    else:
        path.write_text(value if type(value) is str else json.dumps(value), encoding="utf-8")


def good_data(tmp_path):
    """読み込み検査を通る、最小の置き場。返すのは、置き場。"""
    data = tmp_path / "data"
    write(data / "cars.json", {"cars": [CAR]})
    write(data / "tracks" / "test_loop.json", TRACK)
    write(data / "assists.json", {"assists": [ASSIST]})
    write(data / "cameras.json", {"cameras": [CAMERA]})
    write(data / "palettes.json", {"palettes": [PALETTE]})
    return data


def good_pack(tmp_path, name: str = "extreme"):
    """重ねられる、最小の試験用データ。返すのは、試験用データの根。"""
    root = tmp_path / "testpacks"
    write(root / name / "cars.json", {"cars": [{**CAR, "name": "PACKED", "data_version": 2}, {**CAR, "id": "extra", "name": "EXTRA"}]})
    return root


# --- 置き場を読む ---
def test_data_files_reads_every_file_under_the_directory_by_its_relative_name(tmp_path):
    data = good_data(tmp_path)
    sources = read_sources(data)
    assert list(sources) == ["assists.json", "cameras.json", "cars.json", "palettes.json", "tracks/test_loop.json"]  # 名は / 区切りで、整列した順
    assert json.loads(sources["cars.json"]) == {"cars": [CAR]} and json.loads(sources["tracks/test_loop.json"]) == TRACK
    assert json.loads(sources["assists.json"]) == {"assists": [ASSIST]}
    assert json.loads(sources["cameras.json"]) == {"cameras": [CAMERA]} and json.loads(sources["palettes.json"]) == {"palettes": [PALETTE]}
    assert read_sources(str(data)) == sources  # 文字列のパスでも、同じ


def test_data_files_names_the_files_that_fit_neither_shape_too(tmp_path):
    # 2つの形に当たらない名（.json でない、深い階、知らない名）も、読んで、名を挙げて渡す。問題にするのは datadefs。
    data = good_data(tmp_path)
    for name in ("notes.txt", "sounds.json", "tracks/deep/x.json", "tracks/readme.md", "zz/a/b/c.json", ".hidden"):
        write(data / name, "x")
    sources = read_sources(data)
    assert list(sources) == sorted([
        ".hidden", "assists.json", "cameras.json", "cars.json", "notes.txt", "palettes.json", "sounds.json",
        "tracks/deep/x.json", "tracks/readme.md", "tracks/test_loop.json", "zz/a/b/c.json",
    ])
    with pytest.raises(DataError) as info:
        datadefs.load_game_data(sources)
    assert list(info.value.problems) == [f"{name}: unknown file (no table reads this name)" for name in sorted([".hidden", "notes.txt", "sounds.json", "tracks/deep/x.json", "tracks/readme.md", "zz/a/b/c.json"])]


def test_data_files_file_that_cannot_be_read_is_handed_over_as_none(tmp_path):
    data = good_data(tmp_path)
    write(data / "cars.json", b'{"cars": [{"id": "kazane", "name": "KAZANE \xff\xfe", "data_version": 1}]}')  # UTF-8でない
    (data / "tracks" / "broken_link.json").symlink_to(data / "tracks" / "no_such_file.json")  # 開けない（OSError）
    sources = read_sources(data)
    assert sources["cars.json"] is None and sources["tracks/broken_link.json"] is None
    assert type(sources["tracks/test_loop.json"]) is str
    with pytest.raises(DataError) as info:
        datadefs.load_game_data(sources)
    assert list(info.value.problems) == ["cars.json: cannot read the file", "tracks/broken_link.json: cannot read the file"]


def test_data_files_missing_or_empty_directory_reads_as_nothing(tmp_path):
    assert read_sources(tmp_path / "no_such_data") == {}
    (tmp_path / "empty" / "tracks").mkdir(parents=True)
    assert read_sources(tmp_path / "empty") == {}  # ディレクトリだけでは、何も無い
    with pytest.raises(DataError) as info:
        load({}, None, tmp_path / "no_such_data", tmp_path / "testpacks")
    assert list(info.value.problems) == ALL_MISSING


# --- 試験用データの置き場を読む ---
def test_data_files_reads_a_pack_in_the_same_shape(tmp_path):
    root = good_pack(tmp_path)
    write(root / "extreme" / "tracks" / "wide.json", {**TRACK, "id": "wide", "name": "WIDE"})
    write(root / "extreme" / "notes.txt", "x")
    name, files = read_pack("extreme", root)
    assert name == "extreme" and list(files) == ["cars.json", "notes.txt", "tracks/wide.json"]
    assert read_pack("extreme", str(root)) == (name, files)


@pytest.mark.parametrize("name", ["", "Extreme", "extreme pack", "a-b", "a.b", "..", "../extreme", "extreme/", "a" * 44, None, 5])
def test_data_files_pack_name_with_other_characters_or_too_long_is_a_value_error(tmp_path, name):
    # 名は id と同じ字で、43字まで。置き場があっても、名の字が違えば受けない（置き場の外を指す名も）。
    root = good_pack(tmp_path)
    if type(name) is str and name and "/" not in name and name not in ("..",):
        write(root / name / "cars.json", {"cars": [CAR]})
    with pytest.raises(ValueError) as info:
        read_pack(name, root)
    assert not isinstance(info.value, DataError)


def test_data_files_longest_pack_name_is_accepted(tmp_path):
    root = good_pack(tmp_path, "a" * 43)
    assert read_pack("a" * 43, root)[0] == "a" * 43
    assert load({PACK_ENV: "a" * 43}, None, good_data(tmp_path), root).save_namespace == "pack_" + "a" * 43


def test_data_files_missing_or_empty_pack_directory_is_a_value_error(tmp_path):
    root = good_pack(tmp_path)
    with pytest.raises(ValueError, match="no test pack directory"):
        read_pack("nosuch", root)
    with pytest.raises(ValueError, match="no test pack directory"):
        read_pack("extreme", tmp_path / "no_such_root")
    # 置き場はあるが、ファイルが1つも無い（ディレクトリだけ）。空の置き場を、重ねたことにしない。
    (root / "empty" / "tracks").mkdir(parents=True)
    with pytest.raises(ValueError, match="has no files"):
        read_pack("empty", root)
    # 置き場の名の所に、ファイルがある。
    write(root / "plain_file", "x")
    with pytest.raises(ValueError, match="no test pack directory"):
        read_pack("plain_file", root)
    for name in ("nosuch", "empty", "plain_file"):
        with pytest.raises(ValueError) as info:
            load({PACK_ENV: name}, None, good_data(tmp_path / name), root)
        assert not isinstance(info.value, DataError)


# --- 読み込み。環境の辞書と js で分かれる ---
def test_data_files_desktop_without_the_variable_loads_the_shipped_data_only(tmp_path):
    data, root = good_data(tmp_path), good_pack(tmp_path)
    for env in ({}, {PACK_ENV: ""}, {"CP_SMOKE": "/tmp/result.json", "CP_SAVE_DIR": "/tmp/saves"}):
        loaded = load(env, None, data, root)
        assert loaded.pack is None and loaded.save_namespace == "main"
        assert loaded.counts() == ONE_OF_EACH and loaded.entry("cars", "kazane") == CAR


def test_data_files_desktop_with_the_variable_overlays_the_pack(tmp_path):
    data, root = good_data(tmp_path), good_pack(tmp_path)
    loaded = load({PACK_ENV: "extreme"}, None, data, root)
    assert loaded.pack == "extreme" and loaded.save_namespace == "pack_extreme"
    assert loaded.ids("cars") == ("kazane", "extra") and loaded.entry("cars", "kazane")["name"] == "PACKED"
    assert json.loads((data / "cars.json").read_text(encoding="utf-8")) == {"cars": [CAR]}  # 元のファイルは変わらない


def test_data_files_browser_does_not_read_the_environment(tmp_path):
    # ブラウザ版には、環境変数が無い。渡されても、読まない（無い名でも、例外にしない）。試験用データは、出荷物に入らない。
    data, root = good_data(tmp_path), good_pack(tmp_path)
    js = object()
    for env in ({PACK_ENV: "extreme"}, {PACK_ENV: "nosuch"}, {PACK_ENV: "Bad Name"}, {}):
        loaded = load(env, js, data, root)
        assert loaded.pack is None and loaded.save_namespace == "main" and loaded.ids("cars") == ("kazane",)


def test_data_files_problems_of_the_pack_come_out_of_load_as_a_data_error(tmp_path):
    data, root = good_data(tmp_path), good_pack(tmp_path)
    write(root / "extreme" / "cars.json", {"cars": [{**CAR, "name": "K" * 15}]})
    write(root / "extreme" / "notes.txt", "x")
    with pytest.raises(DataError) as info:
        load({PACK_ENV: "extreme"}, None, data, root)
    assert list(info.value.problems) == [
        "testpacks/extreme/notes.txt: unknown file (no table reads this name)",
        f"testpacks/extreme/cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)",
    ]
    assert load({}, None, data, root).pack is None  # 重ねなければ、通る


# --- 実物の置き場 ---
def test_data_files_real_directories_are_found_from_the_place_of_the_module():
    # 作業ディレクトリに頼らない（pyxel.init が変える）。置き場は、モジュールの場所から引いた絶対パス。
    assert os.path.isabs(data_files.DATA_DIR) and os.path.isabs(data_files.PACKS_ROOT)
    assert os.path.samefile(data_files.DATA_DIR, ROOT / "clipping_point" / "data")
    assert os.path.samefile(data_files.PACKS_ROOT, PACKS)  # 試験用データは、clipping_point/ の外（出荷物に入らない）
    assert not (ROOT / "clipping_point" / "testpacks").exists()
    assert PACK_ENV == "CP_DATA_PACK"


def test_data_files_real_shipped_data_loads_with_the_default_places():
    loaded = load({}, None)
    assert loaded.warnings == () and loaded.pack is None and loaded.counts() == ONE_OF_EACH


def test_data_files_every_real_pack_loads_on_top_of_the_shipped_data():
    names = sorted(path.name for path in PACKS.iterdir())
    assert names and "extreme" in names
    assert all((PACKS / name).is_dir() for name in names), "testpacks/ の直下に、置き場でないファイルがある"
    plain = load({}, None)
    for name in names:
        loaded = load({PACK_ENV: name}, None)
        assert loaded.pack == name and loaded.save_namespace == f"pack_{name}"
        assert set(plain.ids("cars")) <= set(loaded.ids("cars")) and set(plain.ids("tracks")) <= set(loaded.ids("tracks"))
    # extreme：車の名を14字に差し替え、14字の名の車を1台と、14字の名のコースを1本足す。
    extreme = load({PACK_ENV: "extreme"}, None)
    assert extreme.counts() == {**ONE_OF_EACH, "cars": 2, "tracks": 2}  # 重ねなかった表（操作補正、カメラ、パレット）は、そのまま
    assert len(extreme.entry("cars", "kazane")["name"]) == 14 != len(plain.entry("cars", "kazane")["name"])
    added_cars = [ident for ident in extreme.ids("cars") if ident not in plain.ids("cars")]
    added_tracks = [ident for ident in extreme.ids("tracks") if ident not in plain.ids("tracks")]
    assert len(added_cars) == 1 and len(extreme.entry("cars", added_cars[0])["name"]) == datadefs.NAME_MAX
    assert len(added_tracks) == 1 and len(extreme.entry("tracks", added_tracks[0])["name"]) == datadefs.NAME_MAX
    assert load({}, None).entry("cars", "kazane") == plain.entry("cars", "kazane")  # 元は変わらない
    # 車とコースの、走りの値と形は、出荷するデータと同じ値（違うのは、id と表示名だけ。極端な走りの値は、ここでは試さない）。
    real_kazane, real_test_loop = plain.entry("cars", "kazane"), plain.entry("tracks", "test_loop")
    for ident in extreme.ids("cars"):
        assert {**extreme.entry("cars", ident), "id": "kazane", "name": "KAZANE"} == real_kazane, ident
    assert extreme.entry("tracks", "test_loop") == real_test_loop
    assert {**extreme.entry("tracks", added_tracks[0]), "id": "test_loop", "name": "TEST LOOP"} == real_test_loop


def test_data_files_real_packs_say_in_their_notes_that_they_are_never_shipped():
    for path in sorted(PACKS.rglob("*.json")):
        notes = json.loads(path.read_text(encoding="utf-8")).get("_notes")
        assert notes and "試験用データ" in json.dumps(notes, ensure_ascii=False) and "出荷物に入らない" in json.dumps(notes, ensure_ascii=False), path


# --- 守りのテスト ---
def test_data_files_tools_do_not_pass_an_outside_data_pack_to_the_app(monkeypatch):
    # 道具は、外から入った CP_DATA_PACK を、子プロセスへ渡さない（渡すのは、道具が自分で決めた名だけ）。
    import _common

    monkeypatch.setenv(PACK_ENV, "extreme")
    assert PACK_ENV not in _common.child_env()
    assert _common.child_env(**{PACK_ENV: "other"})[PACK_ENV] == "other"
    assert PACK_ENV.startswith(_common.APP_ENV_PREFIXES)


def test_data_files_module_does_not_import_pyxel_or_js():
    tree = ast.parse((ROOT / "clipping_point" / "cp_app" / "data_files.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0] if node.level == 0 else "." + (node.module or ""))
    assert imported == {"os", "cp_core"}
    assert data_files.load.__module__ == "cp_app.data_files"


def calls_of(function, owner: str, name: str) -> list:
    """function の中の、owner.name(...) の呼び出しの一覧。"""
    return [call for call in ast.walk(function) if isinstance(call, ast.Call) and is_attribute_of(call.func, owner, name)]


def test_data_files_app_loads_the_data_at_start_and_gives_its_namespace_to_the_settings_store():
    # 守りのテスト。段0の起動は、設定を書かない。アプリが、保存の口へ名前空間を渡し忘れても、保存のファイルでは分からない。
    # ここでは、ソースの上のつながりを見る。実物のアプリでは、道具 run が、結果の data の namespace で見る。
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    # (1) main() が、保存先を選んだ後、巡回の口とアプリを作る前に、定義データを1度だけ読む。
    loads, selects, tours = calls_of(main, "data_files", "load"), calls_of(main, "storage_select", "select"), calls_of(main, "tour", "read_config")
    apps = [call for call in ast.walk(main) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "App"]
    assert len(loads) == len(selects) == len(tours) == len(apps) == 1
    assert selects[0].lineno < loads[0].lineno < tours[0].lineno < apps[0].lineno
    assert len(loads[0].args) == 2 and is_attribute_of(loads[0].args[0], "os", "environ")
    assert isinstance(loads[0].args[1], ast.Name) and loads[0].args[1].id == "js"
    # (2) 読み込んだ定義を、アプリへ渡す（2番目の引数）。
    bound = [node for node in ast.walk(main) if isinstance(node, ast.Assign) and node.value is loads[0]]
    assert len(bound) == 1 and isinstance(bound[0].targets[0], ast.Name)
    assert isinstance(apps[0].args[1], ast.Name) and apps[0].args[1].id == bound[0].targets[0].id
    # (3) __init__() が、設定を読む保存の口を1つだけ作り、名前空間に、読み込んだ定義の保存の名前空間を渡す。
    init = app_method("__init__")
    assert [arg.arg for arg in init.args.args][:3] == ["self", "selected", "data"]
    stores = self_attribute_values(init, "store")
    assert len(stores) == 1 and isinstance(stores[0], ast.Call) and isinstance(stores[0].func, ast.Name) and stores[0].func.id == "SaveStore"
    namespaces = [*stores[0].args[1:2], *(keyword.value for keyword in stores[0].keywords if keyword.arg == "namespace")]
    assert len(namespaces) == 1 and is_attribute_of(namespaces[0], "data", "save_namespace")
    # (4) 設定は、その保存の口から読む（別の保存の口を、その場で作らない）。
    reads = calls_of(init, "profile", "load_settings")
    assert len(reads) == 1 and len(reads[0].args) == 1 and is_self_attribute(reads[0].args[0], "store")
    made = [call for call in ast.walk(init) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "SaveStore"]
    assert len(made) == 1
    # (5) 結果の名前空間は、設定を読んだ保存の口から取る。読み込んだ定義の側の値（save_namespace）を、直に入れない。
    report = app_method("data_report")
    assert not [node for node in ast.walk(report) if isinstance(node, ast.Attribute) and node.attr == "save_namespace"]
    from_store = [node for node in ast.walk(report) if isinstance(node, ast.Attribute) and node.attr == "namespace" and is_self_attribute(node.value, "store")]
    assert len(from_store) == 1
    # (6) 結果の2つの口（画面なしで回す口と、外から渡す値）が、どちらも data_report() を呼ぶ。
    for name in ("finish_run", "finish_probe"):
        calls = [call for call in ast.walk(app_method(name)) if isinstance(call, ast.Call) and is_self_attribute(call.func, "data_report")]
        assert len(calls) == 1, name
