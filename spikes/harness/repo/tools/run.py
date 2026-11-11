"""Headless smoke run: start the real app without a window, feed the fixed input script for N
ticks, and compare the end state with the same script replayed by cp_core alone (no Pyxel).

  python3 tools/run.py [--ticks 120] [--driver flip|run] [--packaged] [--pack NAME] [--timeout 60]

Exit 0 pass / 1 ran but wrong (exception, wrong fingerprint, blank screen, storage round trip) /
2 did not get through all ticks (timeout, process ended early - pyxel.quit() exits with code 0 -,
no result file). "Exit code 0 of the app" alone is never a pass.
"""
import argparse
import json
import shutil
import sys

from _common import APP, FAIL, INCOMPLETE, OK, OUT, PACKS, ROOT, child_env, finish, run, use_app_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--driver", choices=("flip", "run"), default="flip")
    ap.add_argument("--packaged", action="store_true", help="run dist/clipping_point.pyxapp through `pyxel play`")
    ap.add_argument("--pack", default="")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--fault", default="", help="self-test only: update|draw|quit_early|stall")
    args = ap.parse_args()
    use_app_path()
    from cp_core.datadefs import load_game_data
    from cp_core.session import reference_session

    ref = reference_session(load_game_data(APP / "data", (args.pack,) if args.pack else (), PACKS), args.ticks)
    work = OUT / "run"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result = work / "result.json"
    cmd = [sys.executable, APP / "main.py"]
    if args.packaged:
        pyxapp = ROOT / "dist" / "clipping_point.pyxapp"
        if not pyxapp.exists():
            return finish("run", INCOMPLETE, f"{pyxapp} not found: run tools/export.py first")
        cmd = [sys.executable, "-m", "pyxel", "play", pyxapp]
    env = child_env(CP_SMOKE=result, CP_SMOKE_TICKS=args.ticks, CP_SMOKE_DRIVER=args.driver, CP_SMOKE_PACK=args.pack,
                    CP_SMOKE_FAULT=args.fault, CP_SMOKE_SAVE_DIR=work / "saves", TMPDIR=work)
    code, out, err = run(cmd, timeout=args.timeout, env=env, cwd=work)
    err_tail = "\n".join(line for line in err.splitlines() if "ALSA" not in line and "audio" not in line)[-1500:]
    if code is None:
        return finish("run", INCOMPLETE, f"timeout after {args.timeout}s (ticks requested {args.ticks})")
    if code != 0:
        print(err_tail)
        return finish("run", FAIL, f"app exit code {code}")
    if not result.exists():
        return finish("run", INCOMPLETE, "app exited with code 0 before finishing all ticks (no result file)")
    data = json.loads(result.read_text())
    problems = []
    if data.get("ticks") != args.ticks:
        problems.append(f"ticks {data.get('ticks')} != {args.ticks}")
    if data.get("fingerprint") != ref.fingerprint():
        problems.append(f"fingerprint {data.get('fingerprint')} != reference {ref.fingerprint()} (adapter and logic disagree)")
    if data.get("visited") != ref.visited:
        problems.append(f"screens visited {data.get('visited')} != {ref.visited}")
    want = args.ticks // 2
    if not want - 3 <= data.get("renders", -1) <= want + 3:
        problems.append(f"renders {data.get('renders')} not about {want} (30 fps)")
    if len(data.get("screen_colors", [])) < 3:
        problems.append(f"screen looks blank: colours {data.get('screen_colors')}")
    if not data.get("storage", {}).get("ok"):
        problems.append(f"storage round trip failed: {data.get('storage')}")
    if "CP_SMOKE_DONE" not in out:
        problems.append("CP_SMOKE_DONE line missing from stdout")
    for p in problems:
        print("RUN:", p)
    return finish("run", FAIL if problems else OK,
                  f"ticks={data.get('ticks')} renders={data.get('renders')} screens={len(data.get('visited', []))} "
                  f"fingerprint={data.get('fingerprint')} driver={args.driver} packaged={args.packaged} wall={data.get('wall_s')}s problems={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
