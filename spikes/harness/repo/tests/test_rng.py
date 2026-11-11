import os
import subprocess
import sys

import pytest

from cp_core.rng import RngSet, RngStream, hash_u64, hash_unit

APP = os.path.join(os.path.dirname(__file__), "..", "app")


def test_rng_known_values_are_pinned():
    # splitmix64 reference vector (seed 1234567): the generator is the published algorithm
    s = RngStream(1234567)
    assert [s.next_u64() for _ in range(3)] == [6457827717110365317, 3203168211198807973, 9817491932198370423]


def test_rng_streams_are_independent_and_restorable():
    a, b = RngSet(42), RngSet(42)
    for _ in range(100):
        a.stream("ai").unit()  # drawing from one stream ...
    assert a.stream("grid").next_u64() == b.stream("grid").next_u64()  # ... does not move another
    state = a.state()
    x = [a.stream("ai").unit() for _ in range(5)]
    a.restore(state)
    assert [a.stream("ai").unit() for _ in range(5)] == x
    with pytest.raises(KeyError):
        a.stream("particles")  # no silent new stream
    with pytest.raises(ValueError):
        a.restore({"ai": 1})


def test_rng_hash_draw_is_stateless_and_spreads():
    assert hash_u64(1, "brake", "kazane_rs", 3, 4) == hash_u64(1, "brake", "kazane_rs", 3, 4)
    values = {hash_u64(1, "brake", "kazane_rs", lap, corner) for lap in range(50) for corner in range(9)}
    assert len(values) == 450
    assert hash_u64(1, "ab", "c") != hash_u64(1, "a", "bc")
    units = [hash_unit(7, "x", i) for i in range(2000)]
    assert 0.0 <= min(units) and max(units) < 1.0 and 0.45 < sum(units) / len(units) < 0.55
    with pytest.raises(TypeError):
        hash_u64(1, 1.5)


def test_rng_same_result_in_processes_with_different_hash_seeds():
    """Guards against anything that depends on PYTHONHASHSEED (built-in hash(), set order of str)."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from cp_core.rng import hash_u64; "
            "from cp_core.world import run_scenario; print(hash_u64(5, 'grid', 'akane_short'), run_scenario('race_3600').fingerprint_exact())")
    outs = set()
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outs.add(subprocess.run([sys.executable, "-c", code, APP], capture_output=True, text=True, env=env, check=True).stdout)
    assert len(outs) == 1 and len(outs.pop().split()) == 2
