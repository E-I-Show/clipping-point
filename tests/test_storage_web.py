"""localStorage の保存先（cp_app.storage_web）のテスト。ブラウザの機能（js）の代わりに、偽の実装を渡す。

偽の js は、ブラウザ版のPythonでの見え方（Pyodide 314.0.7、ヘッドレスのChromiumでの実測）に合わせてある。
  無い鍵の getItem と、範囲の外の key(i)：型の名が JsNull の物。None ではない
  容量超過の setItem：Exception の子の例外で、name が "QuotaExceededError"
  localStorage に触れると例外になる文書：js.localStorage を読んだ所で、name が "SecurityError" の例外
  localStorage が無い：値が undefined なら None、null なら JsNull の物、名前ごと無ければ AttributeError
実物のブラウザでの読み書きは、道具 web-smoke の筋書き probe と storage_blocked が見る。
"""
import base64

import pytest

from cp_app import storage_web
from cp_app.storage_web import PREFIX, PROBE_FULL, PROBE_OK, PROBE_UNAVAILABLE, WebStorageBackend
from cp_core.storage import BACKEND_METHODS, CorruptError, SaveStore, StorageError, StorageFull, wrap


class JsNull:
    """JavaScriptの null の代わり。型の名を、実物（pyodide.ffi の JsNull）と同じにする。"""

    def __bool__(self) -> bool:
        return False


JS_NULL = JsNull()


class FakeJsException(Exception):
    """JavaScriptの例外が、Pythonで見える物の代わり。name に、JavaScriptの例外の名を持つ。"""

    def __init__(self, name: str, message: str = "planted") -> None:
        super().__init__(f"{name}: {message}")
        self.name = name


class FakeStorage:
    """localStorage の代わり。quota は、全部の値の字数の合計の上限。fail は {口の名: 投げる例外}。"""

    def __init__(self, quota: int | None = None, fail: dict | None = None) -> None:
        self.items: dict = {}
        self.quota = quota
        self.fail = dict(fail or {})
        self.calls: list = []

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def getItem(self, key):  # noqa: N802 - ブラウザの名前のまま
        self._enter("getItem")
        return self.items.get(key, JS_NULL)

    def setItem(self, key, value) -> None:  # noqa: N802
        self._enter("setItem")
        assert type(key) is str and type(value) is str  # localStorage が持てるのは、文字列だけ
        if self.quota is not None:
            total = sum(len(text) for name, text in self.items.items() if name != key) + len(value)
            if total > self.quota:
                raise FakeJsException("QuotaExceededError", f"Setting the value of '{key}' exceeded the quota.")
        self.items[key] = value

    def removeItem(self, key) -> None:  # noqa: N802
        self._enter("removeItem")
        self.items.pop(key, None)

    def key(self, index):
        self._enter("key")
        names = list(self.items)
        return names[index] if 0 <= index < len(names) else JS_NULL

    @property
    def length(self) -> int:
        self._enter("length")
        return len(self.items)


class FakeJs:
    """js のモジュールの代わり。localStorage だけを持つ。"""

    def __init__(self, storage) -> None:
        self.localStorage = storage  # noqa: N815 - ブラウザの名前のまま


class BlockedJs:
    """localStorage に触れると、例外になる文書。"""

    def __init__(self, error=None) -> None:
        self.error = error if error is not None else FakeJsException("SecurityError", "Access is denied for this document.")
        self.touches = 0

    @property
    def localStorage(self):  # noqa: N802
        self.touches += 1
        raise self.error


class JsWithoutStorage:
    """localStorage という名前ごと無いブラウザ。属性を読むと AttributeError。"""


def backend_with(storage=None) -> tuple:
    storage = storage if storage is not None else FakeStorage()
    return WebStorageBackend(FakeJs(storage)), storage


# --- 読み書き ---
def test_storage_web_backend_has_the_four_methods_of_a_backend():
    backend, _ = backend_with()
    assert all(callable(getattr(backend, name)) for name in BACKEND_METHODS)


def test_storage_web_round_trips_through_the_store():
    backend, storage = backend_with()
    store = SaveStore(backend)
    payload = bytes(range(256)) * 4
    assert store.get("settings") is None and store.keys() == []
    store.put("settings", payload, 3)
    store.put("replay.01", b"", 1)
    assert store.get("settings") == (3, payload) and store.get("replay.01") == (1, b"")
    assert store.keys() == ["replay.01", "settings"]
    assert store.used_bytes() == len(payload) + 2 * 14
    store.delete("replay.01")
    store.delete("replay.01")  # 無い鍵でも、黙る
    assert store.get("replay.01") is None and store.keys() == ["settings"]
    assert sorted(storage.items) == ["clippingpoint/main.settings"]


def test_storage_web_values_are_base64_text_under_the_prefix():
    backend, storage = backend_with()
    data = bytes(range(256))
    backend.write("main.settings", data)
    assert PREFIX == "clippingpoint/"
    assert storage.items == {"clippingpoint/main.settings": base64.b64encode(data).decode("ascii")}
    assert backend.read("main.settings") == data and type(backend.read("main.settings")) is bytes


def test_storage_web_missing_key_reads_as_none_not_as_jsnull():
    backend, storage = backend_with()
    assert storage.getItem("clippingpoint/main.settings") is JS_NULL  # 偽物も、実物と同じく jsnull を返す
    assert backend.read("main.settings") is None


@pytest.mark.parametrize("value", [None, JS_NULL, 5, 1.5, True, ["a"]])
def test_storage_web_a_value_that_is_not_text_reads_as_missing(value):
    backend, storage = backend_with()
    storage.items["clippingpoint/main.settings"] = value
    assert backend.read("main.settings") is None


def test_storage_web_delete_removes_only_its_own_key():
    backend, storage = backend_with()
    backend.write("main.a", b"1")
    backend.write("main.b", b"2")
    backend.delete("main.a")
    backend.delete("main.a")
    assert sorted(storage.items) == ["clippingpoint/main.b"]


def test_storage_web_keys_lists_only_the_keys_under_the_prefix_in_order():
    backend, storage = backend_with()
    backend.write("main.settings", b"1")
    backend.write("main.controls", b"2")
    storage.items["someone_else"] = "x"  # 同じ起点の、ほかのページが置いた値
    storage.items["clippingpoint"] = "y"
    assert backend.keys() == ["main.controls", "main.settings"]


def test_storage_web_keys_skips_an_index_that_reads_as_jsnull():
    class ShrinkingStorage(FakeStorage):
        """length を読んだ後で、値が減った形。範囲の外の key(i) は、jsnull で返る。"""

        @property
        def length(self) -> int:
            return len(self.items) + 2

    backend, _ = backend_with(ShrinkingStorage())
    backend.write("main.settings", b"1")
    assert backend.keys() == ["main.settings"]


# --- 容量超過と、ほかの例外 ---
def test_storage_web_quota_error_is_storage_full_and_changes_nothing():
    backend, storage = backend_with(FakeStorage(quota=100))
    store = SaveStore(backend)
    store.put("a", b"1" * 20, 1)
    before = dict(storage.items)
    with pytest.raises(StorageFull):
        store.put("b", b"2" * 80, 1)
    with pytest.raises(StorageFull):
        backend.write("main.a", b"3" * 90)
    assert storage.items == before
    assert store.get("a") == (1, b"1" * 20)  # 読みは生きている


@pytest.mark.parametrize("error", [FakeJsException("SecurityError"), FakeJsException("Error"), RuntimeError("no name at all"), AttributeError("setItem")])
def test_storage_web_other_write_errors_are_storage_errors_but_not_storage_full(error):
    backend, _ = backend_with(FakeStorage(fail={"setItem": error}))
    with pytest.raises(StorageError) as caught:
        backend.write("main.settings", b"x")
    assert type(caught.value) is StorageError
    assert caught.value.__cause__ is error


def test_storage_web_quota_error_is_told_apart_by_the_name_of_the_exception():
    assert storage_web.is_quota_error(FakeJsException("QuotaExceededError"))
    assert not storage_web.is_quota_error(FakeJsException("SecurityError"))
    assert not storage_web.is_quota_error(RuntimeError("QuotaExceededError"))  # name が無い
    assert storage_web.QUOTA_ERROR_NAME == "QuotaExceededError"


@pytest.mark.parametrize("method, call", [
    ("getItem", lambda backend: backend.read("main.settings")),
    ("removeItem", lambda backend: backend.delete("main.settings")),
    ("length", lambda backend: backend.keys()),
    ("key", lambda backend: backend.keys()),
])
def test_storage_web_javascript_errors_while_reading_deleting_or_listing_are_storage_errors(method, call):
    backend, storage = backend_with(FakeStorage(fail={method: FakeJsException("Error", "storage is off")}))
    storage.items["clippingpoint/main.settings"] = "AAAA"
    with pytest.raises(StorageError) as caught:
        call(backend)
    assert type(caught.value) is StorageError


# --- base64 として読めない値 ---
@pytest.mark.parametrize("text", ["not base64 at all!", "abc", "A", "日本語の値", "{\"sfx_volume\": 5}", " AAAA", "AA\nAA"])
def test_storage_web_text_that_is_not_base64_is_returned_as_bytes_not_raised(text):
    backend, storage = backend_with()
    storage.items["clippingpoint/main.settings"] = text
    assert backend.read("main.settings") == text.encode("utf-8")  # 例外にしない。その文字列を符号化したバイト列
    with pytest.raises(CorruptError):
        SaveStore(backend).get("settings")  # 封筒の検査で、壊れた値になる


def test_storage_web_text_with_a_lone_surrogate_does_not_raise_either():
    backend, storage = backend_with()
    storage.items["clippingpoint/main.settings"] = "broken \ud800 text"
    blob = backend.read("main.settings")
    assert type(blob) is bytes and blob.startswith(b"broken ")
    with pytest.raises(CorruptError):
        SaveStore(backend).get("settings")


def test_storage_web_valid_base64_that_is_not_an_envelope_is_a_corrupt_value():
    backend, storage = backend_with()
    storage.items["clippingpoint/main.settings"] = base64.b64encode(b"not an envelope").decode("ascii")
    assert backend.read("main.settings") == b"not an envelope"
    with pytest.raises(CorruptError):
        SaveStore(backend).get("settings")
    storage.items["clippingpoint/main.settings"] = ""  # 空の文字列は、空のバイト列
    assert backend.read("main.settings") == b""


def test_storage_web_value_that_is_not_base64_can_be_quarantined():
    backend, storage = backend_with()
    store = SaveStore(backend)
    storage.items["clippingpoint/main.settings"] = "not base64 at all!"
    assert store.quarantine("settings") is True
    # 退避した値は、読んだバイト列（文字列を符号化したもの）を、base64 にして置く。開けると、元の文字列に戻る。
    assert sorted(storage.items) == ["clippingpoint/main.settings.bad"]
    assert base64.b64decode(storage.items["clippingpoint/main.settings.bad"]) == b"not base64 at all!"
    assert store.get("settings") is None


def test_storage_web_damaged_envelope_is_a_corrupt_value():
    backend, storage = backend_with()
    store = SaveStore(backend)
    damaged = bytearray(wrap(b"payload", 1))
    damaged[-1] ^= 0xFF
    storage.items["clippingpoint/main.settings"] = base64.b64encode(bytes(damaged)).decode("ascii")
    with pytest.raises(CorruptError):
        store.get("settings")


# --- 試し書き ---
def test_storage_web_probe_on_working_storage_is_ok_and_leaves_nothing():
    backend, storage = backend_with()
    storage.items["clippingpoint/main.settings"] = "AAAA"
    assert backend.probe() == (PROBE_OK, "")
    assert storage.items == {"clippingpoint/main.settings": "AAAA"}  # 試しの鍵は、消してある
    assert storage.calls == ["setItem", "getItem", "removeItem"]  # 書いて、読んで、消す


def test_storage_web_probe_key_cannot_collide_with_a_key_of_the_store():
    # 保存の口の鍵は「<名前空間>.<鍵>」で、必ず「.」を含む。
    assert "." not in storage_web.PROBE_KEY
    backend, storage = backend_with()
    backend.probe()
    assert SaveStore(backend).keys() == []


def test_storage_web_probe_on_full_storage_is_full_and_reading_still_works():
    full = FakeStorage(quota=0)
    backend, _ = backend_with(full)
    state, reason = backend.probe()
    assert state == PROBE_FULL and "QuotaExceededError" in reason
    assert "getItem" in full.calls  # 読みが生きていることを、確かめている
    assert backend.read("main.settings") is None


def test_storage_web_probe_on_full_storage_that_cannot_be_read_is_unavailable():
    storage = FakeStorage(quota=0, fail={"getItem": FakeJsException("Error", "storage is off")})
    assert backend_with(storage)[0].probe()[0] == PROBE_UNAVAILABLE


@pytest.mark.parametrize("method", ["setItem", "getItem", "removeItem"])
@pytest.mark.parametrize("error", [FakeJsException("SecurityError"), FakeJsException("Error"), RuntimeError("no name"), AttributeError("x")])
def test_storage_web_probe_with_any_other_error_is_unavailable(method, error):
    backend, _ = backend_with(FakeStorage(fail={method: error}))
    state, reason = backend.probe()
    assert state == PROBE_UNAVAILABLE and reason and "\n" not in reason


def test_storage_web_probe_that_reads_back_another_value_is_unavailable():
    class ForgetfulStorage(FakeStorage):
        def setItem(self, key, value) -> None:  # noqa: N802
            pass  # 書いたふりをして、何も持たない

    state, reason = backend_with(ForgetfulStorage())[0].probe()
    assert state == PROBE_UNAVAILABLE and "read back" in reason


@pytest.mark.parametrize("js", [BlockedJs(), BlockedJs(FakeJsException("Error")), BlockedJs(RuntimeError("no name")), JsWithoutStorage(), FakeJs(None), FakeJs(JS_NULL)])
def test_storage_web_probe_never_raises_when_storage_cannot_be_touched(js):
    state, reason = WebStorageBackend(js).probe()
    assert state == PROBE_UNAVAILABLE and reason


def test_storage_web_probe_results_are_three_distinct_words():
    assert len({PROBE_OK, PROBE_FULL, PROBE_UNAVAILABLE}) == 3


# --- localStorage に触れると例外 ---
def test_storage_web_making_the_backend_does_not_touch_the_storage():
    js = BlockedJs()
    WebStorageBackend(js)
    assert js.touches == 0


@pytest.mark.parametrize("js", [BlockedJs(), JsWithoutStorage(), FakeJs(None), FakeJs(JS_NULL)])
def test_storage_web_every_call_on_storage_that_cannot_be_touched_is_a_storage_error(js):
    backend = WebStorageBackend(js)
    for call in (lambda: backend.read("main.settings"), lambda: backend.write("main.settings", b"x"), lambda: backend.delete("main.settings"), backend.keys):
        with pytest.raises(StorageError) as caught:
            call()
        assert type(caught.value) is StorageError  # 容量超過（StorageFull）とは別
    store = SaveStore(backend)
    with pytest.raises(StorageError):
        store.get("settings")
    with pytest.raises(StorageError):
        store.put("settings", b"x", 1)


def test_storage_web_module_takes_js_as_an_argument_and_never_imports_it():
    import ast

    from conftest import ROOT

    tree = ast.parse((ROOT / "clipping_point" / "cp_app" / "storage_web.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert imported == {"base64", "cp_core"}  # js、pyodide、pyxel を読み込まない
