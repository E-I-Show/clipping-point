"""描画命令と、その列をためる Canvas（純Python）。2Dの描画は必ずここを通す。

Canvas は描画命令を呼ばれた順にためるだけで、絵は描かない。ためた列を
cp_app.canvas_pyxel が Pyxel で実行する。
いまは最小の形で、命令は text と rect だけ。はみ出しの検査、枠、線、画像は段0 区切り6で足す。
"""
from dataclasses import dataclass

SCREEN_W, SCREEN_H = 320, 240  # 画面の大きさ。設計の前提（仮の値にしない）


@dataclass(frozen=True)
class TextCommand:
    """文字を描く命令。(x, y) は左上。"""

    x: int
    y: int
    text: str
    col: int
    kind = "text"  # 命令の種類。項目ではなく、クラスごとの定数


@dataclass(frozen=True)
class RectCommand:
    """塗りつぶした矩形を描く命令。(x, y) は左上。"""

    x: int
    y: int
    w: int
    h: int
    col: int
    kind = "rect"  # 命令の種類。項目ではなく、クラスごとの定数


def _require_int(command: str, **values) -> None:
    """画面の座標と色の番号は整数に限る。bool と小数は受けない。"""
    for name, value in values.items():
        if type(value) is not int:
            raise TypeError(f"{command}: {name}={value!r} must be int (UI coordinates are whole pixels)")


class Canvas:
    """描画命令を呼ばれた順にためる。引数の並びは Pyxel の同名の関数と同じにする。"""

    def __init__(self, w: int = SCREEN_W, h: int = SCREEN_H) -> None:
        self.w, self.h = w, h
        self.commands: list = []  # 呼ばれた順の描画命令

    def text(self, x: int, y: int, s: str, col: int) -> None:
        _require_int("text", x=x, y=y, col=col)
        if type(s) is not str:
            raise TypeError(f"text: s={s!r} must be str")
        self.commands.append(TextCommand(x, y, s, col))

    def rect(self, x: int, y: int, w: int, h: int, col: int) -> None:
        _require_int("rect", x=x, y=y, w=w, h=h, col=col)
        self.commands.append(RectCommand(x, y, w, h, col))
