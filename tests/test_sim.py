"""最小の世界（Sim）のテスト。"""
import json

import pytest

from cp_core.input_frame import DIGEST_START, NEUTRAL, InputFrame, fold, quantize
from cp_core.sim import Sim

LEFT = InputFrame(steer_analog=0.5, held=frozenset({"left"}), pressed=frozenset({"left"}))
GAS = InputFrame(throttle_digital=1)


def test_sim_starts_at_tick_zero():
    assert Sim().tick == 0
    assert Sim().summary() == {"tick": 0, "input_digest": DIGEST_START}


def test_sim_step_advances_exactly_one_tick():
    sim = Sim()
    for expected in range(1, 121):
        sim.step(NEUTRAL)
        assert sim.tick == expected
    assert sim.summary()["tick"] == 120


def test_sim_summary_is_plain_json_data():
    sim = Sim()
    sim.step(LEFT)
    summary = sim.summary()
    assert json.loads(json.dumps(summary)) == summary
    assert all(type(value) in (int, str) for value in summary.values())


def test_sim_summary_is_a_copy_not_the_state():
    sim = Sim()
    summary = sim.summary()
    summary["tick"] = 999
    summary["input_digest"] = 0
    assert sim.tick == 0
    assert sim.summary() == {"tick": 0, "input_digest": DIGEST_START}


def test_sim_two_worlds_with_the_same_steps_agree():
    a, b = Sim(), Sim()
    for index in range(300):
        frame = LEFT if index % 7 == 0 else GAS if index % 3 == 0 else NEUTRAL
        a.step(frame)
        b.step(frame)
    assert a.summary() == b.summary()


# --- 入力フレームを受ける ---
def test_sim_step_needs_an_input_frame():
    sim = Sim()
    with pytest.raises(TypeError):
        sim.step()  # 引数は必須
    for bad in (None, {"steer_analog": 0.0}, (0, 0, 0, 0, 0, 0, 0, 0), "neutral", 0):
        with pytest.raises(TypeError):
            sim.step(bad)
    assert sim.summary() == {"tick": 0, "input_digest": DIGEST_START}  # 受けなかった入力では、進まない


def test_sim_input_digest_folds_the_quantized_frame_of_every_tick():
    sim = Sim()
    digest = DIGEST_START
    for frame in (NEUTRAL, LEFT, LEFT, GAS, NEUTRAL):
        sim.step(frame)
        digest = fold(digest, quantize(frame))
        assert sim.input_digest == digest
    assert sim.summary() == {"tick": 5, "input_digest": digest}


def test_sim_input_digest_changes_even_when_nothing_is_pressed():
    # 何も押していないtickも畳み込む。入力フレームが1 tick欠けたことを、拾えるように。
    a, b = Sim(), Sim()
    a.step(NEUTRAL)
    assert a.input_digest != DIGEST_START
    b.step(NEUTRAL)
    b.step(NEUTRAL)
    assert a.input_digest != b.input_digest


def test_sim_input_digest_depends_on_the_order_of_the_frames():
    a, b = Sim(), Sim()
    for frame in (LEFT, GAS, NEUTRAL):
        a.step(frame)
    for frame in (GAS, LEFT, NEUTRAL):
        b.step(frame)
    assert a.tick == b.tick and a.input_digest != b.input_digest


def test_sim_input_digest_sees_a_frame_that_arrives_one_tick_late():
    frames = [NEUTRAL, LEFT, GAS, NEUTRAL, NEUTRAL]
    on_time, late = Sim(), Sim()
    for frame in frames:
        on_time.step(frame)
    for frame in [NEUTRAL, *frames[:-1]]:
        late.step(frame)
    assert on_time.input_digest != late.input_digest


def test_sim_input_digest_is_a_32_bit_integer():
    sim = Sim()
    for _ in range(200):
        sim.step(LEFT)
        assert type(sim.input_digest) is int and 0 <= sim.input_digest < 2**32
