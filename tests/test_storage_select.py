"""保存先を選ぶ所（cp_app.storage_select）のテスト。偽の js と、環境の辞書を渡す。pyxel は読み込まない。

ブラウザ版の切り替えが、実物のブラウザで働くことは、道具 web-smoke の筋書き storage_blocked が見る。
"""
import pytest

from cp_app import storage_select
from cp_app.storage_file import FileBackend
from cp_app.storage_select import BACKEND_FILE, BACKEND_MEMORY, BACKEND_WEB, SAVE_DIR_ENV, Selected, select
from cp_app.storage_web import WebStorageBackend
from cp_core import storage
from cp_core.profile import SELFCHECK_SETTINGS, Settings, load_settings, save_settings
from cp_core.storage import MemoryBackend, SaveStore, StorageFull
from test_storage_web import JS_NULL, BlockedJs, FakeJs, FakeJsException, FakeStorage, JsWithoutStorage


# --- ブラウザ版：試し書きの3通り ---
def test_storage_select_working_local_storage_is_used_without_a_notice():
    fake = FakeStorage()
    selected = select(FakeJs(fake), {})
    assert isinstance(selected.backend, WebStorageBackend)
    assert (selected.name, selected.notice) == ("localstorage", "") == (BACKEND_WEB, "")
    assert fake.calls == ["setItem", "getItem", "removeItem"]  # 試し書きをしている
    assert fake.items == {}
    # 選んだ保存先で、保存の往復ができる。
    store = SaveStore(selected.backend)
    save_settings(store, SELFCHECK_SETTINGS)
    assert load_settings(store).settings == SELFCHECK_SETTINGS
    assert sorted(fake.items) == ["clippingpoint/main.settings"]


def test_storage_select_full_local_storage_is_kept_without_a_notice():
    # 容量超過。読みは生きているので、localStorage のまま使う。書き込みは、失敗として返る。
    fake = FakeStorage(quota=0)
    selected = select(FakeJs(fake), {})
    assert isinstance(selected.backend, WebStorageBackend)
    assert (selected.name, selected.notice) == (BACKEND_WEB, "")
    store = SaveStore(selected.backend)
    assert load_settings(store) == load_settings(SaveStore(MemoryBackend()))  # 鍵が無い。既定値、知らせ無し
    with pytest.raises(StorageFull):
        save_settings(store, SELFCHECK_SETTINGS)


@pytest.mark.parametrize("js", [
    BlockedJs(),
    BlockedJs(FakeJsException("Error")),
    JsWithoutStorage(),
    FakeJs(None),
    FakeJs(JS_NULL),
    FakeJs(FakeStorage(fail={"setItem": FakeJsException("SecurityError")})),
    FakeJs(FakeStorage(fail={"getItem": FakeJsException("Error")})),
    FakeJs(FakeStorage(fail={"removeItem": RuntimeError("no name")})),
])
def test_storage_select_unusable_local_storage_falls_back_to_memory_with_the_notice(js):
    selected = select(js, {})
    assert isinstance(selected.backend, MemoryBackend)
    assert selected.name == "memory" == BACKEND_MEMORY
    assert selected.notice == storage.NOTICE_MEMORY_FALLBACK and selected.notice in storage.NOTICES
    # 切り替えた先で、保存の往復ができる（このセッションの中だけで持つ）。
    store = SaveStore(selected.backend)
    save_settings(store, SELFCHECK_SETTINGS)
    assert load_settings(store).settings == SELFCHECK_SETTINGS


def test_storage_select_browser_does_not_read_the_environment():
    # ブラウザ版には、環境変数が無い。渡されても、読まない（相対パスでも、例外にしない）。
    selected = select(FakeJs(FakeStorage()), {SAVE_DIR_ENV: "relative/saves"})
    assert selected.name == BACKEND_WEB


def test_storage_select_each_fallback_gets_its_own_memory():
    a, b = select(BlockedJs(), {}), select(BlockedJs(), {})
    a.backend.write("main.settings", b"x")
    assert b.backend.keys() == []


# --- デスクトップ版：CP_SAVE_DIR ---
def test_storage_select_desktop_with_a_save_directory_uses_files(tmp_path):
    saves = tmp_path / "saves"
    selected = select(None, {SAVE_DIR_ENV: str(saves)})
    assert isinstance(selected.backend, FileBackend)
    assert (selected.name, selected.notice) == ("file", "") == (BACKEND_FILE, "")
    assert not saves.exists()  # 選んだだけでは、置き場を作らない
    save_settings(SaveStore(selected.backend), SELFCHECK_SETTINGS)
    assert sorted(path.name for path in saves.iterdir()) == ["main.settings.sav"]
    assert load_settings(SaveStore(select(None, {SAVE_DIR_ENV: str(saves)}).backend)).settings == SELFCHECK_SETTINGS


@pytest.mark.parametrize("env", [{}, {SAVE_DIR_ENV: ""}, {"CP_SMOKE": "/tmp/result.json"}])
def test_storage_select_desktop_without_a_save_directory_uses_memory_without_a_notice(env):
    selected = select(None, env)
    assert isinstance(selected.backend, MemoryBackend)
    assert (selected.name, selected.notice) == (BACKEND_MEMORY, "")
    assert load_settings(SaveStore(selected.backend)).settings == Settings()


@pytest.mark.parametrize("path", ["saves", "./saves", "out/run/saves", "../saves"])
def test_storage_select_desktop_relative_save_directory_is_an_error(path):
    # pyxel.init が作業ディレクトリを変えるので、相対パスは受けない。起動時に落とす。
    with pytest.raises(ValueError):
        select(None, {SAVE_DIR_ENV: path})


def test_storage_select_names_and_the_environment_variable_are_the_documented_ones():
    assert SAVE_DIR_ENV == "CP_SAVE_DIR"
    assert (BACKEND_WEB, BACKEND_FILE, BACKEND_MEMORY) == ("localstorage", "file", "memory")
    assert [field for field in Selected.__dataclass_fields__] == ["backend", "name", "notice"]


def test_storage_select_tools_do_not_pass_an_outside_save_directory_to_the_app(monkeypatch):
    # 道具は、外から入った CP_SAVE_DIR を、子プロセスへ渡さない（渡すのは、道具が自分で決めた置き場だけ）。
    import _common

    monkeypatch.setenv(SAVE_DIR_ENV, "/somewhere/else")
    assert SAVE_DIR_ENV not in _common.child_env()
    assert _common.child_env(**{SAVE_DIR_ENV: "/tmp/x"})[SAVE_DIR_ENV] == "/tmp/x"
    assert SAVE_DIR_ENV.startswith(_common.APP_ENV_PREFIXES)


def test_storage_select_module_does_not_import_pyxel_or_js():
    import ast

    from conftest import ROOT

    tree = ast.parse((ROOT / "clipping_point" / "cp_app" / "storage_select.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0] if node.level == 0 else "." + (node.module or ""))
    assert imported == {"os", "dataclasses", "cp_core", ".storage_file", ".storage_web"}
    assert storage_select.select.__module__ == "cp_app.storage_select"
