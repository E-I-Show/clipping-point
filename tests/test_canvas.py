"""描画命令をためる Canvas（cp_ui.canvas）と、その実行（cp_app.canvas_pyxel）のテスト。Pyxelは使わない。

文字の大きさの式（text_size）が実物の画素と合うことは、ここでは見ない。巡回（tools/tour.py）が、実物のPyxelで照らす。
"""
import dataclasses

import pytest

from cp_app.canvas_pyxel import execute
from cp_ui.canvas import (
    FONT_H, FONT_W, SCREEN_BOX, SCREEN_H, SCREEN_W, Box, Canvas, LineCommand, RectbCommand, RectCommand, TextCommand, text_size,
)


class FakeImage:
    """pyxel.Image の代わり。呼ばれた描画を順に覚えるだけ。"""

    def __init__(self) -> None:
        self.calls = []

    def text(self, x, y, s, col):
        self.calls.append(("text", x, y, s, col))

    def rect(self, x, y, w, h, col):
        self.calls.append(("rect", x, y, w, h, col))

    def rectb(self, x, y, w, h, col):
        self.calls.append(("rectb", x, y, w, h, col))

    def line(self, x1, y1, x2, y2, col):
        self.calls.append(("line", x1, y1, x2, y2, col))


def test_canvas_screen_size_matches_the_design():
    assert (SCREEN_W, SCREEN_H) == (320, 240)
    canvas = Canvas()
    assert (canvas.w, canvas.h) == (320, 240)


def test_canvas_starts_empty():
    canvas = Canvas()
    assert canvas.commands == [] and canvas.boxes == []


def test_canvas_records_text_and_rect_in_call_order():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    canvas.text(4, 3, "CLIPPING POINT", 7)
    canvas.text(4, 20, "TICK 120", 7)
    assert canvas.commands == [
        RectCommand(0, 0, 320, 12, 1),
        TextCommand(4, 3, "CLIPPING POINT", 7),
        TextCommand(4, 20, "TICK 120", 7),
    ]
    assert [command.kind for command in canvas.commands] == ["rect", "text", "text"]


def test_canvas_records_rectb_and_line_with_their_colors():
    canvas = Canvas()
    canvas.rectb(2, 38, 316, 19, 5)
    canvas.line(0, 12, 319, 12, 6)
    assert canvas.commands == [RectbCommand(2, 38, 316, 19, 5), LineCommand(0, 12, 319, 12, 6)]
    assert [command.kind for command in canvas.commands] == ["rectb", "line"]
    assert [command.col for command in canvas.commands] == [5, 6]


def test_canvas_commands_cannot_be_changed_after_recording():
    canvas = Canvas()
    canvas.text(1, 2, "A", 7)
    with pytest.raises(dataclasses.FrozenInstanceError):
        canvas.commands[0].x = 5


def test_canvas_two_canvases_do_not_share_commands():
    a, b = Canvas(), Canvas()
    a.text(1, 2, "A", 7)
    with a.box("panel", 0, 0, 10, 10):
        pass
    assert b.commands == [] and b.boxes == []


@pytest.mark.parametrize(
    "draw",
    [
        lambda c: c.text(1.5, 2, "A", 7),
        lambda c: c.text(1, 2.0, "A", 7),
        lambda c: c.text(1, 2, "A", 7.0),
        lambda c: c.text(True, 2, "A", 7),
        lambda c: c.text(1, 2, 123, 7),
        lambda c: c.rect(0, 0, 10.0, 10, 1),
        lambda c: c.rect(0, 0, 10, 10 / 2, 1),
        lambda c: c.rect("0", 0, 10, 10, 1),
        lambda c: c.rectb(0, 0, 10.0, 10, 1),
        lambda c: c.rectb(0, 0, 10, 10, True),
        lambda c: c.line(0, 0, 10.5, 10, 1),
        lambda c: c.line(0, 0, 10, 10, 1.0),
        lambda c: c.line(None, 0, 10, 10, 1),
        lambda c: c.box("panel", 0, 0, 10.0, 10),
        lambda c: c.box("panel", False, 0, 10, 10),
        lambda c: c.box(7, 0, 0, 10, 10),
    ],
)
def test_canvas_rejects_values_that_are_not_whole_pixels(draw):
    canvas = Canvas()
    with pytest.raises(TypeError):
        draw(canvas)
    assert canvas.commands == [] and canvas.boxes == []


# --- 囲み ---
def test_canvas_box_draws_nothing_and_is_listed_apart_from_the_commands():
    canvas = Canvas()
    with canvas.box("panel", 10, 20, 100, 50):
        pass
    assert canvas.commands == []
    assert canvas.boxes == [Box("panel", 10, 20, 100, 50, SCREEN_BOX)]
    assert canvas.boxes[0].bounds == (10, 20, 100, 50)


def test_canvas_commands_carry_the_number_of_the_box_they_were_drawn_in():
    canvas = Canvas()
    canvas.text(0, 0, "OUT", 7)
    with canvas.box("first", 0, 10, 100, 20) as first:
        canvas.text(2, 12, "IN FIRST", 7)
        canvas.rect(0, 10, 100, 20, 1)
    with canvas.box("second", 0, 40, 100, 20) as second:
        canvas.rectb(0, 40, 100, 20, 5)
        canvas.line(0, 59, 99, 59, 5)
    canvas.text(0, 70, "OUT AGAIN", 7)
    assert (first, second) == (0, 1)
    assert [command.box for command in canvas.commands] == [SCREEN_BOX, 0, 0, 1, 1, SCREEN_BOX]
    assert SCREEN_BOX == -1


def test_canvas_boxes_nest_and_remember_their_parent():
    canvas = Canvas()
    with canvas.box("panel", 0, 0, 200, 100) as panel:
        canvas.text(2, 2, "PANEL", 7)
        with canvas.box("row", 4, 20, 190, 10) as row:
            canvas.text(6, 22, "ROW", 7)
            with canvas.box("cell", 100, 20, 40, 10) as cell:
                canvas.text(102, 22, "CELL", 7)
            canvas.text(150, 22, "ROW AGAIN", 7)
        canvas.text(2, 90, "PANEL AGAIN", 7)
    with canvas.box("footer", 0, 230, 320, 10) as footer:
        canvas.text(2, 232, "FOOTER", 7)
    assert [box.name for box in canvas.boxes] == ["panel", "row", "cell", "footer"]
    assert [box.parent for box in canvas.boxes] == [SCREEN_BOX, panel, row, SCREEN_BOX]
    assert [command.box for command in canvas.commands] == [panel, row, cell, row, panel, footer]


def test_canvas_box_closes_even_when_the_block_raises():
    canvas = Canvas()
    with pytest.raises(RuntimeError):
        with canvas.box("panel", 0, 0, 100, 100):
            raise RuntimeError("inside the box")
    canvas.text(0, 0, "AFTER", 7)
    assert canvas.commands[0].box == SCREEN_BOX


# --- 文字の大きさと、命令の矩形 ---
def test_canvas_font_cell_matches_the_built_in_font():
    assert (FONT_W, FONT_H) == (4, 6)


@pytest.mark.parametrize(
    "text, size",
    [
        ("A", (3, 5)),
        ("AB", (7, 5)),
        ("CLIPPING POINT", (55, 5)),
        ("AB\nC", (7, 11)),  # 2行。2行目は y+6 から
        ("A\nBCD\nE", (11, 17)),  # 幅は、いちばん長い行
        ("gy", (7, 6)),  # g j p q y は、6行目の画素を使う
        ("j", (3, 6)),
        ("AB\ngy", (7, 12)),  # 最後の行に g j p q y があれば、6×行数
        ("gy\nAB", (7, 11)),  # 最後の行でなければ、次の行のセルの内に収まる
        ("   ", (11, 5)),  # 空白も、字数に数える
        ("", (-1, 5)),  # 空の文字列。幅が −1（はみ出しの検査が、空の矩形として数える）
    ],
)
def test_canvas_text_size_is_the_ink_box(text, size):
    assert text_size(text) == size


def test_canvas_every_command_reports_its_rectangle():
    assert TextCommand(4, 3, "AB", 7).bounds == (4, 3, 7, 5)
    assert TextCommand(4, 3, "AB\ngy", 7).bounds == (4, 3, 7, 12)
    assert RectCommand(1, 2, 30, 40, 1).bounds == (1, 2, 30, 40)
    assert RectbCommand(1, 2, 30, 40, 1).bounds == (1, 2, 30, 40)


@pytest.mark.parametrize(
    "ends, bounds",
    [
        ((0, 12, 319, 12), (0, 12, 320, 1)),  # 横。両端を含む
        ((5, 10, 5, 19), (5, 10, 1, 10)),  # 縦
        ((10, 20, 60, 27), (10, 20, 51, 8)),  # 斜め
        ((60, 27, 10, 20), (10, 20, 51, 8)),  # 逆向きでも同じ
        ((60, 20, 10, 70), (10, 20, 51, 51)),  # 右上から左下
        ((7, 7, 7, 7), (7, 7, 1, 1)),  # 1点
    ],
)
def test_canvas_line_rectangle_is_the_bounding_box_with_both_ends(ends, bounds):
    assert LineCommand(*ends, 7).bounds == bounds


# --- 実行 ---
def test_canvas_pyxel_executes_every_command_in_order():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    canvas.text(4, 3, "CLIPPING POINT", 7)
    canvas.line(0, 12, 319, 12, 5)
    canvas.rectb(2, 38, 316, 19, 6)
    target = FakeImage()
    assert execute(canvas.commands, target) == 4
    assert target.calls == [
        ("rect", 0, 0, 320, 12, 1),
        ("text", 4, 3, "CLIPPING POINT", 7),
        ("line", 0, 12, 319, 12, 5),
        ("rectb", 2, 38, 316, 19, 6),
    ]


def test_canvas_pyxel_shifts_every_kind_of_command_by_the_offset():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    canvas.text(4, 3, "CLIPPING POINT", 7)
    canvas.line(0, 12, 319, 12, 5)
    canvas.rectb(2, 38, 316, 19, 6)
    target = FakeImage()
    assert execute(canvas.commands, target, 16, 20) == 4
    # ずれるのは位置だけ。大きさ、文字、色は変わらない。線は、両端がずれる。
    assert target.calls == [
        ("rect", 16, 20, 320, 12, 1),
        ("text", 20, 23, "CLIPPING POINT", 7),
        ("line", 16, 32, 335, 32, 5),
        ("rectb", 18, 58, 316, 19, 6),
    ]


def test_canvas_pyxel_does_not_draw_the_boxes():
    canvas = Canvas()
    with canvas.box("panel", 0, 0, 100, 100):
        canvas.text(2, 2, "A", 7)
    target = FakeImage()
    assert execute(canvas.commands, target) == 1
    assert target.calls == [("text", 2, 2, "A", 7)]


def test_canvas_pyxel_draws_nothing_for_an_empty_list():
    target = FakeImage()
    assert execute([], target) == 0
    assert target.calls == []


def test_canvas_pyxel_rejects_an_unknown_command():
    class ImageCommand:  # 画像の命令（blt）は、まだ無い
        kind = "blt"

    with pytest.raises(ValueError):
        execute([ImageCommand()], FakeImage())
