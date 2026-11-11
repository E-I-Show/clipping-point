# CLIPPING POINT (harness prototype)

<!-- Root CLAUDE.md: 200 lines max (tools/claude/rules_guard.py checks). Area rules go to .claude/rules/. -->

## The promises that matter most
- `app/cp_core` and `app/cp_ui` never import pyxel, js, pyodide, cp_app, random, time. `tools/check.py` fails otherwise.
- pytest never loads pyxel. Anything that needs Pyxel runs through a wrapper in `tools/` in a subprocess.
- Read a file before editing it. Before creating a file, read one existing file of that area.
- `out/` and `dist/` are generated. Never edit them, never commit them. Never run two wrappers at once.
- `docs/spec/` (the approved plan) is not edited by Claude; differences go to `docs/revisions.md`.

## Commands (always through the wrappers)
| Do | Command |
|---|---|
| static checks | `python3 tools/check.py [--only syntax\|arch\|import\|data\|adapter\|docs]` |
| logic tests | `python3 tools/test.py [-k "word or word"]` |
| headless run | `python3 tools/run.py [--ticks N] [--driver flip\|run] [--packaged] [--pack NAME]` |
| 2D overflow | `python3 tools/screen_check.py [--only SCREEN]` |
| screenshots | `python3 tools/tour.py [--only SCREEN]` then look at `out/tour/*.png` |
| build | `python3 tools/export.py` |
| browser run | `python3 tools/web_smoke.py` |
| focused | `python3 tools/verify.py --touched area,area` |
| everything | `python3 tools/verify_all.py` (background) |

Exit codes: 0 pass, 1 problems, 2 could not finish (never a pass).

## Areas and what to run
`python3 tools/verify.py --list` prints the table; `tools/verify.py` is the only definition.

## Rule files
| File | Applies to |
|---|---|
| `.claude/rules/core-sim.md` | world, rng, session, their tests and snapshots |
| `.claude/rules/save.md` | storage, profile, web storage backend |
| `.claude/rules/data.md` | data loader, data files, test packs |
| `.claude/rules/ui.md` | cp_ui screens, canvas, pyxel canvas |
| `.claude/rules/tools.md` | tools/ |
