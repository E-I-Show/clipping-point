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
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path

import input_reference
import screen_check
from _common import FAIL, INCOMPLETE, OK, OUT, ROOT, child_env, finish, run

PY = sys.executable
SCRATCH = OUT / "selftest"
# 複製するもの。道具、テスト、見張りが読むファイルの全部。足りなければ control の件が落ちる。
COPY_ITEMS = ("clipping_point", "tools", "tests", ".claude/rules", ".claude/agents", ".claude/settings.json","docs/canon", "docs/handoff.md", "CLAUDE.md", "pytest.ini")
CASE_TIMEOUT_S = 180  # 1件の時間切れ（秒）。いちばん長い件（verify --all。ブラウザ版の煙テストの4本を含む）で約55秒

RUNTIME_CACHE = ".cache"  # ランタイムの写しの置き場。複製には、ここへのリンクだけを置く（中身は書き換えない）

APP_PY = "clipping_point/cp_app/app.py"
BRIDGE_PY = "clipping_point/cp_app/web_bridge.py"
WEBRUN_JS = "tools/web/webrun.js"
SUMS = "tools/web/SHA256SUMS"
SIM_PY = "clipping_point/cp_core/sim.py"
GATE_PY = "clipping_point/cp_core/fixed_loop.py"
CANVAS_PY = "clipping_point/cp_ui/canvas.py"
UI_RULE = ".claude/rules/ui.md"
FRAME_PY = "clipping_point/cp_core/input_frame.py"
SCRIPT_PY = "clipping_point/cp_core/input_script.py"
PYXEL_INPUT_PY = "clipping_point/cp_app/input_pyxel.py"
WEB_INPUT_PY = "clipping_point/cp_app/input_web.py"
TRACE_PY = "clipping_point/cp_app/input_trace.py"
BUDGETS_JSON = "tools/budgets.json"
SMOKE_SCRIPT_JSON = "tools/input_script_smoke.json"
SCREENS_PY = "clipping_point/cp_ui/screens.py"
FIXTURES_PY = "clipping_point/cp_ui/fixtures.py"
FLOW_PY = "clipping_point/cp_core/flow.py"
EXECUTE_PY = "clipping_point/cp_app/canvas_pyxel.py"
TOUR_APP_PY = "clipping_point/cp_app/tour.py"
TOUR_TOOL_PY = "tools/tour.py"
SKIP_ALL_HOOK = (
    "\n\ndef pytest_collection_modifyitems(items):\n    import pytest\n\n"
    "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='planted'))\n"
)
# 前回の実行が残した、合格の形の結果ファイル。道具が古い結果を読んで合格にしないことの確かめに置く。
STALE_JUNIT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites>'
    '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="999"></testsuite></testsuites>\n'
)
# いまの結果の形に合わせる（入力の出どころ、入力アダプタと直読みを呼んだ回数、入力の要約値つきの世界の要約）。読まれたら合格になる形。
STALE_RESULT = json.dumps({
    "ticks": 120, "renders": 60, "sim": input_reference.sim_summary(input_reference.load_script(input_reference.SMOKE_SCRIPT)[1], 120),
    "back_ink": 4321, "screen_diff": 0, "driver": "flip", "input_source": "script", "adapter_reads": 0, "direct_reads": 0,
}) + "\n"
EXIT_0_TEST = "import os\n\n\ndef test_zz_exit():\n    os._exit(0)\n"
# 前回の実行が残した、合格の形の、ブラウザの実行役の結果（240 tickの probe。入力アダプタから、何も押していない入力を読んだ形）。
STALE_WEB_RESULT = {
    "ticks": 240, "renders": 120, "sim": input_reference.sim_summary(None, 240), "platform": "emscripten", "python": "3.14.2",
    "input_source": "adapter", "adapter_reads": 240, "direct_reads": 240, "warmup_ticks": 60,
    "perf": {"updates": 180, "renders": 90, "updates_per_s": 60.0, "renders_per_s": 30.0, "update_ms_p95": 0.1, "render_ms_p95": 0.2},
}
STALE_WEB_PAGE = json.dumps({
    "htmlSha256": "", "failures": [], "clickedAt": 3500, "untilAt": 7000, "state": {"initialized": True}, "canvas": {"ink": 35000},
    "console": [
        {"t": 7000, "type": "log", "text": "CP_PROBE_RESULT " + json.dumps(STALE_WEB_RESULT)},
        {"t": 7000, "type": "log", "text": "CP_PROBE_DONE"},
    ],
}) + "\n"


def stale_tour_result() -> str:
    """前回の実行が残した、合格の形の、巡回の結果ファイル。命令の数は、いまの画面と見本データから数える（読まれたら合格になる形）。"""
    screens, variants, build, canvas_type, _ = screen_check.load_ui()
    shots = []
    for screen, variant in screen_check.plan(screens, variants):
        canvas, _ = screen_check.build_canvas(screens, build, canvas_type, screen, variant)
        count = len(canvas.commands) if canvas is not None else 0
        shots.append({
            "screen": screen, "variant": variant, "file": f"{screen}_{variant}.png", "commands": count, "checked": count,
            "margin_ink": 0, "screen_ink": 5000, "command_problems": [], "violations": [], "check_ms": 1.0,
        })
    return json.dumps({"shots": shots, "margin": 16, "scale": 2, "wall_s": 0.1}) + "\n"


def blank_png(width: int, height: int) -> bytes:
    """黒1色の、本物のPNG。前回の実行が残した画像の代わりに置く。"""
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    rows = (b"\x00" + b"\x00" * width) * height  # 行ごとに、フィルターの種類（0）と、8ビットの灰色の画素
    head = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


STALE_TOUR_RESULT = stale_tour_result()
STALE_TOUR_PNG = blank_png(640, 480)


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


def add_bytes(path, data):
    """新しいファイルを、バイト列のまま置く（画像など）。"""
    return ("write_bytes", path, data)


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
IN_UPDATE = "        self.sim.step(frame)\n"
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
HANG_ON_WEB = ONLY_ON_WEB + "            while True:\n                pass\n"  # ブラウザ版でだけ、抜けないループに入る


def busy_on_web(ms: int, indent: str = "        ") -> str:
    """ブラウザ版でだけ、ms ミリ秒の空回しをする文。"""
    return (
        f"{indent}if sys.platform == 'emscripten':\n{indent}    busy_until = time.perf_counter() + {ms / 1000}\n"
        f"{indent}    while time.perf_counter() < busy_until:\n{indent}        pass\n"
    )


FETCH_OUTSIDE = "\nif sys.platform == 'emscripten':\n    import js\n\n    js.fetch('https://example.com/ping')\n"
RENDER_COUNT = "            self.renders += 1\n"
RENDER_HEAD = "        canvas = Canvas()\n"  # render() の頭
METER_RENDER = "                self.meter.on_render(started_s, time.perf_counter())\n"
# 実描画のある周期を20 ms重くする（測る区間の外に置く。更新と実描画の時間の線には掛からない）。
HEAVY_FRAME = busy_on_web(20, indent="            ")
# 入力の土台。台本を渡す筋書きと、偽のコントローラーの筋書きは、1本ずつ回す（偽のコントローラーの予定の区間の長さは縮めない）。
WEB_SCRIPT, WEB_PAD = tool("web_smoke", "--only", "script"), tool("web_smoke", "--only", "gamepad")
FROM_SCRIPT = "            return self.script.frame_at(self.sim.tick)\n"  # 台本から入力フレームを作る所
FROM_ADAPTER = "        return self.adapter.read(self.js is not None, self.triggers.read())\n"  # 入力アダプタから作る所
DIRECT_READ = "self.triggers.read()\n"  # 直読みを、余分に1度呼ぶ文
# 道具が、台本を相対パスで渡す。パスは、アプリの作業ディレクトリ（out/run）から見て実在する形にする。
# 実在しないパスだと、アプリの絶対パスの検査が無くても、ファイルが見つからずに同じ落ち方になり、検査の有無を見分けられない。
RELATIVE_SCRIPT = rep("tools/run.py", '        env["CP_SMOKE_SCRIPT"] = str(script_path)\n', f'        env["CP_SMOKE_SCRIPT"] = "../../{SMOKE_SCRIPT_JSON}"\n')
ABS_SCRIPT_CHECK = "        if not os.path.isabs(script_path):\n"  # アプリの、台本の絶対パスの検査
DRAW_FRAME = "        view = PlaceholderView(self.sim.tick, self.renders, self.frame)\n"  # 仮の表示の、表示用の値へ、入力フレームを入れる所
STEER_AXIS_READ = "steer_analog=_clamp(-btnv(self._steer_axis) / AXIS_MAX, -1.0, 1.0)"
DIRECT_ANALOG = "            throttle_analog, brake_analog = _clamp(float(right), 0.0, 1.0), _clamp(float(left), 0.0, 1.0)\n"
# 直読みができたtickにも、Pyxel経由の2値のトリガーをデジタル値へ入れる。
DIRECT_PLUS_DIGITAL = (
    DIRECT_ANALOG
    + "            throttle_digital = 1 if throttle_digital or btnv(self._throttle_axis) > 0 else 0\n"
    + "            brake_digital = 1 if brake_digital or btnv(self._brake_axis) > 0 else 0\n"
)
SKIP_EMPTY_SLOT = "        if is_empty_slot(pad):\n            continue\n"
INT_TO_FLOAT = "    if type(value) is int:\n        value = float(value)\n"  # アナログ値の整数を、小数に直す所
# はみ出しの検査と巡回。
SCREEN, TOUR = tool("screen_check"), tool("tour")
TICK_TEXT = 'f"TICK {view.tick}"'  # 仮の表示の、tick の文字
RENDER_TEXT = 'f"RENDER {view.renders}"'  # 仮の表示の、実描画の回数の文字
TITLE_TEXT = "canvas.text(4, 3, TITLE, COL_TEXT)"
UNDER_BAR = "canvas.line(0, 12, SCREEN_W - 1, 12, COL_EDGE)"  # 帯の下の線
SCREEN_HEAD = '    with canvas.box("title", 0, 0, SCREEN_W, 12):\n'  # 仮の表示の組み立ての頭
# 文字を、囲み（status。幅64）より長くする。ふつうの値でも、極端な値でも、はみ出す。
TEXT_TOO_LONG = rep(SCREENS_PY, TICK_TEXT, 'f"TICKS SINCE START {view.tick}"')
# 極端な値のときだけ、はみ出す。ふつうの値（RENDER COUNT 60）は、囲みの内に収まる。
TEXT_TOO_LONG_WHEN_EXTREME = rep(SCREENS_PY, RENDER_TEXT, 'f"RENDER COUNT {view.renders}"')
TEXT_OFF_SCREEN = rep(SCREENS_PY, TITLE_TEXT, TITLE_TEXT.replace("(4, 3,", "(300, 3,"))
TEXT_NOT_ASCII = rep(SCREENS_PY, TICK_TEXT, 'f"ティック {view.tick}"')
NO_VARIANTS = rep(FIXTURES_PY, 'VARIANTS = ("typical", "extreme")', "VARIANTS = ()")
# 見本データに無い画面を、画面の登録に足す。
SCREEN_WITHOUT_FIXTURES = app(SCREENS_PY, '\nSCREENS["extra"] = build_placeholder\n')
# 文字の幅の計算を、小さく間違える。ためた命令だけを調べる検査（screen_check）は通り、実物の画素と照らす巡回が拾う。
FONT_TOO_NARROW = rep(CANVAS_PY, "FONT_W, FONT_H = 4, 6", "FONT_W, FONT_H = 3, 6")
EXEC_TEXT = "            target.text(command.x + ox, command.y + oy, command.text, command.col)\n"
EXEC_RECTB = "target.rectb(command.x + ox, command.y + oy, command.w, command.h, command.col)"
EXEC_LINE = "target.line(command.x1 + ox, command.y1 + oy, command.x2 + ox, command.y2 + oy, command.col)"
TOUR_VARIANTS = "        for variant in fixtures.VARIANTS:\n"  # 巡回が、変種を順に回す所
TOUR_COMMANDS = "    for index, command in enumerate(commands):\n"  # 巡回が、命令を1つずつ照らす所
TOUR_DRAW_WHOLE = "    execute(commands, whole, MARGIN, MARGIN)\n"  # 巡回が、全体の絵を描く所
TOUR_SAVE = "    shot.save(path, SHOT_SCALE)\n"  # 巡回が、画像を保存する所
TOUR_READY = "    check_reader(single)\n"  # 巡回が、Pyxelを始めた後、画面を回す前
TOUR_ENV = "    env = child_env(CP_TOUR=result_path, CP_TOUR_DIR=WORK)\n"  # 道具が、巡回の口の環境変数を渡す所
TOUR_RELATIVE_RESULT = rep(TOUR_TOOL_PY, TOUR_ENV, TOUR_ENV.replace("CP_TOUR=result_path", 'CP_TOUR="result.json"'))
TOUR_BOTH_SWITCHES = rep(TOUR_TOOL_PY, TOUR_ENV, TOUR_ENV.replace("CP_TOUR_DIR=WORK", "CP_TOUR_DIR=WORK, CP_SMOKE=result_path"))

# (名前, 壊し方の並び, 回す道具, 期待する終了コード, 最後の1行にあるはずの語)
CASES = [
    # --- 壊さない件。0で通ること ---
    ("control_check", [], CHECK, {0}, "check: OK"),
    ("control_test", [], TEST, {0}, "test: OK"),
    ("control_test_k", [], tool("test", "-k", "sim or canvas"), {0}, "test: OK"),
    ("control_test_floor_rises", [add("tests/test_zz_more.py", "def test_zz_more():\n    assert True\n")], TEST, {0}, "floor_was="),
    ("control_test_update_floor", [FEWER_TESTS], tool("test", "--update-floor"), {0}, "floor_was="),
    ("control_run", [], RUN, {0}, "run: OK driver=flip input=script"),
    ("control_run_realtime", [], RUN_RT, {0}, "run: OK driver=run input=adapter"),
    # 台本の有無は、どちらの経路でも入れ替えられる。
    ("control_run_without_script", [], tool("run", "--no-script"), {0}, "run: OK driver=flip input=adapter"),
    ("control_run_realtime_with_script", [], tool("run", "--realtime", "--script", SMOKE_SCRIPT_JSON), {0}, "run: OK driver=run input=script"),
    ("control_export", [], EXPORT, {0}, "export: OK"),
    ("control_export_leaves_out_caches", [add("clipping_point/cp_core/__pycache__/sim.cpython-313.pyc", "x")], EXPORT, {0}, "export: OK"),
    ("control_fetch_runtime_check", [], FETCH_CHECK, {0}, "fetch_runtime: OK"),
    ("control_web_smoke", [], WEB, {0}, "web_smoke: OK scenarios=4 shipped=ok probe=ok script=ok gamepad=ok"),
    ("control_web_smoke_short_probe", [], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_web_heavy_frame_keeps_30_renders", [rep(APP_PY, RENDER_COUNT, RENDER_COUNT + HEAVY_FRAME)], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_verify_list", [], tool("verify", "--list"), {0}, "verify: OK mode=list"),
    ("control_verify_all", [], VERIFY_ALL, {0}, "verify: OK mode=all steps=8 ok=8 failed=0"),
    ("control_screen_check", [], SCREEN, {0}, "screen_check: OK screens=2/2 violations=0 not_checked=0"),
    ("control_screen_check_only_one_screen", [], tool("screen_check", "--only", "placeholder"), {0}, "screen_check: OK screens=2/2 violations=0 not_checked=0"),
    ("control_tour", [], TOUR, {0}, "tour: OK shots=2/2 commands=16 problems=0"),
    ("control_tour_only_one_screen", [], tool("tour", "--only", "placeholder"), {0}, "tour: OK shots=2/2 commands=16 problems=0"),
    # 文字の幅の計算を小さく間違えても、ためた命令だけを調べる検査は通る（検査の穴。巡回が拾うことは tour_text_metrics_too_small）。
    ("control_screen_check_passes_with_text_metrics_too_small", [FONT_TOO_NARROW], SCREEN, {0}, "screen_check: OK screens=2/2 violations=0 not_checked=0"),
    # --- check：構文 ---
    ("check_syntax_error_in_app", [rep(SIM_PY, "    def step(self, frame: InputFrame) -> None:\n", "    def step(self, frame: InputFrame) -> None\n")], CHECK, {1}, "failed=syntax"),
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
    ("test_placeholder_text_not_ascii", [TEXT_NOT_ASCII], TEST, {1}, "reason=failed"),
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
    ("test_canvas_drops_text", [rep(CANVAS_PY, "        self.commands.append(TextCommand(x, y, s, col, self._open[-1]))\n", "        pass\n")], TEST, {1}, "reason=failed"),
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
    # 見本の名前は、設計のモジュールの表に出てこないものにする（本物のファイルと重ならないように）。
    ("check_shipped_file_in_no_area", [add("clipping_point/cp_core/zz_no_area.py", '"""placeholder"""\n')], CHECK, {1}, "failed=areas"),
    ("check_ui_file_in_no_area", [add("clipping_point/cp_ui/zz_no_area.py", '"""placeholder"""\n')], CHECK, {1}, "failed=areas"),
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
    # ブラウザの実行役が、結果を書かずに終了コード0で終わる。前回の合格の形の結果が残っていても、読まない。
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
    ("web_summary_differs_from_desktop", [rep(APP_PY, IN_UPDATE, IN_UPDATE + ONLY_ON_WEB + "            self.sim.step(frame)\n")], WEB_PROBE, {1}, "failed=probe.sim"),
    # 通過条件の線。更新1回の時間、実描画1回の時間、更新の毎秒の回数（実描画の毎秒の回数は web_gate_gets_no_real_time）。
    ("web_update_over_the_time_line", [rep(APP_PY, IN_UPDATE, IN_UPDATE + busy_on_web(6))], WEB_PROBE, {1}, "probe.update_ms_p95"),
    ("web_render_over_the_time_line", [rep(APP_PY, RENDER_HEAD, RENDER_HEAD + busy_on_web(15))], WEB_PROBE, {1}, "probe.render_ms_p95"),
    ("web_update_far_too_slow", [rep(APP_PY, IN_UPDATE, IN_UPDATE + busy_on_web(20))], WEB_PROBE, {1}, "probe.updates_per_s"),
    # 時間を測る所が、実描画1回につき2度呼ばれる（数える所の付け間違い）。
    ("web_render_time_counted_twice", [rep(APP_PY, METER_RENDER, METER_RENDER + METER_RENDER)], WEB_PROBE, {1}, "failed=probe.perf_renders"),
    # ブラウザ版でだけ、更新の中で抜けないループに入る。ページが返らなくなる。集めた分の結果は残り、合格にはならない。
    ("web_browser_hangs_in_update", [rep(APP_PY, IN_UPDATE, IN_UPDATE + HANG_ON_WEB)], [*WEB_SHIPPED, "--timeout", "20"], {1}, "failed=shipped.unresponsive"),
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
        VERIFY_ALL, {1}, "steps=8 ok=7 failed=1 failed_steps=test",
    ),
    ("verify_step_cannot_run", [rm("tools/run.py")], VERIFY_ALL, {1}, "steps=8 ok=6 failed=2 failed_steps=run,run-realtime"),
    # 全体の検証の中で、screen-check と tour が落ちる（文字を、画面の外に置く。突き合わせのテストも落ちる）。
    ("verify_screen_check_and_tour_fail", [TEXT_OFF_SCREEN], VERIFY_ALL, {1}, "steps=8 ok=5 failed=3 failed_steps=test,screen-check,tour"),
    ("verify_nothing_asked", [], tool("verify"), {2}, "reason=nothing_asked"),
    # 複製は、gitの作業ツリーの根でない（親のリポジトリの下にある）。親の変更を読んで回さない。
    ("verify_touched_outside_a_git_work_tree", [], tool("verify", "--touched"), {2}, "reason=git_failed"),
    # --- test：アプリが実時間を RenderGate へ渡していることの守りのテスト ---
    ("test_app_drops_real_time_for_the_gate", [rep(APP_PY, IN_DRAW, "        if self.gate.should_render():\n")], TEST, {1}, "reason=failed"),
    # --- 入力の土台：test（入力フレーム、台本、入力アダプタ、直読み、入力の跡、世界） ---
    ("test_sim_accepts_anything_as_a_frame", [rep(SIM_PY, "        if not isinstance(frame, InputFrame):\n", "        if False:\n")], TEST, {1}, "reason=failed"),
    ("test_frame_rejects_whole_analog_values", [rep(FRAME_PY, INT_TO_FLOAT, "")], TEST, {1}, "reason=failed"),
    # 台本の「押した瞬間」が、区間の全tickに立つ。アプリと参照が同じ台本の読み方を通るので、run では見えない。テストで拾う。
    (
        "test_script_pressed_on_every_tick_of_a_segment",
        [rep(SCRIPT_PY, "        return self._first[index] if tick == self._starts[index] else self._rest[index]\n", "        return self._first[index]\n")],
        TEST, {1}, "reason=failed",
    ),
    ("test_adapter_keeps_the_steer_axis_sign", [rep(PYXEL_INPUT_PY, STEER_AXIS_READ, STEER_AXIS_READ.replace("-btnv", "btnv"))], TEST, {1}, "reason=failed"),
    ("test_adapter_reads_the_axis_with_btn", [rep(PYXEL_INPUT_PY, STEER_AXIS_READ, STEER_AXIS_READ.replace("-btnv", "-btn"))], TEST, {1}, "reason=failed"),
    (
        "test_direct_read_looks_past_a_pad_that_is_not_standard",
        [rep(WEB_INPUT_PY, "        if pad.mapping != STANDARD_MAPPING:\n            return None\n", "        if pad.mapping != STANDARD_MAPPING:\n            continue\n")],
        TEST, {1}, "reason=failed",
    ),
    ("test_trace_keeps_every_tick", [rep(TRACE_PY, "        if self.truncated or values == self._last:\n", "        if self.truncated:\n")], TEST, {1}, "reason=failed"),
    # 仮の表示へ、何も押していない入力フレームを渡す。世界へは正しい入力フレームが届くので、道具は全部通る。守りのテストで拾う。
    ("test_app_draws_a_neutral_frame_on_the_placeholder", [rep(APP_PY, DRAW_FRAME, DRAW_FRAME.replace("self.frame)", "NEUTRAL)"))], TEST, {1}, "reason=failed"),
    # --- 入力の土台：run（速い経路。台本を渡して回す） ---
    # アプリが、入力フレームの代わりに、何も押していない入力フレームを世界へ渡す。
    ("run_world_gets_neutral_instead_of_the_frame", [rep(APP_PY, IN_UPDATE, "        self.sim.step(NEUTRAL)\n")], RUN, {1}, "failed=sim not_yet="),
    # 台本を1 tickずらして読む。
    ("run_script_read_one_tick_off", [rep(APP_PY, FROM_SCRIPT, FROM_SCRIPT.replace("self.sim.tick", "self.sim.tick + 1"))], RUN, {1}, "failed=sim not_yet="),
    # 台本があるのに、入力アダプタから読む。
    ("run_script_is_ignored", [rep(APP_PY, "        if self.script is not None:\n", "        if False:\n")], RUN, {1}, "failed=input_source,adapter_reads,direct_reads,sim"),
    # 台本のときも、直読みを呼ぶ。値は変わらないので、呼んだ回数でしか見えない。
    ("run_direct_read_called_with_a_script", [rep(APP_PY, FROM_SCRIPT, "            " + DIRECT_READ + FROM_SCRIPT)], RUN, {1}, "failed=direct_reads not_yet="),
    ("run_ticks_shorter_than_the_script", [], tool("run", "--ticks", "60"), {2}, "reason=ticks_shorter_than_script"),
    ("run_script_file_is_not_a_script", [], tool("run", "--script", BUDGETS_JSON), {2}, "reason=script_unreadable"),
    ("run_script_file_is_missing", [], tool("run", "--script", "tools/no_such_script.json"), {2}, "reason=script_unreadable"),
    # 道具が、台本を相対パスで渡す。アプリは、起動時に例外にする（pyxel.init が作業ディレクトリを変えるため）。
    ("run_script_path_is_relative", [RELATIVE_SCRIPT], RUN, {1}, "reason=app_exit_code"),
    # 上の件の対。同じ相対パスのまま、アプリの絶対パスの検査を外すと、最後まで回って通る。
    # 上の件が落ちる理由が、ファイルが見つからないことではなく、検査であることの確かめ（壊さない件と同じく、0で通ること）。
    (
        "control_run_relative_script_path_passes_without_the_check",
        [RELATIVE_SCRIPT, rep(APP_PY, ABS_SCRIPT_CHECK, "        if False:\n")],
        RUN, {0}, "run: OK driver=flip input=script",
    ),
    # --- 入力の土台：run --realtime（台本を渡さず、入力アダプタを実物のPyxelで毎tick呼ぶ） ---
    ("run_realtime_adapter_read_twice_per_tick", [rep(APP_PY, FROM_ADAPTER, "        self.adapter.read(self.js is not None, None)\n" + FROM_ADAPTER)], RUN_RT, {1}, "failed=adapter_reads not_yet="),
    # 直読みを、1 tickに2度呼ぶ。デスクトップ版では値を返さないが、呼んだ回数は数える。
    ("run_realtime_direct_read_twice_per_tick", [rep(APP_PY, FROM_ADAPTER, "        " + DIRECT_READ + FROM_ADAPTER)], RUN_RT, {1}, "failed=direct_reads not_yet="),
    # 軸のキーを btn で読む。実物のPyxelの中で落ちる。
    ("run_realtime_axis_key_read_with_btn", [rep(PYXEL_INPUT_PY, STEER_AXIS_READ, STEER_AXIS_READ.replace("-btnv", "-btn"))], RUN_RT, {1}, "reason=app_exit_code"),
    # ボタンのキーを btnv で読む（舵の軸の名を、十字キーの名に取り違える）。これも、実物のPyxelの中で落ちる。
    ("run_realtime_button_key_read_with_btnv", [rep(PYXEL_INPUT_PY, 'STEER_AXIS = "GAMEPAD1_AXIS_LEFTX"', 'STEER_AXIS = "GAMEPAD1_BUTTON_DPAD_LEFT"')], RUN_RT, {1}, "reason=app_exit_code"),
    # 割り当ての表に、Pyxelに無い定数の名前がある。起動時に落ちる（押されるまで分からない形にしない）。
    ("run_realtime_unknown_pyxel_constant", [rep(PYXEL_INPUT_PY, '"shift_up": ("KEY_S", ', '"shift_up": ("KEY_NO_SUCH", ')], RUN_RT, {1}, "reason=app_exit_code"),
    # --- 入力の土台：web-smoke（回り切れない。2。何も開かない） ---
    ("web_pad_stage_has_no_tick_to_judge", [rep(BUDGETS_JSON, '"web_pad_settle_ticks": 10', '"web_pad_settle_ticks": 30')], WEB_PAD, {2}, "reason=pad_stage_too_short"),
    ("web_script_ticks_shorter_than_the_script", [rep(BUDGETS_JSON, '"web_script_ticks": 120', '"web_script_ticks": 40')], WEB_SCRIPT, {2}, "reason=ticks_shorter_than_script"),
    ("web_script_file_is_not_a_script", [rep(SMOKE_SCRIPT_JSON, '"segments"', '"parts"')], WEB_SCRIPT, {2}, "reason=script_unreadable"),
    # 偽のコントローラーのスクリプトが無い。例外で終わらせず（終了コード1）、回り切れない（2）にする。
    ("web_fake_gamepad_script_is_missing", [rm("tools/web/fake_gamepad.js")], WEB_PAD, {2}, "reason=no_fake_gamepad"),
    # --- 入力の土台：web-smoke の筋書き script（台本を渡して開く）。どれも、デスクトップ版の道具（run）は通る ---
    # ブラウザ版でだけ、台本を読まずに入力アダプタから読む。
    (
        "web_script_ignored_only_in_browser",
        [rep(APP_PY, "        if self.script is not None:\n", "        if self.script is not None and sys.platform != 'emscripten':\n")],
        WEB_SCRIPT, {1}, "failed=script.input_source",
    ),
    # 入力の跡が打ち切られる（件数の上限が小さい）。合格にしない。
    ("web_script_trace_is_truncated", [rep(BUDGETS_JSON, '"web_input_trace_max": 400', '"web_input_trace_max": 5')], WEB_SCRIPT, {1}, "failed=script.trace_complete"),
    # アナログ値の整数を受けない。台本の 1.0 と -1.0 は、JavaScriptを通ると整数で届くので、ブラウザ版でだけ落ちる。
    ("web_script_whole_analog_values_are_rejected", [rep(FRAME_PY, INT_TO_FLOAT, "")], WEB_SCRIPT, {1}, "failed=script.error_overlay"),
    # --- 入力の土台：web-smoke の筋書き gamepad（偽のコントローラーを差し込んで開く） ---
    ("web_pad_steer_axis_sign_is_kept", [rep(PYXEL_INPUT_PY, STEER_AXIS_READ, STEER_AXIS_READ.replace("-btnv", "btnv"))], WEB_PAD, {1}, "failed=gamepad.pad_stage_5"),
    ("web_pad_triggers_are_swapped", [rep(PYXEL_INPUT_PY, "            left, right = direct\n", "            right, left = direct\n")], WEB_PAD, {1}, "failed=gamepad.pad_stage_3,gamepad.pad_stage_4"),
    # 直読みができたtickに、Pyxel経由の2値のトリガーをデジタル値へ入れる。
    ("web_pad_pyxel_trigger_goes_digital_beside_a_direct_read", [rep(PYXEL_INPUT_PY, DIRECT_ANALOG, DIRECT_PLUS_DIGITAL)], WEB_PAD, {1}, "failed=gamepad.pad_stage_3,gamepad.pad_stage_4"),
    # 空のコントローラーの枠を見分けずに、属性を読む。例外は捕まえられて「未接続」と同じ値になるので、直読みの警告でしか落ちない。
    ("web_pad_empty_slot_is_not_told_apart", [rep(WEB_INPUT_PY, SKIP_EMPTY_SLOT, "")], WEB_PAD, {1}, "failed=gamepad.input_warn"),
    # tick の印を置かない。偽のコントローラーが、予定を進められない。
    ("web_pad_tick_mark_is_not_set", [rep(APP_PY, "            web_bridge.mark_tick(self.js, self.ticks)\n", "            pass\n")], WEB_PAD, {1}, "failed=gamepad.pad_plan"),
    # --- はみ出しの検査：screen-check（はみ出しがあれば1） ---
    ("screen_text_longer_than_its_box", [TEXT_TOO_LONG], SCREEN, {1}, "violations=2 not_checked=0 failed=placeholder/typical,placeholder/extreme kinds=out_of_box"),
    ("screen_text_off_screen", [TEXT_OFF_SCREEN], SCREEN, {1}, "failed=placeholder/typical,placeholder/extreme kinds=off_screen,out_of_box"),
    ("screen_text_not_ascii", [TEXT_NOT_ASCII], SCREEN, {1}, "violations=2 not_checked=0 failed=placeholder/typical,placeholder/extreme kinds=bad_char"),
    # 極端な値のときだけ、はみ出す。落ちるのは extreme だけ（ふつうの値だけを回す検査なら、通ってしまう）。
    ("screen_overflow_only_in_extreme_variant", [TEXT_TOO_LONG_WHEN_EXTREME], SCREEN, {1}, "violations=1 not_checked=0 failed=placeholder/extreme kinds=out_of_box"),
    # --- はみ出しの検査：screen-check（回り切れなければ2。合格にしない） ---
    ("screen_raises", [rep(SCREENS_PY, SCREEN_HEAD, "    raise RuntimeError('planted')\n" + SCREEN_HEAD)], SCREEN, {2}, "screens=0/2 violations=0 not_checked=2"),
    ("screen_draws_nothing", [rep(SCREENS_PY, SCREEN_HEAD, "    return\n" + SCREEN_HEAD)], SCREEN, {2}, "screens=0/2 violations=0 not_checked=2"),
    ("screen_only_unknown_name", [], tool("screen_check", "--only", "nosuch"), {2}, "reason=unknown_screen"),
    ("screen_no_variants", [NO_VARIANTS], SCREEN, {2}, "screens=0/0 violations=0 not_checked=0 reason=nothing_planned"),
    ("screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], SCREEN, {2}, "screens=2/4 violations=0 not_checked=2"),
    # --- 画面の登録と配線：test（突き合わせのテストと、アプリから画面への配線の守りのテスト） ---
    ("test_screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], TEST, {1}, "reason=failed"),
    ("test_logic_screen_without_registration", [rep(FLOW_PY, 'SCREEN_NAMES = ("placeholder",)', 'SCREEN_NAMES = ("placeholder", "title")')], TEST, {1}, "reason=failed"),
    # アプリが、画面の状態のいまの画面の名を見ずに、決まった画面を描く。いまは画面が1つなので、道具は全部通る。守りのテストで拾う。
    ("test_app_ignores_the_screen_of_the_flow", [rep(APP_PY, "SCREENS[self.flow.screen](canvas, view)", 'SCREENS["placeholder"](canvas, view)')], TEST, {1}, "reason=failed"),
    # はみ出しの検査が、囲みの外を数えない。
    ("test_overflow_check_ignores_the_boxes", [rep("clipping_point/cp_ui/check.py", "    if parent != SCREEN_BOX:\n", "    if False:\n")], TEST, {1}, "reason=failed"),
    # --- 巡回：tour（実物の画素と照らす。問題があれば1） ---
    # 文字の幅の計算を小さく間違える。screen_check は通る（control_screen_check_passes_with_text_metrics_too_small）。
    ("tour_text_metrics_too_small", [FONT_TOO_NARROW], TOUR, {1}, "shots=2/2 commands=16 problems=10 failed=ink_outside"),
    # 実行の側で、縁だけの矩形を、命令より2ピクセル広く描く。
    ("tour_outline_drawn_wider_than_its_command", [rep(EXECUTE_PY, EXEC_RECTB, EXEC_RECTB.replace("command.w,", "command.w + 2,"))], TOUR, {1}, "shots=2/2 commands=16 problems=2 failed=ink_outside"),
    # 実行の側で、文字の命令を描かない。全体の絵は空にならないので、命令ごとに照らさないと見えない。
    ("tour_text_commands_not_drawn", [rep(EXECUTE_PY, EXEC_TEXT, "            pass\n")], TOUR, {1}, "shots=2/2 commands=16 problems=10 failed=no_ink"),
    # 実行の側で、線を、命令より1ピクセル下に描く。
    (
        "tour_line_drawn_at_another_place",
        [rep(EXECUTE_PY, EXEC_LINE, EXEC_LINE.replace("command.y1 + oy,", "command.y1 + oy + 1,").replace("command.y2 + oy,", "command.y2 + oy + 1,"))],
        TOUR, {1}, "shots=2/2 commands=16 problems=4 failed=ink_outside,no_ink",
    ),
    # 画面が、余白へ描く（線が、画面の右へ4ピクセル出る）。はみ出しの検査も数える。
    ("tour_screen_draws_into_the_margin", [rep(SCREENS_PY, UNDER_BAR, UNDER_BAR.replace("SCREEN_W - 1", "SCREEN_W + 3"))], TOUR, {1}, "problems=4 failed=margin_ink,violation"),
    ("tour_overflow_only_in_extreme_variant", [TEXT_TOO_LONG_WHEN_EXTREME], TOUR, {1}, "shots=2/2 commands=16 problems=1 failed=violation"),
    # --- 巡回：tour（回り切れなければ2。合格にしない） ---
    ("tour_one_variant_skipped", [rep(TOUR_APP_PY, TOUR_VARIANTS, TOUR_VARIANTS.replace("VARIANTS:", "VARIANTS[1:]:"))], TOUR, {2}, "shots=1/2 commands=8 problems=0 incomplete=missing_shot"),
    (
        "tour_exception_midway",
        [rep(TOUR_APP_PY, TOUR_VARIANTS, TOUR_VARIANTS + "            if variant == 'extreme':\n                raise RuntimeError('planted')\n")],
        TOUR, {2}, "reason=app_exit_code",
    ),
    ("tour_only_unknown_name", [], tool("tour", "--only", "nosuch"), {2}, "reason=unknown_screen"),
    ("tour_no_variants", [NO_VARIANTS], TOUR, {2}, "shots=0/0 commands=0 problems=0 reason=nothing_planned"),
    ("tour_screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], TOUR, {2}, "reason=cannot_build"),
    # 巡回が、命令ごとの照合を飛ばす（1つ飛ばす。全部飛ばす）。照らした命令の数が、道具が組み立てた命令の数と合わない。
    ("tour_one_command_not_checked", [rep(TOUR_APP_PY, TOUR_COMMANDS, TOUR_COMMANDS.replace("(commands)", "(commands[1:])"))], TOUR, {2}, "shots=0/2 commands=0 problems=0 incomplete=commands_checked"),
    ("tour_no_command_checked", [rep(TOUR_APP_PY, TOUR_COMMANDS, TOUR_COMMANDS.replace("(commands)", "(commands[:0])"))], TOUR, {2}, "shots=0/2 commands=0 problems=0 incomplete=commands_checked"),
    # 巡回が、全体の絵でない絵を保存する（余白ごとの大きさ）。画像を保存しない。全体の絵を描かない（画面が空）。
    ("tour_saves_the_picture_with_its_margin", [rep(TOUR_APP_PY, TOUR_SAVE, "    whole.save(path, SHOT_SCALE)\n")], TOUR, {2}, "incomplete=image_size"),
    ("tour_saves_no_picture", [rep(TOUR_APP_PY, TOUR_SAVE, "    pass\n")], TOUR, {2}, "incomplete=no_image"),
    ("tour_whole_picture_is_blank", [rep(TOUR_APP_PY, TOUR_DRAW_WHOLE, "    len(commands)\n")], TOUR, {2}, "incomplete=blank_screen"),
    # アプリが、何も回さずに終了コード0で終わる。前回の合格の形の結果ファイルと画像が残っていても、読まない。
    (
        "tour_stale_result_is_not_reused",
        [
            add("out/tour/result.json", STALE_TOUR_RESULT),
            add_bytes("out/tour/placeholder_typical.png", STALE_TOUR_PNG),
            add_bytes("out/tour/placeholder_extreme.png", STALE_TOUR_PNG),
            rep(TOUR_APP_PY, TOUR_READY, TOUR_READY + "    pyxel.quit()\n"),
        ],
        TOUR, {2}, "reason=no_result_file",
    ),
    # 道具が、結果ファイルを相対パスで渡す。アプリは、起動時に例外にする（pyxel.init が作業ディレクトリを変えるため）。
    ("tour_result_path_is_relative", [TOUR_RELATIVE_RESULT], TOUR, {2}, "reason=app_exit_code"),
    # 上の件の対。同じ相対パスのまま、アプリの絶対パスの検査を外すと、アプリは終了コード0で終わるが、結果ファイルが
    # 道具の見る所に無い。上の件が落ちる理由が、検査であることの確かめ（落ち方が変わること）。
    (
        "tour_relative_result_path_gets_lost_without_the_check",
        [TOUR_RELATIVE_RESULT, rep(TOUR_APP_PY, "    if not os.path.isabs(result_path):\n", "    if False:\n")],
        TOUR, {2}, "reason=no_result_file",
    ),
    # 画面なしで回す口と、巡回の口を、同時に開く。アプリは、起動時に例外にする。
    ("tour_both_app_switches_at_once", [TOUR_BOTH_SWITCHES], TOUR, {2}, "reason=app_exit_code"),
    # 上の件の対。同じ環境変数のまま、アプリの検査を外すと、巡回して通る（壊さない件と同じく、0で通ること）。
    (
        "control_tour_both_app_switches_pass_without_the_check",
        [TOUR_BOTH_SWITCHES, rep(TOUR_APP_PY, '    if env.get("CP_SMOKE", ""):\n', "    if False:\n")],
        TOUR, {0}, "tour: OK shots=2/2 commands=16 problems=0",
    ),
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
        elif kind == "write_bytes":
            if target.exists():
                raise RuntimeError(f"{path}: 置くはずのファイルが既にある")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(rest[0])
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
