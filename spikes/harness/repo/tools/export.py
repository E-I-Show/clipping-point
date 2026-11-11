"""Build the shipping file: app/ -> dist/clipping_point.pyxapp -> dist/clipping_point.html.

  python3 tools/export.py [--max-html-kb N] [--smoke-config JSON]   (the latter: tools/web_smoke.py only)

Steps: stage a clean copy of app/ (no caches, no saves, no test hooks) -> `pyxel package` ->
`pyxel app2html` -> checks. Exit 0 ok / 1 a check failed / 2 the build tools did not run.
Checks: required files are in the archive, forbidden ones are not (tests, test packs, saves,
smoke_config.json), the HTML payload is the archive, the runtime URL carries the installed Pyxel
version, the sizes are within tools/budgets.json.
"""
import argparse
import base64
import json
import re
import shutil
import sys
import zipfile

from _common import APP, FAIL, INCOMPLETE, OK, OUT, ROOT, finish, run

NAME = "clipping_point"
MUST_HAVE = ("main.py", "cp_core/world.py", "cp_ui/screens.py", "cp_app/app.py", "data/cars.json", "data/tracks.json")
MUST_NOT = ("smoke_config.json", "testpacks", "tests/", ".saves", "__pycache__", ".tmp", ".sav", "conftest")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-html-kb", type=int)
    ap.add_argument("--smoke-config", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    budgets = json.loads((ROOT / "tools" / "budgets.json").read_text())
    shipping = not args.smoke_config
    dist = ROOT / "dist" if shipping else OUT / "web" / "build"
    if args.out:
        dist = ROOT / args.out
    stage = OUT / "stage" / ("ship" if shipping else "smoke") / NAME
    shutil.rmtree(stage.parent, ignore_errors=True)
    if shipping and (APP / "smoke_config.json").exists():
        return finish("export", FAIL, "app/smoke_config.json exists: a test hook must never be shipped")
    shutil.copytree(APP, stage, ignore=shutil.ignore_patterns("__pycache__", ".saves", "*.tmp", "smoke_config.json"))
    if not shipping:
        (stage / "smoke_config.json").write_text(args.smoke_config, encoding="utf-8")
    dist.mkdir(parents=True, exist_ok=True)
    pyxapp, html = dist / f"{NAME}.pyxapp", dist / f"{NAME}.html"
    pyxapp.unlink(missing_ok=True)
    html.unlink(missing_ok=True)
    for cmd in ([sys.executable, "-m", "pyxel", "package", stage, stage / "main.py"], [sys.executable, "-m", "pyxel", "app2html", pyxapp.name]):
        code, out, err = run(cmd, cwd=dist)  # both commands write into the current directory
        if code != 0:
            print(out[-1500:], err[-1500:])
            return finish("export", INCOMPLETE, f"`pyxel {cmd[3]}` failed (exit {code})")
    if not pyxapp.exists() or not html.exists():
        return finish("export", INCOMPLETE, "pyxel reported success but the output files are missing")

    import pyxel  # only for the version constant; no init

    problems = []
    with zipfile.ZipFile(pyxapp) as zf:
        names = zf.namelist()
    for m in MUST_HAVE:
        if f"{NAME}/{m}" not in names:
            problems.append(f"missing from archive: {m}")
    if shipping:
        problems += [f"must not be shipped: {n}" for n in names for bad in MUST_NOT if bad in n]
    text = html.read_text(encoding="utf-8")
    m = re.search(r'base64: "([A-Za-z0-9+/=]+)"', text)
    if not m or base64.b64decode(m.group(1)) != pyxapp.read_bytes():
        problems.append("the HTML payload is not the .pyxapp")
    runtime = re.findall(r'src="(https://[^"]+)"', text)
    if runtime != [f"https://kitao.dev/pyxel/{pyxel.VERSION}/pyxel.js"]:
        problems.append(f"unexpected runtime script {runtime} (installed Pyxel is {pyxel.VERSION})")
    html_kb, app_kb = html.stat().st_size / 1024, pyxapp.stat().st_size / 1024
    max_html = args.max_html_kb or budgets["max_html_kb"]
    if html_kb > max_html:
        problems.append(f"HTML is {html_kb:.1f} KB, limit {max_html} KB")
    if app_kb > budgets["max_pyxapp_kb"]:
        problems.append(f".pyxapp is {app_kb:.1f} KB, limit {budgets['max_pyxapp_kb']} KB")
    for p in problems:
        print("EXPORT:", p)
    return finish("export", FAIL if problems else OK,
                  f"files={len(names)} pyxapp_kb={app_kb:.1f} html_kb={html_kb:.1f} limit_html_kb={max_html} problems={len(problems)} html={html}")


if __name__ == "__main__":
    sys.exit(main())
