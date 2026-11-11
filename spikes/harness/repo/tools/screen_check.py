"""2D overflow check (no Pyxel): draw every screen fixture on a recording canvas and count what
leaves the 320x240 screen or its own box, overlapping texts and non-ASCII text.

  python3 tools/screen_check.py [--only SCREEN] [--pack NAME]

Runs every (data set x screen x variant): data sets = shipped data and each test pack.
Exit 0 clean / 1 violations / 2 did not get round (unknown --only, a screen raised, a screen drew
nothing, visited != planned). The resolution is fixed (320x240, integer scaling), so instead of
several window sizes the sweep varies the CONTENT: typical / extreme values and the test packs.
"""
import argparse
import sys

from _common import APP, FAIL, INCOMPLETE, OK, PACKS, finish, pack_names, use_app_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--pack", default=None)
    args = ap.parse_args()
    use_app_path()
    from cp_core.datadefs import load_game_data
    from cp_ui import fixtures
    from cp_ui.canvas import Canvas
    from cp_ui.check import find_violations
    from cp_ui.screens import SCREENS

    screens = [s for s in SCREENS if args.only in ("", s)]
    if not screens:
        return finish("screen-check", INCOMPLETE, f"no screen named {args.only!r} (known: {sorted(SCREENS)})")
    data_sets = [()] + [(p,) for p in pack_names()] if args.pack is None else [(args.pack,) if args.pack else ()]
    planned = [(d, s, v) for d in data_sets for s in screens for v in fixtures.VARIANTS]
    visited, violations, broken = 0, 0, []
    for packs, screen, variant in planned:
        tag = f"{screen}/{variant}/{'+'.join(packs) or 'base'}"
        try:
            canvas = Canvas()
            SCREENS[screen](canvas, fixtures.build(screen, variant, load_game_data(APP / "data", packs, PACKS)))
        except Exception as exc:  # noqa: BLE001 - a screen that cannot be drawn is "not checked"
            broken.append(f"{tag}: {type(exc).__name__}: {exc}")
            continue
        drawn = [i for i in canvas.items if i.kind != "box"]
        if not drawn:
            broken.append(f"{tag}: drew nothing")
            continue
        visited += 1
        found = find_violations(canvas)
        violations += len(found)
        for v in found:
            print(f"OVERFLOW {tag}: {v}")
    for b in broken:
        print("NOT CHECKED", b)
    summary = f"screens={visited}/{len(planned)} violations={violations} not_checked={len(broken)}"
    if broken or visited != len(planned) or not planned:
        return finish("screen-check", INCOMPLETE, summary)
    return finish("screen-check", FAIL if violations else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
