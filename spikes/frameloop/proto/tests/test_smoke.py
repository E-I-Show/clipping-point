"""Pyxel-dependent checks run in subprocesses only (see tools/run_smoke.py for the reasons)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_build_then_headless_smoke_including_packaged_app():
    build = subprocess.run([sys.executable, str(ROOT / "tools" / "build.py")], capture_output=True, text=True)
    assert build.returncode == 0 and "BUILD_OK" in build.stdout, build.stdout[-2000:] + build.stderr[-2000:]
    smoke = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "run_smoke.py"), "--packaged"], capture_output=True, text=True
    )
    assert smoke.returncode == 0 and "SMOKE_HARNESS_OK" in smoke.stdout, smoke.stdout[-3000:] + smoke.stderr[-2000:]
    assert smoke.stdout.count("[PASS]") == 10, smoke.stdout


def test_screenshot_tour_and_its_exit_codes():
    tour = [sys.executable, str(ROOT / "tools" / "tour.py")]
    ok = subprocess.run(tour, capture_output=True, text=True)
    assert ok.returncode == 0 and "TOUR_OK screens=3" in ok.stdout, ok.stdout + ok.stderr[-1500:]
    incomplete = subprocess.run([*tour, "--only", "nosuch"], capture_output=True, text=True)
    assert incomplete.returncode == 2 and "TOUR_INCOMPLETE" in incomplete.stdout
