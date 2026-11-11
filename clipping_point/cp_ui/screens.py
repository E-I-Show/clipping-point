"""画面ごとの組み立て（純Python）。Canvas に描画命令をためる。どこに何を描くかは、ここで決める。

いまは起動時の仮の表示だけ。画面の一覧とはみ出しの検査は、段0 区切り6で足す。
"""
from cp_ui.canvas import SCREEN_W, Canvas

TITLE = "CLIPPING POINT"
# 仮の値：Pyxelの既定パレットの番号（黒、紺、白）。パレットを決める区切り（段0 区切り10）で定義データへ移す。
COL_BACK, COL_BAR, COL_TEXT = 0, 1, 7


def build_placeholder(canvas: Canvas, tick: int, renders: int) -> None:
    """仮の表示。タイトル、tick数、実描画の回数。画面に出す文字は英数字のみ。"""
    canvas.rect(0, 0, SCREEN_W, 12, COL_BAR)
    canvas.text(4, 3, TITLE, COL_TEXT)
    canvas.text(4, 20, f"TICK {tick}", COL_TEXT)
    canvas.text(4, 28, f"RENDER {renders}", COL_TEXT)
