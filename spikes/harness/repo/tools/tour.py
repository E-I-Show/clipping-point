"""Screenshot tour (real Pyxel, headless): one PNG per screen fixture in out/tour/, plus the pixel
check that keeps the overflow check honest:
  * ink_outside_screen: pixels drawn into a 16 px margin around the 320x240 area
  * ink_unrecorded:     pixels that no recorded draw call covers (a draw that bypassed the canvas,
                        or text metrics that are too small)

  python3 tools/tour.py [--only SCREEN] [--pack NAME]

Exit 0 all captured and clean / 1 captured but a pixel or overflow problem / 2 did not get round
(unknown --only, app failed, a planned PNG is missing or empty). Look at the PNGs yourself: the
tour only proves they exist and that ink stays inside what was recorded.
"""
import argparse
import json
import shutil
import sys

from _common import APP, FAIL, INCOMPLETE, OK, OUT, child_env, finish, run, use_app_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--pack", default="")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--fault", default="", help="self-test only: tour_skip|tour_exception")
    args = ap.parse_args()
    use_app_path()
    from cp_ui import fixtures
    from cp_ui.screens import SCREENS

    planned = [f"{s}_{v}" for s in SCREENS if args.only in ("", s) for v in fixtures.VARIANTS]
    if not planned:
        return finish("tour", INCOMPLETE, f"no screen named {args.only!r} (known: {sorted(SCREENS)})")
    work = OUT / "tour"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result = work / "result.json"
    env = child_env(CP_SMOKE=result, CP_SMOKE_MODE="tour", CP_SMOKE_SHOT_DIR=work, CP_SMOKE_ONLY=args.only,
                    CP_SMOKE_PACK=args.pack, CP_SMOKE_FAULT=args.fault)
    code, out, err = run([sys.executable, APP / "main.py"], timeout=args.timeout, env=env)
    if code != 0 or not result.exists():
        print("\n".join(line for line in err.splitlines() if "ALSA" not in line)[-1500:])
        return finish("tour", INCOMPLETE, f"app did not finish the tour (exit {code}, result file {'present' if result.exists() else 'missing'})")
    shots = {f"{s['screen']}_{s['variant']}": s for s in json.loads(result.read_text())["shots"]}
    missing = [n for n in planned if n not in shots or not (work / f"{n}.png").exists() or (work / f"{n}.png").stat().st_size < 300
               or shots[n]["ink"] == 0]
    problems = []
    for name in planned:
        s = shots.get(name)
        if not s:
            continue
        if s["ink_outside_screen"]:
            problems.append(f"{name}: {s['ink_outside_screen']} pixels drawn outside the screen")
        if s["ink_unrecorded"]:
            problems.append(f"{name}: {s['ink_unrecorded']} pixels not covered by any recorded draw call")
        problems += [f"{name}: {v}" for v in s["violations"]]
        print(f"captured {work / (name + '.png')} items={s['items']} ink={s['ink']}")
    for p in problems:
        print("TOUR:", p)
    summary = f"shots={len(planned) - len(missing)}/{len(planned)} problems={len(problems)} dir={work}"
    if missing:
        print("TOUR: not captured:", missing)
        return finish("tour", INCOMPLETE, summary)
    return finish("tour", FAIL if problems else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
