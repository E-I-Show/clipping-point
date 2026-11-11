"""The one place that says what "verified" means. Runs wrappers one after another (never in
parallel: they share out/ and dist/), keeps going after a failure, prints one table.

  python3 tools/verify.py --all                    full verification (stage end / foundation touched)
  python3 tools/verify.py --touched ui,data        focused verification for the areas you touched
  python3 tools/verify.py --list                   print the area table (CLAUDE.md copies it; check.py compares)

Exit 0 only if every planned step ran and returned 0. A step that did not run counts as failed.
"""
import argparse
import json
import sys
import time

from _common import OUT, finish, run

PY = sys.executable
STEPS = {
    "check": [PY, "tools/check.py"],
    "test": [PY, "tools/test.py"],
    "screen-check": [PY, "tools/screen_check.py"],
    "run": [PY, "tools/run.py"],
    "run-realtime": [PY, "tools/run.py", "--driver", "run"],
    "run-pack": [PY, "tools/run.py", "--pack", "extreme", "--ticks", "600"],
    "tour": [PY, "tools/tour.py"],
    "tour-pack": [PY, "tools/tour.py", "--pack", "extreme"],
    "export": [PY, "tools/export.py"],
    "run-packaged": [PY, "tools/run.py", "--packaged"],
    "web-smoke": [PY, "tools/web_smoke.py"],
    "selftest": [PY, "tools/selftest_break.py"],
}
ALL = ["check", "test", "screen-check", "run", "run-realtime", "run-pack", "tour", "tour-pack", "export", "run-packaged", "web-smoke"]
FOUNDATION = "ALL"  # save format, state types, rng, fixed loop, data loader/validator, tools: run everything
# area -> ("-k" expression for tools/test.py, extra steps). "check" always runs first.
AREAS = {
    "vehicle": ("world or fingerprint or session", ["run"]),
    "track": ("world or fingerprint or data", ["run", "tour"]),
    "assist": ("profile or session", ["run"]),
    "ai": ("world or fingerprint or rng", ["run"]),
    "race": ("session or world or fingerprint", ["run", "screen-check"]),
    "render": ("ui", ["run", "run-realtime", "tour", "web-smoke"]),
    "replay": ("storage or fingerprint", ["run", "web-smoke"]),
    "ui": ("ui", ["screen-check", "tour", "tour-pack"]),
    "audio": ("data", ["run", "web-smoke"]),
    "save": FOUNDATION,
    "data": FOUNDATION,
    "rng": FOUNDATION,
    "tools": FOUNDATION,
}


def plan_for(areas: list) -> list:
    if any(AREAS[a] == FOUNDATION for a in areas):
        return [(s, STEPS[s]) for s in ALL] + ([("selftest", STEPS["selftest"])] if "tools" in areas else [])
    words, steps = [], []
    for a in areas:
        expr, extra = AREAS[a]
        words += [w for w in expr.split(" or ") if w not in words]
        steps += [s for s in extra if s not in steps]
    plan = [("check", STEPS["check"]), ("test", [PY, "tools/test.py", "-k", " or ".join(words)])]
    return plan + [(s, STEPS[s]) for s in ALL if s in steps]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--touched", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for area, spec in AREAS.items():
            print(f"| {area} | " + ("everything (`verify.py --all`)" if spec == FOUNDATION else f"check, test -k \"{spec[0]}\", {', '.join(spec[1])}") + " |")
        return 0
    areas = [a for a in args.touched.split(",") if a]
    unknown = [a for a in areas if a not in AREAS]
    if unknown or (not areas and not args.all):
        return finish("verify", 2, f"unknown area {unknown} or nothing asked (areas: {', '.join(AREAS)})")
    plan = [(s, STEPS[s]) for s in ALL] if args.all else plan_for(areas)
    rows, t_all = [], time.perf_counter()
    for name, cmd in plan:
        t0 = time.perf_counter()
        code, out, err = run(cmd, timeout=1800)
        last = ([line for line in out.strip().splitlines() if line.strip()] or ["(no output)"])[-1]
        rows.append({"step": name, "exit": code, "seconds": round(time.perf_counter() - t0, 2), "summary": last[:230]})
        if code != 0:
            print(f"--- {name} (exit {code}) ---\n" + "\n".join((out + err).strip().splitlines()[-30:]))
    print(f"{'step':14s} {'exit':>4s} {'sec':>6s}  summary")
    for r in rows:
        print(f"{r['step']:14s} {str(r['exit']):>4s} {r['seconds']:6.2f}  {r['summary']}")
    bad = [r["step"] for r in rows if r["exit"] != 0]
    (OUT / "verify").mkdir(parents=True, exist_ok=True)
    (OUT / "verify" / "last.json").write_text(json.dumps({"mode": "all" if args.all else areas, "rows": rows}, indent=1))
    total = time.perf_counter() - t_all
    worst = max((2 if r["exit"] is None else min(r["exit"], 2) if r["exit"] else 0) for r in rows) if rows else 2
    return finish("verify", 0 if not bad and rows else max(worst, 1),
                  f"mode={'all' if args.all else '+'.join(areas)} steps={len(rows)} ok={len(rows) - len(bad)} not_ok={bad} seconds={total:.1f}")


if __name__ == "__main__":
    sys.exit(main())
