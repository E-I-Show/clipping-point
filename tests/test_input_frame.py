"""入力フレーム（cp_core.input_frame）のテスト。型と範囲の検査、アナログ値の整数、量子化、畳み込み。Pyxelは使わない。"""
import dataclasses
import json

import pytest

from cp_core.input_frame import (
    ANALOG_SCALE,
    BUTTONS,
    DIGEST_START,
    NEUTRAL,
    QUANTIZED_FIELDS,
    InputFrame,
    button_bits,
    button_names,
    fold,
    quantize,
)

NAN, INF = float("nan"), float("inf")


# --- 形 ---
def test_input_frame_button_order_is_the_bit_order():
    # 並びは量子化のビットの順。足すときは末尾に足す（並びを替えると、保存した値の意味が変わる）。
    assert BUTTONS == ("shift_up", "shift_down", "view", "pause", "up", "down", "left", "right", "confirm", "back")


def test_input_frame_fields_come_in_the_quantized_order():
    assert tuple(field.name for field in dataclasses.fields(InputFrame)) == QUANTIZED_FIELDS
    assert len(QUANTIZED_FIELDS) == 8


def test_input_frame_default_is_neutral():
    frame = InputFrame()
    assert frame == NEUTRAL
    assert (frame.steer_analog, frame.throttle_analog, frame.brake_analog) == (0.0, 0.0, 0.0)
    assert (frame.steer_digital, frame.throttle_digital, frame.brake_digital) == (0, 0, 0)
    assert frame.held == frozenset() and frame.pressed == frozenset()
    assert quantize(NEUTRAL) == (0, 0, 0, 0, 0, 0, 0, 0)


def test_input_frame_cannot_be_changed_after_it_is_made():
    with pytest.raises(dataclasses.FrozenInstanceError):
        NEUTRAL.steer_analog = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        NEUTRAL.held = frozenset({"up"})


def test_input_frame_holds_analog_and_digital_values_side_by_side():
    # どちらを使うかは、入力フレームでは決めない（決めるのは操作補正）。両方が0でなくても作れる。
    frame = InputFrame(steer_analog=-0.5, steer_digital=1, throttle_analog=0.25, throttle_digital=1, brake_analog=1.0, brake_digital=1)
    assert (frame.steer_analog, frame.steer_digital) == (-0.5, 1)
    assert (frame.throttle_analog, frame.throttle_digital) == (0.25, 1)
    assert (frame.brake_analog, frame.brake_digital) == (1.0, 1)


# --- アナログ値 ---
@pytest.mark.parametrize("name, low", [("steer_analog", -1), ("throttle_analog", 0), ("brake_analog", 0)])
def test_input_frame_analog_integer_becomes_a_float(name, low):
    # 台本をブラウザへ渡すと、JavaScriptを通る間に 1.0 が 1 になり、Pythonでは整数で届く。
    for given in (low, 1):
        value = getattr(InputFrame(**{name: given}), name)
        assert type(value) is float and value == float(given)


def test_input_frame_analog_integer_and_float_make_equal_frames():
    assert InputFrame(steer_analog=-1, throttle_analog=1, brake_analog=0) == InputFrame(steer_analog=-1.0, throttle_analog=1.0, brake_analog=0.0)
    assert quantize(InputFrame(steer_analog=-1, throttle_analog=1)) == quantize(InputFrame(steer_analog=-1.0, throttle_analog=1.0))


@pytest.mark.parametrize("name", ["steer_analog", "throttle_analog", "brake_analog"])
@pytest.mark.parametrize("bad", [True, False, "0.5", None, [0.5], 1 + 0j])
def test_input_frame_analog_of_another_type_is_a_type_error(name, bad):
    with pytest.raises(TypeError):
        InputFrame(**{name: bad})


@pytest.mark.parametrize(
    "name, bad",
    [
        ("steer_analog", 1.0001), ("steer_analog", -1.0001), ("steer_analog", 2), ("steer_analog", NAN), ("steer_analog", INF),
        ("throttle_analog", -0.0001), ("throttle_analog", 1.0001), ("throttle_analog", -1), ("throttle_analog", NAN), ("throttle_analog", -INF),
        ("brake_analog", -0.0001), ("brake_analog", 1.0001), ("brake_analog", 2), ("brake_analog", NAN), ("brake_analog", INF),
    ],
)
def test_input_frame_analog_out_of_range_or_nan_is_a_value_error(name, bad):
    with pytest.raises(ValueError):
        InputFrame(**{name: bad})


def test_input_frame_analog_ends_of_the_range_are_accepted():
    frame = InputFrame(steer_analog=-1.0, throttle_analog=1.0, brake_analog=0.0)
    assert (frame.steer_analog, frame.throttle_analog, frame.brake_analog) == (-1.0, 1.0, 0.0)
    assert InputFrame(steer_analog=1.0).steer_analog == 1.0


# --- デジタル値 ---
@pytest.mark.parametrize("name", ["steer_digital", "throttle_digital", "brake_digital"])
@pytest.mark.parametrize("bad", [True, False, 1.0, 0.0, "1", None])
def test_input_frame_digital_bool_and_float_are_type_errors(name, bad):
    with pytest.raises(TypeError):
        InputFrame(**{name: bad})


@pytest.mark.parametrize(
    "name, bad",
    [("steer_digital", 2), ("steer_digital", -2), ("throttle_digital", -1), ("throttle_digital", 2), ("brake_digital", -1), ("brake_digital", 2)],
)
def test_input_frame_digital_out_of_range_is_a_value_error(name, bad):
    with pytest.raises(ValueError):
        InputFrame(**{name: bad})


def test_input_frame_digital_values_in_range_are_kept():
    for value in (-1, 0, 1):
        assert InputFrame(steer_digital=value).steer_digital == value
    assert InputFrame(throttle_digital=1, brake_digital=1).throttle_digital == 1


# --- ボタン ---
@pytest.mark.parametrize("name", ["held", "pressed"])
def test_input_frame_buttons_become_a_frozenset(name):
    for given in (frozenset({"up", "confirm"}), {"up", "confirm"}, ("up", "confirm"), ["up", "confirm", "up"]):
        value = getattr(InputFrame(**{name: given}), name)
        assert type(value) is frozenset and value == {"up", "confirm"}


@pytest.mark.parametrize("name", ["held", "pressed"])
def test_input_frame_unknown_button_name_is_a_value_error(name):
    with pytest.raises(ValueError):
        InputFrame(**{name: frozenset({"up", "turbo"})})
    with pytest.raises(ValueError):
        InputFrame(**{name: frozenset({"UP"})})  # 名は小文字


@pytest.mark.parametrize("name", ["held", "pressed"])
@pytest.mark.parametrize("bad", ["up", None, 3, {"up": True}, frozenset({1}), [None], ("up", 2)])
def test_input_frame_buttons_of_another_type_are_type_errors(name, bad):
    # 文字列1つは受けない。1文字ずつの集まりに割れてしまう。
    with pytest.raises(TypeError):
        InputFrame(**{name: bad})


def test_input_frame_pressed_may_name_a_button_that_is_not_held():
    # 1回の更新の中で押して離した、短い押し。押した瞬間だけが立つ。
    frame = InputFrame(pressed=frozenset({"pause"}))
    assert frame.held == frozenset() and frame.pressed == {"pause"}


# --- 量子化 ---
def test_input_frame_quantize_gives_eight_plain_integers_in_the_fixed_order():
    frame = InputFrame(
        steer_analog=-0.5, steer_digital=1, throttle_analog=0.3, throttle_digital=1, brake_analog=0.6, brake_digital=0,
        held=frozenset({"shift_up", "back"}), pressed=frozenset({"back"}),
    )
    values = quantize(frame)
    assert values == (-500, 1, 300, 1, 600, 0, 1 | 512, 512)
    assert all(type(value) is int for value in values)
    assert json.loads(json.dumps(list(values))) == list(values)


@pytest.mark.parametrize(
    "value, expected",
    [(1.0, 1000), (-1.0, -1000), (0.0, 0), (0.001, 1), (0.0004, 0), (0.0006, 1), (-0.0006, -1), (0.125, 125), (0.9996, 1000), (0.3, 300), (0.6, 600)],
)
def test_input_frame_quantize_rounds_analog_values_to_thousandths(value, expected):
    assert ANALOG_SCALE == 1000
    assert quantize(InputFrame(steer_analog=value))[0] == expected
    if value >= 0:
        assert quantize(InputFrame(throttle_analog=value))[2] == expected
        assert quantize(InputFrame(brake_analog=value))[4] == expected


def test_input_frame_quantize_keeps_the_sign_of_the_steer_values():
    # 舵は左が正。
    assert quantize(InputFrame(steer_analog=1.0, steer_digital=1))[:2] == (1000, 1)
    assert quantize(InputFrame(steer_analog=-1.0, steer_digital=-1))[:2] == (-1000, -1)


def test_input_frame_button_bits_follow_the_button_order():
    for index, name in enumerate(BUTTONS):
        assert button_bits({name}) == 1 << index
        assert quantize(InputFrame(held=frozenset({name})))[6] == 1 << index
        assert quantize(InputFrame(pressed=frozenset({name})))[7] == 1 << index
    assert button_bits(BUTTONS) == (1 << len(BUTTONS)) - 1 == 1023
    assert button_bits(()) == 0


def test_input_frame_button_names_is_the_inverse_of_button_bits():
    for names in ((), ("up",), ("shift_up", "back"), ("view", "pause", "confirm"), BUTTONS):
        assert button_names(button_bits(names)) == tuple(name for name in BUTTONS if name in names)
    for bits in range(1 << len(BUTTONS)):
        assert button_bits(button_names(bits)) == bits


@pytest.mark.parametrize("bad", [-1, 1 << 10, 1 << 20])
def test_input_frame_button_names_rejects_bits_outside_the_buttons(bad):
    with pytest.raises(ValueError):
        button_names(bad)


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_input_frame_button_names_rejects_other_types(bad):
    with pytest.raises(TypeError):
        button_names(bad)


# --- 畳み込み ---
def test_input_frame_fold_follows_the_fixed_formula():
    assert DIGEST_START == 2166136261
    assert fold(DIGEST_START, []) == DIGEST_START
    assert fold(DIGEST_START, [5]) == ((2166136261 ^ 5) * 16777619) % 2**32
    assert fold(DIGEST_START, [0]) == (2166136261 * 16777619) % 2**32
    # 負の値は、32ビットに切ってから混ぜる。
    assert fold(DIGEST_START, [-1000]) == ((2166136261 ^ (2**32 - 1000)) * 16777619) % 2**32


def test_input_frame_fold_of_the_same_values_is_the_same():
    values = list(quantize(InputFrame(steer_analog=0.5, held=frozenset({"up"}))))
    assert fold(DIGEST_START, values) == fold(DIGEST_START, list(values))
    assert fold(DIGEST_START, tuple(values)) == fold(DIGEST_START, iter(values))


def test_input_frame_fold_depends_on_the_order():
    assert fold(DIGEST_START, [1, 2, 3]) != fold(DIGEST_START, [3, 2, 1])
    assert fold(DIGEST_START, [0, 1]) != fold(DIGEST_START, [1, 0])
    assert fold(DIGEST_START, [0]) != fold(DIGEST_START, [0, 0])  # 0だけの列でも、長さで変わる


def test_input_frame_fold_can_be_fed_in_pieces():
    first, second = [1, -2, 3], [400, 0, 1023]
    assert fold(fold(DIGEST_START, first), second) == fold(DIGEST_START, first + second)


def test_input_frame_fold_stays_inside_32_bits():
    digest = DIGEST_START
    for value in range(-2000, 2000, 7):
        digest = fold(digest, [value, 2**40 + value])
        assert type(digest) is int and 0 <= digest < 2**32


@pytest.mark.parametrize("bad", [0.5, True, "1", None])
def test_input_frame_fold_takes_integers_only(bad):
    with pytest.raises(TypeError):
        fold(DIGEST_START, [1, bad])
    with pytest.raises(TypeError):
        fold(bad, [1])


def test_input_frame_different_frames_give_different_digests():
    frames = [
        NEUTRAL, InputFrame(steer_analog=0.001), InputFrame(steer_digital=1), InputFrame(steer_digital=-1), InputFrame(throttle_analog=0.001),
        InputFrame(throttle_digital=1), InputFrame(brake_analog=0.001), InputFrame(brake_digital=1),
        *(InputFrame(held=frozenset({name})) for name in BUTTONS), *(InputFrame(pressed=frozenset({name})) for name in BUTTONS),
    ]
    digests = {fold(DIGEST_START, quantize(frame)) for frame in frames}
    assert len(digests) == len(frames)
