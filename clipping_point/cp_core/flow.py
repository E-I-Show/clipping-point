"""画面の状態（純Python）。決まりは docs/design/overview.md の「画面とシーン管理」。

いまは最小の形。ロジックが持つ画面の名の一覧（SCREEN_NAMES）、いまの画面の名（Flow.screen）、
表示用の値の型（画面ごとの、書き換えられない dataclass）だけを持つ。画面は、仮の表示の1つだけ。
画面の切り替え、積み重ね、カーソルや選択値は、画面の状態を作る段1 区切り6で足す。
表示用の値は、画面の組み立て（cp_ui.screens）に渡す値。描く側は、受け取って描くだけにする。値は、整数と文字列で渡す
（小数を、描く側で丸めない）。
世界の状態から、表示用の値を作る所（car_view）も、ここに置く（pyxel を読まない。世界のどの状態からでも、作れること）。
画面を足すときは、SCREEN_NAMES、表示用の値の型、cp_ui.screens の SCREENS、cp_ui.fixtures の見本データに足す
（そろっていることは、tests/test_fixtures.py の突き合わせのテストが見る）。
"""
from dataclasses import dataclass

from cp_core.input_frame import InputFrame
from cp_core.track import SURFACES

# ロジックが持つ画面の名。アプリは、この名で cp_ui.screens の SCREENS を引いて描く。
SCREEN_NAMES = ("placeholder",)
START_SCREEN = "placeholder"  # 起動したときの画面
KMH_PER_M_S = 3.6  # 速さ（m/s）を、表示の km/h にする
DM_PER_M = 10  # 位置（m）を、表示の 0.1 m 刻みの整数にする


def _whole(name: str, value) -> int:
    """整数。bool と小数は受けない。"""
    if type(value) is not int:
        raise TypeError(f"{name}={value!r} must be int (bool and float are not accepted)")
    return value


def _count(name: str, value) -> int:
    """0以上の整数。bool と小数は受けない。"""
    if _whole(name, value) < 0:
        raise ValueError(f"{name}={value!r} must be >= 0")
    return value


@dataclass(frozen=True)
class CarView:
    """仮の表示の、車の値（表示用の値の一部）。整数と文字列だけ。作るときに、型と範囲を検査する。世界から作るのは car_view()。"""

    speed_kmh: int  # 速度（km/h）。0以上
    gear: int  # ギア。後退は −1（表示は R）。前進は1〜。0は無い
    rpm: int  # 回転数。0以上
    x_dm: int  # 位置の x（0.1 m 刻み。1234 は 123.4 m）
    z_dm: int  # 位置の z（0.1 m 刻み）
    surface: str  # 路面の種類（cp_core.track の SURFACES のどれか）

    def __post_init__(self) -> None:
        _count("speed_kmh", self.speed_kmh)
        if _whole("gear", self.gear) == 0:
            raise ValueError("gear=0 is not a gear (reverse is -1, forward gears start at 1)")
        _count("rpm", self.rpm)
        _whole("x_dm", self.x_dm)
        _whole("z_dm", self.z_dm)
        if type(self.surface) is not str or self.surface not in SURFACES:
            raise ValueError(f"surface={self.surface!r} must be one of {SURFACES}")


def car_view(sim) -> CarView:
    """世界（cp_core.sim の Sim）の、いまの状態から、仮の表示の車の値を作る。世界は、書き換えない。

    速度は km/h の整数、位置は 0.1 m 刻みの整数に丸める。後退のギア、芝の上、壁に当たっている間も、作れる。
    """
    car = sim.car
    return CarView(
        speed_kmh=round(car.speed * KMH_PER_M_S),
        gear=car.gear,
        rpm=round(car.rpm),
        x_dm=round(car.x * DM_PER_M),
        z_dm=round(car.z * DM_PER_M),
        surface=sim.surface,
    )


@dataclass(frozen=True)
class PlaceholderView:
    """仮の表示の、表示用の値。作るときに、型と範囲を検査する。

    renders（実描画の回数）は、実時間で決まる値。表示にだけ使い、世界へ戻さない。
    いまは cp_app/app.py が、世界のtick、実描画の回数、直近の入力フレーム、知らせの1行、車の値から組み立てる
    （実描画の回数を、ロジックは持たないため）。
    notice は、保存についての知らせの1行（文は cp_core/storage.py の NOTICES）。無ければ空。省けない
    （アプリが渡し忘れたら、作る時に落ちる）。本物の通知は、画面の状態を作る段1で作る。
    car は、車の値（速度、ギア、回転数、位置、路面の種類）。省けない。実機で、車が動いていることを見るための表示（HUDは段1）。
    """

    tick: int  # 世界のtick
    renders: int  # 実描画の回数。表示にだけ使う
    frame: InputFrame  # 直近の入力フレーム
    notice: str  # 知らせの1行。無ければ空
    car: CarView  # 車の値

    def __post_init__(self) -> None:
        _count("tick", self.tick)
        _count("renders", self.renders)
        if not isinstance(self.frame, InputFrame):
            raise TypeError(f"frame must be an InputFrame, got {type(self.frame).__name__}")
        if type(self.notice) is not str:
            raise TypeError(f"notice={self.notice!r} must be str")
        if not isinstance(self.car, CarView):
            raise TypeError(f"car must be a CarView, got {type(self.car).__name__}")


class Flow:
    """画面の状態。いまは、いまの画面の名だけを持つ（いつも START_SCREEN）。切り替えは、まだ無い。"""

    def __init__(self) -> None:
        self.screen = START_SCREEN  # いまの画面の名。SCREEN_NAMES のどれか
