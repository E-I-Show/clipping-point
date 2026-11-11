"""Overflow rules on the recorded canvas (no Pyxel). The full sweep is tools/screen_check.py."""
import pytest

from cp_core.datadefs import load_game_data
from cp_ui import fixtures
from cp_ui.canvas import Canvas, text_size
from cp_ui.check import find_violations
from cp_ui.screens import SCREENS
from conftest import ROOT

DATA = load_game_data(ROOT / "app" / "data")


@pytest.mark.parametrize("screen", sorted(SCREENS))
@pytest.mark.parametrize("variant", fixtures.VARIANTS)
def test_ui_screens_fit_with_shipped_data(screen, variant):
    c = Canvas()
    SCREENS[screen](c, fixtures.build(screen, variant, DATA))
    assert len(c.items) >= 5
    assert find_violations(c) == []


def test_ui_checker_reports_each_kind_of_overflow():
    def kinds(draw):
        c = Canvas()
        draw(c)
        return sorted({v.split(":")[0] for v in find_violations(c)})

    assert kinds(lambda c: c.text(300, 10, "TOO WIDE", 7)) == ["off_screen"]
    assert kinds(lambda c: c.text(10, 236, "LOW", 7)) == ["off_screen"]
    assert kinds(lambda c: c.rect(-1, 0, 10, 10, 7)) == ["off_screen"]

    def in_box(c):
        with c.box("panel", 10, 10, 40, 12):
            c.text(12, 12, "0123456789", 7)  # 39 px wide: 12+39 = 51 > 50

    assert kinds(in_box) == ["out_of_box"]

    def nested(c):
        with c.box("outer", 0, 0, 100, 100):
            with c.box("inner", 90, 90, 20, 20):
                pass

    assert kinds(nested) == ["out_of_box"]
    assert kinds(lambda c: (c.text(10, 10, "LAP 1/3", 7), c.text(30, 12, "POS", 7))) == ["text_overlap"]
    assert kinds(lambda c: c.text(10, 10, "ラップ", 7)) == ["bad_char"]
    assert kinds(lambda c: c.rect(10, 10, 0, 5, 7)) == ["empty"]
    assert kinds(lambda c: c.text(316, 234, "A", 7)) == []  # exactly touching the corner is fine
    with pytest.raises(TypeError):
        Canvas().text(1.5, 2, "A", 7)


def test_ui_text_metrics():
    assert text_size("A") == (3, 5) and text_size("AB") == (7, 5) and text_size("AB\nC") == (7, 11)
    assert text_size("gap") == (11, 6) and text_size("gap\nAB") == (11, 11)  # descenders use row 6
