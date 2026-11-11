"""Thin drawing layer. Every 2D draw call of the game goes through a Canvas.

Canvas records what was drawn (kind, rectangle, the box it belongs to). cp_app.canvas_pyxel.
PyxelCanvas additionally forwards each call to a pyxel.Image. The recording is what
cp_ui.check inspects, so the overflow check needs no Pyxel and runs in milliseconds.

Text metrics of Pyxel's built-in font (pyxel.FONT_WIDTH=4, FONT_HEIGHT=6): a character cell is
4x6; text_size() returns the ink box. tools/tour.py compares it with the real pixels on every run
(a recorder with wrong metrics would make the overflow check pass for the wrong reason).
"""
from dataclasses import dataclass

SCREEN_W, SCREEN_H = 320, 240
FONT_W, FONT_H = 4, 6


DESCENDERS = set("gjpqy")  # the only printable ASCII glyphs that use the 6th row (measured)


def text_size(s: str):
    """Ink box of `s` in the built-in font: glyphs are at most 3 px wide in a 4 px cell and 5 px
    tall in a 6 px cell, except the lowercase descenders, which use all 6 rows."""
    lines = s.split("\n")
    last_row = 0 if DESCENDERS & set(lines[-1]) else 1
    return max(len(line) for line in lines) * FONT_W - 1, len(lines) * FONT_H - last_row


@dataclass
class Item:
    kind: str  # text / rect / rectb / line / blt / box
    x: int
    y: int
    w: int
    h: int
    box: int  # index into Canvas.items of the enclosing box, -1 = screen
    label: str = ""

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h


class _BoxScope:
    def __init__(self, canvas, index):
        self.canvas, self.index = canvas, index

    def __enter__(self):
        self.canvas._stack.append(self.index)
        return self

    def __exit__(self, *exc):
        self.canvas._stack.pop()
        return False


class Canvas:
    def __init__(self, w: int = SCREEN_W, h: int = SCREEN_H) -> None:
        self.w, self.h = w, h
        self.items: list = []
        self._stack: list = [-1]

    # --- recording ---------------------------------------------------------------------
    def _add(self, kind, x, y, w, h, label=""):
        for name, v in (("x", x), ("y", y), ("w", w), ("h", h)):
            if type(v) is not int:
                raise TypeError(f"{kind} {label!r}: {name}={v!r} must be int (UI coordinates are whole pixels)")
        self.items.append(Item(kind, x, y, w, h, self._stack[-1], label))
        return len(self.items) - 1

    def box(self, name: str, x: int, y: int, w: int, h: int):
        """Declare a layout frame (panel, list row, HUD cluster). Nothing is drawn. Everything
        drawn inside the `with` block must stay within it."""
        return _BoxScope(self, self._add("box", x, y, w, h, name))

    # --- draw calls (same argument order as pyxel) ---------------------------------------
    def text(self, x: int, y: int, s: str, col: int) -> None:
        w, h = text_size(s)
        self._add("text", x, y, w, h, s)
        self._draw_text(x, y, s, col)

    def rect(self, x: int, y: int, w: int, h: int, col: int) -> None:
        self._add("rect", x, y, w, h)
        self._draw_rect(x, y, w, h, col)

    def rectb(self, x: int, y: int, w: int, h: int, col: int) -> None:
        self._add("rectb", x, y, w, h)
        self._draw_rectb(x, y, w, h, col)

    def line(self, x1: int, y1: int, x2: int, y2: int, col: int) -> None:
        self._add("line", min(x1, x2), min(y1, y2), abs(x2 - x1) + 1, abs(y2 - y1) + 1)
        self._draw_line(x1, y1, x2, y2, col)

    def blt(self, x: int, y: int, img, u: int, v: int, w: int, h: int, colkey=None) -> None:
        self._add("blt", x, y, abs(w), abs(h))
        self._draw_blt(x, y, img, u, v, w, h, colkey)

    # --- backend hooks: no-ops here, overridden by PyxelCanvas ---------------------------
    def _draw_text(self, x, y, s, col): ...
    def _draw_rect(self, x, y, w, h, col): ...
    def _draw_rectb(self, x, y, w, h, col): ...
    def _draw_line(self, x1, y1, x2, y2, col): ...
    def _draw_blt(self, x, y, img, u, v, w, h, colkey): ...
