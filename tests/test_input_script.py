"""台本（cp_core.input_script）のテスト。入力フレームへの直し方、押した瞬間の導き方、形の検査。

道具の台本（tools/input_script_smoke.json）の中身と、道具の参照（tools/input_reference.py）も、ここで見る。Pyxelは使わない。
"""
import json

import pytest

import input_reference
from cp_core import input_script
from cp_core.input_frame import BUTTONS, DIGEST_START, NEUTRAL, QUANTIZED_FIELDS, InputFrame, fold, quantize
from cp_core.sim import Sim

ANALOG_KEYS = ("steer_analog", "throttle_analog", "brake_analog")
SMOKE_MAX_TICKS = 100  # 道具の台本の合計の上限


def script(*segments):
    return input_script.parse({"segments": list(segments)})


def frames(parsed, ticks=None) -> list:
    return [parsed.frame_at(tick) for tick in range(parsed.total_ticks if ticks is None else ticks)]


# --- 入力フレームへの直し方 ---
def test_input_script_segment_values_last_for_its_ticks():
    parsed = script({"ticks": 3, "steer_analog": 0.5, "throttle_digital": 1}, {"ticks": 2, "brake_analog": 0.25, "steer_digital": -1})
    assert parsed.total_ticks == 5
    first = InputFrame(steer_analog=0.5, throttle_digital=1)
    second = InputFrame(brake_analog=0.25, steer_digital=-1)
    assert frames(parsed) == [first, first, first, second, second]


def test_input_script_omitted_values_are_zero_and_empty():
    parsed = script({"ticks": 2})
    assert frames(parsed) == [NEUTRAL, NEUTRAL]


def test_input_script_past_the_end_is_neutral():
    parsed = script({"ticks": 2, "throttle_digital": 1, "held": ["confirm"]})
    assert parsed.frame_at(1).throttle_digital == 1
    for tick in (2, 3, 1000):
        assert parsed.frame_at(tick) == NEUTRAL


def test_input_script_tick_is_zero_based():
    # 世界のtickが n のときに渡すのが n 番目。
    parsed = script({"ticks": 1, "steer_digital": 1}, {"ticks": 1, "steer_digital": -1})
    assert parsed.frame_at(0).steer_digital == 1
    assert parsed.frame_at(1).steer_digital == -1


@pytest.mark.parametrize("bad", [-1, -100])
def test_input_script_negative_tick_is_a_value_error(bad):
    with pytest.raises(ValueError):
        script({"ticks": 2}).frame_at(bad)


@pytest.mark.parametrize("bad", [0.0, True, "0", None])
def test_input_script_tick_of_another_type_is_a_type_error(bad):
    with pytest.raises(TypeError):
        script({"ticks": 2}).frame_at(bad)


# --- 押した瞬間 ---
def test_input_script_pressed_is_set_only_on_the_first_tick_of_the_segment():
    parsed = script({"ticks": 4, "held": ["shift_up", "confirm"]})
    got = frames(parsed)
    assert got[0].pressed == {"shift_up", "confirm"}
    assert all(frame.pressed == frozenset() for frame in got[1:])
    assert all(frame.held == {"shift_up", "confirm"} for frame in got)


def test_input_script_button_kept_from_the_segment_before_is_not_pressed_again():
    parsed = script({"ticks": 2, "held": ["up"]}, {"ticks": 2, "held": ["up", "confirm"]}, {"ticks": 2, "held": ["confirm"]})
    assert [sorted(frame.pressed) for frame in frames(parsed)] == [["up"], [], ["confirm"], [], [], []]


def test_input_script_first_segment_counts_from_nothing_held():
    assert script({"ticks": 1, "held": ["pause"]}).frame_at(0).pressed == {"pause"}


def test_input_script_same_button_twice_needs_a_gap_and_is_pressed_twice():
    parsed = script({"ticks": 2, "held": ["view"]}, {"ticks": 1}, {"ticks": 2, "held": ["view"]})
    pressed_at = [tick for tick, frame in enumerate(frames(parsed)) if "view" in frame.pressed]
    assert pressed_at == [0, 3]
    # 間を空けなければ、押しっぱなし。押した瞬間は1度だけ。
    held_through = script({"ticks": 2, "held": ["view"]}, {"ticks": 2, "held": ["view"]})
    assert [tick for tick, frame in enumerate(frames(held_through)) if "view" in frame.pressed] == [0]


def test_input_script_pressed_cannot_be_written():
    with pytest.raises(ValueError):
        script({"ticks": 1, "held": ["up"], "pressed": ["up"]})


# --- 形の検査 ---
@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        [{"ticks": 1}],
        "segments",
        {},
        {"segments": []},
        {"segments": None},
        {"segments": {"ticks": 1}},
        {"segments": [{"ticks": 1}], "loop": True},
        {"segments": [[1]]},
        {"segments": [None]},
        {"segments": [{}]},
        {"segments": [{"ticks": 0}]},
        {"segments": [{"ticks": -3}]},
        {"segments": [{"ticks": 1.0}]},
        {"segments": [{"ticks": True}]},
        {"segments": [{"ticks": "3"}]},
        {"segments": [{"ticks": 1, "steer": 0.5}]},
        {"segments": [{"ticks": 1, "steer_analog": "0.5"}]},
        {"segments": [{"ticks": 1, "steer_analog": 1.5}]},
        {"segments": [{"ticks": 1, "steer_analog": True}]},
        {"segments": [{"ticks": 1, "steer_analog": None}]},
        {"segments": [{"ticks": 1, "throttle_analog": -0.5}]},
        {"segments": [{"ticks": 1, "brake_analog": float("nan")}]},
        {"segments": [{"ticks": 1, "steer_digital": 0.5}]},
        {"segments": [{"ticks": 1, "steer_digital": 1.0}]},
        {"segments": [{"ticks": 1, "steer_digital": 2}]},
        {"segments": [{"ticks": 1, "throttle_digital": True}]},
        {"segments": [{"ticks": 1, "brake_digital": -1}]},
        {"segments": [{"ticks": 1, "held": "up"}]},
        {"segments": [{"ticks": 1, "held": None}]},
        {"segments": [{"ticks": 1, "held": {"up": True}}]},
        {"segments": [{"ticks": 1, "held": ["turbo"]}]},
        {"segments": [{"ticks": 1, "held": [1]}]},
        {"segments": [{"ticks": 1, "held": [["up"]]}]},
        {"segments": [{"ticks": 1, "held": ["up", "up"]}]},
        {"segments": [{"ticks": 1}, {"ticks": 1, "held": ["nope"]}]},
    ],
)
def test_input_script_wrong_shape_is_a_value_error(value):
    # 型の違いも ValueError にそろえる（外から渡す値の検査と同じ扱い）。
    with pytest.raises(ValueError):
        input_script.parse(value)


def test_input_script_analog_integers_are_accepted():
    # ブラウザへ渡すと、1.0 と -1.0 は整数で届く。
    as_ints = script({"ticks": 2, "steer_analog": -1, "throttle_analog": 1, "brake_analog": 0})
    as_floats = script({"ticks": 2, "steer_analog": -1.0, "throttle_analog": 1.0, "brake_analog": 0.0})
    assert frames(as_ints) == frames(as_floats)
    assert type(as_ints.frame_at(0).steer_analog) is float


def test_input_script_survives_a_json_round_trip():
    value = {"segments": [{"ticks": 3, "steer_analog": 0.5, "held": ["shift_up"]}, {"ticks": 1}]}
    again = json.loads(json.dumps(value))
    assert frames(input_script.parse(again)) == frames(input_script.parse(value))


def test_input_script_parse_does_not_keep_the_given_dictionary():
    value = {"segments": [{"ticks": 2, "held": ["up"]}]}
    parsed = input_script.parse(value)
    value["segments"][0]["held"].append("down")
    value["segments"].append({"ticks": 5})
    assert parsed.total_ticks == 2 and parsed.frame_at(0).held == {"up"}


# --- 道具の台本（tools/input_script_smoke.json） ---
def smoke() -> tuple:
    return input_reference.load_script(input_reference.SMOKE_SCRIPT)


def test_input_script_smoke_file_is_a_valid_script_within_100_ticks():
    value, parsed = smoke()
    assert 1 <= parsed.total_ticks <= SMOKE_MAX_TICKS
    assert parsed.total_ticks == sum(segment["ticks"] for segment in value["segments"])


def test_input_script_smoke_file_moves_every_value_and_every_button():
    _, parsed = smoke()
    rows = [quantize(frame) for frame in frames(parsed)]
    for index, name in enumerate(QUANTIZED_FIELDS):
        assert any(row[index] != 0 for row in rows), f"{name} が1度も0でない値にならない"
    held = set().union(*(frame.held for frame in frames(parsed)))
    assert held == set(BUTTONS)
    # 舵は、左右の両方へ動く（符号の取り違えを拾うため）。
    assert {row[0] > 0 for row in rows if row[0]} == {True, False}
    assert {row[1] for row in rows} == {-1, 0, 1}


def test_input_script_smoke_file_has_one_whole_positive_and_one_whole_negative_analog_value():
    # 1.0 と -1.0 は、ブラウザへ渡すと整数で届く。その道を、台本の筋書きで通す。
    value, _ = smoke()
    analog = [segment[key] for segment in value["segments"] for key in ANALOG_KEYS if key in segment]
    assert analog.count(1.0) == 1 and analog.count(-1.0) == 1
    assert all(type(number) is float for number in analog)  # ファイルには小数で書いてある


def test_input_script_smoke_file_presses_one_button_twice_with_a_gap():
    _, parsed = smoke()
    presses = {name: [tick for tick, frame in enumerate(frames(parsed)) if name in frame.pressed] for name in BUTTONS}
    assert all(presses[name] for name in BUTTONS), "どのボタンも、1度は押した瞬間が立つ"
    assert any(len(ticks) >= 2 for ticks in presses.values()), "同じボタンを、間を空けて2度押す区間が要る"


def test_input_script_smoke_file_reads_the_same_after_the_trip_through_javascript():
    # JavaScriptを通ると、端数の無い小数は整数になる。同じ台本として読めること。
    value, parsed = smoke()

    def through_javascript(item):
        if isinstance(item, dict):
            return {key: through_javascript(child) for key, child in item.items()}
        if isinstance(item, list):
            return [through_javascript(child) for child in item]
        return int(item) if type(item) is float and item == int(item) else item

    tripped = through_javascript(value)
    assert any(type(number) is int for segment in tripped["segments"] for key, number in segment.items() if key in ANALOG_KEYS)
    assert frames(input_script.parse(tripped), 120) == frames(parsed, 120)


# --- 道具の参照（tools/input_reference.py） ---
def test_input_reference_summary_is_the_world_fed_with_the_script_frames():
    _, parsed = smoke()
    ticks = parsed.total_ticks + 10
    sim = Sim()
    for tick in range(ticks):
        sim.step(parsed.frame_at(tick))
    assert input_reference.sim_summary(parsed, ticks) == sim.summary()
    assert input_reference.sim_summary(parsed, ticks)["tick"] == ticks


def test_input_reference_without_a_script_feeds_neutral_frames():
    sim = Sim()
    for _ in range(50):
        sim.step(NEUTRAL)
    assert input_reference.sim_summary(None, 50) == sim.summary()
    assert input_reference.quantized_rows(None, 3) == [(0,) * 8] * 3


def test_input_reference_digest_of_the_rows_is_the_input_digest():
    _, parsed = smoke()
    rows = input_reference.quantized_rows(parsed, 90)
    assert len(rows) == 90 and rows[0] == quantize(parsed.frame_at(0))
    assert input_reference.digest_of(rows) == input_reference.sim_summary(parsed, 90)["input_digest"]
    assert input_reference.digest_of([]) == DIGEST_START
    assert input_reference.digest_of(rows[:1]) == fold(DIGEST_START, rows[0])


def test_input_reference_summary_changes_when_the_script_is_shifted_by_one_tick():
    # 参照と照らす確かめが、1 tickのずれを拾えること。
    _, parsed = smoke()
    ticks = parsed.total_ticks + 5
    shifted = Sim()
    for tick in range(ticks):
        shifted.step(parsed.frame_at(tick + 1))
    assert shifted.summary() != input_reference.sim_summary(parsed, ticks)


@pytest.mark.parametrize("text", ["", "{broken", "[1, 2]", '{"segments": []}', '{"segments": [{"ticks": 1, "pressed": ["up"]}]}'])
def test_input_reference_unreadable_script_file_is_a_value_error(tmp_path, text):
    path = tmp_path / "script.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        input_reference.load_script(path)


def test_input_reference_missing_script_file_is_a_value_error(tmp_path):
    with pytest.raises(ValueError):
        input_reference.load_script(tmp_path / "nope.json")
