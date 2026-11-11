"""最小の世界（Sim）のテスト。"""
import json

from cp_core.sim import Sim


def test_sim_starts_at_tick_zero():
    assert Sim().tick == 0
    assert Sim().summary() == {"tick": 0}


def test_sim_step_advances_exactly_one_tick():
    sim = Sim()
    for expected in range(1, 121):
        sim.step()
        assert sim.tick == expected
    assert sim.summary() == {"tick": 120}


def test_sim_summary_is_plain_json_data():
    sim = Sim()
    sim.step()
    summary = sim.summary()
    assert json.loads(json.dumps(summary)) == summary
    assert all(type(value) in (int, str) for value in summary.values())


def test_sim_summary_is_a_copy_not_the_state():
    sim = Sim()
    summary = sim.summary()
    summary["tick"] = 999
    assert sim.tick == 0
    assert sim.summary() == {"tick": 0}


def test_sim_two_worlds_with_the_same_steps_agree():
    a, b = Sim(), Sim()
    for _ in range(300):
        a.step()
        b.step()
    assert a.summary() == b.summary()
