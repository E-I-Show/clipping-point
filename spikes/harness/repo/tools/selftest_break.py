"""Break things on purpose and make sure the wrappers notice.

  python3 tools/selftest_break.py [--only PREFIX] [--json FILE]

Each case copies the repository to a scratch directory, plants one fault, runs one wrapper and
compares its exit code with the expected one. A planted fault that is NOT caught makes this
script exit 1. Controls (no fault, must exit 0) guard against wrappers that always fail.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from _common import OUT, ROOT, child_env, run

PY = sys.executable
T = lambda *a: [PY, "tools/" + a[0] + ".py", *a[1:]]  # noqa: E731


def rep(path, old, new):
    return ("replace", path, old, new)


def add(path, text):
    return ("write", path, text)


def app(path, text):
    return ("append", path, text)


def rm(path):
    return ("delete", path)


CASES = [
    # name, faults, command, expected exit codes
    ("control_check", [], T("check"), {0}),
    ("control_test", [], T("test"), {0}),
    ("control_run", [], T("run"), {0}),
    ("control_screen_check", [], T("screen_check"), {0}),
    ("control_tour", [], T("tour"), {0}),
    ("control_export", [], T("export"), {0}),
    ("control_export_ignores_saves_dir", [add("app/.saves/main.profile.sav", "x")], T("export"), {0}),
    ("control_verify_ui", [], T("verify", "--touched", "ui"), {0}),
    # --- check
    ("check_syntax_error", [rep("app/cp_app/app.py", "def main() -> None:", "def main() -> None")], T("check"), {1}),
    ("check_core_imports_pyxel", [app("app/cp_core/world.py", "\nimport pyxel\n")], T("check"), {1}),
    ("check_core_lazy_import_in_function", [app("app/cp_core/world.py", "\ndef dbg():\n    import pyxel\n")], T("check"), {1}),
    ("check_ui_imports_adapter", [app("app/cp_ui/screens.py", "\nfrom cp_app import canvas_pyxel\n")], T("check"), {1}),
    ("check_core_uses_random", [app("app/cp_core/world.py", "\nimport random\n")], T("check"), {1}),
    ("check_core_uses_builtin_hash", [app("app/cp_core/world.py", "\nBAD = hash('x')\n")], T("check"), {1}),
    ("check_data_unknown_key", [rep("app/data/cars.json", '"power_ps": 165', '"pwoer_ps": 165')], T("check"), {1}),
    ("check_data_dangling_ref", [rep("app/data/cars.json", '"turbo": true, "engine_sound": "eng_turbo4", "default_assist": "standard"', '"turbo": true, "engine_sound": "eng_v8", "default_assist": "standard"')], T("check"), {1}),
    ("check_data_out_of_range", [rep("app/data/cars.json", '"mass_kg": 960', '"mass_kg": 96')], T("check"), {1}),
    ("check_data_non_ascii_name", [rep("app/data/cars.json", '"name": "KAZANE RS"', '"name": "カザネ RS"')], T("check"), {1}),
    ("check_data_unused_definition", [rep("app/data/audio.json", '{"id": "bgm_menu", "kind": "bgm", "channel": 0}', '{"id": "bgm_menu", "kind": "bgm", "channel": 0},\n  {"id": "sfx_unused", "kind": "sfx", "channel": 2}')], T("check"), {1}),
    ("check_test_pack_broken", [rep("testpacks/extreme/cars.json", '"layout": "MR"', '"layout": "RR"')], T("check"), {1}),
    ("check_adapter_import_error", [rep("app/cp_app/app.py", "import AXIS_MAX, Session, script_events", "import AXIS_MAX, Session, script_event")], T("check"), {1}),
    ("check_rules_glob_matches_nothing", [rep(".claude/rules/ui.md", '"app/cp_ui/*.py"', '"app/cp_gui/*.py"')], T("check"), {1}),
    ("check_rules_file_not_in_index", [rep("CLAUDE.md", "| `.claude/rules/save.md` | storage, profile, web storage backend |\n", "")], T("check"), {1}),
    ("check_claude_md_too_long", [app("CLAUDE.md", "\n- filler" * 200)], T("check"), {1}),
    # --- test
    ("test_logic_change_moves_fingerprint", [rep("app/cp_core/world.py", "(target - car.v) * 1.8 * TICK_DT", "(target - car.v) * 1.81 * TICK_DT")], T("test"), {1}),
    ("test_snapshot_file_deleted", [rm("tests/snapshots/world_ta_600.json")], T("test"), {1}),
    ("test_set_order_depends_on_hash_seed", [rep("app/cp_core/world.py", "order = list(car_ids)", "order = list(set(car_ids))")], T("test", "-k", "rng"), {1}),
    ("test_codec_drops_a_field", [rep("app/cp_core/profile.py", 'for f in fields(obj) if f"{cls}.{f.name}" not in NOT_SAVED}', 'for f in fields(obj) if f"{cls}.{f.name}" not in NOT_SAVED and f.name != "steer_curve"}')], T("test"), {1}),
    ("test_new_saved_field_without_decision", [rep("app/cp_core/profile.py", "    race_laps: int = 3\n", "    race_laps: int = 3\n    ghost_visible: bool = True\n")], T("test"), {1}),
    ("test_stale_not_saved_entry", [rep("app/cp_core/profile.py", 'NOT_SAVED = {\n', 'NOT_SAVED = {\n    "Profile.menu_cache": "screen cache that was removed long ago",\n')], T("test"), {1}),
    ("test_file_write_truncates", [rep("app/cp_core/storage.py", "f.write(data)  # the whole blob at once", "f.write(data[:-1])  # the whole blob at once")], T("test", "-k", "storage or profile"), {1}),
    ("test_k_matches_nothing", [], T("test", "-k", "zzz"), {2}),
    ("test_k_one_word_is_a_typo", [], T("test", "-k", "rng or profle"), {2}),
    ("test_one_test_skipped", [rep("tests/test_session.py", "def test_session_script", "import pytest\n\n\n@pytest.mark.skip(reason='later')\ndef test_session_script")], T("test"), {1}),
    ("test_process_dies_with_exit_0", [add("tests/test_zz_exit.py", "import os\n\n\ndef test_zz_exit():\n    os._exit(0)\n")], T("test"), {2}),
    ("test_file_fails_to_load", [add("tests/test_zz_load.py", "import no_such_module_xyz\n\n\ndef test_zz():\n    pass\n")], T("test"), {1}),
    ("test_file_vanished_count_below_floor", [rm("tests/test_storage.py")], T("test"), {1}),
    ("test_pyxel_loaded_in_test_process", [add("tests/test_zz_px.py", "def test_zz_px():\n    import pyxel\n    assert pyxel.VERSION\n")], T("test"), {1}),
    ("test_exception_only_in_thread", [add("tests/test_zz_thread.py", "import threading\n\n\ndef test_zz_thread():\n    t = threading.Thread(target=lambda: 1 / 0)\n    t.start()\n    t.join()\n")], T("test"), {1}),
    # --- run
    ("run_exception_in_update", [], T("run", "--fault", "update"), {1}),
    ("run_exception_in_draw", [], T("run", "--fault", "draw"), {1}),
    ("run_quit_early_exit_0", [], T("run", "--fault", "quit_early"), {2}),
    ("run_stall_hits_timeout", [], T("run", "--fault", "stall", "--timeout", "4"), {2}),
    ("run_adapter_drops_steering", [rep("app/cp_app/app.py", "            pyxel.btnv(pyxel.GAMEPAD1_AXIS_LEFTX),\n        )", "            0,\n        )")], T("run"), {1}),
    ("run_storage_write_truncates", [rep("app/cp_core/storage.py", "f.write(data)  # the whole blob at once", "f.write(data[:-1])  # the whole blob at once")], T("run"), {1}),
    ("run_packaged_without_build", [], T("run", "--packaged"), {2}),
    # --- screen-check
    ("screen_text_wider_than_its_box", [rep("app/cp_ui/screens.py", "f\"TIME {vm['time']}\"", "f\"TOTAL TIME ELAPSED {vm['time']}\"")], T("screen_check"), {1}),
    ("screen_text_off_screen", [rep("app/cp_ui/screens.py", 'c.text(4, SCREEN_H - 8, vm["hint"], COL_DIM)\n        v = "VER "', 'c.text(250, SCREEN_H - 8, vm["hint"], COL_DIM)\n        v = "VER "')], T("screen_check"), {1}),
    ("screen_non_ascii_label", [rep("app/cp_ui/screens.py", '"SETTING", COL_HI', '"セッティング", COL_HI')], T("screen_check"), {1}),
    ("screen_overflow_only_in_extreme_variant", [rep("app/cp_ui/screens.py", "14 * THEATER_VISIBLE_ROWS + 18)", "14 * THEATER_VISIBLE_ROWS + 12)")], T("screen_check"), {1}),
    ("screen_name_budget_raised_layout_not", [rep("app/cp_core/datadefs.py", "CAR_NAME_MAX = 14", "CAR_NAME_MAX = 24"), rep("testpacks/extreme/cars.json", '"name": "WWWWWWWWWWWWWW"', '"name": "WWWWWWWWWWWWWWWWWWWWWWWW"')], T("screen_check"), {1}),
    ("screen_raises", [rep("app/cp_ui/screens.py", "def draw_hud(c: Canvas, vm: dict) -> None:\n", "def draw_hud(c: Canvas, vm: dict) -> None:\n    raise RuntimeError('boom')\n")], T("screen_check"), {2}),
    ("screen_draws_nothing", [rep("app/cp_ui/screens.py", "def draw_hud(c: Canvas, vm: dict) -> None:\n", "def draw_hud(c: Canvas, vm: dict) -> None:\n    return\n")], T("screen_check"), {2}),
    ("screen_only_unknown_name", [], T("screen_check", "--only", "nosuch"), {2}),
    ("screen_no_variants_zero_visited", [rep("app/cp_ui/fixtures.py", 'VARIANTS = ("typical", "extreme")', "VARIANTS = ()")], T("screen_check"), {2}),
    # --- tour (pixel check)
    ("tour_draw_bypasses_recording", [rep("app/cp_app/canvas_pyxel.py", "self.t.rectb(x + self.ox, y + self.oy, w, h, col)", "self.t.rectb(x + self.ox, y + self.oy, w + 2, h, col)")], T("tour"), {1}),
    ("tour_text_metrics_too_small", [rep("app/cp_ui/canvas.py", "FONT_W, FONT_H = 4, 6", "FONT_W, FONT_H = 3, 6")], T("tour"), {1}),
    ("tour_text_metrics_too_small_seen_by_screen_check", [rep("app/cp_ui/canvas.py", "FONT_W, FONT_H = 4, 6", "FONT_W, FONT_H = 3, 6")], T("screen_check"), {0}),
    ("tour_screen_skipped", [], T("tour", "--fault", "tour_skip"), {2}),
    ("tour_exception_midway", [], T("tour", "--fault", "tour_exception"), {2}),
    ("tour_only_unknown_name", [], T("tour", "--only", "nosuch"), {2}),
    # --- export
    ("export_test_hook_left_in_app", [add("app/smoke_config.json", '{"ticks": 10}')], T("export"), {1}),
    ("export_over_size_limit", [], T("export", "--max-html-kb", "10"), {1}),
    ("export_main_py_missing", [rm("app/main.py")], T("export"), {1, 2}),
    # --- verify
    ("verify_reports_a_failed_step", [rep("app/cp_ui/screens.py", "f\"TIME {vm['time']}\"", "f\"TOTAL TIME ELAPSED {vm['time']}\"")], T("verify", "--touched", "ui"), {1}),
    ("verify_unknown_area", [], T("verify", "--touched", "nosuch"), {2}),
    # --- browser
    ("web_control", [], T("web_smoke"), {0}),
    ("web_mirror_missing", [], T("web_smoke"), {2}, {"CP_WEB_MIRROR": "/nonexistent/mirror"}),
    ("web_exception_in_update", [], T("web_smoke", "--fault", "update", "--timeout", "40"), {1}),
    ("web_storage_backend_broken", [rep("app/cp_app/storage_web.py", "return base64.b64decode(v)", "return base64.b64decode(v)[:-1]")], T("web_smoke", "--timeout", "40"), {1}),
]


def plant(work: Path, faults) -> None:
    for kind, path, *rest in faults:
        target = work / path
        if kind == "replace":
            text = target.read_text(encoding="utf-8")
            if text.count(rest[0]) != 1:
                raise RuntimeError(f"{path}: fault anchor found {text.count(rest[0])} times (the self-test is out of date)")
            target.write_text(text.replace(rest[0], rest[1]), encoding="utf-8")
        elif kind == "append":
            target.write_text(target.read_text(encoding="utf-8") + rest[0], encoding="utf-8")
        elif kind == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rest[0], encoding="utf-8")
        elif kind == "delete":
            target.unlink()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default=str(OUT / "selftest" / "break_results.json"))
    args = ap.parse_args()
    cases = [c for c in CASES if c[0].startswith(args.only)]
    if not cases:
        print(f"SELFTEST_INCOMPLETE no case starts with {args.only!r}")
        return 2
    rows, wrong = [], 0
    scratch = OUT / "selftest"
    scratch.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("out", "dist", "__pycache__", ".saves", ".cache", ".git")
    for name, faults, cmd, expected, *env_extra in cases:
        with tempfile.TemporaryDirectory(dir=scratch, prefix=name + "-") as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(ROOT, work, ignore=ignore)
            t0 = time.perf_counter()
            try:
                plant(work, faults)
                code, out, err = run(cmd, timeout=180, cwd=work, env=child_env(**(env_extra[0] if env_extra else {})))
            except RuntimeError as exc:
                code, out, err = "plant-error", str(exc), ""
            last = ([line for line in out.strip().splitlines() if line.strip()] or [err.strip()[-200:] or "(no output)"])[-1]
        ok = code in expected
        wrong += not ok
        rows.append({"case": name, "command": " ".join(c.replace(PY, "python3") for c in cmd), "expected_exit": sorted(expected),
                     "exit": code, "verdict": "as expected" if ok else "NOT CAUGHT / WRONG", "seconds": round(time.perf_counter() - t0, 2),
                     "last_line": last[:200]})
        print(f"[{'ok' if ok else 'WRONG'}] {name:48s} exit={code} expected={sorted(expected)}  {last[:110]}")
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    faults_n = sum(1 for r in rows if r["expected_exit"] != [0])
    print(f"SELFTEST_{'OK' if not wrong else 'FAILED'} cases={len(rows)} planted_faults={faults_n} controls={len(rows) - faults_n} wrong={wrong}")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
