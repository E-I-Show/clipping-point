import pytest

from cp_core.storage import CorruptError, FileBackend, MemoryBackend, SaveStore, StorageError, StorageFull, unwrap, wrap


def backends(tmp_path):
    return [MemoryBackend(), FileBackend(tmp_path / "saves")]


def test_storage_round_trip_on_every_backend(tmp_path):
    payload = bytes(range(256)) * 40
    for backend in backends(tmp_path):
        store = SaveStore(backend, "main")
        assert store.get("replay.01") is None
        store.put("replay.01", payload, version=3)
        store.put("ghost.akane_short.kazane_rs", b"")
        assert store.get("replay.01") == (3, payload)
        assert store.get("ghost.akane_short.kazane_rs") == (1, b"")
        assert store.keys("replay.") == ["replay.01"]
        assert store.used_bytes() == len(payload) + 2 * 14
        other = SaveStore(backend, "pack_extreme")
        assert other.get("replay.01") is None and other.keys() == []  # namespaces do not mix
        store.delete("replay.01")
        assert store.get("replay.01") is None


def test_storage_detects_every_single_byte_corruption_and_truncation():
    blob = wrap(b"hello world, this is a save", 1)
    for i in range(len(blob)):
        bad = bytearray(blob)
        bad[i] ^= 0x01
        with pytest.raises(CorruptError):
            unwrap(bytes(bad))
        with pytest.raises(CorruptError):
            unwrap(blob[:i])
    assert unwrap(blob) == (1, b"hello world, this is a save")


def test_storage_file_write_is_atomic_and_syncs_once(tmp_path):
    backend = FileBackend(tmp_path / "saves")
    store = SaveStore(backend)
    store.put("profile", b"old")
    before = backend.fsyncs
    store.put("profile", b"x" * 800_000)
    assert backend.fsyncs - before == 1
    assert sorted(p.name for p in (tmp_path / "saves").iterdir()) == ["main.profile.sav"]  # no temp file left
    # a crash between "write temp" and "replace" leaves the old save readable
    (tmp_path / "saves" / "main.profile.tmp").write_bytes(b"half written")
    assert store.get("profile") == (1, b"x" * 800_000)
    assert store.keys() == ["profile"]


def test_storage_full_changes_nothing_and_bad_keys_are_refused():
    store = SaveStore(MemoryBackend(capacity=100))
    store.put("a", b"1" * 50)
    with pytest.raises(StorageFull):
        store.put("b", b"2" * 80)
    assert store.keys() == ["a"] and store.get("a") == (1, b"1" * 50)
    for bad in ("", "UPPER", "sp ace", "a/b", "x" * 49):
        with pytest.raises(StorageError):
            store.put(bad, b"")
