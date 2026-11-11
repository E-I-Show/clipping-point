"""画面の組み立て（cp_ui.screens）のテスト。Pyxelは使わない。"""
import pytest

from cp_core.input_frame import BUTTONS, NEUTRAL, InputFrame
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, TITLE, build_placeholder

FONT_W, FONT_H = 4, 6  # 内蔵フォントの1文字の大きさ（設計の前提）
# いちばん長くなる入力フレーム。舵は負（符号の分、1字長い）、10個のボタンを全部押している。
EVERYTHING = InputFrame(
    steer_analog=-1.0, steer_digital=-1, throttle_analog=1.0, throttle_digital=1, brake_analog=1.0, brake_digital=1,
    held=frozenset(BUTTONS), pressed=frozenset(BUTTONS),
)


def placeholder(tick: int = 120, renders: int = 60, frame: InputFrame = NEUTRAL) -> list:
    canvas = Canvas()
    build_placeholder(canvas, tick, renders, frame)
    return canvas.commands


def texts(*args, **kwargs) -> list:
    return [command.text for command in placeholder(*args, **kwargs) if command.kind == "text"]


def test_screens_placeholder_shows_title_tick_and_render_count():
    assert texts(120, 60)[:3] == [TITLE, "TICK 120", "RENDER 60"]


def test_screens_placeholder_follows_the_given_numbers():
    assert texts(7, 3)[1:3] == ["TICK 7", "RENDER 3"]


def test_screens_placeholder_has_two_lines_for_the_input_frame():
    assert len(texts()) == 5
    values, held = texts()[3:]
    assert values == "STEER A    +0 D +0  THROTTLE A    0 D 0  BRAKE A    0 D 0"
    assert held == "HELD -"


def test_screens_placeholder_shows_analog_values_in_thousandths_and_digital_values():
    frame = InputFrame(steer_analog=0.5, steer_digital=1, throttle_analog=0.3, throttle_digital=1, brake_analog=0.6)
    assert texts(frame=frame)[3] == "STEER A  +500 D +1  THROTTLE A  300 D 1  BRAKE A  600 D 0"
    # 舵は左が正。右へ切ると負。
    right = InputFrame(steer_analog=-1.0, steer_digital=-1, brake_analog=1.0, brake_digital=1)
    assert texts(frame=right)[3] == "STEER A -1000 D -1  THROTTLE A    0 D 0  BRAKE A 1000 D 1"


def test_screens_placeholder_shows_the_held_buttons_in_upper_case_in_the_fixed_order():
    assert texts(frame=InputFrame(held=frozenset({"confirm", "up"})))[4] == "HELD UP CONFIRM"
    assert texts(frame=EVERYTHING)[4] == "HELD " + " ".join(name.upper() for name in BUTTONS)


def test_screens_placeholder_shows_held_buttons_not_the_pressed_ones():
    # 押した瞬間は1 tickだけなので、目で追えない。出すのは、押しているボタン。
    assert texts(frame=InputFrame(pressed=frozenset({"pause"})))[4] == "HELD -"


def test_screens_placeholder_input_lines_keep_their_width():
    # 値が変わっても、1行目の長さは変わらない（数字がちらつかない）。
    lengths = {len(texts(frame=frame)[3]) for frame in (NEUTRAL, EVERYTHING, InputFrame(steer_analog=0.001, throttle_analog=0.5))}
    assert len(lengths) == 1


@pytest.mark.parametrize("frame", [NEUTRAL, EVERYTHING])
def test_screens_placeholder_text_is_ascii_only(frame):
    for command in placeholder(frame=frame):
        if command.kind == "text":
            assert command.text.isascii() and command.text.isprintable()
            assert command.text == command.text.upper()


@pytest.mark.parametrize("frame", [NEUTRAL, EVERYTHING])
def test_screens_placeholder_stays_inside_the_screen(frame):
    # 6桁のtick（約4.6時間ぶん）でも、10個のボタンを全部押していても、画面の内に収まる。
    for command in placeholder(999999, 999999, frame):
        assert 0 <= command.x < SCREEN_W and 0 <= command.y < SCREEN_H
        if command.kind == "rect":
            assert command.x + command.w <= SCREEN_W and command.y + command.h <= SCREEN_H
        else:
            assert command.x + FONT_W * len(command.text) <= SCREEN_W
            assert command.y + FONT_H <= SCREEN_H


def test_screens_placeholder_lines_do_not_overlap():
    rows = sorted(command.y for command in placeholder(frame=EVERYTHING) if command.kind == "text")
    assert all(later - earlier >= FONT_H for earlier, later in zip(rows, rows[1:]))


def test_screens_placeholder_draws_something_other_than_the_background():
    assert any(command.col != COL_BACK for command in placeholder())
