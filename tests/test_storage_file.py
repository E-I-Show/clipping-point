"""ファイルの保存先（cp_app.storage_file）のテスト。一時の置き場（tmp_path）の中だけで回す。pyxel は読み込まない。

道具 run（`python3 tools/run.py`）が、実物のアプリに置き場を渡して、書かれたファイルを自分で読んで照らす。
"""
import os

import pytest

from cp_app import storage_file
from cp_app.storage_file import FileBackend
from cp_core.storage import BACKEND_METHODS, CorruptError, SaveStore, StorageError, StorageFull


def names_in(directory) -> list:
    return sorted(path.name for path in directory.iterdir())


def test_storage_file_backend_has_the_four_methods_of_a_backend(tmp_path):
    backend = FileBackend(tmp_path / "saves")
    assert all(callable(getattr(backend, name)) for name in BACKEND_METHODS)


def test_storage_file_round_trips_through_the_store(tmp_path):
    saves = tmp_path / "saves"
    store = SaveStore(FileBackend(saves))
    payload = bytes(range(256)) * 40
    assert store.get("replay.01") is None and store.keys() == []  # 置き場が、まだ無い
    assert not saves.exists()
    store.put("replay.01", payload, 3)
    store.put("settings", b"", 1)
    assert store.get("replay.01") == (3, payload) and store.get("settings") == (1, b"")
    assert store.keys() == ["replay.01", "settings"]
    assert store.used_bytes() == len(payload) + 2 * 14
    assert names_in(saves) == ["main.replay.01.sav", "main.settings.sav"]  # 1つの鍵が、1つのファイル
    # 別の保存先の物として読み直しても、同じ（ファイルに残っている）。
    assert SaveStore(FileBackend(saves)).get("replay.01") == (3, payload)
    store.delete("replay.01")
    store.delete("replay.01")  # 無い鍵でも、黙る
    assert store.get("replay.01") is None and names_in(saves) == ["main.settings.sav"]


def test_storage_file_namespaces_do_not_mix(tmp_path):
    backend = FileBackend(tmp_path)
    SaveStore(backend, "main").put("settings", b"main", 1)
    SaveStore(backend, "selfcheck").put("settings", b"check", 1)
    assert SaveStore(backend, "main").get("settings") == (1, b"main")
    assert SaveStore(backend, "selfcheck").get("settings") == (1, b"check")
    assert names_in(tmp_path) == ["main.settings.sav", "selfcheck.settings.sav"]


def test_storage_file_write_leaves_no_temporary_file_and_syncs_once(tmp_path):
    backend = FileBackend(tmp_path)
    store = SaveStore(backend)
    store.put("settings", b"old", 1)
    before = backend.fsyncs
    store.put("settings", b"x" * 800_000, 1)
    assert backend.fsyncs - before == 1  # 書き込み1回につき、fsync は1回
    assert names_in(tmp_path) == ["main.settings.sav"]  # 一時ファイルが残っていない
    assert store.get("settings") == (1, b"x" * 800_000)


def test_storage_file_fsync_is_called_once_per_write_before_the_replace(tmp_path, monkeypatch):
    calls = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(storage_file.os, "fsync", lambda fd: (calls.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(storage_file.os, "replace", lambda src, dst: (calls.append("replace"), real_replace(src, dst))[1])
    backend = FileBackend(tmp_path)
    backend.write("main.settings", b"one")
    backend.write("main.settings", b"two")
    assert calls == ["fsync", "replace", "fsync", "replace"]
    assert backend.fsyncs == 2


def test_storage_file_leftover_temporary_file_does_not_hide_the_old_save(tmp_path):
    # 一時ファイルに書いた後、差し替える前に止まった形。古い保存は、読めるまま。
    backend = FileBackend(tmp_path)
    store = SaveStore(backend)
    store.put("settings", b"old", 1)
    (tmp_path / "main.settings.tmp").write_bytes(b"half written")
    assert store.get("settings") == (1, b"old")
    assert store.keys() == ["settings"] and backend.keys() == ["main.settings"]  # 一時ファイルは、鍵の一覧に出ない
    store.put("settings", b"new", 1)  # 次の書き込みは、残った一時ファイルを上書きして通る
    assert store.get("settings") == (1, b"new")
    assert names_in(tmp_path) == ["main.settings.sav"]


def test_storage_file_other_files_in_the_directory_are_not_keys(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".sav").write_bytes(b"x")
    backend = FileBackend(tmp_path)
    backend.write("a", b"1")
    assert backend.keys() == ["a"]


def test_storage_file_failed_replace_is_storage_full_and_keeps_the_old_save(tmp_path, monkeypatch):
    backend = FileBackend(tmp_path)
    store = SaveStore(backend)
    store.put("settings", b"old", 1)

    def refuse(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(storage_file.os, "replace", refuse)
    with pytest.raises(StorageFull):
        store.put("settings", b"new", 1)
    assert store.get("settings") == (1, b"old")
    assert names_in(tmp_path) == ["main.settings.sav"]  # 一時ファイルは、消してある


def test_storage_file_directory_that_cannot_be_made_is_storage_full(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    backend = FileBackend(blocker / "saves")
    with pytest.raises(StorageFull):
        backend.write("main.settings", b"x")
    # 保存の口は、書く前に、いまある値を読む。置き場が壊れていると、その読みが先に StorageError になる。
    with pytest.raises(StorageError):
        SaveStore(backend).put("settings", b"x", 1)
    assert blocker.read_text(encoding="utf-8") == "a file where the directory should be"


def test_storage_file_read_error_other_than_a_missing_file_is_a_storage_error(tmp_path):
    backend = FileBackend(tmp_path)
    assert backend.read("main.settings") is None  # 無いファイルは、None
    (tmp_path / "main.settings.sav").mkdir()  # ファイルの名の所に、ディレクトリがある
    with pytest.raises(StorageError) as caught:
        backend.read("main.settings")
    assert type(caught.value) is StorageError
    with pytest.raises(StorageError):
        SaveStore(backend).get("settings")


def test_storage_file_listing_and_deleting_report_os_errors_as_storage_errors(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    backend = FileBackend(blocker)  # 置き場の名の所に、ファイルがある
    with pytest.raises(StorageError):
        backend.keys()
    with pytest.raises(StorageError):
        backend.delete("main.settings")
    assert FileBackend(tmp_path / "missing").keys() == []


@pytest.mark.parametrize("key", ["", "../outside", "a/b", "a\\b", "UPPER", None, "sp ace"])
def test_storage_file_keys_that_could_leave_the_directory_are_refused(tmp_path, key):
    backend = FileBackend(tmp_path / "saves")
    for call in (lambda: backend.read(key), lambda: backend.write(key, b"x"), lambda: backend.delete(key)):
        with pytest.raises(StorageError):
            call()
    assert names_in(tmp_path) == []


def test_storage_file_damaged_file_reads_as_a_corrupt_value(tmp_path):
    store = SaveStore(FileBackend(tmp_path))
    store.put("settings", b"payload", 1)
    path = tmp_path / "main.settings.sav"
    path.write_bytes(path.read_bytes()[:-1])  # 最後の1バイトが欠けた
    with pytest.raises(CorruptError):
        store.get("settings")
    assert store.quarantine("settings") is True
    assert names_in(tmp_path) == ["main.settings.bad.sav"]


def test_storage_file_accepts_a_path_object_or_a_string(tmp_path):
    FileBackend(tmp_path / "a").write("k", b"1")
    FileBackend(str(tmp_path / "b")).write("k", b"2")
    assert FileBackend(str(tmp_path / "a")).read("k") == b"1" and FileBackend(tmp_path / "b").read("k") == b"2"
