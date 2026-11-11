"""入力アダプタ（cp_app.input_pyxel）のテスト。Pyxelの代わりに、偽の実装を渡す。

割り当ては、正本（docs/canon/planning.md）の操作の表と照らす。実物のPyxelで全部の名前が引けることは、
道具 run（`python3 tools/run.py --realtime`）が見る。ブラウザ版での読み方は、道具 web-smoke の筋書き gamepad が見る。
"""
import math
import re

import pytest

from conftest import ROOT
from cp_app import input_pyxel
from cp_app.input_pyxel import AXIS_MAX, PyxelInput
from cp_core.input_frame import BUTTONS, NEUTRAL, InputFrame

CANON = ROOT / "docs" / "canon" / "planning.md"
PAD = "GAMEPAD1_"
# 実物のPyxelにある定数の名前。割り当ての表（input_pyxel）からは作らず、ここに書く（表の打ち間違いを写さないため）。
KEY_NAMES = (
    "KEY_LEFT", "KEY_RIGHT", "KEY_UP", "KEY_DOWN", "KEY_Z", "KEY_X", "KEY_S", "KEY_A", "KEY_C", "KEY_RETURN", "KEY_ESCAPE",
    "KEY_SPACE", "KEY_W", "KEY_D",
)
PAD_BUTTON_NAMES = tuple(
    PAD + "BUTTON_" + name
    for name in (
        "A", "B", "X", "Y", "BACK", "GUIDE", "START", "LEFTSTICK", "RIGHTSTICK", "LEFTSHOULDER", "RIGHTSHOULDER",
        "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
    )
)
AXIS_NAMES = tuple(PAD + "AXIS_" + name for name in ("LEFTX", "LEFTY", "RIGHTX", "RIGHTY", "TRIGGERLEFT", "TRIGGERRIGHT"))
STEER, TRIGGER_L, TRIGGER_R = PAD + "AXIS_LEFTX", PAD + "AXIS_TRIGGERLEFT", PAD + "AXIS_TRIGGERRIGHT"
# 正本の操作の表（操作: (キーボード, ゲームパッド・画面上パッド)）。
CANON_ROWS = {
    "ステアリング": ("← →", "左スティック（十字キー左右も可）"),
    "アクセル": ("Z", "右トリガー（Aボタンも可）"),
    "ブレーキ・バック": ("X", "左トリガー（Bボタンも可）"),
    "シフトアップ（MT）": ("S", "X"),
    "シフトダウン（MT）": ("A", "Y"),
    "視点切替": ("C", "BACK"),
    "ポーズ": ("Enter", "START"),
}
# キー1つだけを押したときに、入力フレームに立つ値。上の操作の表に、設計と細目の分を足したもの
# （Esc はポーズと戻る、Enter と START は決定も、Z と Aボタンは決定も、X と Bボタンは戻るも、矢印と十字キーはメニュー操作も）。
ONE_KEY = {
    "KEY_LEFT": {"steer_digital": 1, "held": {"left"}},
    "KEY_RIGHT": {"steer_digital": -1, "held": {"right"}},
    "KEY_UP": {"held": {"up"}},
    "KEY_DOWN": {"held": {"down"}},
    "KEY_Z": {"throttle_digital": 1, "held": {"confirm"}},
    "KEY_X": {"brake_digital": 1, "held": {"back"}},
    "KEY_S": {"held": {"shift_up"}},
    "KEY_A": {"held": {"shift_down"}},
    "KEY_C": {"held": {"view"}},
    "KEY_RETURN": {"held": {"pause", "confirm"}},
    "KEY_ESCAPE": {"held": {"pause", "back"}},
    PAD + "BUTTON_DPAD_LEFT": {"steer_digital": 1, "held": {"left"}},
    PAD + "BUTTON_DPAD_RIGHT": {"steer_digital": -1, "held": {"right"}},
    PAD + "BUTTON_DPAD_UP": {"held": {"up"}},
    PAD + "BUTTON_DPAD_DOWN": {"held": {"down"}},
    PAD + "BUTTON_A": {"throttle_digital": 1, "held": {"confirm"}},
    PAD + "BUTTON_B": {"brake_digital": 1, "held": {"back"}},
    PAD + "BUTTON_X": {"held": {"shift_up"}},
    PAD + "BUTTON_Y": {"held": {"shift_down"}},
    PAD + "BUTTON_BACK": {"held": {"view"}},
    PAD + "BUTTON_START": {"held": {"pause", "confirm"}},
}
# 割り当てに無いキー。押しても、何も立たない。
UNUSED = ("KEY_SPACE", "KEY_W", "KEY_D", PAD + "BUTTON_GUIDE", PAD + "BUTTON_LEFTSTICK", PAD + "BUTTON_RIGHTSTICK", PAD + "BUTTON_LEFTSHOULDER", PAD + "BUTTON_RIGHTSHOULDER")


class WrongKeyKind(Exception):
    """実物のPyxelは、軸のキーを btn で読むと（ボタンのキーを btnv で読むと）、中で落ちる。"""


class FakePyxel:
    """偽の pyxel。定数は、名前ごとの整数。読み方を取り違えると例外を出す。呼ばれ方を覚える。"""

    def __init__(self, down=(), hit=(), axes=None, missing=()) -> None:
        names = [name for name in (*KEY_NAMES, *PAD_BUTTON_NAMES, *AXIS_NAMES) if name not in missing]
        self._name_of = {}
        for index, name in enumerate(names):
            setattr(self, name, 5000 + index)
            self._name_of[5000 + index] = name
        self.down, self.hit, self.axes = set(down), set(hit), dict(axes or {})
        self.calls = []  # (読み方, キーの名前)

    def _key(self, how: str, key, extra: tuple) -> str:
        if extra:
            raise AssertionError(f"{how} takes the key only (no hold or repeat), got extra {extra!r}")
        name = self._name_of[key]
        if ("_AXIS_" in name) != (how == "btnv"):
            raise WrongKeyKind(f"{how}({name})")
        self.calls.append((how, name))
        return name

    def btn(self, key, *extra) -> bool:
        return self._key("btn", key, extra) in self.down

    def btnp(self, key, *extra) -> bool:
        return self._key("btnp", key, extra) in self.hit

    def btnv(self, key, *extra) -> int:
        return self.axes.get(self._key("btnv", key, extra), 0)


def read(is_web=False, direct=None, **state) -> InputFrame:
    return PyxelInput(FakePyxel(**state)).read(is_web, direct)


# --- 割り当て ---
def test_input_pyxel_canon_controls_table_is_the_one_the_assignment_was_made_from():
    # 正本の操作の表が変わったら、ここが落ちる。割り当ての表（input_pyxel）と、下の ONE_KEY を直す合図。
    text = CANON.read_text(encoding="utf-8")
    table = text.split("| 操作 | キーボード | ゲームパッド・画面上パッド |", 1)[1].split("\n\n", 1)[0]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in table.strip().splitlines()[1:]]
    assert {row[0]: (row[1], row[2]) for row in rows} == CANON_ROWS


@pytest.mark.parametrize("key", list(ONE_KEY))
def test_input_pyxel_one_key_down_sets_the_values_in_the_table(key):
    expected = InputFrame(**{name: frozenset(value) if name == "held" else value for name, value in ONE_KEY[key].items()})
    assert read(down=[key]) == expected
    assert read(down=[key], is_web=True) == expected


@pytest.mark.parametrize("key", list(ONE_KEY))
def test_input_pyxel_one_key_hit_sets_pressed_from_btnp_only(key):
    # 「押した瞬間」は btnp で読む。btn が偽でも立つ（1回の更新の中で押して離した）。舵やペダルのデジタル値は立たない。
    assert read(hit=[key]) == InputFrame(pressed=frozenset(ONE_KEY[key]["held"]))


@pytest.mark.parametrize("key", UNUSED)
def test_input_pyxel_keys_outside_the_table_do_nothing(key):
    assert read(down=[key], hit=[key]) == NEUTRAL


def test_input_pyxel_every_button_of_the_input_frame_has_keys():
    assert tuple(input_pyxel.BUTTON_KEYS) == BUTTONS
    for name, keys in input_pyxel.BUTTON_KEYS.items():
        assert any(key.startswith("KEY_") for key in keys), name  # キーボードだけでも遊べる
        assert any(key.startswith(PAD + "BUTTON_") for key in keys), name  # 十字キーと6ボタンにも収まる


def test_input_pyxel_table_and_the_expected_values_name_the_same_keys():
    table = {*input_pyxel.STEER_LEFT_KEYS, *input_pyxel.STEER_RIGHT_KEYS, *input_pyxel.THROTTLE_KEYS, *input_pyxel.BRAKE_KEYS}
    table |= {key for keys in input_pyxel.BUTTON_KEYS.values() for key in keys}
    assert table == set(ONE_KEY)


def test_input_pyxel_nothing_down_is_neutral():
    assert read() == NEUTRAL
    assert read(is_web=True) == NEUTRAL


def test_input_pyxel_left_and_right_together_cancel_the_digital_steer():
    assert read(down=["KEY_LEFT", "KEY_RIGHT"]) == InputFrame(held=frozenset({"left", "right"}))
    assert read(down=["KEY_LEFT", PAD + "BUTTON_DPAD_RIGHT"]).steer_digital == 0
    assert read(down=["KEY_LEFT", PAD + "BUTTON_DPAD_LEFT"]).steer_digital == 1  # 同じ向きの2つは、1のまま


def test_input_pyxel_pressed_is_not_made_from_the_change_of_held():
    # 前のtickとの差からは作らない。押しっぱなしでも、btnp が偽なら立たない。
    fake = FakePyxel(down=["KEY_S"])
    adapter = PyxelInput(fake)
    assert adapter.read(False, None) == InputFrame(held=frozenset({"shift_up"}))
    assert adapter.read(False, None) == InputFrame(held=frozenset({"shift_up"}))
    fake.hit = {"KEY_S"}
    assert adapter.read(False, None).pressed == {"shift_up"}


# --- 舵の符号と丸め ---
@pytest.mark.parametrize(
    "raw, expected",
    [(0, 0.0), (32767, -1.0), (-32767, 1.0), (-32768, 1.0), (40000, -1.0), (-40000, 1.0), (16384, -16384 / 32767), (-8191, 8191 / 32767)],
)
def test_input_pyxel_steer_axis_is_flipped_so_that_left_is_positive(raw, expected):
    # Pyxelの左スティックの軸は、右が正。入力フレームの舵は、左が正。
    for is_web in (False, True):
        frame = read(axes={STEER: raw}, is_web=is_web)
        assert frame.steer_analog == pytest.approx(expected, abs=1e-12)
        assert -1.0 <= frame.steer_analog <= 1.0
        assert frame.steer_digital == 0  # スティックは、デジタル値へ入れない


def test_input_pyxel_steer_at_rest_is_positive_zero():
    assert math.copysign(1.0, read().steer_analog) == 1.0


def test_input_pyxel_adapter_only_scales_the_range():
    # 遊びの除去と応答カーブは入れない（操作補正に置く）。小さな値も、そのまま通す。
    assert read(axes={STEER: -1}).steer_analog == pytest.approx(1 / AXIS_MAX)
    assert read(axes={TRIGGER_R: 1}).throttle_analog == pytest.approx(1 / AXIS_MAX)
    assert AXIS_MAX == 32767


# --- トリガーの3通り ---
def test_input_pyxel_desktop_triggers_are_analog():
    frame = read(axes={TRIGGER_R: 32767, TRIGGER_L: 16384})
    assert frame.throttle_analog == 1.0 and frame.brake_analog == pytest.approx(16384 / 32767)
    assert (frame.throttle_digital, frame.brake_digital) == (0, 0)
    assert read(axes={TRIGGER_R: 40000, TRIGGER_L: -5}) == InputFrame(throttle_analog=1.0, brake_analog=0.0)  # 0〜1 に丸める


def test_input_pyxel_web_direct_read_goes_to_the_analog_values_left_is_brake():
    # 直読みの結果は（左トリガー, 右トリガー）。左がブレーキ、右がアクセル。
    frame = read(is_web=True, direct=(0.6, 0.3))
    assert frame == InputFrame(throttle_analog=0.3, brake_analog=0.6)
    assert read(is_web=True, direct=(0, 1)) == InputFrame(throttle_analog=1.0)  # 整数で届いても受ける
    assert read(is_web=True, direct=(1.5, -0.2)) == InputFrame(brake_analog=1.0)  # 0〜1 に丸める


def test_input_pyxel_web_direct_read_does_not_read_the_pyxel_triggers():
    # Pyxel経由は2値で届く。デジタル値へ入れると、アナログで踏んでいるのに、デジタル操作と見なされる。
    fake = FakePyxel(axes={TRIGGER_R: 32767, TRIGGER_L: 32767})
    frame = PyxelInput(fake).read(True, (0.0, 0.3))
    assert frame == InputFrame(throttle_analog=0.3)
    assert (frame.throttle_digital, frame.brake_digital) == (0, 0)
    assert [name for how, name in fake.calls if how == "btnv"] == [STEER]


def test_input_pyxel_web_without_direct_read_puts_the_pyxel_triggers_into_the_digital_values():
    frame = read(is_web=True, axes={TRIGGER_R: 32767})
    assert frame == InputFrame(throttle_digital=1)
    assert read(is_web=True, axes={TRIGGER_L: 32767}) == InputFrame(brake_digital=1)
    assert read(is_web=True, axes={TRIGGER_L: 1, TRIGGER_R: 1}) == InputFrame(throttle_digital=1, brake_digital=1)  # 0より大きければ1
    assert read(is_web=True, axes={TRIGGER_L: 0, TRIGGER_R: 0}) == NEUTRAL


def test_input_pyxel_web_buttons_still_set_the_digital_pedals_beside_the_direct_read():
    frame = read(is_web=True, direct=(0.0, 0.5), down=[PAD + "BUTTON_A"])
    assert frame == InputFrame(throttle_analog=0.5, throttle_digital=1, held=frozenset({"confirm"}))


def test_input_pyxel_direct_read_on_the_desktop_is_an_error():
    with pytest.raises(ValueError):
        read(is_web=False, direct=(0.0, 0.0))


# --- 読み方 ---
def test_input_pyxel_never_reads_an_axis_with_btn_or_a_button_with_btnv():
    # 偽の pyxel は、取り違えると例外を出す。3通りのどれでも、最後まで読めること。
    everything = dict(down=list(ONE_KEY), hit=list(ONE_KEY), axes={name: 12345 for name in AXIS_NAMES})
    for is_web, direct in ((False, None), (True, None), (True, (0.2, 0.8))):
        fake = FakePyxel(**everything)
        PyxelInput(fake).read(is_web, direct)
        assert all(("_AXIS_" in name) == (how == "btnv") for how, name in fake.calls)


def test_input_pyxel_fake_raises_on_the_wrong_key_kind():
    fake = FakePyxel()
    with pytest.raises(WrongKeyKind):
        fake.btn(getattr(fake, STEER))
    with pytest.raises(WrongKeyKind):
        fake.btnv(fake.KEY_LEFT)


def test_input_pyxel_reads_each_key_once_per_tick():
    fake = FakePyxel()
    adapter = PyxelInput(fake)
    adapter.read(False, None)
    for how in ("btn", "btnp"):
        names = [name for called, name in fake.calls if called == how]
        assert sorted(names) == sorted(ONE_KEY)  # 2つの値に入るキー（矢印の左右、Z など）も、1度だけ
    assert sorted(name for how, name in fake.calls if how == "btnv") == sorted([STEER, TRIGGER_L, TRIGGER_R])


def test_input_pyxel_counts_its_reads():
    adapter = PyxelInput(FakePyxel())
    assert adapter.reads == 0
    for expected in (1, 2, 3):
        adapter.read(False, None)
        assert adapter.reads == expected


def test_input_pyxel_constant_names_are_real_pyxel_names():
    used = {input_pyxel.STEER_AXIS, input_pyxel.THROTTLE_AXIS, input_pyxel.BRAKE_AXIS, *ONE_KEY}
    assert used <= {*KEY_NAMES, *PAD_BUTTON_NAMES, *AXIS_NAMES}
    assert (input_pyxel.STEER_AXIS, input_pyxel.THROTTLE_AXIS, input_pyxel.BRAKE_AXIS) == (STEER, TRIGGER_R, TRIGGER_L)
    assert all(re.fullmatch(r"[A-Z0-9_]+", name) for name in used)


@pytest.mark.parametrize("name", [*ONE_KEY, STEER, TRIGGER_L, TRIGGER_R])
def test_input_pyxel_missing_constant_fails_when_the_adapter_is_made(name):
    # 起動時に、全部の名前を引く。押されるまで分からない形にしない。
    with pytest.raises(AttributeError):
        PyxelInput(FakePyxel(missing=[name]))
