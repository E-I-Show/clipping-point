"""画面の状態（純Python）。決まりは docs/design/overview.md の「画面とシーン管理」。

いまは最小の形。ロジックが持つ画面の名の一覧（SCREEN_NAMES）、いまの画面の名（Flow.screen）、
表示用の値の型（画面ごとの、書き換えられない dataclass）だけを持つ。画面は、仮の表示の1つだけ。
画面の切り替え、積み重ね、カーソルや選択値は、画面の状態を作る段1 区切り6で足す。
表示用の値は、画面の組み立て（cp_ui.screens）に渡す値。描く側は、受け取って描くだけにする。
画面を足すときは、SCREEN_NAMES、表示用の値の型、cp_ui.screens の SCREENS、cp_ui.fixtures の見本データに足す
（そろっていることは、tests/test_fixtures.py の突き合わせのテストが見る）。
"""
from dataclasses import dataclass

from cp_core.input_frame import InputFrame

# ロジックが持つ画面の名。アプリは、この名で cp_ui.screens の SCREENS を引いて描く。
SCREEN_NAMES = ("placeholder",)
START_SCREEN = "placeholder"  # 起動したときの画面


def _count(name: str, value) -> int:
    """0以上の整数。bool と小数は受けない。"""
    if type(value) is not int:
        raise TypeError(f"{name}={value!r} must be int (bool and float are not accepted)")
    if value < 0:
        raise ValueError(f"{name}={value!r} must be >= 0")
    return value


@dataclass(frozen=True)
class PlaceholderView:
    """仮の表示の、表示用の値。作るときに、型と範囲を検査する。

    renders（実描画の回数）は、実時間で決まる値。表示にだけ使い、世界へ戻さない。
    いまは cp_app/app.py が、世界のtick、実描画の回数、直近の入力フレームから組み立てる
    （実描画の回数を、ロジックは持たないため）。
    """

    tick: int  # 世界のtick
    renders: int  # 実描画の回数。表示にだけ使う
    frame: InputFrame  # 直近の入力フレーム

    def __post_init__(self) -> None:
        _count("tick", self.tick)
        _count("renders", self.renders)
        if not isinstance(self.frame, InputFrame):
            raise TypeError(f"frame must be an InputFrame, got {type(self.frame).__name__}")


class Flow:
    """画面の状態。いまは、いまの画面の名だけを持つ（いつも START_SCREEN）。切り替えは、まだ無い。"""

    def __init__(self) -> None:
        self.screen = START_SCREEN  # いまの画面の名。SCREEN_NAMES のどれか
