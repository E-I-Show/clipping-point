"""ファイルの保存先（デスクトップ版）。保存先の決まりは cp_core/storage.py。pyxel も js も読み込まない。

1つの鍵を、1つのファイル（<置き場>/<鍵>.sav）に持つ。デスクトップ版は、開発とテストにだけ使う（配布物はHTML）。
書き込みは、一時ファイル（<鍵>.tmp）に全部を書く → flush → fsync を1回 → os.replace で差し替える。
途中で止まっても、古い保存は読めるまま残る。残った一時ファイルは、鍵の一覧に出さない。
ファイルと os に触れるので、純Pythonの層（cp_core）には置かない。出荷するコードは、保存の口（SaveStore）を通して使う。
"""
import os

from cp_core.storage import KEY_CHARS, StorageError, StorageFull

SUFFIX = ".sav"  # 保存のファイルの名の、後ろに付ける字。道具（tools/run.py）も、ここから読む
TMP_SUFFIX = ".tmp"  # 一時ファイルの名の、後ろに付ける字


class FileBackend:
    """ファイルの保存先。directory は、置き場のディレクトリ（無ければ、最初の書き込みで作る）。"""

    def __init__(self, directory) -> None:
        self.directory = os.fspath(directory)
        self.fsyncs = 0  # fsync を呼んだ回数。書き込み1回につき1回であることを、テストが見る

    def _path(self, key: str, suffix: str = SUFFIX) -> str:
        # 置き場の外へ出る名（区切りの字、空の名）を受けない。使える字は、保存の鍵と同じ（長さは見ない。退避の鍵は長い）。
        if type(key) is not str or not key or not set(key) <= KEY_CHARS:
            raise StorageError(f"bad file key {key!r}")
        return os.path.join(self.directory, key + suffix)

    def read(self, key: str):
        try:
            with open(self._path(key), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError(f"{key}: cannot be read: {exc}") from exc

    def write(self, key: str, data: bytes) -> None:
        path, tmp_path = self._path(key), self._path(key, TMP_SUFFIX)
        try:
            os.makedirs(self.directory, exist_ok=True)
            with open(tmp_path, "wb") as f:
                f.write(data)  # 全部を、1度に書く
                f.flush()
                os.fsync(f.fileno())  # 書き込み1回につき、1回だけ
                self.fsyncs += 1
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # 一時ファイルが、できていなかった
            raise StorageFull(f"{key}: cannot be written: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            os.unlink(self._path(key))
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise StorageError(f"{key}: cannot be deleted: {exc}") from exc

    def keys(self) -> list:
        try:
            names = os.listdir(self.directory)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise StorageError(f"{self.directory}: cannot be listed: {exc}") from exc
        # 一時ファイル（.tmp）と、ほかの名のファイルは出さない。
        return sorted(name[:-len(SUFFIX)] for name in names if name.endswith(SUFFIX) and len(name) > len(SUFFIX))
