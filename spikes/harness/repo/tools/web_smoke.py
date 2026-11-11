"""Browser smoke run: the same app, packaged as the single HTML, in headless Chromium on Pyodide.

  python3 tools/web_smoke.py [--ticks 120] [--timeout 120] [--fault update]

Needs a local mirror of the Pyxel web runtime (GitHub kitao/pyxel v3.0.1 wasm/ + npm pyodide;
kitao.dev itself is not contacted): directory given by CP_WEB_MIRROR, default .cache/pyxel_web/mirror
(build it once per container with tools/web/fetch_runtime.sh + tools/web/build_mirror.sh).
Exit 0 pass / 1 the page failed or the result is wrong / 2 could not run (no mirror, no node,
build failed, no RESULT_JSON line). A missing mirror is NOT a skip that counts as a pass.

What it proves that the native run cannot: the code imports and runs on Pyodide (Python 3.14,
emscripten), pyxel.run drives 60 Hz ticks, the localStorage backend round-trips, and the coarse
world summary equals the native one. The exact float fingerprint is printed for information only
(libm differs by 1 ulp between the platforms).
"""
import argparse
import json
import os
import shutil
import sys

from _common import APP, FAIL, INCOMPLETE, OK, OUT, PACKS, ROOT, finish, run, use_app_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--fault", default="")
    args = ap.parse_args()
    mirror = os.environ.get("CP_WEB_MIRROR", str(ROOT / ".cache" / "pyxel_web" / "mirror"))
    if not os.path.isdir(os.path.join(mirror, "kitao.dev", "pyxel")):
        return finish("web-smoke", INCOMPLETE, f"runtime mirror not found at {mirror} (set CP_WEB_MIRROR or build it)")
    if not shutil.which("node"):
        return finish("web-smoke", INCOMPLETE, "node not found")
    work = OUT / "web"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cfg = json.dumps({"ticks": args.ticks, "fault": args.fault})
    code, out, err = run([sys.executable, "tools/export.py", "--smoke-config", cfg])
    if code != 0:
        print(out[-1500:], err[-800:])
        return finish("web-smoke", INCOMPLETE, f"smoke build failed (export exit {code})")
    html = work / "build" / "clipping_point.html"
    result = work / "result.json"
    code, out, err = run(["node", "tools/web/webrun.js", "--url", html, "--mirror", mirror, "--until", "^CP_SMOKE_DONE",
                          "--timeout", args.timeout * 1000, "--json", result, "--shot", work / "page.png", "--quiet"], timeout=args.timeout + 60)
    if not result.exists():
        print(out[-1500:], err[-1500:])
        return finish("web-smoke", INCOMPLETE, f"the browser runner produced no result (exit {code})")
    page = json.loads(result.read_text())
    lines = [c["text"] for c in page["console"] if c["text"].startswith("RESULT_JSON smoke ")]
    if code != 0:
        kinds = sorted({f["kind"] for f in page["failures"]})
        for f in page["failures"][:5]:
            print("WEB:", f["kind"], str(f["detail"])[:300])
        return finish("web-smoke", FAIL, f"page failed (runner exit {code}, signals {kinds}, result lines {len(lines)})")
    if not lines:
        return finish("web-smoke", INCOMPLETE, "page finished but printed no RESULT_JSON line")
    data = json.loads(lines[-1].split(" ", 2)[2])
    use_app_path()
    from cp_core.datadefs import load_game_data
    from cp_core.session import reference_session

    ref = reference_session(load_game_data(APP / "data", (), PACKS), args.ticks)
    problems = []
    if data.get("platform") != "emscripten":
        problems.append(f"platform {data.get('platform')!r}: this was not the browser build")
    if data.get("ticks") != args.ticks or data.get("visited") != ref.visited:
        problems.append(f"ticks/screens {data.get('ticks')} {data.get('visited')} != {args.ticks} {ref.visited}")
    if data.get("portable") != json.loads(json.dumps(ref.world.summary_portable())):
        problems.append(f"coarse world summary differs from native:\n  web    {data.get('portable')}\n  native {ref.world.summary_portable()}")
    st = data.get("storage", {})
    if not st.get("ok") or st.get("backend") != "WebStorageBackend":
        problems.append(f"localStorage round trip failed: {st}")
    if data.get("renders", 0) < 1:
        problems.append("no scene render happened")
    exact_same = data.get("fingerprint") == ref.fingerprint()
    for p in problems:
        print("WEB:", p)
    return finish("web-smoke", FAIL if problems else OK,
                  f"python={data.get('python')} ticks={data.get('ticks')} renders={data.get('renders')} storage={st.get('backend')} "
                  f"coarse_summary_equal={'portable' in data and not any('coarse' in p for p in problems)} exact_fingerprint_equal={exact_same} "
                  f"page_wall_s={data.get('wall_s')} problems={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
