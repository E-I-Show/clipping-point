"""画面の組み立て（cp_ui.screens）のテスト。Pyxelは使わない。"""
import ast

import pytest

from conftest import ROOT
from cp_core import storage
from cp_core.flow import SCREEN_NAMES, PlaceholderView
from cp_core.input_frame import BUTTONS, NEUTRAL, InputFrame
from cp_ui import fixtures
from cp_ui.canvas import FONT_H, SCREEN_BOX, SCREEN_H, SCREEN_W, Canvas
from cp_ui.check import find_violations
from cp_ui.screens import COL_BACK, SCREENS, TITLE, build_placeholder

APP_PY = ROOT / "clipping_point" / "cp_app" / "app.py"
# いちばん長くなる入力フレーム。舵は負（符号の分、1字長い）、10個のボタンを全部押している。
EVERYTHING = InputFrame(
    steer_analog=-1.0, steer_digital=-1, throttle_analog=1.0, throttle_digital=1, brake_analog=1.0, brake_digital=1,
    held=frozenset(BUTTONS), pressed=frozenset(BUTTONS),
)


def placeholder_canvas(tick: int = 120, renders: int = 60, frame: InputFrame = NEUTRAL, notice: str = "") -> Canvas:
    canvas = Canvas()
    build_placeholder(canvas, PlaceholderView(tick, renders, frame, notice))
    return canvas


def placeholder(*args, **kwargs) -> list:
    return placeholder_canvas(*args, **kwargs).commands


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
    # 7桁のtick（約46時間ぶん）でも、10個のボタンを全部押していても、画面の内に収まる。
    canvas = placeholder_canvas(9999999, 9999999, frame)
    for command in canvas.commands:
        x, y, w, h = command.bounds
        assert w > 0 and h > 0
        assert 0 <= x and x + w <= SCREEN_W and 0 <= y and y + h <= SCREEN_H
    assert find_violations(canvas) == []


def test_screens_placeholder_lines_do_not_overlap():
    rows = sorted(command.y for command in placeholder(frame=EVERYTHING) if command.kind == "text")
    assert all(later - earlier >= FONT_H for earlier, later in zip(rows, rows[1:]))


def test_screens_placeholder_draws_something_other_than_the_background():
    assert any(command.col != COL_BACK for command in placeholder())


def test_screens_placeholder_uses_every_kind_of_command():
    # 巡回が、どの種類の命令も、実物のPyxelの画素と照らせるようにするため。1つも使わない種類は、照らされない。
    assert {command.kind for command in placeholder()} == {"text", "rect", "rectb", "line"}


def test_screens_placeholder_is_built_from_boxes():
    canvas = placeholder_canvas(frame=EVERYTHING)
    assert [box.name for box in canvas.boxes] == ["title", "status", "input", "input_values"]
    # 入力の2行の囲みは、縁だけの矩形の囲みの中（入れ子）。
    assert [box.parent for box in canvas.boxes] == [SCREEN_BOX, SCREEN_BOX, SCREEN_BOX, 2]
    # どの文字も、どれかの囲みの中にある（囲みの外へ出たことを、数えられる）。
    assert all(command.box != SCREEN_BOX for command in canvas.commands if command.kind == "text")
    by_box = {box.name: [c.text for c in canvas.commands if c.kind == "text" and canvas.boxes[c.box] is box] for box in canvas.boxes}
    assert [len(by_box[name]) for name in ("title", "status", "input", "input_values")] == [1, 2, 0, 2]


# --- 知らせの1行 ---
def test_screens_placeholder_shows_the_notice_as_one_more_line_in_its_own_box():
    notice = "SAVE DATA UNREADABLE. USING DEFAULTS"
    canvas = placeholder_canvas(notice=notice)
    assert texts(notice=notice) == [*texts(), notice]  # ほかの行は、そのまま。知らせを、最後に足す
    assert [box.name for box in canvas.boxes] == ["title", "status", "input", "input_values", "notice"]
    box = canvas.boxes[-1]
    assert box.parent == SCREEN_BOX
    last = canvas.commands[-1]
    assert last.kind == "text" and last.text == notice and canvas.boxes[last.box] is box
    # 入力フレームの囲みの下に置く（重ならない）。
    assert box.y >= 38 + 19 and last.y >= box.y


def test_screens_placeholder_without_a_notice_draws_no_notice_line_and_no_box():
    canvas = placeholder_canvas(notice="")
    assert len([command for command in canvas.commands if command.kind == "text"]) == 5
    assert "notice" not in [box.name for box in canvas.boxes]


@pytest.mark.parametrize("notice", storage.NOTICES)
@pytest.mark.parametrize("frame", [NEUTRAL, EVERYTHING])
def test_screens_placeholder_with_every_notice_stays_inside_the_screen_and_its_box(notice, frame):
    canvas = placeholder_canvas(9999999, 9999999, frame, notice)
    assert find_violations(canvas) == []
    rows = sorted(command.y for command in canvas.commands if command.kind == "text")
    assert all(later - earlier >= FONT_H for earlier, later in zip(rows, rows[1:]))  # 行が重ならない


def test_screens_placeholder_notice_box_has_room_for_78_characters_and_no_more():
    # 知らせの文の長さの上限。囲みの内に収まるのは、78字まで（文は cp_core/storage.py の NOTICES。いまは、いちばん長くて51字）。
    assert find_violations(placeholder_canvas(notice="X" * 78)) == []
    assert [violation.kind for violation in find_violations(placeholder_canvas(notice="X" * 79))] == ["off_screen", "out_of_box"]
    assert max(len(notice) for notice in storage.NOTICES) <= 78


# --- 画面の登録 ---
def test_screens_registry_holds_the_placeholder():
    assert SCREENS == {"placeholder": build_placeholder}


def test_screens_registry_has_the_same_names_as_the_logic():
    # 突き合わせ（見本データを含めた形は tests/test_fixtures.py）。
    assert set(SCREENS) == set(SCREEN_NAMES) and len(SCREENS) == len(SCREEN_NAMES)


@pytest.mark.parametrize("screen", sorted(SCREENS))
@pytest.mark.parametrize("variant", fixtures.VARIANTS)
def test_screens_every_screen_builds_without_violations_in_every_variant(screen, variant):
    canvas = Canvas()
    SCREENS[screen](canvas, fixtures.build(screen, variant))
    assert canvas.commands, "画面が、描画命令を1つも残さない"
    assert find_violations(canvas) == []


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


def assigned_once(function: ast.FunctionDef, name: str) -> list:
    """function の中で、名 name へ代入している文の一覧。"""
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]


def test_screens_app_shows_the_input_frame_it_gave_to_the_world():
    # 守りのテスト。仮の表示の入力フレームの2行は、実機で、実物のコントローラーの値を見るための表示。
    # update() の `self.frame = frame` を消しても、render() が表示用の値に NEUTRAL を入れても、世界へは正しい入力フレームが
    # 届くので、道具は全部通り、表示だけが0と「HELD -」で固まる（run も web-smoke も、画面は「背景と違う画素がある」までしか
    # 見ない。巡回は、見本データで描くので、この配線を通らない）。
    # 見るのは、ソースの上のつながりだけ。画面の状態を作る段1で、入力で画面を進める巡回に置き換える。
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
    assert len(assigned_once(update, stored[0].id)) == 1
    # (2) render() が、表示用の値を1つだけ組み立て、その入力フレームに self.frame を入れていること。
    render = app_method("render")
    views = [
        call
        for call in ast.walk(render)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "PlaceholderView"
    ]
    assert len(views) == 1
    frame_args = [*views[0].args[2:3], *(keyword.value for keyword in views[0].keywords if keyword.arg == "frame")]
    assert len(frame_args) == 1 and is_self_attribute(frame_args[0], "frame")
    # (3) render() が、画面の登録を、画面の状態のいまの画面の名で引き、(2) の表示用の値を渡して描いていること。
    draws = [
        call
        for call in ast.walk(render)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Subscript)
        and isinstance(call.func.value, ast.Name) and call.func.value.id == "SCREENS"
    ]
    assert len(draws) == 1 and len(draws[0].args) == 2 and not draws[0].keywords
    name = draws[0].func.slice
    assert isinstance(name, ast.Attribute) and name.attr == "screen" and is_self_attribute(name.value, "flow")
    view_arg = draws[0].args[1]
    assert isinstance(view_arg, ast.Name)
    bound = assigned_once(render, view_arg.id)
    assert len(bound) == 1 and bound[0].value is views[0]


def self_attribute_values(function: ast.FunctionDef, name: str) -> list:
    """function の中で、self.<name> へ代入している値の一覧。"""
    return [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Assign) and any(is_self_attribute(target, name) for target in node.targets)
    ]


def is_attribute_of(node, owner: str, name: str) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == name and isinstance(node.value, ast.Name) and node.value.id == owner


def test_screens_app_passes_the_notice_to_the_view_and_reports_it_from_the_view():
    # 守りのテスト。知らせの1行（保存先を切り替えた、保存が読めない）が、表示用の値へ渡っていること。
    # ふつうの起動では知らせが無いので、渡し忘れても、run も、web-smoke の4本の筋書きも通る。落ちるのは、
    # 保存先に触れると例外になる筋書き（storage_blocked）だけ。ここでは、ソースの上のつながりを見る。
    # 画面の状態を作る段1で、本物の通知に置き換える。
    # (1) __init__() が、知らせを1度だけ決める。保存先の切り替えの知らせが先で、無ければ、読み込みの知らせ（一度に出すのは、多くて1つ）。
    init = app_method("__init__")
    notices = self_attribute_values(init, "notice")
    assert len(notices) == 1 and isinstance(notices[0], ast.BoolOp) and isinstance(notices[0].op, ast.Or)
    first, second = notices[0].values
    assert is_attribute_of(first, "selected", "notice") and is_attribute_of(second, "loaded", "notice")
    # (2) render() が、表示用の値の知らせに self.notice を入れ、組み立てた表示用の値を self.view に残す。
    render = app_method("render")
    views = [
        call
        for call in ast.walk(render)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "PlaceholderView"
    ]
    assert len(views) == 1
    notice_args = [*views[0].args[3:4], *(keyword.value for keyword in views[0].keywords if keyword.arg == "notice")]
    assert len(notice_args) == 1 and is_self_attribute(notice_args[0], "notice")
    kept = self_attribute_values(render, "view")
    assert len(kept) == 1 and isinstance(kept[0], ast.Name)
    bound = assigned_once(render, kept[0].id)
    assert len(bound) == 1 and bound[0].value is views[0]
    # (3) 結果に入れる知らせは、最後に組み立てた表示用の値（self.view）から取る。アプリが持つ知らせ（self.notice）を、直に入れない。
    report = app_method("storage_report")
    assert not [node for node in ast.walk(report) if is_self_attribute(node, "notice")]
    from_view = [
        node for node in ast.walk(report)
        if isinstance(node, ast.Attribute) and node.attr == "notice" and is_self_attribute(node.value, "view")
    ]
    assert len(from_view) == 1
    # (4) 結果の2つの口（画面なしで回す口と、外から渡す値）が、どちらも storage_report() を呼ぶ。
    for name in ("finish_run", "finish_probe"):
        calls = [
            call for call in ast.walk(app_method(name))
            if isinstance(call, ast.Call) and is_self_attribute(call.func, "storage_report")
        ]
        assert len(calls) == 1, name
