"""保存先を選ぶ。pyxel も js もimportしない。ブラウザの機能（js のモジュール）と、環境の辞書は、引数で受ける。

  ブラウザ版（js を渡したとき）    localStorage の保存先で、試し書きをする。
      使える                       localStorage
      容量超過                     localStorage のまま使う（読みは生きている。書き込みは、失敗として返る）
      使えない                     メモリの保存先に切り替えて、知らせの1行を返す（保存は残らない）
  デスクトップ版（js が None）      環境の辞書に CP_SAVE_DIR（絶対パス）があればファイル、無ければメモリ（保存は残らない）。
                                   相対パスは ValueError（pyxel.init が作業ディレクトリを変える）。
デスクトップ版は、どの起動でも CP_SAVE_DIR を読む（ふつうの起動、画面なしで回す口、巡回の口）。呼ぶのは cp_app/app.py の main()。
道具は、外から入った CP_SAVE_DIR を子プロセスへ渡さない（tools/_common.py の APP_ENV_PREFIXES）。
"""
import os
from dataclasses import dataclass

from cp_core.storage import NOTICE_MEMORY_FALLBACK, MemoryBackend

from .storage_file import FileBackend
from .storage_web import PROBE_UNAVAILABLE, WebStorageBackend

SAVE_DIR_ENV = "CP_SAVE_DIR"  # デスクトップ版の、保存のファイルの置き場（絶対パス）
BACKEND_WEB, BACKEND_FILE, BACKEND_MEMORY = "localstorage", "file", "memory"  # 保存先の名。結果に入れる


@dataclass(frozen=True)
class Selected:
    """選んだ保存先。"""

    backend: object  # 保存先（read、write、delete、keys を持つ）
    name: str  # 保存先の名（"localstorage"、"file"、"memory"）
    notice: str  # 知らせの1行。ブラウザ版で、メモリへ切り替えたときだけ。ほかは空


def select(js, env) -> Selected:
    """保存先を選ぶ。js は、ブラウザの機能（デスクトップ版では None）。env は、環境の辞書（os.environ）。"""
    if js is not None:
        backend = WebStorageBackend(js)
        state, _ = backend.probe()
        if state == PROBE_UNAVAILABLE:
            # 割り切り：試し書きが通らなかった理由（例外の型と文）は、画面にもコンソールにも出さない。
            # 本物の通知を作る段1（画面の状態）で見直す。
            return Selected(MemoryBackend(), BACKEND_MEMORY, NOTICE_MEMORY_FALLBACK)
        return Selected(backend, BACKEND_WEB, "")
    directory = env.get(SAVE_DIR_ENV, "")
    if not directory:
        return Selected(MemoryBackend(), BACKEND_MEMORY, "")
    if not os.path.isabs(directory):
        raise ValueError(f"{SAVE_DIR_ENV} must be an absolute path (pyxel.init changes the working directory)")
    # 割り切り：設計は「利用者データ用のディレクトリのファイル」。いまは、環境変数で置き場を渡されたときだけ、ファイルに持つ
    # （デスクトップ版は、開発とテストにだけ使う。利用者のホームに、黙ってファイルを作らない）。設定の画面を作る段1で見直す。
    return Selected(FileBackend(directory), BACKEND_FILE, "")
