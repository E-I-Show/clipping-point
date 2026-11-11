"""localStorage の保存先（ブラウザ版）。保存先の決まりは cp_core/storage.py。

このモジュールは js をimportしない。ブラウザの機能（js のモジュール）は引数で受ける。テストから、偽の実装を渡して確かめるため。
値は base64 の文字列で置く。鍵の頭に PREFIX（clippingpoint/）を付ける。
出荷するコードは、保存の口（SaveStore）を通して使う。js.localStorage を、ほかの所から直に触らない。

ブラウザ版のPythonでの見え方（Pyodide 314.0.7、ヘッドレスのChromiumでの実測）：
  無い鍵の getItem、範囲の外の key(i)   None ではなく jsnull（型の名が JsNull）。文字列でなければ「無い」と読む
  容量超過（約500万字）の setItem        pyodide.ffi.JsException（Exception の子）。name が "QuotaExceededError"。読みは生きている
  localStorage に触れると例外            js.localStorage を読んだ所で JsException。name は、投げられた物による（下）
  localStorage が無い                    値が undefined なら None、null なら jsnull、名前ごと無ければ AttributeError
  試し書き（書く、読む、消す）           1回 約0.05 ms
触れると例外になるときの name は、stack（文字列）を持つ DOMException なら、その名（"SecurityError"）。stack の無い物
（スクリプトで作っただけの DOMException）は、Pyodide が別の Error に包み直すので "Error" になる。ブラウザが自分で投げる
SecurityError は stack を持つ（JavaScriptの側で実測）が、Pythonからの見え方は、偽物（tools/web/block_storage.js）でしか見ていない。
このため、切り替えの判定は、例外の型にも、SecurityError の名にも頼らない。捕まえるのは Exception（JsException も AttributeError も入る。
pyodide をimportせずに済む）で、見分けるのは「容量超過（name が QuotaExceededError）か、そのほかか」だけ。

読んだ値が base64 として読めなければ、例外にせず、その文字列を符号化したバイト列で返す。封筒の検査で壊れた値になり、
読み込み（cp_core/profile.py の load_settings）が退避する。読みで例外にすると、退避のための読みも例外になり、退避できない。
"""
import base64

from cp_core.storage import StorageError, StorageFull

PREFIX = "clippingpoint/"  # localStorage での鍵の頭。道具（tools/web_smoke.py）も、ここから読む
QUOTA_ERROR_NAME = "QuotaExceededError"  # 容量超過のときの、JavaScriptの例外の名
JS_NULL_TYPE_NAME = "JsNull"  # JavaScriptの null が、ブラウザ版のPythonで見える物の、型の名
# 試し書きの鍵と値。保存の口の鍵（「<名前空間>.<鍵>」）は必ず「.」を含むので、「.」の無い名は重ならない。
PROBE_KEY = "storage-probe"
PROBE_VALUE = "cp"
PROBE_OK, PROBE_FULL, PROBE_UNAVAILABLE = "ok", "full", "unavailable"  # 試し書きの結果


def is_missing(value) -> bool:
    """JavaScriptの undefined（None）か、null（jsnull）。"""
    return value is None or type(value).__name__ == JS_NULL_TYPE_NAME


def is_quota_error(exc) -> bool:
    """容量超過の例外か。JavaScriptの例外の name で見る。"""
    return str(getattr(exc, "name", "")) == QUOTA_ERROR_NAME


def describe(exc) -> str:
    """例外を、1行の文にする。"""
    return f"{type(exc).__name__}: {exc}".splitlines()[0][:200]


class WebStorageBackend:
    """localStorage の保存先。js は、ブラウザの機能（js のモジュール）。"""

    def __init__(self, js) -> None:
        # js.localStorage は、ここでは読まない（触れると例外になる文書がある）。使うたびに読む。
        self._js = js

    def _storage(self):
        """js.localStorage。無ければ StorageError。触れたときの例外は、呼ぶ側が捕まえる。"""
        storage = self._js.localStorage
        if is_missing(storage):
            raise StorageError("localStorage is missing")
        return storage

    def probe(self) -> tuple:
        """試し書き。試しの鍵を書いて、読んで、消す。返すのは (結果, 理由の文)。例外を外へ出さない。

        結果は、PROBE_OK（使える）、PROBE_FULL（容量超過。読みは生きている）、PROBE_UNAVAILABLE（使えない）。
        """
        name = PREFIX + PROBE_KEY
        try:
            storage = self._storage()
        except Exception as exc:  # noqa: BLE001 - 触れると例外になる文書、localStorage が無いブラウザ
            return PROBE_UNAVAILABLE, describe(exc)
        try:
            storage.setItem(name, PROBE_VALUE)
        except Exception as exc:  # noqa: BLE001
            if not is_quota_error(exc):
                return PROBE_UNAVAILABLE, describe(exc)
            try:
                storage.getItem(name)  # 容量超過でも、読みが生きていること
            except Exception as read_exc:  # noqa: BLE001
                return PROBE_UNAVAILABLE, describe(read_exc)
            return PROBE_FULL, describe(exc)
        try:
            back = storage.getItem(name)
            storage.removeItem(name)
        except Exception as exc:  # noqa: BLE001
            return PROBE_UNAVAILABLE, describe(exc)
        if back != PROBE_VALUE:
            return PROBE_UNAVAILABLE, f"the probe value read back as {back!r}"
        return PROBE_OK, ""

    def read(self, key: str):
        try:
            value = self._storage().getItem(PREFIX + key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - 読みの途中の、JavaScriptの例外
            raise StorageError(f"{key}: cannot be read: {describe(exc)}") from exc
        if not isinstance(value, str):
            return None  # 無い鍵は、None ではなく jsnull で返る
        try:
            return base64.b64decode(value, validate=True)
        except ValueError:  # base64 として読めない（binascii.Error も、ASCIIでない字も、ここへ来る）
            # 例外にしない。封筒の検査で、壊れた値になる。対を成さないサロゲートがあっても、符号化で例外を出さない。
            return value.encode("utf-8", "surrogatepass")

    def write(self, key: str, data: bytes) -> None:
        text = base64.b64encode(bytes(data)).decode("ascii")
        try:
            self._storage().setItem(PREFIX + key, text)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            if is_quota_error(exc):
                raise StorageFull(f"{key}: {describe(exc)}") from exc
            raise StorageError(f"{key}: cannot be written: {describe(exc)}") from exc

    def delete(self, key: str) -> None:
        try:
            self._storage().removeItem(PREFIX + key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"{key}: cannot be deleted: {describe(exc)}") from exc

    def keys(self) -> list:
        try:
            storage = self._storage()
            names = [storage.key(index) for index in range(int(storage.length))]
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"localStorage cannot be listed: {describe(exc)}") from exc
        # 途中で減ると、範囲の外の key(i) が jsnull で返る。文字列でないものは読み飛ばす。
        return sorted(name[len(PREFIX):] for name in names if isinstance(name, str) and name.startswith(PREFIX))
