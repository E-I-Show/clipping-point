"""画面ごとの組み立て（純Python）。Canvas に描画命令をためる。どこに何を描くかは、ここで決める。

いまは起動時の仮の表示だけ。画面の一覧とはみ出しの検査は、段0 区切り6で足す。
"""
from cp_core.input_frame import BUTTONS, InputFrame, quantize
from cp_ui.canvas import SCREEN_W, Canvas

TITLE = "CLIPPING POINT"
# 仮の値：Pyxelの既定パレットの番号（黒、紺、白）。パレットを決める区切り（段0 区切り10）で定義データへ移す。
COL_BACK, COL_BAR, COL_TEXT = 0, 1, 7
NO_BUTTON = "-"  # 押しているボタンが無いときに出す字


def build_placeholder(canvas: Canvas, tick: int, renders: int, frame: InputFrame) -> None:
    """仮の表示。タイトル、tick数、実描画の回数、入力フレームの値。画面に出す文字は英数字と記号のみ。

    入力フレームの2行は、実機で、実物のコントローラーの値を見るための表示。
    1行目は、舵、アクセル、ブレーキのアナログ値（A。千分率の整数）とデジタル値（D）。舵は左が正。
    2行目は、押しているボタンの名（BUTTONS の並び）。10個とも押した状態でも、画面の内に収まる。
    """
    canvas.rect(0, 0, SCREEN_W, 12, COL_BAR)
    canvas.text(4, 3, TITLE, COL_TEXT)
    canvas.text(4, 20, f"TICK {tick}", COL_TEXT)
    canvas.text(4, 28, f"RENDER {renders}", COL_TEXT)
    steer_a, steer_d, throttle_a, throttle_d, brake_a, brake_d, _, _ = quantize(frame)
    canvas.text(
        4, 40, f"STEER A {steer_a:+5d} D {steer_d:+d}  THROTTLE A {throttle_a:4d} D {throttle_d}  BRAKE A {brake_a:4d} D {brake_d}", COL_TEXT
    )
    held = " ".join(name.upper() for name in BUTTONS if name in frame.held)
    canvas.text(4, 48, f"HELD {held or NO_BUTTON}", COL_TEXT)
