"""道具と検査をわざと壊して、落ちることを確かめる。

  python3 tools/selftest_break.py [--only 名前の頭]

件ごとに、要るファイルだけを out/selftest/ の下へ一時に複製し、複製の上で1か所壊し、
複製の中の道具を1本回して、終了コードと最後の1行の語を期待と比べる。作業ツリーは書き換えない。
壊したのに落ちない件（終了コードが違う、落ちた理由が違う）が1つでもあれば1。
壊さない件（control）は0で通ること。何でも落とす道具になっていないことの確かめ。
終了コード：0＝全件が期待どおり、1＝期待と違う件がある、2＝壊す所が見つからず回せない件がある・件が0。
道具か検査の決まりに触れた区切りと、段の仕上げで回す。新しい検査を足したら、ここに壊す件を足す。
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from _common import FAIL, INCOMPLETE, OK, OUT, ROOT, child_env, finish, run

PY = sys.executable
SCRATCH = OUT / "selftest"
# 複製するもの。道具、テスト、見張りが読むファイルの全部。足りなければ control の件が落ちる。
COPY_ITEMS = ("clipping_point", "tools", "tests", ".claude/rules", "docs/canon", "docs/handoff.md", "CLAUDE.md", "pytest.ini")
CASE_TIMEOUT_S = 180  # 1件の時間切れ（秒）。いちばん長い件（verify --all。ブラウザ版の煙テストを含む）で約40秒

RUNTIME_CACHE = ".cache"  # ランタイムの写しの置き場。複製には、ここへのリンクだけを置く（中身は書き換えない）

APP_PY = "clipping_point/cp_app/app.py"
BRIDGE_PY = "clipping_point/cp_app/web_bridge.py"
WEBRUN_JS = "tools/web/webrun.js"
SUMS = "tools/web/SHA256SUMS"
SIM_PY = "clipping_point/cp_core/sim.py"
GATE_PY = "clipping_point/cp_core/fixed_loop.py"
CANVAS_PY = "clipping_point/cp_ui/canvas.py"
UI_RULE = ".claude/rules/ui.md"
SKIP_ALL_HOOK = (
    "\n\ndef pytest_collection_modifyitems(items):\n    import pytest\n\n"
    "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='planted'))\n"
)
# 前回の実行が残した、合格の形の結果ファイル。道具が古い結果を読んで合格にしないことの確かめに置く。
STALE_JUNIT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites>'
    '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="999"></testsuite></testsuites>\n'
)
STALE_RESULT = '{"ticks": 120, "renders": 60, "sim": {"tick": 120}, "back_ink": 3981, "screen_diff": 0, "driver": "flip"}\n'
EXIT_0_TEST = "import os\n\n\ndef test_zz_exit():\n    os._exit(0)\n"
# 前回の実行が残した、合格の形の、ブラウザ版の実行役の結果。
STALE_WEB_PAGE = (
    '{"htmlSha256": "", "failures": [], "clickedAt": 3500, "untilAt": 7000, "state": {"initialized": true},'
    ' "canvas": {"ink": 35000}, "console": [{"t": 7000, "type": "log", "text": "CP_PROBE_RESULT {\\"ticks\\": 240,'
    ' \\"renders\\": 120, \\"sim\\": {\\"tick\\": 240}, \\"platform\\": \\"emscripten\\", \\"python\\": \\"3.14.2\\",'
    ' \\"perf\\": {\\"updates\\": 180, \\"updates_per_s\\": 60.0, \\"renders_per_s\\": 30.0, \\"update_ms_p95\\": 0.1,'
    ' \\"render_ms_p95\\": 0.2}}"}, {"t": 7000, "type": "log", "text": "CP_PROBE_DONE"}]}\n'
)


# --- 壊し方 ---
def rep(path, old, new):
    """old（ちょうど1か所にあること）を new に置き換える。"""
    return ("replace", path, old, new)


def app(path, text):
    """末尾に足す。"""
    return ("append", path, text)


def add(path, text):
    """新しいファイルを置く。"""
    return ("write", path, text)


def rm(path):
    return ("delete", path)


def rm_glob(pattern):
    """当たるファイルを全部消す（1つ以上当たること）。"""
    return ("delete_glob", pattern)


def drop_line(path, needle):
    """needle を含む行（ちょうど1行あること）を消す。"""
    return ("drop_line", path, needle)


def first_char(path):
    """頭の1文字を別の文字に変える。"""
    return ("first_char", path)


def tool(name, *args):
    return [PY, f"tools/{name}.py", *args]


CHECK, TEST, RUN, RUN_RT, EXPORT = tool("check"), tool("test"), tool("run"), tool("run", "--realtime"), tool("export")
# テストを1件、集められない名前に変える。件数だけが1つ減る。
# テストのファイルを丸ごと消す形にしない（規則ファイルの当て先の空振りが先に落ちて、件数の下限まで届かない）。
FEWER_TESTS = rep("tests/test_sim.py", "def test_sim_starts_at_tick_zero():", "def no_longer_collected():")
IN_UPDATE = "        self.sim.step()\n"
IN_DRAW = "        if self.gate.should_render(time.perf_counter() * 1000.0):\n"
PRESENT = "        pyxel.blt(0, 0, self.back, 0, 0, SCREEN_W, SCREEN_H)\n"
EXECUTE = "        execute(canvas.commands, self.back)\n"
QUIT_EARLY = IN_UPDATE + "        if self.ticks == 5:\n            pyxel.quit()\n"
# ブラウザ版の煙テスト。probe の件は、慣らしの60 tickの後に180 tick（3秒）だけ測って、件の時間を縮める。
WEB, WEB_SHIPPED = tool("web_smoke"), tool("web_smoke", "--only", "shipped")
WEB_PROBE = tool("web_smoke", "--only", "probe", "--ticks", "240")
VERIFY_ALL = tool("verify", "--all")
FETCH_CHECK = tool("web/fetch_runtime", "--check")
ONLY_ON_WEB = "        if sys.platform == 'emscripten' and self.ticks == 5:\n"
BUSY_6_MS = (
    "        if sys.platform == 'emscripten':\n            busy_until = time.perf_counter() + 0.006\n"
    "            while time.perf_counter() < busy_until:\n                pass\n"
)
FETCH_OUTSIDE = "\nif sys.platform == 'emscripten':\n    import js\n\n    js.fetch('https://example.com/ping')\n"
RENDER_COUNT = "            self.renders += 1\n"
# 実描画のある周期を20 ms重くする（測る区間の外に置く。更新と実描画の時間の線には掛からない）。
HEAVY_FRAME = (
    "            if sys.platform == 'emscripten':\n                busy_until = time.perf_counter() + 0.020\n"
    "                while time.perf_counter() < busy_until:\n                    pass\n"
)

# (名前, 壊し方の並び, 回す道具, 期待する終了コード, 最後の1行にあるはずの語)
CASES = [
    # --- 壊さない件。0で通ること ---
    ("control_check", [], CHECK, {0}, "check: OK"),
    ("control_test", [], TEST, {0}, "test: OK"),
    ("control_test_k", [], tool("test", "-k", "sim or canvas"), {0}, "test: OK"),
    ("control_test_floor_rises", [add("tests/test_zz_more.py", "def test_zz_more():\n    assert True\n")], TEST, {0}, "floor_was="),
    ("control_test_update_floor", [FEWER_TESTS], tool("test", "--update-floor"), {0}, "floor_was="),
    ("control_run", [], RUN, {0}, "run: OK"),
    ("control_run_realtime", [], RUN_RT, {0}, "run: OK"),
    ("control_export", [], EXPORT, {0}, "export: OK"),
    ("control_export_leaves_out_caches", [add("clipping_point/cp_core/__pycache__/sim.cpython-313.pyc", "x")], EXPORT, {0}, "export: OK"),
    ("control_fetch_runtime_check", [], FETCH_CHECK, {0}, "fetch_runtime: OK"),
    ("control_web_smoke", [], WEB, {0}, "web_smoke: OK scenarios=2 shipped=ok probe=ok"),
    ("control_web_smoke_short_probe", [], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_web_heavy_frame_keeps_30_renders", [rep(APP_PY, RENDER_COUNT, RENDER_COUNT + HEAVY_FRAME)], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_verify_list", [], tool("verify", "--list"), {0}, "verify: OK mode=list"),
    ("control_verify_all", [], VERIFY_ALL, {0}, "verify: OK mode=all steps=6 ok=6 failed=0"),
    # --- check：構文 ---
    ("check_syntax_error_in_app", [rep(SIM_PY, "    def step(self) -> None:\n", "    def step(self) -> None\n")], CHECK, {1}, "failed=syntax"),
    ("check_syntax_error_in_test_file", [add("tests/test_zz_broken.py", "def test_zz(:\n    pass\n")], CHECK, {1}, "failed=syntax"),
    ("check_syntax_error_in_tool", [app("tools/run.py", "\ndef broken(:\n    pass\n")], CHECK, {1}, "failed=syntax"),
    # --- check：層の分離（cp_core と cp_ui へ、エンジン、上の層、乱数、実時間を持ち込む） ---
    ("check_core_imports_pyxel", [app(SIM_PY, "\nimport pyxel\n")], CHECK, {1}, "failed=arch"),
    ("check_core_from_import_pyxel", [app(SIM_PY, "\nfrom pyxel import btn\n")], CHECK, {1}, "failed=arch"),
    ("check_core_lazy_import_in_function", [app(SIM_PY, "\n\ndef debug_draw():\n    import pyxel\n\n    pyxel.cls(0)\n")], CHECK, {1}, "failed=arch"),
    ("check_core_guarded_import", [app(SIM_PY, "\ntry:\n    import pyxel\nexcept ImportError:\n    pyxel = None\n")], CHECK, {1}, "failed=arch"),
    ("check_core_dunder_import", [app(SIM_PY, "\npx = __import__('py' + 'xel')\n")], CHECK, {1}, "failed=arch"),
    ("check_core_importlib", [app(SIM_PY, "\nimport importlib\n\npx = importlib.import_module('pyxel')\n")], CHECK, {1}, "failed=arch"),
    ("check_core_exec_string", [app(SIM_PY, "\nexec('import pyxel')\n")], CHECK, {1}, "failed=arch"),
    ("check_core_new_module_nobody_imports", [add("clipping_point/cp_core/debug_overlay.py", "import pyxel\n")], CHECK, {1}, "failed=arch"),
    ("check_core_imports_adapter", [app(SIM_PY, "\nfrom cp_app.canvas_pyxel import execute\n")], CHECK, {1}, "failed=arch"),
    ("check_core_imports_ui", [app(SIM_PY, "\nfrom cp_ui.canvas import Canvas\n")], CHECK, {1}, "failed=arch"),
    ("check_ui_imports_adapter", [app(CANVAS_PY, "\nfrom cp_app import canvas_pyxel\n")], CHECK, {1}, "failed=arch"),
    ("check_ui_imports_pyxel", [app(CANVAS_PY, "\nimport pyxel\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_random", [app(SIM_PY, "\nimport random\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_time", [app(GATE_PY, "\nimport time\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_builtin_hash", [app(SIM_PY, "\nBAD = hash('x')\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_os", [app(SIM_PY, "\nimport os\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_os_urandom", [app(SIM_PY, "\nfrom os import urandom\n")], CHECK, {1}, "failed=arch"),
    ("check_core_uses_pathlib", [app(SIM_PY, "\nfrom pathlib import Path\n")], CHECK, {1}, "failed=arch"),
    ("check_no_pure_sources", [rm_glob("clipping_point/cp_core/*.py"), rm_glob("clipping_point/cp_ui/*.py")], CHECK, {2}, "empty=arch"),
    # --- check：規則ファイルの見張り ---
    ("check_rules_target_matches_nothing", [rep(UI_RULE, '"clipping_point/cp_ui/**"', '"clipping_point/cp_gui/**"')], CHECK, {1}, "failed=rules"),
    ("check_rules_target_hits_hub_file", [rep(UI_RULE, '"clipping_point/cp_app/canvas_pyxel.py"', '"clipping_point/cp_app/*.py"')], CHECK, {1}, "failed=rules"),
    ("check_rules_file_not_in_index", [drop_line("CLAUDE.md", "| `.claude/rules/ui.md` |")], CHECK, {1}, "failed=rules"),
    ("check_rules_new_file_not_in_index", [add(".claude/rules/extra.md", '---\npaths:\n  - "tools/check.py"\n---\n\n# extra\n')], CHECK, {1}, "failed=rules"),
    ("check_rules_index_row_without_file", [rm(UI_RULE)], CHECK, {1}, "failed=rules"),
    ("check_rules_file_without_paths", [rep(UI_RULE, "---\npaths:\n", "---\nnotes:\n")], CHECK, {1}, "failed=rules"),
    ("check_rules_file_too_big", [app(".claude/rules/tools.md", "- filler line\n" * 500)], CHECK, {1}, "failed=rules"),
    ("check_claude_md_too_long", [app("CLAUDE.md", "- filler\n" * 200)], CHECK, {1}, "failed=rules"),
    ("check_handoff_too_long", [app("docs/handoff.md", "- filler\n" * 30)], CHECK, {1}, "failed=rules"),
    ("check_no_rule_files", [rm_glob(".claude/rules/*.md")], CHECK, {2}, "empty=rules"),
    # --- check：正本の見張り ---
    ("check_canon_one_char_changed", [first_char("docs/canon/planning.md")], CHECK, {1}, "failed=canon"),
    ("check_canon_text_appended", [app("docs/canon/planning.md", "\n")], CHECK, {1}, "failed=canon"),
    ("check_canon_new_file_without_digest", [add("docs/canon/appendix.md", "appendix\n")], CHECK, {1}, "failed=canon"),
    ("check_canon_snapshot_deleted", [rm("tests/snapshots/canon_digest.json")], CHECK, {2}, "empty=canon"),
    ("check_has_no_update_flag", [], tool("check", "--update"), {2}, "unrecognized arguments"),
    # --- test ---
    ("test_zero_tests", [rm_glob("tests/test_*.py")], TEST, {2}, "reason=no_tests"),
    ("test_all_skipped", [app("tests/conftest.py", SKIP_ALL_HOOK)], TEST, {1}, "reason=skipped"),
    ("test_one_skipped", [rep("tests/test_sim.py", "def test_sim_starts_at_tick_zero():", "import pytest\n\n\n@pytest.mark.skip(reason='later')\ndef test_sim_starts_at_tick_zero():")], TEST, {1}, "reason=skipped"),
    ("test_k_matches_nothing", [], tool("test", "-k", "zzz"), {2}, "reason=k_word_matches_nothing"),
    ("test_k_one_word_is_a_typo", [], tool("test", "-k", "sim or canvsa"), {2}, "reason=k_word_matches_nothing"),
    ("test_k_word_spans_a_path", [], tool("test", "-k", "canvas or tests/test_sim.py"), {2}, "reason=k_word_matches_nothing"),
    ("test_pyxel_loaded_at_import_time", [app("clipping_point/cp_app/canvas_pyxel.py", "\nimport pyxel\n")], TEST, {1}, "reason=pyxel_loaded"),
    ("test_stale_report_is_not_reused", [add("out/test/junit.xml", STALE_JUNIT), add("tests/test_zz_exit.py", EXIT_0_TEST)], TEST, {2}, "reason=no_report"),
    ("test_gate_default_drops_the_time_rule", [rep(GATE_PY, "min_interval_ms: float | None = RENDER_MIN_INTERVAL_MS", "min_interval_ms: float | None = None")], TEST, {1}, "reason=failed"),
    ("test_export_payload_check_disabled", [rep("tools/export.py", "    return bool(payload) and base64.b64decode(payload.group(1)) == pyxapp_bytes\n", "    return True\n")], TEST, {1}, "reason=failed"),
    ("test_placeholder_text_not_ascii", [rep("clipping_point/cp_ui/screens.py", 'f"TICK {tick}"', 'f"ティック {tick}"')], TEST, {1}, "reason=failed"),
    ("test_count_below_floor", [FEWER_TESTS], TEST, {1}, "reason=below_floor"),
    ("test_floor_file_deleted", [rm("tests/count_floor.txt")], TEST, {1}, "reason=floor_missing"),
    ("test_one_failing", [add("tests/test_zz_fail.py", "def test_zz_fail():\n    assert 1 == 2\n")], TEST, {1}, "reason=failed"),
    ("test_file_fails_to_load", [add("tests/test_zz_load.py", "import no_such_module_xyz\n\n\ndef test_zz_load():\n    pass\n")], TEST, {1}, "reason=collection_error"),
    ("test_process_dies_with_exit_0", [add("tests/test_zz_exit.py", EXIT_0_TEST)], TEST, {2}, "reason=no_report"),
    ("test_pyxel_loaded_in_test_process", [add("tests/test_zz_px.py", "def test_zz_px():\n    import pyxel\n\n    assert pyxel.VERSION\n")], TEST, {1}, "reason=pyxel_loaded"),
    ("test_exception_only_in_thread", [add("tests/test_zz_thread.py", "import threading\n\n\ndef test_zz_thread():\n    t = threading.Thread(target=lambda: 1 / 0)\n    t.start()\n    t.join()\n")], TEST, {1}, "reason=failed"),
    ("test_sim_steps_two_ticks", [rep(SIM_PY, "        self.tick += 1\n", "        self.tick += 2\n")], TEST, {1}, "reason=failed"),
    ("test_gate_thins_too_much", [rep(GATE_PY, "due = self._ticks_since_render >= self.divisor", "due = self._ticks_since_render > self.divisor")], TEST, {1}, "reason=failed"),
    ("test_gate_redraws_without_new_tick", [rep(GATE_PY, "            and self._ticks_since_render >= 1  #", "            and self._ticks_since_render >= 0  #")], TEST, {1}, "reason=failed"),
    ("test_canvas_drops_text", [rep(CANVAS_PY, "        self.commands.append(TextCommand(x, y, s, col))\n", "        pass\n")], TEST, {1}, "reason=failed"),
    ("test_canvas_accepts_float", [rep(CANVAS_PY, "        if type(value) is not int:\n", "        if False:\n")], TEST, {1}, "reason=failed"),
    # --- run：速い経路 ---
    ("run_exception_in_update", [rep(APP_PY, IN_UPDATE, IN_UPDATE + "        if self.ticks == 5:\n            raise RuntimeError('planted')\n")], RUN, {1}, "reason=app_exit_code"),
    ("run_exception_in_draw", [rep(APP_PY, "        canvas = Canvas()\n", "        canvas = Canvas()\n        if self.renders == 3:\n            raise RuntimeError('planted')\n")], RUN, {1}, "reason=app_exit_code"),
    ("run_quit_early_exit_0", [rep(APP_PY, IN_UPDATE, QUIT_EARLY)], RUN, {2}, "reason=no_result_file"),
    ("run_stall_hits_timeout", [rep(APP_PY, IN_UPDATE, IN_UPDATE + "        if self.ticks == 5:\n            time.sleep(3600)\n")], tool("run", "--timeout", "4"), {2}, "reason=timeout"),
    ("run_ticks_short", [rep(APP_PY, "self.ticks >= config.ticks:", "self.ticks >= config.ticks - 1:")], RUN, {1}, "failed=ticks"),
    ("run_sim_not_stepped", [rep(APP_PY, IN_UPDATE, "        pass\n")], RUN, {1}, "failed=sim_tick"),
    ("run_sim_steps_two_ticks", [rep(SIM_PY, "        self.tick += 1\n", "        self.tick += 2\n")], RUN, {1}, "failed=sim_tick"),
    ("run_zero_renders", [rep(APP_PY, IN_DRAW, "        if False:\n")], RUN, {1}, "failed=renders"),
    ("run_renders_every_tick", [rep(APP_PY, IN_DRAW, "        if True:\n")], RUN, {1}, "failed=renders"),
    ("run_back_buffer_blank", [rep(APP_PY, EXECUTE, "        len(canvas.commands)\n")], RUN, {1}, "failed=back_ink"),
    ("run_not_presented", [rep(APP_PY, PRESENT, "        pass\n")], RUN, {1}, "failed=screen_diff"),
    ("run_stale_result_is_not_reused", [add("out/run/result.json", STALE_RESULT), rep(APP_PY, IN_UPDATE, QUIT_EARLY)], RUN, {2}, "reason=no_result_file"),
    ("run_too_few_ticks", [], tool("run", "--ticks", "3"), {2}, "reason=too_few_ticks"),
    # --- run：本番と同じ経路（pyxel.run） ---
    ("run_realtime_exception_in_update", [rep(APP_PY, IN_UPDATE, IN_UPDATE + "        if self.ticks == 5:\n            raise RuntimeError('planted')\n")], RUN_RT, {1}, "reason=app_exit_code"),
    ("run_realtime_quit_early_exit_0", [rep(APP_PY, IN_UPDATE, QUIT_EARLY)], RUN_RT, {2}, "reason=no_result_file"),
    ("run_realtime_zero_renders", [rep(APP_PY, IN_DRAW, "        if False:\n")], RUN_RT, {1}, "failed=renders"),
    ("run_realtime_takes_fast_path", [rep(APP_PY, 'driver = env.get("CP_SMOKE_DRIVER", "flip")', 'driver = "flip"')], RUN_RT, {1}, "failed=driver"),
    # 指定は run のまま、自前のループへ入る。結果ファイルには、実際に入ったループが書かれる。
    ("run_realtime_loop_ignores_driver", [rep(APP_PY, '        if config is not None and config.driver == "flip":\n', "        if config is not None:\n")], RUN_RT, {1}, "failed=driver"),
    # --- export ---
    ("export_tests_dir_mixed_in", [add("clipping_point/tests/test_zz.py", "def test_zz():\n    pass\n")], EXPORT, {1}, "failed=forbidden"),
    ("export_test_file_mixed_in", [add("clipping_point/cp_core/test_sim.py", "def test_zz():\n    pass\n")], EXPORT, {1}, "failed=forbidden"),
    ("export_doc_mixed_in", [add("clipping_point/README.md", "# notes\n")], EXPORT, {1}, "failed=forbidden"),
    ("export_tool_mixed_in", [add("clipping_point/tools/check.py", "print('tool')\n")], EXPORT, {1}, "failed=forbidden"),
    ("export_unknown_file_type", [add("clipping_point/data/notes.txt", "notes\n")], EXPORT, {1}, "failed=unknown_type"),
    ("export_over_size_limit", [rep("tools/budgets.json", '"html_max_bytes": 1000000', '"html_max_bytes": 1000')], EXPORT, {1}, "failed=size"),
    ("export_main_py_missing", [rm("clipping_point/main.py")], EXPORT, {2}, "reason=pyxel_package_failed"),
    # --- check：分野ごとの組の表（tools/verify.py の AREAS）に当たらないファイル ---
    ("check_shipped_file_in_no_area", [add("clipping_point/cp_core/vehicle.py", '"""placeholder"""\n')], CHECK, {1}, "failed=areas"),
    ("check_test_file_in_no_area", [add("tests/test_zz_new.py", "def test_zz_new():\n    assert True\n")], CHECK, {1}, "failed=areas"),
    # --- fetch_runtime：ランタイムの写しの照合 ---
    ("fetch_runtime_checksum_mismatch", [rep(SUMS, "0ecaf7fa", "1ecaf7fa")], FETCH_CHECK, {1}, "reason=checksum_mismatch"),
    ("fetch_runtime_cache_missing", [rm(RUNTIME_CACHE)], FETCH_CHECK, {2}, "reason=missing"),
    # --- web-smoke：回り切れない（2。合格にしない） ---
    ("web_runtime_mirror_missing", [rm(RUNTIME_CACHE)], WEB, {2}, "reason=no_runtime_mirror"),
    ("web_runtime_mirror_does_not_match_sums", [rep(SUMS, "0ecaf7fa", "1ecaf7fa")], WEB, {2}, "reason=runtime_mirror_mismatch"),
    ("web_build_fails", [rm("clipping_point/main.py")], WEB, {2}, "reason=export_failed"),
    ("web_too_few_ticks", [], tool("web_smoke", "--only", "probe", "--ticks", "30"), {2}, "reason=too_few_ticks"),
    ("web_no_done_signal", [rep(BRIDGE_PY, "    js.console.log(DONE_MARK)\n", "    pass\n")], [*WEB_PROBE, "--timeout", "15"], {2}, "incomplete=probe.no_done_signal"),
    # 実行役が、結果を書かずに終了コード0で終わる。前回の合格の形の結果が残っていても、読まない。
    (
        "web_stale_result_is_not_reused",
        [add("out/web_smoke/probe.json", STALE_WEB_PAGE), rep(WEBRUN_JS, 'const crypto = require("crypto");\n', "process.exit(0);\n")],
        WEB_PROBE, {2}, "incomplete=probe.no_runner_result",
    ),
    # --- web-smoke：ブラウザ版でだけ起きる崩れ（1）。どれも、デスクトップ版の道具（run）は通る ---
    ("web_python_error_only_in_browser", [rep(APP_PY, IN_UPDATE, IN_UPDATE + ONLY_ON_WEB + "            raise RuntimeError('planted')\n")], WEB_SHIPPED, {1}, "failed=shipped.error_overlay"),
    ("web_request_outside_mirror", [app(APP_PY, FETCH_OUTSIDE)], WEB_SHIPPED, {1}, "shipped.outside_mirror"),
    ("web_blank_screen", [rep(APP_PY, PRESENT, "        pass\n")], WEB_SHIPPED, {1}, "failed=shipped.canvas_ink"),
    ("web_probe_ticks_short", [rep(APP_PY, "self.ticks >= probe.ticks:", "self.ticks >= probe.ticks - 1:")], WEB_PROBE, {1}, "failed=probe.ticks"),
    ("web_summary_differs_from_desktop", [rep(APP_PY, IN_UPDATE, IN_UPDATE + ONLY_ON_WEB + "            self.sim.step()\n")], WEB_PROBE, {1}, "failed=probe.sim"),
    ("web_update_over_the_time_line", [rep(APP_PY, IN_UPDATE, IN_UPDATE + BUSY_6_MS)], WEB_PROBE, {1}, "probe.update_ms_p95"),
    # アプリが実時間を RenderGate へ渡さない。デスクトップ版の道具では見えず、ブラウザ版の実描画の回数で見える。
    # 差が出るのは、実描画のある周期が1周期（16.7 ms）に収まらないときだけ。重い周期を足して確かめる
    # （重くしただけなら毎秒30回のまま通ることは、control_web_heavy_frame_keeps_30_renders で見る）。
    (
        "web_gate_gets_no_real_time",
        [rep(APP_PY, RENDER_COUNT, RENDER_COUNT + HEAVY_FRAME), rep(APP_PY, IN_DRAW, "        if self.gate.should_render():\n")],
        WEB_PROBE, {1}, "failed=probe.renders",
    ),
    # --- verify：1本落ちても最後まで回し、失敗にする。回らなかった手順も失敗に数える ---
    (
        "verify_one_step_fails",
        [rep("tests/test_sim.py", "    assert Sim().tick == 0\n", "    assert Sim().tick == 1\n")],
        VERIFY_ALL, {1}, "steps=6 ok=5 failed=1 failed_steps=test",
    ),
    ("verify_step_cannot_run", [rm("tools/run.py")], VERIFY_ALL, {1}, "steps=6 ok=4 failed=2 failed_steps=run,run-realtime"),
    ("verify_nothing_asked", [], tool("verify"), {2}, "reason=nothing_asked"),
]


def plant(work: Path, faults) -> None:
    """複製の上で壊す。壊す所が見つからなければ RuntimeError（このスクリプトの件が古くなっている）。"""
    for kind, path, *rest in faults:
        target = work / path
        if kind == "replace":
            text = target.read_text(encoding="utf-8")
            if text.count(rest[0]) != 1:
                raise RuntimeError(f"{path}: 壊す所が {text.count(rest[0])} か所に当たった（1か所のはず）")
            target.write_text(text.replace(rest[0], rest[1]), encoding="utf-8")
        elif kind == "append":
            target.write_text(target.read_text(encoding="utf-8") + rest[0], encoding="utf-8")
        elif kind == "write":
            if target.exists():
                raise RuntimeError(f"{path}: 置くはずのファイルが既にある")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rest[0], encoding="utf-8")
        elif kind == "delete":
            target.unlink()
        elif kind == "delete_glob":
            hits = sorted(work.glob(path))
            if not hits:
                raise RuntimeError(f"{path}: 消すファイルが1つも無い")
            for hit in hits:
                hit.unlink()
        elif kind == "drop_line":
            lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            hits = [line for line in lines if rest[0] in line]
            if len(hits) != 1:
                raise RuntimeError(f"{path}: 消す行が {len(hits)} 行に当たった（1行のはず）")
            target.write_text("".join(line for line in lines if rest[0] not in line), encoding="utf-8")
        elif kind == "first_char":
            text = target.read_text(encoding="utf-8")
            target.write_text(("=" if text[0] != "=" else "#") + text[1:], encoding="utf-8")
        else:
            raise RuntimeError(f"知らない壊し方：{kind}")


def copy_repo(work: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__")
    for item in COPY_ITEMS:
        source, target = ROOT / item, work / item
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignore)
        else:
            shutil.copyfile(source, target)
    # ランタイムの写し（約45 MB）は複製せず、リンクを置く。複製の中の道具は、ここを読むだけ
    # （取得して書き込む `fetch_runtime.py` は、--check を付けた形でしか回さない）。
    if (ROOT / RUNTIME_CACHE).is_dir():
        (work / RUNTIME_CACHE).symlink_to(ROOT / RUNTIME_CACHE, target_is_directory=True)


def last_line(out: str, err: str) -> str:
    """道具の最後の1行。標準出力に何も無ければ、標準エラーの最後の行。"""
    for text in (out, err):
        lines = [line for line in text.strip().splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return "(no output)"


def main() -> int:
    ap = argparse.ArgumentParser(description="道具と検査をわざと壊して、落ちることを確かめる")
    ap.add_argument("--only", default="", metavar="PREFIX", help="名前がこの語で始まる件だけ回す")
    args = ap.parse_args()
    cases = [case for case in CASES if case[0].startswith(args.only)]
    if not cases:
        return finish("selftest_break", INCOMPLETE, f"cases=0 only={args.only!r}")
    missing = [item for item in COPY_ITEMS if not (ROOT / item).exists()]
    if missing:
        return finish("selftest_break", INCOMPLETE, f"cases=0 missing={','.join(missing)}")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rows, wrong, plant_errors = [], 0, 0
    for name, faults, cmd, expected, needle in cases:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(dir=SCRATCH, prefix=name + "-") as tmp:
            work = Path(tmp) / "repo"
            copy_repo(work)
            try:
                plant(work, faults)
            except (RuntimeError, OSError) as exc:
                code, line = "plant-error", str(exc)
            else:
                code, out, err = run(cmd, timeout=CASE_TIMEOUT_S, cwd=work, env=child_env())
                line = last_line(out, err)
        if code == "plant-error":
            verdict = "COULD NOT PLANT"
            plant_errors += 1
        elif code not in expected:
            verdict = "CONTROL FAILED" if expected == {0} else "NOT CAUGHT"
            wrong += 1
        elif needle not in line:
            verdict = "WRONG REASON"
            wrong += 1
        else:
            verdict = "ok"
        rows.append({
            "case": name, "command": " ".join(c.replace(PY, "python3") for c in cmd), "expected_exit": sorted(expected),
            "expected_word": needle, "exit": code, "verdict": verdict, "seconds": round(time.perf_counter() - started, 2),
            "last_line": line[:300],
        })
        print(f"[{verdict}] {name:40s} exit={code} expected={sorted(expected)}  {line[:150]}")
    (SCRATCH / "break_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    controls = sum(1 for row in rows if row["expected_exit"] == [0])
    summary = f"cases={len(rows)} planted={len(rows) - controls} controls={controls} wrong={wrong} plant_errors={plant_errors}"
    return finish("selftest_break", FAIL if wrong else INCOMPLETE if plant_errors else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
