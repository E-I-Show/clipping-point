"""Demonstrates the false-pass hazard: pyxel.quit() inside a pytest process.
Run:  python3 -m pytest -q pytest_hazard/test_quit_hazard.py ; echo exit=$?
"""
import pyxel


def test_a_calls_quit():
    pyxel.init(64, 64, headless=True)
    pyxel.quit()  # -> std::process::exit(0): the whole pytest process ends here with code 0


def test_b_fails():
    assert False, "this failure is never reported if test_a killed the process"
