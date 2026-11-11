"""ロジックのテストと守りのテストの共通部。

このプロセスに pyxel を読み込ませない。pyxel.quit() は終了コード0で終わり、後ろの失敗を消すため。
Pyxelを通す確かめは、tools/ の道具が別プロセスで回す。回すときは tools/test.py を通す。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clipping_point"))  # cp_core、cp_ui、cp_app を読めるようにする
sys.path.append(str(ROOT / "tools"))  # 守りのテストが、見張りの本体を読めるようにする（標準ライブラリより後ろ）
FORBIDDEN = ("pyxel",)


def pytest_sessionfinish(session, exitstatus):
    loaded = [name for name in FORBIDDEN if name in sys.modules]
    if loaded:
        # この行の頭の語は、tools/test.py が理由を見分けるのに使う。
        print(f"\nFORBIDDEN MODULES LOADED IN THE TEST PROCESS: {loaded}")
        session.exitstatus = 1
