"""見本データ（純Python）。はみ出しの検査（tools/screen_check.py）と巡回（tools/tour.py）で、画面を組み立てるための表示用の値。

変種は2つ。typical は、ふつうの値。extreme は、極端な値（いちばん長くなる文字、いちばん大きい数）。
極端な値でだけ起きるはみ出しがあるので、道具は両方で回す。
build(画面の名, 変種) が、その画面の表示用の値（cp_core.flow の型）を返す。知らない画面と変種は KeyError。
画面を足したら、BUILDERS に足す（画面の登録 cp_ui.screens.SCREENS と同じ集まりであることを、突き合わせのテストが見る）。
定義データから極端な値を導く形（いちばん長い車名など）は、定義データができる段0 区切り8より後で足す。
"""
from cp_core.flow import DM_PER_M, CarView, PlaceholderView
from cp_core.input_frame import BUTTONS, InputFrame
from cp_core.storage import NOTICES
from cp_core.track import MAX_LENGTH_M, SURFACE_ASPHALT, SURFACES
from cp_core.vehicle import REVERSE
from cp_ui.screens import RPM_DIGITS, SPEED_DIGITS

VARIANTS = ("typical", "extreme")
# 仮の値：極端な値に使う、tick と実描画の回数（7桁。毎秒60 tickで約46時間ぶん）。表示の桁の上限は、まだ決めていない。
# 定義データから極端な値を導く形にする時（段0 区切り8より後）に合わせる。
BIGGEST_COUNT = 9_999_999
# 極端な値に使う、速度（km/h）と回転数。仮の表示の桁（cp_ui.screens の SPEED_DIGITS、RPM_DIGITS）を、いっぱいに使う値
# （999 と 99,999。実物の車は、時速213 km、毎分7,200回転まで）。桁を変えると、ここも付いて変わる。
FASTEST_KMH = 10 ** SPEED_DIGITS - 1
HIGHEST_RPM = 10 ** RPM_DIGITS - 1


def longest_notice() -> str:
    """知らせの文の組（cp_core.storage の NOTICES）の、いちばん長い文。同じ長さなら、組の中で先のもの。"""
    return max(NOTICES, key=len)


def longest_surface() -> str:
    """路面の種類（cp_core.track の SURFACES）の、いちばん長い名。同じ長さなら、組の中で先のもの。"""
    return max(SURFACES, key=len)


def farthest_position_dm() -> int:
    """極端な値に使う、位置（0.1 m 刻み）。コースの座標の上限（cp_core.track の MAX_LENGTH_M）の、負の側（符号の分、1字長い）。"""
    return -round(MAX_LENGTH_M * DM_PER_M)


def _placeholder(variant: str) -> PlaceholderView:
    if variant == "extreme":
        # 舵は負（符号の分、1字長い）。アクセルとブレーキは最大。ボタンを10個とも押している。知らせは、いちばん長い文。
        frame = InputFrame(
            steer_analog=-1.0, steer_digital=-1, throttle_analog=1.0, throttle_digital=1, brake_analog=1.0, brake_digital=1,
            held=frozenset(BUTTONS), pressed=frozenset(BUTTONS),
        )
        # 車の値は、桁をいっぱいに使う。ギアは後退（R）。位置は、コースの座標の上限の、負の側。路面は、いちばん長い名。
        far = farthest_position_dm()
        car = CarView(speed_kmh=FASTEST_KMH, gear=REVERSE, rpm=HIGHEST_RPM, x_dm=far, z_dm=far, surface=longest_surface())
        return PlaceholderView(tick=BIGGEST_COUNT, renders=BIGGEST_COUNT, frame=frame, notice=longest_notice(), car=car)
    # ふつうの値は、知らせが無い（保存先が使えて、保存が読めた起動）。車は、舗装の上を、3速で走っている。
    frame = InputFrame(steer_analog=0.5, steer_digital=1, throttle_analog=0.3, throttle_digital=1, held=frozenset({"up", "confirm"}))
    car = CarView(speed_kmh=87, gear=3, rpm=5200, x_dm=1234, z_dm=-56, surface=SURFACE_ASPHALT)
    return PlaceholderView(tick=120, renders=60, frame=frame, notice="", car=car)


# 画面の名ごとの、見本データの作り方。(変種) を受けて、表示用の値を返す。
BUILDERS = {"placeholder": _placeholder}


def screen_names() -> tuple:
    """見本データを組み立てられる画面の名。"""
    return tuple(BUILDERS)


def build(screen: str, variant: str):
    """screen の、variant の見本データ（表示用の値）を返す。知らない画面と変種は KeyError。"""
    if variant not in VARIANTS:
        raise KeyError(variant)
    return BUILDERS[screen](variant)
