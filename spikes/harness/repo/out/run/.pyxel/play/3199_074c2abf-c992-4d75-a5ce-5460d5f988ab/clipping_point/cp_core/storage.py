"""One persistence layer for desktop (files) and browser (localStorage). Pure Python.

  SaveStore(backend)            envelope (magic, version, length, crc32) + size accounting
    backend = FileBackend(dir)      desktop: temp file + fsync once + os.replace (atomic)
    backend = MemoryBackend()       tests
    backend = WebStorageBackend()   browser: cp_app.storage_web (the only part that touches `js`)

A backend stores opaque bytes under short ASCII keys. Everything above it is the same code on
both platforms, so the round-trip tests that run natively also cover the browser code path
except the 60 lines of the web backend itself (covered by tools/web_smoke.py).
"""
import os
import struct
import zlib
from pathlib import Path

MAGIC = b"CPSV"
ENVELOPE = struct.Struct("<4sHI")  # magic, format version, payload length ; then payload ; then crc32
KEY_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_.-")


class StorageError(Exception):
    pass


class CorruptError(StorageError):
    """The stored bytes are not a complete envelope (truncated, edited, wrong file)."""


class StorageFull(StorageError):
    """The backend refused the write. Nothing was changed."""


def check_key(key: str) -> str:
    if not key or len(key) > 48 or not set(key) <= KEY_CHARS:
        raise StorageError(f"bad storage key {key!r} (lowercase ASCII, digits, _ . - ; max 48)")
    return key


def wrap(payload: bytes, version: int) -> bytes:
    head = ENVELOPE.pack(MAGIC, version, len(payload))
    return head + payload + struct.pack("<I", zlib.crc32(head + payload))


def unwrap(blob: bytes):
    if len(blob) < ENVELOPE.size + 4:
        raise CorruptError("too short")
    magic, version, length = ENVELOPE.unpack_from(blob)
    if magic != MAGIC:
        raise CorruptError("bad magic")
    if len(blob) != ENVELOPE.size + length + 4:
        raise CorruptError(f"length mismatch (header says {length}, have {len(blob) - ENVELOPE.size - 4})")
    (crc,) = struct.unpack_from("<I", blob, ENVELOPE.size + length)
    if zlib.crc32(blob[: ENVELOPE.size + length]) != crc:
        raise CorruptError("checksum mismatch")
    return version, blob[ENVELOPE.size : ENVELOPE.size + length]


class MemoryBackend:
    def __init__(self, capacity: int | None = None) -> None:
        self.items: dict = {}
        self.capacity = capacity
        self.writes = 0

    def read(self, key: str):
        return self.items.get(key)

    def write(self, key: str, data: bytes) -> None:
        if self.capacity is not None:
            total = sum(len(v) for k, v in self.items.items() if k != key) + len(data)
            if total > self.capacity:
                raise StorageFull(key)
        self.items[key] = bytes(data)
        self.writes += 1

    def delete(self, key: str) -> None:
        self.items.pop(key, None)

    def keys(self) -> list:
        return sorted(self.items)


class FileBackend:
    """One file per key in one directory. A write is: temp file -> flush -> fsync -> os.replace."""

    def __init__(self, directory) -> None:
        self.dir = Path(directory)
        self.fsyncs = 0

    def _path(self, key: str) -> Path:
        return self.dir / (key + ".sav")

    def read(self, key: str):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def write(self, key: str, data: bytes) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(key).with_suffix(".tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)  # the whole blob at once
                f.flush()
                os.fsync(f.fileno())  # exactly one sync per save
                self.fsyncs += 1
            os.replace(tmp, self._path(key))
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise StorageFull(f"{key}: {exc}") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def keys(self) -> list:
        if not self.dir.is_dir():
            return []
        return sorted(p.stem for p in self.dir.glob("*.sav"))


class SaveStore:
    """What the game talks to. `namespace` separates test data packs from the real saves."""

    def __init__(self, backend, namespace: str = "main") -> None:
        self.backend = backend
        self.prefix = check_key(namespace) + "."

    def put(self, key: str, payload: bytes, version: int = 1) -> None:
        self.backend.write(self.prefix + check_key(key), wrap(payload, version))

    def get(self, key: str):
        """-> (version, payload) or None. Raises CorruptError; the caller decides what to do
        (the profile loader keeps the broken blob under '<key>.bad' and starts from defaults)."""
        blob = self.backend.read(self.prefix + check_key(key))
        return None if blob is None else unwrap(blob)

    def quarantine(self, key: str) -> None:
        blob = self.backend.read(self.prefix + key)
        if blob is not None:
            self.backend.write(self.prefix + key + ".bad", blob)
            self.backend.delete(self.prefix + key)

    def delete(self, key: str) -> None:
        self.backend.delete(self.prefix + check_key(key))

    def keys(self, starts_with: str = "") -> list:
        n = len(self.prefix)
        return [k[n:] for k in self.backend.keys() if k.startswith(self.prefix + starts_with)]

    def used_bytes(self, starts_with: str = "") -> int:
        return sum(len(self.backend.read(self.prefix + k) or b"") for k in self.keys(starts_with))
