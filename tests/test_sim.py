"""最小の世界（Sim）のテスト。"""
import json

import pytest

from cp_core.input_frame import DIGEST_START, NEUTRAL, InputFrame, fold, quantize
from cp_core.rng import PURPOSES, RngSet
from cp_core.sim import Sim

LEFT = InputFrame(steer_analog=0.5, held=frozenset({"left"}), pressed=frozenset({"left"}))
GAS = InputFrame(throttle_digital=1)
RNG_AI_OF_SEED_0 = "0ad0a11cea5bd376"  # 種0の世界の、用途 ai の流れの、始まりの状態（16桁の16進）


def test_sim_starts_at_tick_zero():
    assert Sim().tick == 0
    assert Sim().summary() == {"tick": 0, "input_digest": DIGEST_START, "seed": 0, "rng_ai": RNG_AI_OF_SEED_0}
    assert DIGEST_START == 2166136261  # 要約の値を、数字でも固定する


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
    summary["seed"] = 5
    summary["rng_ai"] = "0" * 16
    assert sim.tick == 0
    assert sim.summary() == {"tick": 0, "input_digest": DIGEST_START, "seed": 0, "rng_ai": RNG_AI_OF_SEED_0}


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
    assert sim.summary() == {"tick": 0, "input_digest": DIGEST_START, "seed": 0, "rng_ai": RNG_AI_OF_SEED_0}  # 受けなかった入力では、進まない


def test_sim_input_digest_folds_the_quantized_frame_of_every_tick():
    sim = Sim()
    digest = DIGEST_START
    for frame in (NEUTRAL, LEFT, LEFT, GAS, NEUTRAL):
        sim.step(frame)
        digest = fold(digest, quantize(frame))
        assert sim.input_digest == digest
    assert sim.summary() == {"tick": 5, "input_digest": digest, "seed": 0, "rng_ai": RNG_AI_OF_SEED_0}
    assert digest == 3821819394  # 5 tick分を畳み込んだ値を、数字でも固定する


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


# --- 種と、用途ごとの乱数の流れ ---
def test_sim_takes_a_seed_and_puts_it_and_the_stream_states_into_the_summary():
    assert Sim().seed == 0 and Sim(seed=7).seed == 7
    assert Sim(1).summary() == {"tick": 0, "input_digest": DIGEST_START, "seed": 1, "rng_ai": "3c07e3cc992538ed"}
    assert Sim(20261111).summary() == {"tick": 0, "input_digest": DIGEST_START, "seed": 20261111, "rng_ai": "3581644b167e57b5"}


def test_sim_summary_has_one_stream_state_per_registered_purpose():
    summary = Sim(3).summary()
    assert list(summary) == ["tick", "input_digest", "seed", *(f"rng_{name}" for name in PURPOSES)]
    for name in PURPOSES:
        text = summary[f"rng_{name}"]
        # 16桁の16進の文字列（小文字）。64ビットの整数を、JavaScriptを通っても欠けない形にする。
        assert type(text) is str and len(text) == 16 and text == text.lower()
        assert int(text, 16) == RngSet(3).state()[name]


def test_sim_summary_stays_flat_integers_and_strings():
    # 要約は、整数と文字列だけの、入れ子の無い辞書（JSONにそのまま書ける）。
    for sim in (Sim(), Sim(2**63 + 12345)):
        summary = sim.summary()
        assert all(type(key) is str for key in summary)
        assert all(type(value) in (int, str) for value in summary.values())
        assert json.loads(json.dumps(summary)) == summary


def test_sim_stream_state_in_the_summary_follows_the_stream():
    sim = Sim(7)
    assert sim.summary()["rng_ai"] == "7da0ebdcb37404f3"
    sim.rng.stream("ai").next_u64()  # 流れを1回引くと、要約が変わる
    assert sim.summary()["rng_ai"] == "1bd8659632be8108"


def test_sim_steps_do_not_draw_from_the_streams_yet():
    # いまは、乱数を引く所が無い（AIを作る段3から）。入力を流しても、流れの状態は動かない。
    sim = Sim(7)
    for frame in (NEUTRAL, LEFT, GAS) * 40:
        sim.step(frame)
    assert sim.summary()["rng_ai"] == Sim(7).summary()["rng_ai"]


def test_sim_worlds_with_different_seeds_differ_only_in_the_seed_and_the_streams():
    a, b = Sim(1), Sim(2)
    for frame in (LEFT, GAS, NEUTRAL):
        a.step(frame)
        b.step(frame)
    assert a.summary() != b.summary()
    assert {key for key in a.summary() if a.summary()[key] != b.summary()[key]} == {"seed", "rng_ai"}


@pytest.mark.parametrize("seed", [1.0, True, "1", None])
def test_sim_seed_must_be_an_integer(seed):
    with pytest.raises(TypeError):
        Sim(seed)
