"""Screenshot tour: drives the app through its screens with injected input and saves one PNG each.

  python3 tools/tour.py [--only NAME]

Exit codes: 0 = every requested screen was captured, 1 = the run failed, 2 = the tour did not
get round all screens (so "0 screens captured" can never look like a pass).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "cp_proto"
sys.path.insert(0, str(APP))

from cp_core.game import Game  # noqa: E402
from cp_core.input_script import TOUR_SCRIPT, TOUR_SHOTS, TOUR_TICKS, reference_raw_inputs  # noqa: E402


def main() -> int:
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else ""
    names = [n for _, n in TOUR_SHOTS if only in ("", n)]
    if not names:
        print(f"TOUR_INCOMPLETE: no screen named {only!r} (known: {[n for _, n in TOUR_SHOTS]})")
        return 2
    out = ROOT / "out" / "tour"
    out.mkdir(parents=True, exist_ok=True)
    for n in names:
        (out / f"{n}.png").unlink(missing_ok=True)
    result = out / "result.json"
    result.unlink(missing_ok=True)
    env = dict(os.environ, CP_SMOKE=str(result), CP_SMOKE_SCRIPT="tour", CP_SMOKE_SHOT_DIR=str(out), CP_SMOKE_ONLY=only)
    env.pop("PYTHONUNBUFFERED", None)
    proc = subprocess.run([sys.executable, str(APP / "main.py")], env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 or not result.exists():
        print(f"TOUR_FAILED: exit={proc.returncode} result_exists={result.exists()}\n{proc.stderr[-600:]}")
        return 1
    data = json.loads(result.read_text())
    game = Game()
    for raw in reference_raw_inputs(TOUR_SCRIPT, TOUR_TICKS):
        game.tick(raw)
    if data["fingerprint"] != game.fingerprint():
        print(f"TOUR_FAILED: state {data['fingerprint']} != reference {game.fingerprint()}")
        return 1
    missing = [n for n in names if n not in data["shots_saved"] or not (out / f"{n}.png").exists()]
    if missing:
        print(f"TOUR_INCOMPLETE: not captured: {missing}")
        return 2
    blobs = {n: (out / f"{n}.png").read_bytes() for n in names}
    if "race" in blobs and "pause" in blobs and blobs["race"] == blobs["pause"]:
        print("TOUR_FAILED: pause screen is identical to race screen (injected START had no effect)")
        return 1
    for n in names:
        print(f"captured {out / (n + '.png')} ({len(blobs[n])} B)")
    print(f"TOUR_OK screens={len(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
