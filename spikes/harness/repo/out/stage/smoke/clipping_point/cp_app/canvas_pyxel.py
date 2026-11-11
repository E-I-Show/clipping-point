"""Canvas that also draws: forwards every recorded call to a pyxel.Image."""
from cp_ui.canvas import Canvas


class PyxelCanvas(Canvas):
    def __init__(self, target, w: int, h: int, ox: int = 0, oy: int = 0) -> None:
        super().__init__(w, h)
        self.t, self.ox, self.oy = target, ox, oy  # (ox, oy): draw offset, used by the ink check

    def _draw_text(self, x, y, s, col):
        self.t.text(x + self.ox, y + self.oy, s, col)

    def _draw_rect(self, x, y, w, h, col):
        self.t.rect(x + self.ox, y + self.oy, w, h, col)

    def _draw_rectb(self, x, y, w, h, col):
        self.t.rectb(x + self.ox, y + self.oy, w, h, col)

    def _draw_line(self, x1, y1, x2, y2, col):
        self.t.line(x1 + self.ox, y1 + self.oy, x2 + self.ox, y2 + self.oy, col)

    def _draw_blt(self, x, y, img, u, v, w, h, colkey):
        self.t.blt(x + self.ox, y + self.oy, img, u, v, w, h, colkey)
