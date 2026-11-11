"""描画命令と、その列をためる Canvas（純Python）。2Dの描画は必ずここを通す。

Canvas は描画命令を呼ばれた順にためるだけで、絵は描かない。ためた列を
cp_app.canvas_pyxel が Pyxel で実行する。
命令は、文字（text）、塗りつぶした矩形（rect）、縁だけの矩形（rectb）、線（line）。色を含めて持つ。
画像（blt）は、使う画面を作る区切りで足す。
囲み（Canvas.box）は、描画命令をまとめる範囲。何も描かない。`with` の中で呼んだ命令は、その囲みの番号を持ち、
囲みの内に収まっていなければ、はみ出しになる（数えるのは cp_ui.check）。囲みは Canvas.boxes に並べ、
描く命令の列（Canvas.commands）には入れない。
`with` を付けずに `canvas.box(...)` を呼ぶと、囲みは宣言されるだけで開かれず、後の命令は囲みに入らない。
`with` で1度でも入った囲みの番号を Canvas.entered に残し、はみ出しの検査が、開かれなかった囲みを数える。
どの命令も、矩形を返す口（bounds。左上と、幅、高さ）を持つ。文字の矩形は、インクの箱（text_size）。
文字の大きさの式が実物の画素と合うことは、巡回（tools/tour.py）が毎回照らす。
"""
from dataclasses import dataclass

SCREEN_W, SCREEN_H = 320, 240  # 画面の大きさ。設計の前提（仮の値にしない）
FONT_W, FONT_H = 4, 6  # 内蔵フォントの1字のセル（Pyxelの FONT_WIDTH、FONT_HEIGHT）。設計の前提
# 6行目の画素を使う字。印字できるASCIIの中では、この5つだけ（実測）。
DESCENDERS = frozenset("gjpqy")
SCREEN_BOX = -1  # 囲みの番号で、画面そのものを指す値


def text_size(s: str) -> tuple:
    """文字のインクの箱（実際に画素を置く範囲）の (幅, 高さ)。

    内蔵フォントのインクは、4×6のセルの中で、幅が最大3、高さが5。g j p q y だけ高さが6（実測）。
    幅は 4×（いちばん長い行の字数）−1、高さは 6×行数−1。最後の行に g j p q y があれば 6×行数。
    空の文字列は、幅が −1 になる（はみ出しの検査が、空の矩形として数える）。
    """
    lines = s.split("\n")
    last_row = 0 if DESCENDERS & set(lines[-1]) else 1
    return FONT_W * max(len(line) for line in lines) - 1, FONT_H * len(lines) - last_row


@dataclass(frozen=True)
class TextCommand:
    """文字を描く命令。(x, y) は左上。"""

    x: int
    y: int
    text: str
    col: int
    box: int = SCREEN_BOX  # 自分を囲む囲みの番号（Canvas.boxes の位置）。−1 は画面
    kind = "text"  # 命令の種類。項目ではなく、クラスごとの定数

    @property
    def bounds(self) -> tuple:
        """矩形 (x, y, w, h)。インクの箱。"""
        return (self.x, self.y, *text_size(self.text))


@dataclass(frozen=True)
class RectCommand:
    """塗りつぶした矩形を描く命令。(x, y) は左上。"""

    x: int
    y: int
    w: int
    h: int
    col: int
    box: int = SCREEN_BOX  # 自分を囲む囲みの番号。−1 は画面
    kind = "rect"  # 命令の種類。項目ではなく、クラスごとの定数

    @property
    def bounds(self) -> tuple:
        """矩形 (x, y, w, h)。"""
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class RectbCommand:
    """縁だけの矩形を描く命令。(x, y) は左上。中は塗らない。"""

    x: int
    y: int
    w: int
    h: int
    col: int
    box: int = SCREEN_BOX  # 自分を囲む囲みの番号。−1 は画面
    kind = "rectb"  # 命令の種類。項目ではなく、クラスごとの定数

    @property
    def bounds(self) -> tuple:
        """矩形 (x, y, w, h)。"""
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class LineCommand:
    """線を描く命令。(x1, y1) から (x2, y2) まで。両端を含む。"""

    x1: int
    y1: int
    x2: int
    y2: int
    col: int
    box: int = SCREEN_BOX  # 自分を囲む囲みの番号。−1 は画面
    kind = "line"  # 命令の種類。項目ではなく、クラスごとの定数

    @property
    def bounds(self) -> tuple:
        """矩形 (x, y, w, h)。両端を含む、外接の矩形。"""
        return (min(self.x1, self.x2), min(self.y1, self.y2), abs(self.x2 - self.x1) + 1, abs(self.y2 - self.y1) + 1)


@dataclass(frozen=True)
class Box:
    """囲み。描画命令をまとめる範囲（パネル、一覧の行、HUDのまとまり）。何も描かない。"""

    name: str
    x: int
    y: int
    w: int
    h: int
    parent: int = SCREEN_BOX  # 親の囲みの番号（Canvas.boxes の位置）。−1 は画面

    @property
    def bounds(self) -> tuple:
        """矩形 (x, y, w, h)。"""
        return (self.x, self.y, self.w, self.h)


def _require_int(command: str, **values) -> None:
    """画面の座標と色の番号は整数に限る。bool と小数は受けない。"""
    for name, value in values.items():
        if type(value) is not int:
            raise TypeError(f"{command}: {name}={value!r} must be int (UI coordinates are whole pixels)")


class _BoxScope:
    """`with canvas.box(...)` の間だけ、その囲みを、いま開いている囲みにする。"""

    def __init__(self, canvas: "Canvas", index: int) -> None:
        self._canvas, self.index = canvas, index

    def __enter__(self) -> int:
        self._canvas._open.append(self.index)
        self._canvas.entered.add(self.index)  # 中に何も描かなくても、入ったことは残す
        return self.index  # 囲みの番号

    def __exit__(self, *exc) -> bool:
        self._canvas._open.pop()
        return False  # 中の例外は、そのまま外へ出す


class Canvas:
    """描画命令を呼ばれた順にためる。引数の並びは Pyxel の同名の関数と同じにする。"""

    def __init__(self, w: int = SCREEN_W, h: int = SCREEN_H) -> None:
        self.w, self.h = w, h
        self.commands: list = []  # 呼ばれた順の描画命令
        self.boxes: list = []  # 宣言した順の囲み。命令の box と、囲みの parent は、ここの位置
        self.entered: set = set()  # `with` で1度でも入った囲みの番号。ここに無い囲みは、開かれなかった囲み
        self._open: list = [SCREEN_BOX]  # いま開いている囲みの番号の積み重ね。底は画面

    def box(self, name: str, x: int, y: int, w: int, h: int) -> _BoxScope:
        """囲みを宣言する。`with canvas.box(名, x, y, w, h):` の形で使う。入れ子にできる。何も描かない。

        `with` を付けないと、囲みは開かれない（はみ出しの検査が、box_not_entered として数える）。
        """
        if type(name) is not str:
            raise TypeError(f"box: name={name!r} must be str")
        _require_int("box", x=x, y=y, w=w, h=h)
        self.boxes.append(Box(name, x, y, w, h, self._open[-1]))
        return _BoxScope(self, len(self.boxes) - 1)

    def text(self, x: int, y: int, s: str, col: int) -> None:
        _require_int("text", x=x, y=y, col=col)
        if type(s) is not str:
            raise TypeError(f"text: s={s!r} must be str")
        self.commands.append(TextCommand(x, y, s, col, self._open[-1]))

    def rect(self, x: int, y: int, w: int, h: int, col: int) -> None:
        _require_int("rect", x=x, y=y, w=w, h=h, col=col)
        self.commands.append(RectCommand(x, y, w, h, col, self._open[-1]))

    def rectb(self, x: int, y: int, w: int, h: int, col: int) -> None:
        _require_int("rectb", x=x, y=y, w=w, h=h, col=col)
        self.commands.append(RectbCommand(x, y, w, h, col, self._open[-1]))

    def line(self, x1: int, y1: int, x2: int, y2: int, col: int) -> None:
        _require_int("line", x1=x1, y1=y1, x2=x2, y2=y2, col=col)
        self.commands.append(LineCommand(x1, y1, x2, y2, col, self._open[-1]))
