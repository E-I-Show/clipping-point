"""道具 run（tools/run.py）の、保存のファイルを自分で読む関数のテスト。一時の置き場（tmp_path）の中だけで回す。Pyxelは使わない。

アプリを別プロセスで回すこと（終了コード、結果ファイルの有無、古い結果、世界の要約、保存の往復の申告）は、道具 selftest-break が見る。
ここでは、道具が、保存の往復が残したファイルを読んで、往復の見本と比べる所（read_saved_settings）と、
ふつうの保存（名前空間 main）のファイルを挙げる所（main_namespace_files）を見る。
合っている場合だけでなく、合わない場合（違う値、違う形式バージョン、壊れた封筒、ファイルが無い）が、どれも落ちること。
定義データ（結果の data の確かめ、試験用データを重ねて回す口 --pack）は、道具が使う関数（tools/data_reference.py）を、
道具 run の使い方で見る。数え方と確かめの1つずつは tests/test_data_reference.py。
"""
import dataclasses

import pytest

import run as run_tool
from cp_app.storage_file import FileBackend
from cp_core import profile, storage
from cp_core.storage import SaveStore

SELFCHECK_FILE = "selfcheck.settings.sav"  # 保存の往復が残すファイルの名
MAIN_FILE = "main.settings.sav"  # ふつうの保存の、設定のファイルの名


def blob_of(settings=profile.SELFCHECK_SETTINGS, version: int = profile.SETTINGS_VERSION) -> bytes:
    """設定の、封筒つきの値。既定は、往復の見本。"""
    return storage.wrap(profile.encode(settings), version)


SAMPLE = blob_of()


def saves_with(tmp_path, blob: bytes = SAMPLE, name: str = SELFCHECK_FILE):
    """置き場を作って、ファイルを1つ、バイト列のまま置く。返すのは、置き場。"""
    saves = tmp_path / "saves"
    saves.mkdir(parents=True)
    (saves / name).write_bytes(blob)
    return saves


# --- 保存の往復が残したファイルを読む ---
def test_run_tool_reads_the_file_that_the_round_trip_of_the_app_leaves(tmp_path):
    # アプリと同じ道（ファイルの保存先で、保存の往復を回す）で書かせたファイルを、道具が読める。ファイルの名も、ここで合う。
    saves = tmp_path / "saves"
    assert profile.selfcheck(FileBackend(saves)) == (True, "")
    assert sorted(path.name for path in saves.iterdir()) == [SELFCHECK_FILE]
    assert (saves / SELFCHECK_FILE).read_bytes() == SAMPLE
    ok, _ = run_tool.read_saved_settings(saves)
    assert ok is True
    assert run_tool.main_namespace_files(saves) == []


def test_run_tool_saved_file_equal_to_the_sample_passes(tmp_path):
    ok, message = run_tool.read_saved_settings(saves_with(tmp_path))
    assert ok is True and type(message) is str


@pytest.mark.parametrize(
    "settings",
    [
        profile.Settings(),  # 既定値（往復の終わりに、既定値で書き直した形）
        dataclasses.replace(profile.SELFCHECK_SETTINGS, race_serial=profile.SELFCHECK_SETTINGS.race_serial + 1),  # 1項目だけ違う
        dataclasses.replace(profile.SELFCHECK_SETTINGS, assist=not profile.SELFCHECK_SETTINGS.assist),
    ],
)
def test_run_tool_saved_file_with_another_value_fails(tmp_path, settings):
    # 封筒は読める。本体が、往復の見本と違う。「封筒が読めれば合格」にしない。
    ok, message = run_tool.read_saved_settings(saves_with(tmp_path, blob_of(settings)))
    assert ok is False and "往復の見本と違う" in message and SELFCHECK_FILE in message


@pytest.mark.parametrize("version", [profile.SETTINGS_VERSION + 1, profile.SETTINGS_VERSION + 7, storage.VERSION_MAX])
def test_run_tool_saved_file_with_another_format_version_fails(tmp_path, version):
    # 本体は往復の見本と同じ。形式バージョンだけが違う。
    ok, message = run_tool.read_saved_settings(saves_with(tmp_path, blob_of(version=version)))
    assert ok is False and "往復の見本と違う" in message and f"形式バージョン {version}" in message


@pytest.mark.parametrize(
    "blob",
    [
        SAMPLE[:-1],  # 最後の1バイトが欠けた
        bytes([SAMPLE[0] ^ 1]) + SAMPLE[1:],  # 印の1ビットが違う
        SAMPLE[:-1] + bytes([SAMPLE[-1] ^ 0x80]),  # チェックサムの1ビットが違う
        SAMPLE + b"\x00",  # 1バイト長い
        b"",
        b"not an envelope",
        profile.encode(profile.SELFCHECK_SETTINGS),  # 封筒の無い、本体だけ
    ],
)
def test_run_tool_saved_file_with_a_damaged_envelope_fails(tmp_path, blob):
    ok, message = run_tool.read_saved_settings(saves_with(tmp_path, blob))
    assert ok is False and "封筒が読めない" in message and SELFCHECK_FILE in message


def test_run_tool_missing_saved_file_fails(tmp_path):
    # 置き場が無い（アプリが、1度も書いていない）。
    ok, message = run_tool.read_saved_settings(tmp_path / "no_such_saves")
    assert ok is False and "読めない" in message and SELFCHECK_FILE in message
    # 置き場はあるが、空。
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_tool.read_saved_settings(empty)[0] is False
    # 往復の見本と同じ値が、別の名（名前空間 main、一時ファイル、退避の鍵）にあっても、読まない。
    for index, name in enumerate((MAIN_FILE, "selfcheck.settings.tmp", "selfcheck.settings.bad.sav", "selfcheck.settings")):
        ok, message = run_tool.read_saved_settings(saves_with(tmp_path / f"other_{index}", name=name))
        assert ok is False and "読めない" in message, name
    # ファイルの名の所に、ディレクトリがある。
    folder = tmp_path / "folder"
    (folder / SELFCHECK_FILE).mkdir(parents=True)
    assert run_tool.read_saved_settings(folder)[0] is False


def test_run_tool_saved_file_name_is_built_from_the_names_the_app_uses():
    name = f"{profile.SELFCHECK_NAMESPACE}{storage.NAMESPACE_SEPARATOR}{profile.SETTINGS_KEY}{run_tool.storage_file.SUFFIX}"
    assert name == SELFCHECK_FILE


# --- ふつうの保存（名前空間 main）のファイル ---
def test_run_tool_main_namespace_files_are_listed_in_order(tmp_path):
    saves = saves_with(tmp_path)
    assert run_tool.main_namespace_files(saves) == []  # 保存の往復のファイルだけ
    for name in ("main.settings.sav", "main.settings.bad.sav", "main.controls.sav", "mainline.settings.sav", "selfcheck.main.sav", "pack.main.settings.sav"):
        (saves / name).write_bytes(b"x")
    # 名前空間 main のものだけ（名の頭が「main.」）。中身は見ない。
    assert run_tool.main_namespace_files(saves) == ["main.controls.sav", "main.settings.bad.sav", "main.settings.sav"]


def test_run_tool_main_namespace_file_written_through_the_store_is_seen(tmp_path):
    # 保存の往復を、名前空間 main で回した形（アプリの申告は「通った」になる）。道具は、ファイルで見分ける。
    saves = tmp_path / "saves"
    SaveStore(FileBackend(saves)).put(profile.SETTINGS_KEY, profile.encode(profile.SELFCHECK_SETTINGS), profile.SETTINGS_VERSION)
    assert run_tool.main_namespace_files(saves) == [MAIN_FILE]
    ok, message = run_tool.read_saved_settings(saves)
    assert ok is False and "読めない" in message  # 名前空間 selfcheck のファイルは、できていない


# --- 定義データと、試験用データを重ねて回す口（--pack） ---
def test_run_tool_passes_the_pack_by_the_variable_the_app_reads_and_counts_by_itself():
    # 道具は、アプリが読む環境変数の名で、試験用データの名を渡す。外から入った値は、子プロセスへ渡さない。
    import _common

    assert run_tool.data_files.PACK_ENV == "CP_DATA_PACK"
    assert run_tool.data_files.PACK_ENV.startswith(_common.APP_ENV_PREFIXES)
    # 結果の data と照らす件数は、道具が、定義データのファイルを自分で読んで数える（数え方のテストは tests/test_data_reference.py）。
    assert run_tool.data_reference.expected_tables() == ({"cars": 1, "tracks": 1, "assists": 1}, "")
    assert run_tool.data_reference.expected_tables("extreme") == ({"cars": 2, "tracks": 2, "assists": 1}, "")


def test_run_tool_result_data_of_a_plain_run_and_of_a_pack_run():
    checks = run_tool.data_reference.data_checks
    plain = {"data": {"tables": {"cars": 1, "tracks": 1}, "warnings": 0, "pack": None, "namespace": "main"}}
    packed = {"data": {"tables": {"cars": 2, "tracks": 2}, "warnings": 0, "pack": "extreme", "namespace": "pack_extreme"}}
    assert [name for name, ok, _ in checks(plain, {"cars": 1, "tracks": 1}, None) if not ok] == []
    assert [name for name, ok, _ in checks(packed, {"cars": 2, "tracks": 2}, "extreme") if not ok] == []
    # 試験用データを渡したのに、重ねていない結果（重ねる口を読まない）。
    assert [name for name, ok, _ in checks(plain, {"cars": 2, "tracks": 2}, "extreme") if not ok] == ["data_tables", "data_pack", "data_namespace"]
    # 重ねたのに、設定を読む保存の口の名前空間が main のまま。
    packed["data"]["namespace"] = storage.DEFAULT_NAMESPACE
    assert [name for name, ok, _ in checks(packed, {"cars": 2, "tracks": 2}, "extreme") if not ok] == ["data_namespace"]


def test_run_tool_pack_that_is_missing_or_empty_is_found_before_the_app_runs(tmp_path):
    # --pack の名に当たる置き場が無い、置き場にファイルが1つも無い、は回り切れない（2）。アプリを回す前に見る。
    reason = run_tool.data_reference.pack_or_reason
    assert reason("extreme") == ""
    assert reason("no_such_pack_zz") and reason("Bad Name")
    (tmp_path / "empty").mkdir()
    assert reason("empty", tmp_path) and reason("nosuch", tmp_path)


def test_run_tool_main_namespace_files_of_a_missing_or_empty_directory_are_none(tmp_path):
    assert run_tool.main_namespace_files(tmp_path / "no_such_saves") == []
    assert run_tool.main_namespace_files(tmp_path) == []
    not_a_directory = tmp_path / "file"
    not_a_directory.write_bytes(b"x")
    assert run_tool.main_namespace_files(not_a_directory) == []
