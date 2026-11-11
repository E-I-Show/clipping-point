"""Determinism guard: the summary of fixed-input scenarios is pinned in tests/snapshots/."""
import pytest

from cp_core.world import SCENARIOS, run_scenario
from snapshot import check_snapshot


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_world_fingerprint_matches_snapshot(request, name):
    world = run_scenario(name)
    assert world.tick == SCENARIOS[name]["ticks"] > 0
    check_snapshot(request, f"world_{name}", world.summary())


def test_world_fingerprint_is_sensitive_and_repeatable():
    a, b = run_scenario("ta_600"), run_scenario("ta_600")
    assert a.fingerprint_exact() == b.fingerprint_exact()
    b.step()
    assert a.fingerprint_exact() != b.fingerprint_exact()  # one more tick must show
    c = run_scenario("ta_600")
    c.cars[0].lateral += 1e-15
    assert a.fingerprint_exact() != c.fingerprint_exact()  # the last bit must show
    assert a.summary_portable() == c.summary_portable()  # the coarse summary ignores it
