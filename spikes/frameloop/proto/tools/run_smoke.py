"""Headless smoke harness (runs the Pyxel app in SUBPROCESSES and judges the outcome).

  python3 tools/run_smoke.py            # direct runs + fault injection
  python3 tools/run_smoke.py --packaged # also `pyxel play dist/cp_proto.pyxapp` (run tools/build.py first)

A run passes only if ALL of these hold (exit code 0 alone is never enough):
  exit code == 0, result JSON exists and says ok, ticks == requested, fingerprint == the value
  computed here by cp_core alone (no Pyxel), renders in the expected range, screenshot not blank.
The fault cases must be DETECTED; if a broken run is judged as passing, this script fails.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "cp_proto"
sys.path.insert(0, str(APP))

from cp_core.game import Game  # noqa: E402
from cp_core.input_script import DEMO_SCRIPT, reference_raw_inputs  # noqa: E402

assert "pyxel" not in sys.modules, "cp_core must not import pyxel"

TICKS = 120


def reference(ticks: int):
    game = Game()
    for raw in reference_raw_inputs(DEMO_SCRIPT, ticks):
        game.tick(raw)
    return game.fingerprint(), game.sim.shift_count


def launch(cmd, workdir: Path, name: str, **env_extra):
    result = workdir / f"{name}.json"
    shot = workdir / f"{name}.png"
    env = dict(os.environ)
    env.pop("PYTHONUNBUFFERED", None)  # behave like a default Python
    env.update(
        CP_SMOKE=str(result),
        CP_SMOKE_SHOT=str(shot),
        CP_SMOKE_TICKS=str(TICKS),
        TMPDIR=str(workdir),  # `pyxel play` extracts under tempfile.gettempdir()/.pyxel/play
    )
    env.update({k: str(v) for k, v in env_extra.items()})
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120, cwd=workdir)
    wall = time.perf_counter() - t0
    data = json.loads(result.read_text()) if result.exists() else None
    return proc, data, shot, wall


def judge(proc, data, shot, *, renders_range, expect_fp, expect_shifts):
    """Return a list of problems; empty list == pass."""
    problems = []
    if proc.returncode != 0:
        problems.append(f"exit code {proc.returncode}")
    if data is None:
        problems.append("no result file (process ended before finishing all ticks)")
        return problems
    if data.get("ok") is not True:
        problems.append("result not ok")
    if data.get("ticks") != TICKS:
        problems.append(f"ticks {data.get('ticks')} != {TICKS}")
    if data.get("fingerprint") != expect_fp:
        problems.append(f"fingerprint {data.get('fingerprint')} != reference {expect_fp}")
    if data.get("shift_count") != expect_shifts:
        problems.append(f"shift_count {data.get('shift_count')} != reference {expect_shifts}")
    lo, hi = renders_range
    if not (lo <= data.get("renders", -1) <= hi):
        problems.append(f"renders {data.get('renders')} outside [{lo}, {hi}]")
    if len(data.get("screen_colors", [])) < 4:
        problems.append(f"screen looks blank: colours {data.get('screen_colors')}")
    if not shot.exists() or shot.stat().st_size < 200:
        problems.append("screenshot missing or tiny")
    if len(data.get("cars", [])) != 4 or data.get("track_points") != 48:
        problems.append("data files not loaded as expected")
    return problems


def main() -> int:
    packaged = "--packaged" in sys.argv
    fp, shifts = reference(TICKS)
    print(f"reference (cp_core only, no Pyxel): fingerprint={fp} shift_count={shifts}")
    direct = [sys.executable, str(APP / "main.py")]
    half = TICKS // 2
    failures = 0
    with tempfile.TemporaryDirectory(dir=ROOT / "out", prefix="smoke-") as tmp:
        work = Path(tmp)
        positive = [
            ("direct_flip", direct, dict(CP_SMOKE_DRIVER="flip"), (half, half + 1)),
            ("direct_run_realtime", direct, dict(CP_SMOKE_DRIVER="run"), (half - 2, half + 2)),
            # slow scene render (20 ms): Pyxel calls update twice per draw; sim result must not change
            ("direct_run_slow_draw", direct, dict(CP_SMOKE_DRIVER="run", CP_SMOKE_DRAW_SLEEP_MS=20), (half - 3, half + 3)),
        ]
        if packaged:
            play = [sys.executable, "-m", "pyxel", "play", str(ROOT / "dist" / "cp_proto.pyxapp")]
            positive.append(("packaged_flip", play, dict(CP_SMOKE_DRIVER="flip"), (half, half + 1)))
            positive.append(("packaged_run_realtime", play, dict(CP_SMOKE_DRIVER="run"), (half - 2, half + 2)))
        for name, cmd, extra, rr in positive:
            proc, data, shot, wall = launch(cmd, work, name, **extra)
            problems = judge(proc, data, shot, renders_range=rr, expect_fp=fp, expect_shifts=shifts)
            detail = "" if data is None else f"ticks={data['ticks']} draw_calls={data['draw_calls']} renders={data['renders']} sim_wall={data['wall_s']}s"
            print(f"[{'PASS' if not problems else 'FAIL'}] {name}: exit={proc.returncode} process_wall={wall:.2f}s {detail} {problems or ''}")
            if "SMOKE_OK" not in proc.stdout:
                problems.append("SMOKE_OK line missing from stdout")
                print(f"       stdout lost? {proc.stdout[-200:]!r}")
            if problems:
                failures += 1
                print("       stderr tail:", proc.stderr[-400:])

        # fault injection: each of these MUST be judged as failing
        negative = [
            ("fault_update_exception", dict(CP_SMOKE_DRIVER="run", CP_SMOKE_FAULT="update")),
            ("fault_draw_exception", dict(CP_SMOKE_DRIVER="run", CP_SMOKE_FAULT="draw")),
            ("fault_update_exception_flip", dict(CP_SMOKE_DRIVER="flip", CP_SMOKE_FAULT="update")),
            ("fault_quit_early_exit0", dict(CP_SMOKE_DRIVER="run", CP_SMOKE_FAULT="quit_early")),
            ("fault_never_renders", dict(CP_SMOKE_DRIVER="flip", CP_SMOKE_FAULT="no_render")),
        ]
        for name, extra in negative:
            proc, data, shot, wall = launch(direct, work, name, **extra)
            problems = judge(proc, data, shot, renders_range=(half, half + 1), expect_fp=fp, expect_shifts=shifts)
            detected = bool(problems)
            tb = "Traceback" in proc.stderr
            print(f"[{'PASS' if detected else 'FAIL'}] {name}: exit={proc.returncode} traceback_on_stderr={tb} detected_as={problems}")
            if not detected:
                failures += 1
    print("SMOKE_HARNESS_OK" if failures == 0 else f"SMOKE_HARNESS_FAILED ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
