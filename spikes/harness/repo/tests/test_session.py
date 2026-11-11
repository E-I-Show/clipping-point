from cp_core.datadefs import load_game_data
from cp_core.session import SCREEN_ORDER, reference_session
from conftest import ROOT


def test_session_script_visits_every_screen_and_only_drives_on_the_hud():
    s = reference_session(load_game_data(ROOT / "app" / "data"), 120)
    assert s.visited == ["menu", "hud", "settings", "theater", "menu"]
    assert set(s.visited) == set(SCREEN_ORDER)
    assert s.ticks == 120 and s.world.tick == 70  # hud was shown for ticks 10..79
