"""画面の状態（純Python）。決まりは docs/design/overview.md の「画面とシーン管理」。

いまは最小の形。ロジックが持つ画面の名の一覧（SCREEN_NAMES）、いまの画面の名（Flow.screen）、
表示用の値の型（画面ごとの、書き換えられない dataclass）だけを持つ。画面は、仮の表示の1つだけ。
画面の切り替え、積み重ね、カーソルや選択値は、画面の状態を作る段1 区切り6で足す。
表示用の値は、画面の組み立て（cp_ui.screens）に渡す値。描く側は、受け取って描くだけにする。値は、整数と文字列で渡す
（小数を、描く側で丸めない）。
世界の状態から、表示用の値を作る所（car_view）も、ここに置く（pyxel を読まない。世界のどの状態からでも、作れること）。
測った値（処理時間、毎秒の回数、起動にかかった時間）を、表示の 0.1 刻みの整数にして、桁いっぱいで頭打ちにする所（capped_tenths）も、ここに置く。
処理時間の値の型（PerfView）は、整数か None（測れていない）だけを持つ。測るのは cp_app（実時間を読むのは、そこだけ）。
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


def capped_tenths(value, whole_digits: int):
    """測った値（処理時間の ms、毎秒の回数、秒など。小数）を、表示の 0.1 刻みの整数にする（12.34 は 123）。描く側で、小数を丸めない。

    None（測れていない）は、None のまま返す。NaN も、測れていない扱いで None。
    表示の桁（整数部が whole_digits 桁）を超えた値は、桁いっぱいの値に頭打ちにする（2桁なら 999 ＝ 99.9。無限大も）。負の値は 0。
    値の大きさでは、例外にしない（ふつうの起動の、更新か実描画の中で呼ぶ。例外になると、ブラウザ版は、エラー表示で止まる）。
    数でない値（文字列、bool）と、1未満の桁の数は、呼ぶ側の誤りなので、TypeError と ValueError。
    """
    if type(whole_digits) is not int or whole_digits < 1:
        raise ValueError(f"whole_digits={whole_digits!r} must be an integer >= 1")
    if value is None:
        return None
    if type(value) not in (int, float):
        raise TypeError(f"value={value!r} must be a number or None (bool and str are not accepted)")
    if value != value:  # NaN
        return None
    top = 10 ** (whole_digits + 1) - 1  # 桁いっぱいの値（0.1 刻みの整数）
    if value <= 0:
        return 0
    if value * 10 >= top:  # 無限大も、ここで頭打ちになる（丸める前に比べる。無限大は、整数に丸められない）
        return top
    return round(value * 10)


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
class PerfView:
    """仮の表示の、処理時間の値（表示用の値の一部）。どれも、0.1 刻みの整数（123 は 12.3）か、None（測れていない）。

    実時間で決まる値。表示にだけ使い、世界へ戻さない。作るのは cp_app/perf.py の view_of()（測った値を、capped_tenths で、
    表示の桁いっぱいに頭打ちにして渡す）。ここでは、型と、0以上であることだけを検査する。上限では、例外にしない
    （ふつうの起動の、実描画の中で作る。例外になると、ブラウザ版は、エラー表示で止まる）。
    """

    update_mean_ms_x10: int | None  # 更新1回の時間の、直近の平均（0.1 ms 刻み）
    update_max_ms_x10: int | None  # 同じく、直近の最大
    render_mean_ms_x10: int | None  # 実描画1回の時間の、直近の平均（0.1 ms 刻み）
    render_max_ms_x10: int | None  # 同じく、直近の最大
    updates_per_s_x10: int | None  # 毎秒の更新の回数（0.1回刻み）
    renders_per_s_x10: int | None  # 毎秒の実描画の回数（0.1回刻み）
    boot_s_x10: int | None  # アプリの起動にかかった時間（0.1秒刻み）。main() の始まりから、最初の更新まで
    page_s_x10: int | None  # ブラウザ版だけ。ページを開いてから、main() が始まるまで（0.1秒刻み）。デスクトップ版は None

    def __post_init__(self) -> None:
        for field in PERF_FIELDS:
            value = getattr(self, field)
            if value is not None:
                _count(field, value)


# 処理時間の値の、項目の名（並びは、PerfView の項目の順）。
PERF_FIELDS = (
    "update_mean_ms_x10", "update_max_ms_x10", "render_mean_ms_x10", "render_max_ms_x10",
    "updates_per_s_x10", "renders_per_s_x10", "boot_s_x10", "page_s_x10",
)
PERF_NOT_MEASURED = PerfView(*(None,) * len(PERF_FIELDS))  # どれも、測れていない


@dataclass(frozen=True)
class PlaceholderView:
    """仮の表示の、表示用の値。作るときに、型と範囲を検査する。

    renders（実描画の回数）は、実時間で決まる値。表示にだけ使い、世界へ戻さない。
    いまは cp_app/app.py が、世界のtick、実描画の回数、直近の入力フレーム、知らせの1行、車の値、処理時間の値から組み立てる
    （実描画の回数と、処理時間を、ロジックは持たないため）。
    notice は、保存についての知らせの1行（文は cp_core/storage.py の NOTICES）。無ければ空。省けない
    （アプリが渡し忘れたら、作る時に落ちる）。本物の通知は、画面の状態を作る段1で作る。
    car は、車の値（速度、ギア、回転数、位置、路面の種類）。省けない。実機で、車が動いていることを見るための表示（HUDは段1）。
    perf は、処理時間の値（更新1回と実描画1回の時間、毎秒の回数、起動にかかった時間）。省けない。実機で、人が読んで知らせるための表示。
    """

    tick: int  # 世界のtick
    renders: int  # 実描画の回数。表示にだけ使う
    frame: InputFrame  # 直近の入力フレーム
    notice: str  # 知らせの1行。無ければ空
    car: CarView  # 車の値
    perf: PerfView  # 処理時間の値。表示にだけ使う

    def __post_init__(self) -> None:
        _count("tick", self.tick)
        _count("renders", self.renders)
        if not isinstance(self.frame, InputFrame):
            raise TypeError(f"frame must be an InputFrame, got {type(self.frame).__name__}")
        if type(self.notice) is not str:
            raise TypeError(f"notice={self.notice!r} must be str")
        if not isinstance(self.car, CarView):
            raise TypeError(f"car must be a CarView, got {type(self.car).__name__}")
        if not isinstance(self.perf, PerfView):
            raise TypeError(f"perf must be a PerfView, got {type(self.perf).__name__}")


class Flow:
    """画面の状態。いまは、いまの画面の名だけを持つ（いつも START_SCREEN）。切り替えは、まだ無い。"""

    def __init__(self) -> None:
        self.screen = START_SCREEN  # いまの画面の名。SCREEN_NAMES のどれか
