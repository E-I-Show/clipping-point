"""画面の組み立て（cp_ui.screens）のテスト。Pyxelは使わない。"""
import ast

import pytest

from conftest import ROOT
from cp_core.input_frame import BUTTONS, NEUTRAL, InputFrame
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, TITLE, build_placeholder

APP_PY = ROOT / "clipping_point" / "cp_app" / "app.py"
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


# --- アプリから仮の表示への配線 ---
def app_method(name: str) -> ast.FunctionDef:
    """app.py の App のメソッドを、ソースから読む。pyxel は読み込まない。"""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    found = [
        node
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "App"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(found) == 1, name
    return found[0]


def is_self_attribute(node, name: str) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == name and isinstance(node.value, ast.Name) and node.value.id == "self"


def test_screens_app_shows_the_input_frame_it_gave_to_the_world():
    # 守りのテスト。仮の表示の入力フレームの2行は、実機で、実物のコントローラーの値を見るための表示。
    # update() の `self.frame = frame` を消しても、render() に NEUTRAL を渡しても、世界へは正しい入力フレームが届くので、
    # 道具は全部通り、表示だけが0と「HELD -」で固まる（run も web-smoke も、画面は「背景と違う画素がある」までしか見ない）。
    # 見るのは、ソースの上のつながりだけ。段0 区切り6の巡回で、実際の画素と照らせるようになったら置き換える。
    update = app_method("update")
    # (1) update() の中に self.frame への代入が1つあり、その値が、sim.step() に渡したものと同じ名であること。
    stored = [
        node.value
        for node in ast.walk(update)
        if isinstance(node, ast.Assign) and any(is_self_attribute(target, "frame") for target in node.targets)
    ]
    assert len(stored) == 1 and isinstance(stored[0], ast.Name)
    steps = [
        call
        for call in ast.walk(update)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "step" and is_self_attribute(call.func.value, "sim")
    ]
    assert len(steps) == 1 and len(steps[0].args) == 1 and not steps[0].keywords
    assert isinstance(steps[0].args[0], ast.Name) and steps[0].args[0].id == stored[0].id
    # その名は、update() の中で1度だけ決まる（同じ名でも、途中で別の値に替わっていないこと）。
    bound = [
        node
        for node in ast.walk(update)
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == stored[0].id for target in node.targets)
    ]
    assert len(bound) == 1
    # (2) render() が、画面の組み立てに self.frame を渡していること。
    render = app_method("render")
    builds = [
        call
        for call in ast.walk(render)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "build_placeholder"
    ]
    assert len(builds) == 1
    frame_args = [*builds[0].args[3:4], *(keyword.value for keyword in builds[0].keywords if keyword.arg == "frame")]
    assert len(frame_args) == 1 and is_self_attribute(frame_args[0], "frame")
