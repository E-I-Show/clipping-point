"""画面ごとの組み立て（純Python）。Canvas に描画命令をためる。どこに何を描くかは、ここで決める。

画面は、(canvas, 表示用の値) を受ける関数。SCREENS = {画面の名: 関数} に登録する。
画面の名は cp_core.flow の SCREEN_NAMES、表示用の値の型も cp_core.flow に置く。見本データは cp_ui.fixtures。
パネル、一覧の行、HUDのまとまりは、囲み（canvas.box）にする。囲みにしないと、囲みの外へ出たことを数えられない。
囲みは `with canvas.box(...):` の形で書く。`with` を付けないと開かれず、はみ出しの検査が、開かれなかった囲みとして数える。
色の番号は、役割の名（cp_core.palette）で引く。番号を、直に書かない。
いまは起動時の仮の表示だけ。仮の表示は、3Dの絵の上に重ねる。上の帯と、下の帯に分け、画面の中ほどは、3Dの絵を隠さない。
"""
from cp_core import palette
from cp_core.flow import CarView, PerfView, PlaceholderView
from cp_core.input_frame import BUTTONS, quantize
from cp_core.vehicle import REVERSE
from cp_ui.canvas import SCREEN_W, Canvas

TITLE = "CLIPPING POINT"
# 仮の表示の色（色の役割の名で引く）。COL_BACK は、2Dだけを描くとき（巡回の、画面の絵）の背景の色。アプリの実描画では、3Dの絵が背景になる。
# COL_PANEL は、文字の後ろに敷く、暗い色の矩形。
COL_BACK, COL_BAR, COL_PANEL, COL_TEXT, COL_EDGE = palette.BLACK, palette.NAVY, palette.BLACK, palette.WHITE, palette.BLUE
NO_BUTTON = "-"  # 押しているボタンが無いときに出す字
NOT_MEASURED = "-"  # 測れていない値（処理時間の、最初の数tick。デスクトップ版の PAGE）に出す字
REVERSE_TEXT = "R"  # 後退のギアの字
POSITION_WIDTH = 8  # 位置の字の幅（-20000.0 が収まる。コースの座標の上限は、cp_core.track の MAX_LENGTH_M）
SPEED_DIGITS = 3  # 仮の表示の、速度（km/h）の桁の数。見本データの極端な値（cp_ui.fixtures）は、ここから導く
RPM_DIGITS = 5  # 仮の表示の、回転数の桁の数
# 処理時間の行の、整数部の桁の数。測った値は、cp_app/perf.py が、この桁いっぱいで頭打ちにして渡す。見本データの極端な値も、ここから導く。
MS_DIGITS = 2  # 更新1回と実描画1回の時間（ms）。99.9 まで
RATE_DIGITS = 3  # 毎秒の回数。999.9 まで
SECONDS_DIGITS = 3  # 起動にかかった時間（秒）。999.9 まで


def _tenths(value: int) -> str:
    """0.1 刻みの整数を、符号つきの、小数第1位までの字にする（1234 は +123.4）。整数だけで作る（小数の丸めを、描く側で持たない）。"""
    size = -value if value < 0 else value
    return f"{'-' if value < 0 else '+'}{size // 10}.{size % 10}"


def _measured(value, whole_digits: int) -> str:
    """測った値（0.1 刻みの、0以上の整数。測れていなければ None）を、小数第1位までの字にする。幅は、整数部の桁＋2字で、そろえる。"""
    text = NOT_MEASURED if value is None else f"{value // 10}.{value % 10}"
    return f"{text:>{whole_digits + 2}}"


def car_lines(car: CarView) -> tuple:
    """車の値の2行。1行目は、速度（km/h）、ギア（後退は R）、回転数。2行目は、位置（m。小数第1位まで）と、路面の種類。"""
    gear = REVERSE_TEXT if car.gear == REVERSE else str(car.gear)
    return (
        f"SPEED {car.speed_kmh:{SPEED_DIGITS}d} KM/H  GEAR {gear}  RPM {car.rpm:{RPM_DIGITS}d}",
        f"POS X {_tenths(car.x_dm):>{POSITION_WIDTH}} Z {_tenths(car.z_dm):>{POSITION_WIDTH}}  ON {car.surface.upper()}",
    )


def perf_lines(perf: PerfView) -> tuple:
    """処理時間の2行。1行目は、更新1回と実描画1回の時間（ms。直近の平均と最大）。2行目は、毎秒の更新と実描画の回数と、
    起動にかかった時間（秒。BOOT はアプリの起動、PAGE は、ブラウザ版でページを開いてからアプリが始まるまで）。測れていない値は「-」。"""
    return (
        f"UPDATE MS AVG {_measured(perf.update_mean_ms_x10, MS_DIGITS)} MAX {_measured(perf.update_max_ms_x10, MS_DIGITS)}"
        f"  RENDER MS AVG {_measured(perf.render_mean_ms_x10, MS_DIGITS)} MAX {_measured(perf.render_max_ms_x10, MS_DIGITS)}",
        f"PER SEC UPDATE {_measured(perf.updates_per_s_x10, RATE_DIGITS)} RENDER {_measured(perf.renders_per_s_x10, RATE_DIGITS)}"
        f"  BOOT S {_measured(perf.boot_s_x10, SECONDS_DIGITS)}  PAGE S {_measured(perf.page_s_x10, SECONDS_DIGITS)}",
    )


def build_placeholder(canvas: Canvas, view: PlaceholderView) -> None:
    """仮の表示。3Dの絵の上に重ねる。画面に出す文字は英数字と記号のみ。文字の後ろには、囲みごとに、暗い色の矩形を敷く。

    上の帯：タイトル、tick数と実描画の回数、処理時間の2行。下の帯：入力フレームの値の2行、車の値の2行、知らせの1行。
    画面の中ほど（上の帯の下から、下の帯の上まで）には、何も置かない（3Dの絵を隠さない）。
    処理時間の2行は、実機で、人が読んで知らせるための表示（更新1回と実描画1回の時間、毎秒の回数、起動にかかった時間）。
    入力フレームの2行は、実機で、実物のコントローラーの値を見るための表示。
    1行目は、舵、アクセル、ブレーキのアナログ値（A。千分率の整数）とデジタル値（D）。舵は左が正。
    2行目は、押しているボタンの名（BUTTONS の並び）。10個とも押した状態でも、囲みの内に収まる。
    車の値の2行は、実機で、車が動いていることを見るための表示（速度、ギア、回転数、位置、路面の種類。HUDは段1）。
    知らせの1行（保存先を切り替えた、保存が読めない、など。文は cp_core/storage.py の NOTICES）は、あるときだけ出す。
    """
    # --- 上の帯 ---
    with canvas.box("title", 0, 0, SCREEN_W, 12):
        canvas.rect(0, 0, SCREEN_W, 12, COL_BAR)
        canvas.text(4, 3, TITLE, COL_TEXT)
    canvas.line(0, 12, SCREEN_W - 1, 12, COL_EDGE)  # 帯の下の線
    with canvas.box("status", 2, 15, 62, 17):
        canvas.rect(2, 15, 62, 17, COL_PANEL)
        canvas.text(4, 17, f"TICK {view.tick}", COL_TEXT)
        canvas.text(4, 25, f"RENDER {view.renders}", COL_TEXT)
    with canvas.box("perf", 70, 15, 248, 17):
        canvas.rect(70, 15, 248, 17, COL_PANEL)
        times, rates = perf_lines(view.perf)
        canvas.text(72, 17, times, COL_TEXT)
        canvas.text(72, 25, rates, COL_TEXT)
    # --- 下の帯 ---
    with canvas.box("input", 2, 190, SCREEN_W - 4, 19):
        canvas.rect(2, 190, SCREEN_W - 4, 19, COL_PANEL)
        canvas.rectb(2, 190, SCREEN_W - 4, 19, COL_EDGE)
        # 文字は、縁から2ピクセル内側の囲みに入れる（縁に重ならないように）。
        with canvas.box("input_values", 4, 192, SCREEN_W - 8, 15):
            steer_a, steer_d, throttle_a, throttle_d, brake_a, brake_d, _, _ = quantize(view.frame)
            canvas.text(
                6, 193, f"STEER A {steer_a:+5d} D {steer_d:+d}  THROTTLE A {throttle_a:4d} D {throttle_d}  BRAKE A {brake_a:4d} D {brake_d}", COL_TEXT
            )
            held = " ".join(name.upper() for name in BUTTONS if name in view.frame.held)
            canvas.text(6, 201, f"HELD {held or NO_BUTTON}", COL_TEXT)
    with canvas.box("car", 2, 211, SCREEN_W - 4, 17):
        canvas.rect(2, 211, SCREEN_W - 4, 17, COL_PANEL)
        first, second = car_lines(view.car)
        canvas.text(6, 213, first, COL_TEXT)
        canvas.text(6, 221, second, COL_TEXT)
    if view.notice:
        # 知らせの1行。無いときは、囲みも、下に敷く矩形も作らない。
        with canvas.box("notice", 2, 230, SCREEN_W - 4, 9):
            canvas.rect(2, 230, SCREEN_W - 4, 9, COL_PANEL)
            canvas.text(6, 232, view.notice, COL_TEXT)


# 画面の登録。鍵は cp_core.flow の SCREEN_NAMES と同じ集まり（tests/test_fixtures.py の突き合わせのテストが見る）。
SCREENS = {"placeholder": build_placeholder}
