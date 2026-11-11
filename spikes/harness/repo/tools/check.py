"""Static and load-time checks. No game frames are run.

  python3 tools/check.py [--only syntax|arch|import|data|adapter|docs]

  syntax   every .py under app/ tools/ tests/ compiles
  arch     tools/arch_check.py (source analysis: pure packages import only the allow-list)
  import   tools/import_probe.py (import every pure module in a fresh process; pyxel must not load)
  data     shipped data loads with zero warnings; every test pack loads on top of it
  adapter  `import cp_app.app` succeeds in a subprocess (no pyxel.init)
  docs     tools/claude/rules_guard.py (.claude/rules globs, sizes, index; CLAUDE.md length)
Exit 0 all sections ok / 1 a section failed / 2 a section could not run or checked nothing.
"""
import argparse
import sys

from _common import APP, FAIL, INCOMPLETE, OK, PACKS, ROOT, finish, pack_names, run, use_app_path

PY = sys.executable


def syntax():
    files = [p for d in ("app", "tools", "tests") for p in sorted((ROOT / d).rglob("*.py")) if "__pycache__" not in p.parts]
    bad = []
    for p in files:
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec", dont_inherit=True)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            bad.append(f"{p.relative_to(ROOT)}: {exc}")
    return (INCOMPLETE if not files else FAIL if bad else OK), f"files={len(files)} errors={len(bad)}", bad


def sub(cmd):
    def section():
        code, out, err = run(cmd)
        lines = (out + err).strip().splitlines()
        code = INCOMPLETE if code is None or code not in (OK, FAIL, INCOMPLETE) else code
        return code, lines[-1] if lines else "no output", lines[:-1] if code else []
    return section


def data():
    use_app_path()
    from cp_core.datadefs import DataError, load_game_data

    problems, loaded = [], 0
    for packs in [()] + [(p,) for p in pack_names()]:
        try:
            d = load_game_data(APP / "data", packs, PACKS)
            loaded += 1
            problems += [f"warning ({'+'.join(packs) or 'base'}): {w}" for w in d.warnings]
        except DataError as exc:
            problems += [f"({'+'.join(packs) or 'base'}) {p}" for p in exc.problems]
    return (INCOMPLETE if not loaded and not problems else FAIL if problems else OK), f"data_sets={loaded} problems={len(problems)}", problems


SECTIONS = {
    "syntax": syntax,
    "arch": sub([PY, "tools/arch_check.py"]),
    "import": sub([PY, "tools/import_probe.py"]),
    "data": data,
    "adapter": sub([PY, "-c", f"import sys; sys.path.insert(0, {str(APP)!r}); import cp_app.app, cp_app.storage_web; print('adapter modules imported')"]),
    "docs": sub([PY, "tools/claude/rules_guard.py"]),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SECTIONS))
    args = ap.parse_args()
    worst, parts = OK, []
    for name, fn in SECTIONS.items():
        if args.only and name != args.only:
            continue
        code, summary, details = fn()
        for d in details[:40]:
            print(f"  {name}: {d}")
        print(f"[{'ok' if code == OK else 'FAIL' if code == FAIL else 'INCOMPLETE'}] {name}: {summary}")
        worst = max(worst, code)
        parts.append(f"{name}={'ok' if code == OK else 'FAIL' if code == FAIL else 'INCOMPLETE'}")
    return finish("check", worst, f"sections={len(parts)} " + " ".join(parts))


if __name__ == "__main__":
    sys.exit(main())
