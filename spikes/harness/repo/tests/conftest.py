"""Logic tests only. This process must never load pyxel (pyxel.quit() exits with code 0 and would
erase failures): anything that needs Pyxel is run by the tools/ wrappers in a subprocess."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
FORBIDDEN = ("pyxel", "cp_app")


def pytest_addoption(parser):
    parser.addoption("--update-snapshots", action="store_true", help="rewrite tests/snapshots (own commit, with the reason)")


def pytest_sessionfinish(session, exitstatus):
    loaded = [m for m in FORBIDDEN if m in sys.modules]
    if loaded:
        print(f"\nFORBIDDEN MODULES LOADED IN THE TEST PROCESS: {loaded}")
        session.exitstatus = 1
