"""画面ごとの組み立て（純Python）。Canvas に描画命令をためる。どこに何を描くかは、ここで決める。

画面は、(canvas, 表示用の値) を受ける関数。SCREENS = {画面の名: 関数} に登録する。
画面の名は cp_core.flow の SCREEN_NAMES、表示用の値の型も cp_core.flow に置く。見本データは cp_ui.fixtures。
パネル、一覧の行、HUDのまとまりは、囲み（canvas.box）にする。囲みにしないと、囲みの外へ出たことを数えられない。
いまは起動時の仮の表示だけ。
"""
from cp_core.flow import PlaceholderView
from cp_core.input_frame import BUTTONS, quantize
from cp_ui.canvas import SCREEN_W, Canvas

TITLE = "CLIPPING POINT"
# 仮の値：Pyxelの既定パレットの番号（黒、紺、白、暗い青）。パレットを決める区切り（段0 区切り10）で定義データへ移す。
COL_BACK, COL_BAR, COL_TEXT, COL_EDGE = 0, 1, 7, 5
NO_BUTTON = "-"  # 押しているボタンが無いときに出す字


def build_placeholder(canvas: Canvas, view: PlaceholderView) -> None:
    """仮の表示。タイトル、tick数、実描画の回数、入力フレームの値。画面に出す文字は英数字と記号のみ。

    入力フレームの2行は、実機で、実物のコントローラーの値を見るための表示。
    1行目は、舵、アクセル、ブレーキのアナログ値（A。千分率の整数）とデジタル値（D）。舵は左が正。
    2行目は、押しているボタンの名（BUTTONS の並び）。10個とも押した状態でも、囲みの内に収まる。
    """
    with canvas.box("title", 0, 0, SCREEN_W, 12):
        canvas.rect(0, 0, SCREEN_W, 12, COL_BAR)
        canvas.text(4, 3, TITLE, COL_TEXT)
    canvas.line(0, 12, SCREEN_W - 1, 12, COL_EDGE)  # 帯の下の線
    with canvas.box("status", 2, 18, 64, 18):
        canvas.text(4, 20, f"TICK {view.tick}", COL_TEXT)
        canvas.text(4, 28, f"RENDER {view.renders}", COL_TEXT)
    with canvas.box("input", 2, 38, SCREEN_W - 4, 19):
        canvas.rectb(2, 38, SCREEN_W - 4, 19, COL_EDGE)
        # 文字は、縁から2ピクセル内側の囲みに入れる（縁に重ならないように）。
        with canvas.box("input_values", 4, 40, SCREEN_W - 8, 15):
            steer_a, steer_d, throttle_a, throttle_d, brake_a, brake_d, _, _ = quantize(view.frame)
            canvas.text(
                6, 41, f"STEER A {steer_a:+5d} D {steer_d:+d}  THROTTLE A {throttle_a:4d} D {throttle_d}  BRAKE A {brake_a:4d} D {brake_d}", COL_TEXT
            )
            held = " ".join(name.upper() for name in BUTTONS if name in view.frame.held)
            canvas.text(6, 49, f"HELD {held or NO_BUTTON}", COL_TEXT)


# 画面の登録。鍵は cp_core.flow の SCREEN_NAMES と同じ集まり（tests/test_fixtures.py の突き合わせのテストが見る）。
SCREENS = {"placeholder": build_placeholder}
