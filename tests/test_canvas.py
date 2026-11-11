"""描画命令の記録（cp_ui.canvas）と、その実行（cp_app.canvas_pyxel）のテスト。Pyxelは使わない。"""
import dataclasses

import pytest

from cp_app.canvas_pyxel import execute
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas, RectCommand, TextCommand


class FakeImage:
    """pyxel.Image の代わり。呼ばれた描画を順に覚えるだけ。"""

    def __init__(self) -> None:
        self.calls = []

    def text(self, x, y, s, col):
        self.calls.append(("text", x, y, s, col))

    def rect(self, x, y, w, h, col):
        self.calls.append(("rect", x, y, w, h, col))


def test_canvas_screen_size_matches_the_design():
    assert (SCREEN_W, SCREEN_H) == (320, 240)
    canvas = Canvas()
    assert (canvas.w, canvas.h) == (320, 240)


def test_canvas_starts_empty():
    assert Canvas().commands == []


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


def test_canvas_commands_cannot_be_changed_after_recording():
    canvas = Canvas()
    canvas.text(1, 2, "A", 7)
    with pytest.raises(dataclasses.FrozenInstanceError):
        canvas.commands[0].x = 5


def test_canvas_two_canvases_do_not_share_commands():
    a, b = Canvas(), Canvas()
    a.text(1, 2, "A", 7)
    assert b.commands == []


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
    ],
)
def test_canvas_rejects_values_that_are_not_whole_pixels(draw):
    canvas = Canvas()
    with pytest.raises(TypeError):
        draw(canvas)
    assert canvas.commands == []


def test_canvas_pyxel_executes_every_command_in_order():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    canvas.text(4, 3, "CLIPPING POINT", 7)
    target = FakeImage()
    assert execute(canvas.commands, target) == 2
    assert target.calls == [("rect", 0, 0, 320, 12, 1), ("text", 4, 3, "CLIPPING POINT", 7)]


def test_canvas_pyxel_draws_nothing_for_an_empty_list():
    target = FakeImage()
    assert execute([], target) == 0
    assert target.calls == []


def test_canvas_pyxel_rejects_an_unknown_command():
    class LineCommand:
        kind = "line"

    with pytest.raises(ValueError):
        execute([LineCommand()], FakeImage())
