"""保存の口と、保存先の決まり（純Python）。決まりは docs/design/overview.md の「決定性と保存」。

保存は、保存の口と保存先の2つに分ける。出荷するコードは、保存の口だけを使う。ファイルや localStorage を、直に触らない。
  保存の口（SaveStore）  値に封筒を付けて、保存先へ渡す。保存先での鍵は「<名前空間>.<鍵>」。
  保存先                 値を実際に置く所。次の4つを持つ。値はバイト列、鍵は短いASCII。
      read(key)          バイト列。無ければ None
      write(key, data)   書く。書けなければ StorageFull（何も変わっていない）
      delete(key)        消す。無い鍵でも、黙る
      keys()             鍵の一覧（整列した list）
    保存先は3つ。メモリ（MemoryBackend。ここ）、ファイル（cp_app/storage_file.py）、localStorage（cp_app/storage_web.py）。
    選ぶのは cp_app/storage_select.py。保存先の失敗（読めない、書けない）は、StorageError かその子で返す。
封筒は、印（CPSV）、形式バージョン（16ビット）、本体の長さ（32ビット）、本体、チェックサム（crc32）。本体より14バイト長い。
読めない封筒（短い、印が違う、長さが違う、チェックサムが違う）は、壊れた値（CorruptError）。
「自分より新しい形式バージョンの値がある鍵には、上書きしない」の守りは、put に置く（呼ぶ側には置かない）。
知らせの文（画面に1行で出す文）は、全部ここの定数に置く。見本データ（cp_ui）が、いちばん長い文を引くため。
"""
import struct
import zlib

MAGIC = b"CPSV"  # 封筒の印
ENVELOPE = struct.Struct("<4sHI")  # 印、形式バージョン、本体の長さ。この後ろに、本体とチェックサムが続く
CHECKSUM = struct.Struct("<I")  # 頭と本体の crc32
VERSION_MIN, VERSION_MAX = 1, 65535  # 形式バージョンの範囲（16ビット。0は使わない）
PAYLOAD_MAX = 0xFFFFFFFF  # 本体の長さの上限（32ビット）
KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_.-")  # 保存の鍵に使える字
KEY_MAX = 48  # 保存の鍵の長さの上限（字）
NAMESPACE_SEPARATOR = "."  # 名前空間と鍵の間の字。名前空間には使えない
BAD_SUFFIX = ".bad"  # 壊れた値を退避する鍵の、後ろに付ける字
DEFAULT_NAMESPACE = "main"  # ふつうの保存の名前空間
BACKEND_METHODS = ("read", "write", "delete", "keys")  # 保存先が持つ4つの口

# 知らせの文。印字できるASCIIの大文字で、仮の表示の囲みに収まる長さ（全部の文を tests/test_storage.py が、はみ出しの検査に掛ける）。
NOTICE_MEMORY_FALLBACK = "SAVE STORAGE UNAVAILABLE. PROGRESS WILL NOT BE KEPT"  # 保存先を、メモリへ切り替えた
NOTICE_UNREADABLE = "SAVE DATA UNREADABLE. USING DEFAULTS"  # 保存が読めないので、既定値で動かす
NOTICE_NEWER_VERSION = "SAVE DATA IS FROM A NEWER VERSION. NOT SAVING"  # 保存が新しい形式バージョンなので、保存しない
NOTICE_BACKEND_UNREADABLE = "SAVE STORAGE CANNOT BE READ. USING DEFAULTS"  # 保存先が読めない
NOTICES = (NOTICE_MEMORY_FALLBACK, NOTICE_UNREADABLE, NOTICE_NEWER_VERSION, NOTICE_BACKEND_UNREADABLE)


class StorageError(Exception):
    """保存の失敗の親。保存の口と保存先は、失敗を、この型かその子で返す。"""


class CorruptError(StorageError):
    """壊れた値。保存先にあるバイト列が、読める封筒でない。"""


class StorageFull(StorageError):
    """書けない。保存先は、何も変わっていない。"""


class NewerVersionError(StorageError):
    """新しい形式バージョンの値がある鍵へ、書こうとした。保存先は、何も変わっていない。"""


def check_key(key) -> str:
    """保存の鍵の検査。小文字のASCII、数字、_ . - だけで、1〜48字。外れたら StorageError。"""
    if type(key) is not str or not key or len(key) > KEY_MAX or not set(key) <= KEY_CHARS:
        raise StorageError(f"bad storage key {key!r} (lowercase ASCII, digits, _ . - ; 1 to {KEY_MAX} characters)")
    return key


def check_namespace(namespace) -> str:
    """名前空間の検査。保存の鍵と同じ字で、「.」を含まない（別の名前空間の鍵と混ざらない）。外れたら StorageError。"""
    check_key(namespace)
    if NAMESPACE_SEPARATOR in namespace:
        raise StorageError(f"bad storage namespace {namespace!r} (it cannot contain {NAMESPACE_SEPARATOR!r})")
    return namespace


def wrap(payload: bytes, version: int) -> bytes:
    """本体に封筒を付ける。形式バージョンは、1〜65535 の、bool でない整数。外れたら StorageError。"""
    if type(version) is not int or not VERSION_MIN <= version <= VERSION_MAX:
        raise StorageError(f"bad format version {version!r} (an integer in {VERSION_MIN}..{VERSION_MAX}, not bool)")
    if type(payload) not in (bytes, bytearray):
        raise StorageError(f"payload must be bytes, got {type(payload).__name__}")
    if len(payload) > PAYLOAD_MAX:
        raise StorageError(f"payload is too long ({len(payload)} bytes)")
    head = ENVELOPE.pack(MAGIC, version, len(payload))
    return head + bytes(payload) + CHECKSUM.pack(zlib.crc32(head + payload))


def unwrap(blob: bytes) -> tuple:
    """封筒を開ける。返すのは (形式バージョン, 本体)。読めない封筒は CorruptError。"""
    if type(blob) not in (bytes, bytearray):
        raise CorruptError(f"not bytes ({type(blob).__name__})")
    if len(blob) < ENVELOPE.size + CHECKSUM.size:
        raise CorruptError(f"too short ({len(blob)} bytes)")
    magic, version, length = ENVELOPE.unpack_from(blob)
    if magic != MAGIC:
        raise CorruptError("bad magic")
    if len(blob) != ENVELOPE.size + length + CHECKSUM.size:
        raise CorruptError(f"length mismatch (the head says {length}, the body has {len(blob) - ENVELOPE.size - CHECKSUM.size})")
    (checksum,) = CHECKSUM.unpack_from(blob, ENVELOPE.size + length)
    if zlib.crc32(blob[:ENVELOPE.size + length]) != checksum:
        raise CorruptError("checksum mismatch")
    if version < VERSION_MIN:
        raise CorruptError(f"format version {version} is never written")
    return version, bytes(blob[ENVELOPE.size:ENVELOPE.size + length])


class MemoryBackend:
    """メモリの保存先。辞書で持つ。テストと、保存先が使えないときの切り替え先に使う。

    capacity を渡すと、全部の値の合計がそのバイト数を超える書き込みを、何も変えずに StorageFull にする。
    """

    def __init__(self, capacity: int | None = None) -> None:
        self.items: dict = {}  # {鍵: バイト列}
        self.capacity = capacity  # 全部の値の合計の上限（バイト）。None なら、上限なし

    def read(self, key: str):
        return self.items.get(key)

    def write(self, key: str, data: bytes) -> None:
        if self.capacity is not None:
            total = sum(len(value) for name, value in self.items.items() if name != key) + len(data)
            if total > self.capacity:
                raise StorageFull(f"{key}: {total} bytes would exceed the capacity of {self.capacity} bytes")
        self.items[key] = bytes(data)

    def delete(self, key: str) -> None:
        self.items.pop(key, None)

    def keys(self) -> list:
        return sorted(self.items)


class SaveStore:
    """保存の口。出荷するコードは、これだけを使う。保存先での鍵は「<名前空間>.<鍵>」。"""

    def __init__(self, backend, namespace: str = DEFAULT_NAMESPACE) -> None:
        self.backend = backend
        self.namespace = check_namespace(namespace)
        self._prefix = namespace + NAMESPACE_SEPARATOR

    def _name(self, key) -> str:
        """保存先での鍵。"""
        return self._prefix + check_key(key)

    def get(self, key: str):
        """返すのは (形式バージョン, 本体)。鍵が無ければ None。壊れていれば CorruptError。"""
        blob = self.backend.read(self._name(key))
        return None if blob is None else unwrap(blob)

    def put(self, key: str, payload: bytes, version: int) -> None:
        """封筒を付けて書く。新しい形式バージョンの値がある鍵へは、書かずに NewerVersionError。"""
        name = self._name(key)
        blob = wrap(payload, version)
        # 割り切り：書くたびに、いまある値の読みが1回入る（新しい形式バージョンの値を、上書きしないための守り）。
        # 大きい値（リプレイの本体）を入れる段2で見直す。
        existing = self.backend.read(name)
        if existing is not None:
            try:
                existing_version, _ = unwrap(existing)
            except CorruptError:
                existing_version = None  # 壊れた値は、上書きする
            if existing_version is not None and existing_version > version:
                raise NewerVersionError(f"{key}: the stored value has format version {existing_version}, newer than {version}")
        self.backend.write(name, blob)

    def quarantine(self, key: str) -> bool:
        """壊れた値の退避。保存先のバイト列を、封筒を開けずに、そのまま「<鍵>.bad」へ写して、元の鍵を消す。

        返すのは、退避したか（鍵が無ければ False）。退避の書き込みが失敗したら、元の鍵は消さずに StorageFull。
        保存先の読みの例外は、そのまま外へ出す。退避の鍵は、鍵の検査を通さずに作る（48字の鍵も退避できる）。
        """
        name = self._name(key)
        blob = self.backend.read(name)
        if blob is None:
            return False
        try:
            self.backend.write(name + BAD_SUFFIX, blob)
        except StorageFull:
            raise
        except StorageError as exc:
            raise StorageFull(f"{key}: could not be set aside: {exc}") from exc
        self.backend.delete(name)
        return True

    def delete(self, key: str) -> None:
        """消す。無い鍵でも、黙る。"""
        self.backend.delete(self._name(key))

    def keys(self) -> list:
        """この名前空間の鍵の一覧（整列した list）。退避の鍵（<鍵>.bad）も入る。"""
        size = len(self._prefix)
        return sorted(name[size:] for name in self.backend.keys() if name.startswith(self._prefix))

    def used_bytes(self) -> int:
        """この名前空間の値の、保存先でのバイト数の合計（封筒を含む）。"""
        total = 0
        for key in self.keys():
            blob = self.backend.read(self._prefix + key)
            total += len(blob) if blob is not None else 0
        return total
