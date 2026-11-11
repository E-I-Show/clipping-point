"""Browser backend for cp_core.storage.SaveStore: localStorage, values are base64 text.
Shape taken from the web spike (apps/_shared/web_bridge.py, exercised in headless Chromium)."""
import base64
import sys

IS_WEB = sys.platform == "emscripten"
if IS_WEB:
    import js
    from pyodide.ffi import JsException

from cp_core.storage import StorageFull

PREFIX = "clippingpoint/"


class WebStorageBackend:
    def read(self, key: str):
        v = js.localStorage.getItem(PREFIX + key)
        if not isinstance(v, str):  # a missing key is JS null (pyodide.ffi.jsnull), not None
            return None
        return base64.b64decode(v)

    def write(self, key: str, data: bytes) -> None:
        try:
            js.localStorage.setItem(PREFIX + key, base64.b64encode(data).decode("ascii"))
        except JsException as e:
            if str(getattr(e, "name", "")) == "QuotaExceededError":
                raise StorageFull(key) from None
            raise

    def delete(self, key: str) -> None:
        js.localStorage.removeItem(PREFIX + key)

    def keys(self) -> list:
        ls = js.localStorage
        names = [str(ls.key(i)) for i in range(int(ls.length))]
        return sorted(n[len(PREFIX):] for n in names if n.startswith(PREFIX))


def default_backend(native_dir):
    if IS_WEB:
        return WebStorageBackend()
    from cp_core.storage import FileBackend

    return FileBackend(native_dir)
