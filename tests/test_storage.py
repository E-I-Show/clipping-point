"""保存の口（cp_core.storage）のテスト。封筒、鍵の検査、メモリの保存先、保存の口、知らせの文。

ファイルの保存先は tests/test_storage_file.py、localStorage の保存先は tests/test_storage_web.py、
保存先を選ぶ所は tests/test_storage_select.py、保存する項目と読み込みは tests/test_profile.py。
"""
import dataclasses
import struct
import zlib

import pytest

from cp_core import storage
from cp_core.storage import (
    BACKEND_METHODS,
    NOTICES,
    CorruptError,
    MemoryBackend,
    NewerVersionError,
    SaveStore,
    StorageError,
    StorageFull,
    check_key,
    check_namespace,
    unwrap,
    wrap,
)
from cp_ui import fixtures
from cp_ui.canvas import Canvas
from cp_ui.check import find_violations
from cp_ui.screens import SCREENS

PAYLOAD = b"hello world, this is a save"


class RefusingBackend(MemoryBackend):
    """決めた鍵への書き込みを、StorageFull で断る保存先。"""

    def __init__(self, refuse_suffix: str, error=StorageFull) -> None:
        super().__init__()
        self.refuse_suffix = refuse_suffix
        self.error = error

    def write(self, key, data) -> None:
        if key.endswith(self.refuse_suffix):
            raise self.error(key)
        super().write(key, data)


class UnreadableBackend(MemoryBackend):
    """読むと StorageError になる保存先。"""

    def read(self, key):
        raise StorageError(f"{key}: cannot be read")


# --- 封筒 ---
def test_storage_envelope_round_trips_and_adds_14_bytes():
    blob = wrap(PAYLOAD, 1)
    assert unwrap(blob) == (1, PAYLOAD)
    assert len(blob) == len(PAYLOAD) + 14
    assert blob[:4] == b"CPSV" == storage.MAGIC
    assert unwrap(wrap(b"", 7)) == (7, b"")
    assert unwrap(wrap(bytes(range(256)) * 40, 65535)) == (65535, bytes(range(256)) * 40)
    assert unwrap(wrap(bytearray(b"abc"), 2)) == (2, b"abc")


def test_storage_envelope_layout_is_magic_version_length_payload_crc32():
    blob = wrap(PAYLOAD, 0x0102)
    head = b"CPSV" + struct.pack("<HI", 0x0102, len(PAYLOAD))
    assert blob == head + PAYLOAD + struct.pack("<I", zlib.crc32(head + PAYLOAD))


def test_storage_envelope_detects_every_single_bit_flip():
    blob = wrap(PAYLOAD, 1)
    for index in range(len(blob)):
        for bit in range(8):
            damaged = bytearray(blob)
            damaged[index] ^= 1 << bit
            with pytest.raises(CorruptError):
                unwrap(bytes(damaged))
    assert unwrap(blob) == (1, PAYLOAD)


def test_storage_envelope_detects_every_truncation_and_extra_bytes():
    blob = wrap(PAYLOAD, 1)
    for length in range(len(blob)):
        with pytest.raises(CorruptError):
            unwrap(blob[:length])
    with pytest.raises(CorruptError):
        unwrap(blob + b"\x00")
    with pytest.raises(CorruptError):
        unwrap(b"")


@pytest.mark.parametrize("blob", [b"not an envelope at all", b"CPSV", b"XXXX" + wrap(PAYLOAD, 1)[4:], None, "CPSV", 5])
def test_storage_anything_that_is_not_an_envelope_is_corrupt(blob):
    with pytest.raises(CorruptError):
        unwrap(blob)


def test_storage_envelope_with_version_zero_is_corrupt():
    # 形式バージョン0は、書かない。チェックサムが合っていても、読めない封筒として扱う。
    head = b"CPSV" + struct.pack("<HI", 0, 3)
    with pytest.raises(CorruptError):
        unwrap(head + b"abc" + struct.pack("<I", zlib.crc32(head + b"abc")))


@pytest.mark.parametrize("version", [0, -1, 65536, 10**9, True, False, 1.0, "1", None])
def test_storage_wrap_rejects_a_format_version_out_of_range_as_a_storage_error(version):
    # struct.error を外へ出さない。
    with pytest.raises(StorageError):
        wrap(PAYLOAD, version)
    store = SaveStore(MemoryBackend())
    with pytest.raises(StorageError):
        store.put("settings", PAYLOAD, version)
    assert store.keys() == []  # 何も書いていない


@pytest.mark.parametrize("version", [1, 2, 65535])
def test_storage_wrap_accepts_the_whole_range_of_format_versions(version):
    assert unwrap(wrap(PAYLOAD, version)) == (version, PAYLOAD)


@pytest.mark.parametrize("payload", ["text", None, 5, ["a"]])
def test_storage_wrap_rejects_a_payload_that_is_not_bytes(payload):
    with pytest.raises(StorageError):
        wrap(payload, 1)


# --- 例外の型 ---
def test_storage_every_failure_is_a_storage_error():
    for child in (CorruptError, StorageFull, NewerVersionError):
        assert issubclass(child, StorageError)
    assert issubclass(StorageError, Exception)
    assert len({CorruptError, StorageFull, NewerVersionError}) == 3


# --- 鍵の検査 ---
@pytest.mark.parametrize("key", ["settings", "a", "replay.01", "ghost.akane_short.kazane-rs", "x" * 48, "0", "a_b-c.d"])
def test_storage_good_keys_pass(key):
    assert check_key(key) == key


@pytest.mark.parametrize("key", ["", "UPPER", "sp ace", "a/b", "a\\b", "x" * 49, "日本語", "a:b", "a\n", None, 5, b"key"])
def test_storage_bad_keys_are_refused(key):
    with pytest.raises(StorageError):
        check_key(key)
    store = SaveStore(MemoryBackend())
    for call in (lambda: store.put(key, b"", 1), lambda: store.get(key), lambda: store.delete(key), lambda: store.quarantine(key)):
        with pytest.raises(StorageError):
            call()
    assert store.backend.items == {}


@pytest.mark.parametrize("namespace", ["a.b", ".", "main.", "", "MAIN", "x" * 49, "a/b"])
def test_storage_namespace_cannot_contain_a_dot_or_other_bad_characters(namespace):
    with pytest.raises(StorageError):
        check_namespace(namespace)
    with pytest.raises(StorageError):
        SaveStore(MemoryBackend(), namespace)


def test_storage_default_namespace_is_main():
    backend = MemoryBackend()
    SaveStore(backend).put("settings", PAYLOAD, 1)
    assert backend.keys() == ["main.settings"]
    assert SaveStore(backend).namespace == "main" == storage.DEFAULT_NAMESPACE


# --- メモリの保存先 ---
def test_storage_memory_backend_has_the_four_methods_of_a_backend():
    assert BACKEND_METHODS == ("read", "write", "delete", "keys")
    backend = MemoryBackend()
    assert all(callable(getattr(backend, name)) for name in BACKEND_METHODS)


def test_storage_memory_backend_reads_writes_deletes_and_lists():
    backend = MemoryBackend()
    assert backend.read("a") is None and backend.keys() == []
    backend.write("b", b"2")
    backend.write("a", bytearray(b"1"))
    assert backend.read("a") == b"1" and type(backend.read("a")) is bytes
    assert backend.keys() == ["a", "b"]  # 整列している
    backend.delete("a")
    backend.delete("a")  # 無い鍵でも、黙る
    assert backend.keys() == ["b"]


def test_storage_memory_backend_over_capacity_changes_nothing():
    backend = MemoryBackend(capacity=100)
    backend.write("a", b"1" * 50)
    with pytest.raises(StorageFull):
        backend.write("b", b"2" * 51)
    assert backend.keys() == ["a"] and backend.read("a") == b"1" * 50
    # 同じ鍵の書き直しは、古い値の分を数えない。
    backend.write("a", b"3" * 100)
    with pytest.raises(StorageFull):
        backend.write("a", b"4" * 101)
    assert backend.read("a") == b"3" * 100
    backend.write("a", b"")
    backend.write("b", b"5" * 100)  # ちょうど上限は、書ける


def test_storage_store_reports_a_full_backend_and_keeps_the_old_value():
    store = SaveStore(MemoryBackend(capacity=100))
    store.put("a", b"1" * 50, 1)
    with pytest.raises(StorageFull):
        store.put("b", b"2" * 80, 1)
    with pytest.raises(StorageFull):
        store.put("a", b"3" * 90, 1)
    assert store.keys() == ["a"] and store.get("a") == (1, b"1" * 50)


# --- 保存の口 ---
def test_storage_store_round_trips_and_lists_its_keys():
    store = SaveStore(MemoryBackend())
    payload = bytes(range(256)) * 40
    assert store.get("replay.01") is None
    store.put("replay.01", payload, 3)
    store.put("ghost.akane_short.kazane_rs", b"", 1)
    assert store.get("replay.01") == (3, payload)
    assert store.get("ghost.akane_short.kazane_rs") == (1, b"")
    assert store.keys() == ["ghost.akane_short.kazane_rs", "replay.01"]
    assert store.used_bytes() == len(payload) + 2 * 14
    store.delete("replay.01")
    store.delete("replay.01")  # 無い鍵でも、黙る
    assert store.get("replay.01") is None and store.keys() == ["ghost.akane_short.kazane_rs"]


def test_storage_namespaces_do_not_mix():
    backend = MemoryBackend()
    main, other, longer = SaveStore(backend, "main"), SaveStore(backend, "selfcheck"), SaveStore(backend, "main2")
    main.put("settings", b"main", 1)
    other.put("settings", b"other", 1)
    longer.put("settings", b"longer", 1)
    assert main.get("settings") == (1, b"main") and other.get("settings") == (1, b"other") and longer.get("settings") == (1, b"longer")
    assert main.keys() == other.keys() == longer.keys() == ["settings"]
    assert backend.keys() == ["main.settings", "main2.settings", "selfcheck.settings"]
    other.delete("settings")
    assert main.get("settings") == (1, b"main") and other.get("settings") is None
    assert main.used_bytes() == 4 + 14 and other.used_bytes() == 0


def test_storage_get_of_a_damaged_value_is_a_corrupt_error():
    backend = MemoryBackend()
    store = SaveStore(backend)
    store.put("settings", PAYLOAD, 1)
    backend.items["main.settings"] = backend.items["main.settings"][:-1]
    with pytest.raises(CorruptError):
        store.get("settings")


# --- 退避 ---
def test_storage_quarantine_copies_the_raw_bytes_and_removes_the_key():
    backend = MemoryBackend()
    store = SaveStore(backend)
    raw = b"\x00\xffthis was never an envelope"
    backend.items["main.settings"] = raw
    assert store.quarantine("settings") is True
    assert backend.items == {"main.settings.bad": raw}  # 封筒を開けずに、そのまま写す
    assert store.get("settings") is None
    assert store.keys() == ["settings.bad"]


def test_storage_quarantine_of_a_missing_key_does_nothing():
    backend = MemoryBackend()
    assert SaveStore(backend).quarantine("settings") is False
    assert backend.items == {}


def test_storage_quarantine_works_for_a_key_of_the_longest_length():
    # 退避の鍵（<鍵>.bad）は52字になる。鍵の検査を通さずに作る。
    backend = MemoryBackend()
    store = SaveStore(backend)
    key = "k" * 48
    backend.items["main." + key] = b"broken"
    assert store.quarantine(key) is True
    assert backend.items == {"main." + key + ".bad": b"broken"}


def test_storage_quarantine_replaces_an_older_quarantined_value():
    backend = MemoryBackend()
    store = SaveStore(backend)
    backend.items.update({"main.settings": b"new broken", "main.settings.bad": b"old broken"})
    store.quarantine("settings")
    assert backend.items == {"main.settings.bad": b"new broken"}


@pytest.mark.parametrize("error", [StorageFull, StorageError])
def test_storage_quarantine_that_cannot_write_keeps_the_key_and_is_storage_full(error):
    backend = RefusingBackend(".bad", error)
    store = SaveStore(backend)
    backend.items["main.settings"] = b"broken"
    with pytest.raises(StorageFull):
        store.quarantine("settings")
    assert backend.items == {"main.settings": b"broken"}  # 元の鍵は、消していない


def test_storage_quarantine_lets_a_read_error_of_the_backend_through():
    store = SaveStore(UnreadableBackend())
    with pytest.raises(StorageError) as caught:
        store.quarantine("settings")
    assert type(caught.value) is StorageError


# --- 新しい形式バージョンの値を、上書きしない守り ---
def test_storage_put_refuses_to_overwrite_a_newer_format_version():
    backend = MemoryBackend()
    store = SaveStore(backend)
    store.put("settings", b"from the future", 3)
    before = dict(backend.items)
    for version in (1, 2):
        with pytest.raises(NewerVersionError):
            store.put("settings", b"older build", version)
    assert backend.items == before
    assert store.get("settings") == (3, b"from the future")


def test_storage_put_overwrites_the_same_and_older_format_versions():
    store = SaveStore(MemoryBackend())
    store.put("settings", b"one", 1)
    store.put("settings", b"one again", 1)
    assert store.get("settings") == (1, b"one again")
    store.put("settings", b"two", 2)
    assert store.get("settings") == (2, b"two")


def test_storage_put_overwrites_a_damaged_value():
    backend = MemoryBackend()
    store = SaveStore(backend)
    backend.items["main.settings"] = b"garbage"
    store.put("settings", PAYLOAD, 1)
    assert store.get("settings") == (1, PAYLOAD)


def test_storage_put_guard_only_looks_at_its_own_key_and_namespace():
    backend = MemoryBackend()
    SaveStore(backend, "other").put("settings", b"future", 9)
    SaveStore(backend).put("controls", b"future", 9)
    SaveStore(backend).put("settings", b"now", 1)
    assert SaveStore(backend).get("settings") == (1, b"now")


def test_storage_put_reports_a_backend_that_cannot_be_read():
    store = SaveStore(UnreadableBackend())
    with pytest.raises(StorageError):
        store.put("settings", PAYLOAD, 1)
    assert store.backend.items == {}


# --- 知らせの文 ---
def test_storage_notices_are_the_four_documented_ones():
    assert NOTICES == (
        storage.NOTICE_MEMORY_FALLBACK, storage.NOTICE_UNREADABLE, storage.NOTICE_NEWER_VERSION, storage.NOTICE_BACKEND_UNREADABLE,
    )
    assert len(set(NOTICES)) == 4 and all(NOTICES)


@pytest.mark.parametrize("notice", NOTICES)
def test_storage_notices_are_printable_ascii_in_upper_case_on_one_line(notice):
    assert type(notice) is str and notice.isascii() and notice.isprintable()
    assert all(32 <= ord(char) <= 126 for char in notice)
    assert notice == notice.upper() and notice == notice.strip() and "\n" not in notice


@pytest.mark.parametrize("notice", NOTICES)
@pytest.mark.parametrize("variant", fixtures.VARIANTS)
def test_storage_every_notice_fits_the_placeholder_screen(notice, variant):
    # 全部の文を、見本データを通して、はみ出しの検査に掛ける。
    view = dataclasses.replace(fixtures.build("placeholder", variant), notice=notice)
    canvas = Canvas()
    SCREENS["placeholder"](canvas, view)
    assert notice in [command.text for command in canvas.commands if command.kind == "text"]
    assert find_violations(canvas) == []


def test_storage_extreme_fixture_carries_the_longest_notice():
    longest = fixtures.build("placeholder", "extreme").notice
    assert longest in NOTICES and len(longest) == max(len(notice) for notice in NOTICES)
