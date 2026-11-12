"""道具と検査をわざと壊して、落ちることを確かめる。

  python3 tools/selftest_break.py [--only 名前の頭] [--jobs N]

件ごとに、要るファイルだけを out/selftest/ の下へ一時に複製し、複製の上で1か所壊し、
複製の中の道具を1本回して、終了コードと最後の1行の語を期待と比べる。作業ツリーは書き換えない。
時間に頼らない件（test、check、画面なしの run、tour、export など）は、同時に N 件ずつ回す（既定は tools/budgets.json の selftest_jobs）。
時間に頼る件（ブラウザ版の煙テスト、本番と同じ経路の run、全体の検証。is_timed()）は、その後に、1件ずつ回す
（並列に回すと、毎秒の回数や、処理時間の線が揺れる）。件は、どれも自分の複製の中だけを書くので、同時に回しても、取り合わない。
壊したのに落ちない件（終了コードが違う、落ちた理由が違う）が1つでもあれば1。
壊さない件（control）は0で通ること。何でも落とす道具になっていないことの確かめ。
終了コード：0＝全件が期待どおり、1＝期待と違う件がある、2＝壊す所が見つからず回せない件がある・件が0。
道具か検査の決まりに触れた区切りと、段の仕上げで回す。新しい検査を足したら、ここに壊す件を足す。
"""
import argparse
import base64
import json
import shutil
import struct
import sys
import tempfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import data_reference
import fingerprint
import input_reference
import screen_check
from _common import FAIL, INCOMPLETE, OK, OUT, ROOT, child_env, finish, load_budgets, run

from cp_core import profile, storage  # noqa: E402 - cp_core への道は、input_reference が足す

PY = sys.executable
SCRATCH = OUT / "selftest"
# 複製するもの。道具、テスト、見張りが読むファイルの全部。足りなければ control の件が落ちる。
# testpacks（試験用データ）が無いと、複製の中で、規則ファイルの当て先（testpacks/**）が空振りし、run --pack が2になる。
COPY_ITEMS = ("clipping_point", "tools", "tests", "testpacks", ".claude/rules", ".claude/agents", ".claude/settings.json","docs/canon", "docs/handoff.md", "CLAUDE.md", "pytest.ini")
CASE_TIMEOUT_S = 180  # 1件の時間切れ（秒）。いちばん長い件（verify --all。ブラウザ版の煙テストの5本を含む）で約95秒

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
STORAGE_PY = "clipping_point/cp_core/storage.py"
PROFILE_PY = "clipping_point/cp_core/profile.py"
RNG_PY = "clipping_point/cp_core/rng.py"
FILE_STORAGE_PY = "clipping_point/cp_app/storage_file.py"
WEB_STORAGE_PY = "clipping_point/cp_app/storage_web.py"
SELECT_PY = "clipping_point/cp_app/storage_select.py"
RUN_TOOL_PY = "tools/run.py"
FINGERPRINT_JSON = fingerprint.FINGERPRINT_SNAPSHOT  # 指紋の写し
SCHEMA_JSON = fingerprint.SCHEMA_SNAPSHOT  # 保存する項目の一覧の写し
SKIP_ALL_HOOK = (
    "\n\ndef pytest_collection_modifyitems(items):\n    import pytest\n\n"
    "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='planted'))\n"
)
# 前回の実行が残した、合格の形の結果ファイル。道具が古い結果を読んで合格にしないことの確かめに置く。
STALE_JUNIT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites>'
    '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="999"></testsuite></testsuites>\n'
)
# いまの結果の形に合わせる（入力の出どころ、入力アダプタと直読みを呼んだ回数、種と乱数の流れの状態つきの世界の要約、保存の往復、
# 定義データ）。読まれたら合格になる形。保存の往復が残したファイル（STALE_SAVE）も、一緒に置く。
STALE_FIELDS = {
    "ticks": 120, "renders": 60, "sim": input_reference.sim_summary(input_reference.load_script(input_reference.SMOKE_SCRIPT)[1], 120),
    "back_ink": 4321, "screen_diff": 0, "driver": "flip", "input_source": "script", "adapter_reads": 0, "direct_reads": 0,
    "storage": {"backend": "file", "ok": True, "notice": "", "detail": ""},
}
# 定義データの件数は、道具が自分で数えた値（いまの定義データで、読まれたら合格になる値）。
STALE_DATA = {"tables": data_reference.expected_tables()[0], "warnings": 0, "pack": None, "namespace": "main"}
STALE_RESULT = json.dumps({**STALE_FIELDS, "data": STALE_DATA}) + "\n"
# 試験用データ（extreme）を重ねて回した形の、前回の結果。
STALE_PACK_DATA = {"tables": data_reference.expected_tables("extreme")[0], "warnings": 0, "pack": "extreme", "namespace": "pack_extreme"}
STALE_PACK_RESULT = json.dumps({**STALE_FIELDS, "data": STALE_PACK_DATA}) + "\n"
# 前回の実行が残した、保存の往復の値（封筒つき）。置き場は、run が out/run/saves、ブラウザ版が localStorage。
STALE_SAVE = storage.wrap(profile.encode(profile.SELFCHECK_SETTINGS), profile.SETTINGS_VERSION)
STALE_SAVE_FILE = "out/run/saves/selfcheck.settings.sav"
EXIT_0_TEST = "import os\n\n\ndef test_zz_exit():\n    os._exit(0)\n"
# 前回の実行が残した、合格の形の、ブラウザの実行役の結果（240 tickの probe。入力アダプタから、何も押していない入力を読んだ形）。
STALE_WEB_RESULT = {
    "ticks": 240, "renders": 120, "sim": input_reference.sim_summary(None, 240), "platform": "emscripten", "python": "3.14.2",
    "input_source": "adapter", "adapter_reads": 240, "direct_reads": 240, "warmup_ticks": 60,
    "perf": {"updates": 180, "renders": 90, "updates_per_s": 60.0, "renders_per_s": 30.0, "update_ms_p95": 0.1, "render_ms_p95": 0.2},
    "storage": {"backend": "localstorage", "ok": True, "notice": "", "detail": ""},
    "data": STALE_DATA,
}
STALE_WEB_PAGE = json.dumps({
    "htmlSha256": "", "failures": [], "clickedAt": 3500, "untilAt": 7000, "state": {"initialized": True}, "canvas": {"ink": 35000},
    "console": [
        {"t": 7000, "type": "log", "text": "CP_PROBE_RESULT " + json.dumps(STALE_WEB_RESULT)},
        {"t": 7000, "type": "log", "text": "CP_PROBE_DONE"},
    ],
    "localStorage": {
        "prefix": "clippingpoint/", "error": None,
        "entries": {"clippingpoint/selfcheck.settings": base64.b64encode(STALE_SAVE).decode("ascii")},
    },
}) + "\n"


def snapshot_with_another_environment() -> str:
    """指紋の写しの、環境の値（Pythonの版と、数学関数の試し値の1つ）だけを変えたもの。写しが読めなければ、空の文字列。

    変える試し値は cos。指紋のテストが、自分で置き換える試し値（sin）とは別の関数にする。同じ関数だと、テストが、
    指紋の写しの環境の値に頼っていても（指紋の写しといまの環境で、ほかの試し値が違うと落ちる形でも）、壊さない件では見えない。
    """
    try:
        data = json.loads((ROOT / FINGERPRINT_JSON).read_text(encoding="utf-8"))
        data["environment"]["python"] = "0.0.0"
        data["environment"]["math"]["cos"] = "0" * 16
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


OTHER_ENVIRONMENT_SNAPSHOT = snapshot_with_another_environment()


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


def rm_tree(path):
    """ディレクトリを、中身ごと消す（ディレクトリであること）。"""
    return ("delete_tree", path)


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
# 仮の表示の、表示用の値へ、入力フレームと、知らせと、車の値を入れる所。
DRAW_FRAME = "        view = PlaceholderView(self.sim.tick, self.renders, self.frame, self.notice, car_view(self.sim))\n"
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
TOUR_CLEAR_WHOLE = "    whole.cls(COL_BACK)\n"  # 巡回が、全体の絵を、描く前に消す所
TOUR_BUILD = "fixtures.build(screen, variant)"  # 巡回が、見本データを作る所
TOUR_WRITE_RESULT = "        json.dump(result, f, indent=1, sort_keys=True)\n"  # 巡回が、結果ファイルの中身を書く所
RENDER_TEXT_AT = 'canvas.text(4, 28, f"RENDER {view.renders}", COL_TEXT)'  # 仮の表示の、実描画の回数の文字を置く所
BAR_RECT = "canvas.rect(0, 0, SCREEN_W, 12, COL_BAR)"  # 仮の表示の、タイトルの帯
STATUS_BOX = '    with canvas.box("status", 2, 18, 64, 18):\n'  # 仮の表示の、状態の2行の囲み
SCREEN_DEF = "def build_placeholder(canvas: Canvas, view: PlaceholderView) -> None:\n"
# 画面の組み立てのモジュールに、構文の誤りを入れる（行末の「:」を落とす）。道具は、画面の登録を読み込めない。
SCREENS_SYNTAX_ERROR = rep(SCREENS_PY, SCREEN_DEF, SCREEN_DEF.replace(" -> None:\n", " -> None\n"))
# 保存と決定性の土台。
FINGERPRINT = tool("fingerprint")
# 指紋のテストだけに絞る。絞らないと、定数を数字で固定している入力フレームのテストが先に落ちて、指紋のテストが効いているかを見られない。
TEST_FINGERPRINT = tool("test", "-k", "fingerprint")
# この道具（tools/selftest_break.py）の、件の回し方のテストだけを回す。壊す所は、時間に頼る件の判定と、件の分け方。
SELFTEST_PY = "tools/selftest_break.py"
TEST_SELFTEST_TOOL = tool("test", "-k", "selftest_tool")
SELFTEST_IS_TIMED = '    return "web_smoke.py" in words or "verify.py" in words or "--realtime" in words\n'
SELFTEST_SPLIT = "    return [case for case in cases if not is_timed(case[2])], [case for case in cases if is_timed(case[2])]\n"
# ハッシュの種を変えた別プロセスどうしを比べるテストだけに絞る（指紋の写しと比べるテストを入れない。集合の順に頼ったことだけで落ちる形にする）。
TEST_HASH_SEED = tool("test", "-k", "fingerprint and hash_seed")
# 保存する項目の一覧の写しのテスト1件だけに絞る。絞らないと、設定の項目と既定値を、数字と文字で固定しているテストが先に落ちて、
# 一覧の写しのテストが効いているかを見られない。
TEST_SCHEMA_SNAPSHOT = tool("test", "-k", "saved_item_list_matches_the_snapshot")
# 退避の途中で、容量超過でない失敗が出る道のテストだけに絞る（ほかのテストは、読み込みが捕まえる型を狭めても通る）。
TEST_SET_ASIDE_MIDWAY = tool("test", "-k", "set_aside_fails_midway")
WEB_BLOCKED = tool("web_smoke", "--only", "storage_blocked")
CHECKSUM_CHECK = "    if zlib.crc32(blob[:ENVELOPE.size + length]) != checksum:\n"  # 封筒のチェックサムを見る所
NEWER_GUARD = "            if existing_version is not None and existing_version > version:\n"  # put の、新しい形式バージョンを上書きしない守り
FILE_WRITE = "                f.write(data)  # 全部を、1度に書く\n"  # ファイルの保存先が、一時ファイルへ書く所
TO_PLAIN = "    return {name: getattr(settings, name) for name in saved_names(Settings)}\n"  # 設定を、保存の本体の辞書にする所
LAST_SETTING = "    race_serial: int = 0  # レースの通し番号。0以上\n"  # 設定の、最後の項目
LOAD_NEWER = "        return Loaded(Settings(), NOTICE_NEWER_VERSION, False)\n"  # 読み込みが、新しい形式バージョンを、触れずに返す所
LOAD_UNREADABLE = "    except StorageError:\n        return Loaded(Settings(), NOTICE_BACKEND_UNREADABLE, False)\n"  # 読み込みが、保存先の例外を捕まえる所
SELFCHECK_STORE = "        store = SaveStore(backend, SELFCHECK_NAMESPACE)\n"  # 保存の往復の、名前空間
WEB_READ = "            return base64.b64decode(value, validate=True)\n"  # localStorage の保存先が、読んだ値を開ける所
WEB_NOT_BASE64 = '            return value.encode("utf-8", "surrogatepass")\n'  # base64 として読めない値を、バイト列で返す所
PROBE_TOUCH = (  # 試し書きが、localStorage に触れたときの例外を捕まえる所
    "        except Exception as exc:  # noqa: BLE001 - 触れると例外になる文書、localStorage が無いブラウザ\n"
    "            return PROBE_UNAVAILABLE, describe(exc)\n"
)
PROBE_CALL = "        state, _ = backend.probe()\n"  # 保存先を選ぶ所の、試し書き
FALLBACK = "            return Selected(MemoryBackend(), BACKEND_MEMORY, NOTICE_MEMORY_FALLBACK)\n"  # メモリへ切り替える所
SAVE_DIR_READ = '    directory = env.get(SAVE_DIR_ENV, "")\n'  # デスクトップ版が、保存のファイルの置き場を読む所
SELFCHECK_CALL = "profile.selfcheck(selected.backend) if run_config is not None or probe is not None else None"  # アプリが、保存の往復を回す所
SAVE_DIR_ENV_ARG = "**{storage_select.SAVE_DIR_ENV: save_dir})"  # 道具 run が、置き場を絶対パスで渡す所
HELD_BITS = "        button_bits(frame.held),\n"  # 入力の量子化の、押しているボタンのビット
# 押しているボタンを、ビットの和でなく、名の集合を回した順の番号の列（16進の桁）で返す。2個以上を押していると、回した順で値が変わる。
HELD_IN_SET_ORDER = "        sum(BUTTONS.index(name) * 16 ** place for place, name in enumerate(frame.held)),\n"
NO_NOTICE_IN_VIEW = rep(APP_PY, DRAW_FRAME, DRAW_FRAME.replace("self.notice,", '"",'))  # 知らせを、表示用の値へ渡さない
WORLD_FORMULA = rep(FRAME_PY, "DIGEST_PRIME = 16777619", "DIGEST_PRIME = 16777621")  # 世界の式を変える（入力の要約値の畳み込みの定数）
RNG_FORMULA = rep(RNG_PY, "GAMMA = 0x9E3779B97F4A7C15", "GAMMA = 0x9E3779B97F4A7C17")  # 乱数の式を変える（状態の増分）
FILE_DROPS_LAST_BYTE = rep(FILE_STORAGE_PY, FILE_WRITE, "                f.write(data[:-1])\n")
ROUND_TRIP_IN_MAIN = rep(PROFILE_PY, SELFCHECK_STORE, "        store = SaveStore(backend)\n")
NO_PROBE = rep(SELECT_PY, PROBE_CALL, '        state = "ok"\n')
SELFCHECK_PASSED = '    return True, ""\n'  # 保存の往復が、通ったと返す所
# 保存の往復の終わりに、既定値で書き直す。封筒は読めて、アプリの申告（往復が通った）も合っている。本体だけが、往復の見本と違う。
ROUND_TRIP_ENDS_WITH_DEFAULTS = rep(PROFILE_PY, SELFCHECK_PASSED, "    save_settings(store, Settings())\n" + SELFCHECK_PASSED)
PROFILE_IMPORT_END = "    StorageError,\n)\n"  # 保存する項目のモジュールが、保存の口から読み込む名の並びの、終わり
SET_ASIDE_CATCH = (  # 読み込みが、退避の失敗を捕まえる所
    "    except StorageError:\n        return Loaded(Settings(), NOTICE_UNREADABLE, False)  # 退避できない。元の鍵に触れない\n"
)
# 読み込みが、退避の失敗のうち、容量超過（StorageFull）だけを捕まえる（名を読み込ませてから、捕まえる型を狭める）。
SET_ASIDE_CATCHES_ONLY_FULL = [
    rep(PROFILE_PY, PROFILE_IMPORT_END, "    StorageError,\n    StorageFull,\n)\n"),
    rep(PROFILE_PY, SET_ASIDE_CATCH, SET_ASIDE_CATCH.replace("except StorageError:", "except StorageFull:")),
]
ROUND_TRIP_ON_EVERY_START = rep(APP_PY, SELFCHECK_CALL, "profile.selfcheck(selected.backend)")  # 検証の口でなくても、保存の往復を回す
PROBE_READ_AND_REMOVE = "            back = storage.getItem(name)\n            storage.removeItem(name)\n"  # 試し書きが、試しの鍵を読んで、消す所
PROBE_KEY_NOT_REMOVED = rep(WEB_STORAGE_PY, PROBE_READ_AND_REMOVE, "            back = storage.getItem(name)\n")  # 試しの鍵を、消さない
# 規則ファイルの末尾に足す、上限（tools/budgets.json の rule_file_max_bytes）より大きい埋め草。上限の数字を、ここに直に書かない。
RULE_FILLER_LINE = "- filler line\n"
RULE_FILLER = RULE_FILLER_LINE * (load_budgets()["rule_file_max_bytes"] // len(RULE_FILLER_LINE) + 1)
OTHER_ENVIRONMENT = [rm(FINGERPRINT_JSON), add(FINGERPRINT_JSON, OTHER_ENVIRONMENT_SNAPSHOT)]  # 指紋の写しの、環境の値だけを変える
# 定義データの読み込み検査と、試験用データ。
# check は、data の節だけに絞る。絞らないと、ファイルを足す件、消す件が、分野の見張り（areas）や規則ファイルの見張り（rules）でも
# 落ちて、読み込み検査で落ちたのかを見分けられない。期待の語の data=2 は、調べた組の数（出荷するデータと、試験用データ extreme）。
CHECK_DATA = tool("check", "--only", "data")
RUN_PACK = tool("run", "--pack", "extreme")  # 試験用データを重ねて回す
CARS_JSON = "clipping_point/data/cars.json"
LOOP_JSON = "clipping_point/data/tracks/test_loop.json"
PACK_DIR = "testpacks/extreme"
PACK_CARS_JSON = f"{PACK_DIR}/cars.json"
PACK_LOOP_JSON = f"{PACK_DIR}/tracks/wide_test_loop.json"
DATADEFS_PY = "clipping_point/cp_core/datadefs.py"
DATA_FILES_PY = "clipping_point/cp_app/data_files.py"
CHECK_TOOL_PY = "tools/check.py"
EXPORT_TOOL_PY = "tools/export.py"
COMMON_PY = "tools/_common.py"
CAR_NAME = '      "name": "KAZANE",\n'  # 実物の車の、表示名の行
CAR_NAME_VALUE = '"name": "KAZANE"'
CAR_VERSION = '"data_version": 1'  # 実物の車の、データの版
CAR_TABLE_END = "    }\n  ]"  # 実物の車の表の、並びの終わり
CAR_TABLE_HEAD = '  "cars": [\n'  # 実物の車の表の、並びの頭
NO_SUCH_TEXT = "\0 no such text \0"  # どのファイルにも無い文。壊し方を作れなかったときに、置けない壊し方にするために使う


def second_car_with_the_same_id() -> list:
    """実物の車の表に、実物の項目の複製（同じ id）を、2台目として足す。作れなければ、置けない壊し方。

    3つの鍵だけの項目を足す形にしない（足りない鍵の問題も並んで、id の重複だけの確かめにならない）。
    """
    try:
        text = (ROOT / CARS_JSON).read_text(encoding="utf-8")
    except OSError:
        return [rep(CARS_JSON, NO_SUCH_TEXT, "")]
    if text.count(CAR_TABLE_HEAD) != 1 or text.count(CAR_TABLE_END) != 1:
        return [rep(CARS_JSON, NO_SUCH_TEXT, "")]
    entry = text[text.index(CAR_TABLE_HEAD) + len(CAR_TABLE_HEAD):text.index(CAR_TABLE_END)] + "    }"  # 実物の項目の、頭の { から、終わりの } まで
    return [rep(CARS_JSON, CAR_TABLE_END, "    },\n" + entry + "\n  ]")]


DATA_UNKNOWN_KEY = rep(CARS_JSON, CAR_NAME, CAR_NAME + '      "nmae": "KAZANE",\n')  # 出荷するデータに、知らない鍵（鍵の名の打ち間違い）
DATA_CARS_DELETED = rm(CARS_JSON)
PACK_NAME_TOO_LONG = rep(PACK_CARS_JSON, '"name": "WWWWWWWWWWWWWW"', '"name": "WWWWWWWWWWWWWWW"')  # 試験用データの表示名を、15字にする


def loop_file_under_another_name() -> list:
    """実物のコースのファイルを、中身はそのままで、別の名に置き直す（ファイルの名と id が食い違う）。読めなければ、置けない壊し方。"""
    try:
        text = (ROOT / LOOP_JSON).read_text(encoding="utf-8")
    except OSError:
        return [rm(LOOP_JSON), rm(LOOP_JSON)]  # 2つ目で、壊す所が見つからずに止まる
    return [rm(LOOP_JSON), add("clipping_point/data/tracks/other_loop.json", text)]


LOAD_DATA = "    data = data_files.load(os.environ, js)\n"  # アプリが、起動時に定義データを読む所
# 定義データを読まずに、空の定義で起動する。世界が、車の id を引けないので、起動時に、例外で止まる。
NO_DATA_AT_START = LOAD_DATA.replace("data_files.load(os.environ, js)", "data_files.datadefs.GameData({name: {} for name in data_files.datadefs.TABLES}, (), None)")
# 読み込んだ定義に、ファイルに無い車を1台足す。世界は、決めた id の車とコースで動くので、起動して、最後まで回る。
# 表ごとの件数だけが、道具が、定義データのファイルを自分で読んで数えた件数と違う（件数の確かめだけが落ちる形）。
ENTRY_NOT_ON_DISK = '    data._entries["cars"]["zz_not_on_disk"] = {}\n'
READ_PACK_ENV = '        name = env.get(PACK_ENV, "")\n'  # デスクトップ版が、重ねる試験用データの名を読む所
SETTINGS_STORE = "        self.store = SaveStore(selected.backend, data.save_namespace)\n"  # アプリが、設定を読む保存の口を作る所
# 重ねたのに、設定を読む保存の口へ、名前空間を渡さない（main のままになる）。
NAMESPACE_NOT_PASSED = rep(APP_PY, SETTINGS_STORE, "        self.store = SaveStore(selected.backend)\n")
EXPORT_DATA_CHECK = "    problems += inspect_data(names, source_data_files(), data_reference.datadefs.TABLES)\n"  # 道具 export が、出荷物の中の定義データのファイルを調べる所
UNKNOWN_KEY_FOUND = '        found.append(((*path, key), "unknown key"))\n'  # 読み込み検査が、知らない鍵を問題にする所
RAISE_ALL = "        raise DataError(problems)\n"  # 読み込み検査が、全部の問題を並べて止まる所
RETURN_DATA = "    return GameData(entries, warnings, pack_name)\n"  # 読み込み検査が、警告を付けて返す所
SHIPPED_WARNINGS = '        problems += [f"({SHIPPED_SET}) warning: {line}" for line in shipped_warnings]\n'  # check の data の節が、出荷するデータの警告を問題に数える所
# check の data の節が、試験用データを重ねた組の警告を問題に数える所。
PACK_WARNINGS = '            problems += [f"({path.name}) warning: {line}" for line in overlaid.warnings if line not in shipped_warnings]\n'
# 項目の中の、注の鍵の値に NaN を置く。規則の部品は、注の鍵を見ない。拾えるのは、JSONの文を読む所で NaN を受けない検査だけ。
DATA_NAN_IN_A_NOTE = rep(CARS_JSON, CAR_NAME, CAR_NAME + '      "_trial": NaN,\n')
APP_ENV_LIST = 'APP_ENV_PREFIXES = ("CP_SMOKE", "CP_TOUR", "CP_SAVE", "CP_DATA")'  # 道具が、子プロセスへ渡さない環境変数の名の頭

# --- 車両モデル、コース、操作補正、車とコースの定義データ（段0 区切り9） ---
VEHICLE_PY = "clipping_point/cp_core/vehicle.py"
TRACK_PY = "clipping_point/cp_core/track.py"
CONTROLS_PY = "clipping_point/cp_core/controls.py"
ASSISTS_JSON = "clipping_point/data/assists.json"
TIRE_BRAKE_CLAMP = "            if fbrk > lim:\n                fbrk = lim\n"  # タイヤの制動力の、止める力の頭打ち
TIRE_SIDE_CLAMP = "        if fy > lim:\n            fy = lim\n"  # タイヤの横力の、止める力の頭打ち
STEER_CLAMP = "        steer = max_steer if steer_cmd > max_steer else -max_steer if steer_cmd < -max_steer else steer_cmd\n"  # 車両モデルが、舵角の指令を最大舵角で切る所
# 車両モデルが、舵の速さも制限する（毎秒1 rad。試作の形）。
STEER_RATE_LIMITED = STEER_CLAMP + "        steer = max(self.steer - DT, min(self.steer + DT, steer))\n"
ENGINE_BRAKE_BRANCH = "            if torque >= 0.0:\n"  # 車両モデルが、正味のトルクの符号で、駆動とエンジンブレーキを分ける所
WALL_NO_CONTACT = "        if side == 0:\n            return x, z, wvx, wvz, False, 0.0\n"  # 壁の押し戻しが、当たっていないときに、そのまま返す所
QUERY_FROM_HINT = "            found, i, t = self._locate(x, z, hint % n, QUERY_MAX_WALK)\n"  # 照会が、前回の区間から探す所
QUERY_REQUERY = "        if not found:\n            start = self.nearest_index(x, z)\n"  # 照会が、届かなかったときに、全部を探して取り直す所
ASK_REVERSE = "        shift = SHIFT_TO_REVERSE if state.brake_hold_ticks >= params.brake_hold_ticks else SHIFT_NONE\n"  # 操作補正が、後退へ入る指示を出す所
NEVER_ASK_REVERSE = "        shift = SHIFT_NONE\n"  # 後退へ入る指示を、出さない
REVERSE_PEDALS = "        return Command(steer, brake_in, throttle_in, shift)\n"  # 操作補正が、後退中に、ペダルを読み替える所
STEER_LIMIT_RESULT = "    return limit if limit < max_steer else max_steer\n"  # 操作補正が、車速に応じた最大舵角を返す所
CROSS_CHECK_CALL = "    if not found and item.has_id and definition.check is not None:\n"  # 読み込み検査が、項目をまたぐ検査を呼ぶ条件
CROSS_CHECK_CATCH = "        except Exception as exc:  # noqa: BLE001 - どの例外も、その項目の問題の行にする\n"  # 検査の関数の例外を、問題の行に直す所
CAR_GEARS = '"gears": [3.136, 1.888, 1.33, 1.0, 0.86]'  # 実物の車の、変速比
LOOP_POINT = '    {"x_m": 100.0, "z_m": 0.0},\n'  # 実物のコースの、1本目の直線の途中の制御点
LOOP_POINT_HEAD = '    {"x_m": '  # 実物のコースの、制御点の行の頭


def loop_lines() -> tuple:
    """実物のコースのファイルの行と、制御点の行の番号。読めないか、制御点が無ければ、(None, [])。"""
    try:
        lines = (ROOT / LOOP_JSON).read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError:
        return None, []
    return lines, [index for index, line in enumerate(lines) if line.startswith(LOOP_POINT_HEAD)]


def loop_with_only_the_first_points(keep: int) -> list:
    """実物のコースの制御点を、頭の keep 点だけにする（末尾から頭へ戻るすき間が、大きく空く）。作れなければ、置けない壊し方。"""
    lines, points = loop_lines()
    if len(points) <= keep:
        return [rep(LOOP_JSON, NO_SUCH_TEXT, "")]
    cut = "".join(lines[points[keep - 1]:points[-1] + 1])  # 残す最後の点の行から、最後の点の行まで
    return [rep(LOOP_JSON, cut, lines[points[keep - 1]].rstrip("\n").rstrip(",") + "\n")]


PACK_STEERING_GROUP = '      "steering": {\n        "max_steer_rad": 0.55\n      },\n'  # 試験用データの車の、入れ子の項目の1つ（2台とも持つ）


def pack_car_without_the_steering_group() -> list:
    """試験用データ（extreme）の、1台目の車（kazane の差し替え）から、入れ子の項目 steering を消す。作れなければ、置けない壊し方。"""
    try:
        text = (ROOT / PACK_CARS_JSON).read_text(encoding="utf-8")
    except OSError:
        return [rep(PACK_CARS_JSON, NO_SUCH_TEXT, "")]
    if text.count(PACK_STEERING_GROUP) != 2:
        return [rep(PACK_CARS_JSON, NO_SUCH_TEXT, "")]
    return [rm(PACK_CARS_JSON), add(PACK_CARS_JSON, text.replace(PACK_STEERING_GROUP, "", 1))]


def loop_with_every_point_at_the_same_place() -> list:
    """実物のコースの制御点を、全部、同じ点にする（鍵ごとの規則は通る。表を作る計算は、0で割る）。作れなければ、置けない壊し方。"""
    lines, points = loop_lines()
    if not points:
        return [rep(LOOP_JSON, NO_SUCH_TEXT, "")]
    for index in points:
        lines[index] = LOOP_POINT_HEAD + '5.0, "z_m": 5.0}' + ("," if lines[index].rstrip("\n").endswith(",") else "") + "\n"
    return [rm(LOOP_JSON), add(LOOP_JSON, "".join(lines))]


# --- 世界への組み込み、指紋の筋書き、走る台本と壁の台本（段0 区切り9） ---
FINGERPRINT_PY = "tools/fingerprint.py"
DRIVE_SCRIPT_JSON = "tools/input_script_drive.json"
WALL_SCRIPT_JSON = "tools/input_script_wall.json"
# 走る台本の回と、壁の台本の回（全体の検証の run-drive と run-wall と同じ形。tick数は、指紋の筋書きと同じ）。画面なしの速い経路。
RUN_DRIVE = tool("run", "--script", DRIVE_SCRIPT_JSON, "--ticks", "900")
RUN_WALL = tool("run", "--script", WALL_SCRIPT_JSON, "--ticks", "780")
RUN_PACK_DRIVE = tool("run", "--pack", "extreme", "--script", DRIVE_SCRIPT_JSON, "--ticks", "900")  # 試験用データを重ねて、走る台本を回す
# 走る台本を、アクセルを踏まない台本（900 tick、何も押さない）に替える。車は、スタート位置から動かない。
DRIVE_SCRIPT_DOES_NOT_DRIVE = [rm(DRIVE_SCRIPT_JSON), add(DRIVE_SCRIPT_JSON, '{\n  "segments": [\n    {"ticks": 900}\n  ]\n}\n')]
SIM_SURFACE_MU = "        self.mu = course.surface_mu(surface)  # 次のtickの、操作補正と車両モデルへ渡す\n"  # 世界が、路面の種類から、次のtickの摩擦係数を引く所
SIM_FIELD_X = '    ("x_mm", MM, COMPARE_NEAR),  # 位置\n'  # 要約の項目の表の、位置の x の行
SIM_QUANTIZE = "            summary[name] = round(values[name] * scale) if scale else values[name]\n"  # 世界が、要約の値を量子化する所
SIM_COMPARE_RULES = "    kinds = {name: kind for name, _, kind in SUMMARY_FIELDS}\n"  # 世界が、項目ごとの比べ方の表を作る所
SIM_WALL_HIT = "            if not self.on_wall:\n                self.wall_hits += 1  # 当たり始めだけを数える\n"  # 世界が、壁に当たった回数を数える所
SIM_ODOMETER = "        if 0.0 < moved <= ODOMETER_MAX_STEP_M:\n"  # 世界が、前へ進んだ分だけを、進行距離に足す所
SIM_QUERY_AFTER_PUSH = "            query = course.query(x, z, query.index)\n"  # 世界が、押し戻した後の位置で、照会し直す所
SIM_TICK = "        self.tick += 1\n"  # 世界が、tick を数える所（step の終わり）
# 世界が、標準の乱数を読む（毎tick、乱数を、照会を取り直した回数に足す）。同じ入力でも、回すたびに、要約が変わる。
SIM_READS_RANDOM = SIM_TICK + "        import random\n\n        self.requery_count += random.getrandbits(20)\n"
APP_TRACK_ID = 'TRACK_ID = "test_loop"\n'  # アプリの、コースの id の定数
CAR_MASS = '"mass_kg": 960.0'  # 実物の車の、質量（走りに効く値）
DRIVE_FLOOR_ODOMETER = '("odometer_mm", ">=", 230_000)'  # 走る台本の筋書きの、進行距離の下限
CAR_VIEW_GEAR_CHECK = '        if _whole("gear", self.gear) == 0:\n'  # 仮の表示の車の値が、ギアを検査する所
# ブラウザ版でだけ、台本の筋書きの、最後の更新で、世界を進めた直後に、世界の値を、外から動かす文の頭
# （回すtick数は tools/budgets.json の web_script_ticks。最後の更新の中では、回した更新の数は、まだ、それより1つ少ない）。
ONLY_ON_WEB_AT_THE_END = f"        if sys.platform == 'emscripten' and self.ticks == {load_budgets()['web_script_ticks'] - 1}:\n"

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
    ("control_web_smoke", [], WEB, {0}, "web_smoke: OK scenarios=5 shipped=ok probe=ok script=ok gamepad=ok storage_blocked=ok"),
    ("control_web_smoke_short_probe", [], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_web_heavy_frame_keeps_30_renders", [rep(APP_PY, RENDER_COUNT, RENDER_COUNT + HEAVY_FRAME)], WEB_PROBE, {0}, "web_smoke: OK scenarios=1 probe=ok"),
    ("control_verify_list", [], tool("verify", "--list"), {0}, "verify: OK mode=list"),
    ("control_verify_all", [], VERIFY_ALL, {0}, "verify: OK mode=all steps=12 ok=12 failed=0"),
    ("control_screen_check", [], SCREEN, {0}, "screen_check: OK screens=2/2 violations=0 not_checked=0"),
    ("control_screen_check_only_one_screen", [], tool("screen_check", "--only", "placeholder"), {0}, "screen_check: OK screens=2/2 violations=0 not_checked=0"),
    # 命令の数は、ふつうの値で10（車の値の2行を含む）、極端な値で11（知らせの1行）。
    ("control_tour", [], TOUR, {0}, "tour: OK shots=2/2 commands=21 problems=0"),
    ("control_tour_only_one_screen", [], tool("tour", "--only", "placeholder"), {0}, "tour: OK shots=2/2 commands=21 problems=0"),
    # 期待の語は `env=` で止める（下の、世界の式や設定の項目を変える件も同じ）。環境の値（Pythonの版、数学関数の試し値）が、
    # 指紋の写しと違うだけで、この道具を落とさない。env=same になることは、一時の置き場で取り直して照らすテスト（tests/test_fingerprint.py）が見る。
    # 筋書きは4本（道具の台本、台本なし、走る台本、壁の台本）。
    ("control_fingerprint", [], FINGERPRINT, {0}, "fingerprint: OK scenarios=4 fields=6 problems=0 env="),
    # 環境の値（Pythonの版、数学関数の試し値）だけが、指紋の写しと違っても、合否は変えない。最後の1行に出すだけ。
    ("control_fingerprint_passes_when_only_the_environment_changed", OTHER_ENVIRONMENT, FINGERPRINT, {0}, "fingerprint: OK scenarios=4 fields=6 problems=0 env=changed"),
    ("control_test_fingerprint_passes_when_only_the_environment_changed", OTHER_ENVIRONMENT, TEST_FINGERPRINT, {0}, "test: OK"),
    ("control_web_smoke_storage_blocked", [], WEB_BLOCKED, {0}, "web_smoke: OK scenarios=1 storage_blocked=ok blocked_save=memory"),
    # 指紋の筋書きに無い回し方（回すtick数が違う）。指紋の確かめを外して、通る。
    ("control_run_other_ticks_skips_the_fingerprint", [], tool("run", "--ticks", "200"), {0}, "problems=0 fingerprint=skipped not_yet="),
    # 定義データの読み込み検査だけを回す。調べた組は、出荷するデータと、試験用データ（extreme）を重ねたものの2つ。
    ("control_check_data", [], CHECK_DATA, {0}, "check: OK data=2 problems=0"),
    # 試験用データを重ねて回す。重ねた名と、保存の名前空間（pack_extreme）が結果に出る。指紋は照らさない（確かめは1つ少ない）。
    ("control_run_pack", [], RUN_PACK, {0}, "pack=extreme namespace=pack_extreme save=file checks=20 problems=0 fingerprint=skipped not_yet="),
    # 重ねずに回す。重ねた名は無く、保存の名前空間は main。
    ("control_run_reports_no_pack", [], RUN, {0}, "pack=none namespace=main save=file checks=21 problems=0 not_yet="),
    # 走る台本の回と、壁の台本の回（全体の検証の run-drive と run-wall）。指紋の写しと、筋書きの走行の下限を照らす（確かめは1つ多い）。
    ("control_run_drive", [], RUN_DRIVE, {0}, "pack=none namespace=main save=file checks=22 problems=0 not_yet="),
    ("control_run_wall", [], RUN_WALL, {0}, "pack=none namespace=main save=file checks=22 problems=0 not_yet="),
    # 試験用データを重ねて、走る台本を回す。指紋は照らさないが、筋書きが同じなので、走行の下限は見る。
    ("control_run_pack_drive_checks_the_floor", [], RUN_PACK_DRIVE, {0}, "pack=extreme namespace=pack_extreme save=file checks=21 problems=0 fingerprint=skipped not_yet="),
    # 指紋の写しを取り直しても、変わらない（いまの写しは、いまのコードの値）。期待の語に、変わったファイルの名を入れない
    # （環境の値が、写しを取ったときと違うと、fingerprint.json だけが変わる）。
    ("control_fingerprint_update", [], tool("fingerprint", "--update"), {0}, "fingerprint: OK updated=2 changed="),
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
    # 組み込みの open。import を1つも足さずに、ファイルに届く。呼ばれない関数の中に置いても、拾う。違反は、この1件だけ。
    ("check_core_uses_open", [app(SIM_PY, "\n\ndef read_text(path):\n    with open(path, encoding='utf-8') as f:\n        return f.read()\n")], CHECK, {1}, "problems=1 failed=arch"),
    ("check_no_pure_sources", [rm_glob("clipping_point/cp_core/*.py"), rm_glob("clipping_point/cp_ui/*.py")], CHECK, {2}, "empty=arch"),
    # --- check：規則ファイルの見張り ---
    ("check_rules_target_matches_nothing", [rep(UI_RULE, '"clipping_point/cp_ui/**"', '"clipping_point/cp_gui/**"')], CHECK, {1}, "failed=rules"),
    ("check_rules_target_hits_hub_file", [rep(UI_RULE, '"clipping_point/cp_app/canvas_pyxel.py"', '"clipping_point/cp_app/*.py"')], CHECK, {1}, "failed=rules"),
    ("check_rules_file_not_in_index", [drop_line("CLAUDE.md", "| `.claude/rules/ui.md` |")], CHECK, {1}, "failed=rules"),
    ("check_rules_new_file_not_in_index", [add(".claude/rules/extra.md", '---\npaths:\n  - "tools/check.py"\n---\n\n# extra\n')], CHECK, {1}, "failed=rules"),
    ("check_rules_index_row_without_file", [rm(UI_RULE)], CHECK, {1}, "failed=rules"),
    ("check_rules_file_without_paths", [rep(UI_RULE, "---\npaths:\n", "---\nnotes:\n")], CHECK, {1}, "failed=rules"),
    ("check_rules_file_too_big", [app(".claude/rules/tools.md", RULE_FILLER)], CHECK, {1}, "failed=rules"),
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
    (
        "run_stale_result_is_not_reused",
        [add("out/run/result.json", STALE_RESULT), add_bytes(STALE_SAVE_FILE, STALE_SAVE), rep(APP_PY, IN_UPDATE, QUIT_EARLY)],
        RUN, {2}, "reason=no_result_file",
    ),
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
        [rep("tests/test_sim.py", "    assert make().tick == 0\n", "    assert make().tick == 1\n")],
        VERIFY_ALL, {1}, "steps=12 ok=11 failed=1 failed_steps=test",
    ),
    # 道具 run のファイルを消す。run、run --realtime、run --pack、走る台本の回、壁の台本の回は、起動できない（回らなかった手順）。
    # 道具 run の関数のテスト（tests/test_run_tool.py）も、道具を読み込めずに落ちるので、test も落ちる。
    ("verify_step_cannot_run", [rm("tools/run.py")], VERIFY_ALL, {1}, "steps=12 ok=6 failed=6 failed_steps=test,run,run-realtime,run-pack,run-drive,run-wall"),
    # 全体の検証の中で、screen-check と tour が落ちる（文字を、画面の外に置く。突き合わせのテストも落ちる）。
    ("verify_screen_check_and_tour_fail", [TEXT_OFF_SCREEN], VERIFY_ALL, {1}, "steps=12 ok=9 failed=3 failed_steps=test,screen-check,tour"),
    # 全体の検証の中で、指紋の照合（fingerprint）が落ちる（世界の式を変える。指紋のテストと、run の指紋の確かめも落ちる）。
    # web-smoke は、ブラウザ版とデスクトップ版を比べるので、通る（どちらも、同じ変えた式で回る）。指紋の写しと比べる手順だけが落ちる
    # （走る台本の回と、壁の台本の回も、指紋の写しと比べる）。試験用データを重ねて回す手順（run-pack）は、指紋を照らさないので、通る。
    ("verify_fingerprint_step_fails", [WORLD_FORMULA], VERIFY_ALL, {1}, "steps=12 ok=6 failed=6 failed_steps=test,fingerprint,run,run-realtime,run-drive,run-wall"),
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
    ("test_app_draws_a_neutral_frame_on_the_placeholder", [rep(APP_PY, DRAW_FRAME, DRAW_FRAME.replace("self.frame,", "NEUTRAL,"))], TEST, {1}, "reason=failed"),
    # --- 入力の土台：run（速い経路。台本を渡して回す） ---
    # 世界の要約が違うと、参照との確かめ（sim）と、指紋の写しとの確かめ（fingerprint）の両方が落ちる。
    # アプリが、入力フレームの代わりに、何も押していない入力フレームを世界へ渡す。
    ("run_world_gets_neutral_instead_of_the_frame", [rep(APP_PY, IN_UPDATE, "        self.sim.step(NEUTRAL)\n")], RUN, {1}, "failed=sim,fingerprint not_yet="),
    # 台本を1 tickずらして読む。
    ("run_script_read_one_tick_off", [rep(APP_PY, FROM_SCRIPT, FROM_SCRIPT.replace("self.sim.tick", "self.sim.tick + 1"))], RUN, {1}, "failed=sim,fingerprint not_yet="),
    # 台本があるのに、入力アダプタから読む。
    ("run_script_is_ignored", [rep(APP_PY, "        if self.script is not None:\n", "        if False:\n")], RUN, {1}, "failed=input_source,adapter_reads,direct_reads,sim,fingerprint not_yet="),
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
    # 文字を2つ、同じ位置に置く（文字どうしの重なり）。
    ("screen_two_texts_at_the_same_place", [rep(SCREENS_PY, RENDER_TEXT_AT, RENDER_TEXT_AT.replace("(4, 28,", "(4, 20,"))], SCREEN, {1}, "violations=2 not_checked=0 failed=placeholder/typical,placeholder/extreme kinds=text_overlap"),
    # 矩形の幅を0にする（空の矩形）。
    ("screen_rectangle_without_width", [rep(SCREENS_PY, BAR_RECT, BAR_RECT.replace("SCREEN_W, 12", "0, 12"))], SCREEN, {1}, "violations=2 not_checked=0 failed=placeholder/typical,placeholder/extreme kinds=empty"),
    # 囲みの1つから `with` を外す（開かれなかった囲み）。中の文字は囲みに入らないので、囲みの外へ出ても数えられなくなる。
    (
        "screen_box_declared_without_with",
        [rep(SCREENS_PY, STATUS_BOX, STATUS_BOX.replace("    with canvas.box(", "    canvas.box(").replace("):\n", ")\n    if True:\n"))],
        SCREEN, {1}, "violations=2 not_checked=0 failed=placeholder/typical,placeholder/extreme kinds=box_not_entered",
    ),
    # --- はみ出しの検査：screen-check（回り切れなければ2。合格にしない） ---
    ("screen_raises", [rep(SCREENS_PY, SCREEN_HEAD, "    raise RuntimeError('planted')\n" + SCREEN_HEAD)], SCREEN, {2}, "screens=0/2 violations=0 not_checked=2"),
    ("screen_draws_nothing", [rep(SCREENS_PY, SCREEN_HEAD, "    return\n" + SCREEN_HEAD)], SCREEN, {2}, "screens=0/2 violations=0 not_checked=2"),
    ("screen_only_unknown_name", [], tool("screen_check", "--only", "nosuch"), {2}, "reason=unknown_screen"),
    ("screen_no_variants", [NO_VARIANTS], SCREEN, {2}, "screens=0/0 violations=0 not_checked=0 reason=nothing_planned"),
    ("screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], SCREEN, {2}, "screens=2/4 violations=0 not_checked=2"),
    # 画面の組み立てのモジュールが、読み込めない（構文の誤り）。例外で終わらせず（終了コード1）、回り切れない（2）にする。
    ("screen_module_cannot_be_loaded", [SCREENS_SYNTAX_ERROR], SCREEN, {2}, "screens=0/0 violations=0 not_checked=0 reason=cannot_load"),
    # --- 画面の登録と配線：test（突き合わせのテストと、アプリから画面への配線の守りのテスト） ---
    ("test_screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], TEST, {1}, "reason=failed"),
    ("test_logic_screen_without_registration", [rep(FLOW_PY, 'SCREEN_NAMES = ("placeholder",)', 'SCREEN_NAMES = ("placeholder", "title")')], TEST, {1}, "reason=failed"),
    # アプリが、画面の状態のいまの画面の名を見ずに、決まった画面を描く。いまは画面が1つなので、道具は全部通る。守りのテストで拾う。
    ("test_app_ignores_the_screen_of_the_flow", [rep(APP_PY, "SCREENS[self.flow.screen](canvas, view)", 'SCREENS["placeholder"](canvas, view)')], TEST, {1}, "reason=failed"),
    # はみ出しの検査が、囲みの外を数えない。
    ("test_overflow_check_ignores_the_boxes", [rep("clipping_point/cp_ui/check.py", "    if parent != SCREEN_BOX:\n", "    if False:\n")], TEST, {1}, "reason=failed"),
    # はみ出しの検査が、開かれなかった囲みを数えない。
    ("test_overflow_check_ignores_boxes_that_were_not_entered", [rep("clipping_point/cp_ui/check.py", "        if index not in canvas.entered:\n", "        if False:\n")], TEST, {1}, "reason=failed"),
    # 分野「カメラと画面の状態」のテストの絞りが、突き合わせのテストに当たらない（絞りを flow だけに戻す）。
    ("test_flow_area_does_not_select_the_registry_tests", [rep("tools/verify.py", '"flow or fixtures or screens or fingerprint"', '"flow"')], TEST, {1}, "reason=failed"),
    # --- 巡回の口：test（保存する絵の中身。道具 tour は、画像の大きさまでしか見ない） ---
    # 全体の絵を、描く前に消さない。前の件の絵が残る。命令の数も、画面が空でないことも変わらないので、道具は通る。
    ("test_tour_whole_picture_is_not_cleared", [rep(TOUR_APP_PY, TOUR_CLEAR_WHOLE, "    pass\n")], TEST, {1}, "reason=failed"),
    # 見本データの変種を取り違える（どの変種でも、ふつうの値で描く）。極端な値の名の画像が、ふつうの値の絵になる。
    ("test_tour_draws_the_typical_values_for_every_variant", [rep(TOUR_APP_PY, TOUR_BUILD, 'fixtures.build(screen, "typical")')], TEST, {1}, "reason=failed"),
    # --- 巡回：tour（実物の画素と照らす。問題があれば1） ---
    # 文字の幅の計算を小さく間違える。screen_check は通る（control_screen_check_passes_with_text_metrics_too_small）。
    # 文字の命令は、ふつうの値で7つ、極端な値で8つ（知らせの1行）。合わせて15。
    ("tour_text_metrics_too_small", [FONT_TOO_NARROW], TOUR, {1}, "shots=2/2 commands=21 problems=15 failed=ink_outside"),
    # 実行の側で、縁だけの矩形を、命令より2ピクセル広く描く。
    ("tour_outline_drawn_wider_than_its_command", [rep(EXECUTE_PY, EXEC_RECTB, EXEC_RECTB.replace("command.w,", "command.w + 2,"))], TOUR, {1}, "shots=2/2 commands=21 problems=2 failed=ink_outside"),
    # 実行の側で、文字の命令を描かない。全体の絵は空にならないので、命令ごとに照らさないと見えない。
    ("tour_text_commands_not_drawn", [rep(EXECUTE_PY, EXEC_TEXT, "            pass\n")], TOUR, {1}, "shots=2/2 commands=21 problems=15 failed=no_ink"),
    # 実行の側で、線を、命令より1ピクセル下に描く。
    (
        "tour_line_drawn_at_another_place",
        [rep(EXECUTE_PY, EXEC_LINE, EXEC_LINE.replace("command.y1 + oy,", "command.y1 + oy + 1,").replace("command.y2 + oy,", "command.y2 + oy + 1,"))],
        TOUR, {1}, "shots=2/2 commands=21 problems=4 failed=ink_outside,no_ink",
    ),
    # 画面が、余白へ描く（線が、画面の右へ4ピクセル出る）。はみ出しの検査も数える。
    ("tour_screen_draws_into_the_margin", [rep(SCREENS_PY, UNDER_BAR, UNDER_BAR.replace("SCREEN_W - 1", "SCREEN_W + 3"))], TOUR, {1}, "problems=4 failed=margin_ink,violation"),
    ("tour_overflow_only_in_extreme_variant", [TEXT_TOO_LONG_WHEN_EXTREME], TOUR, {1}, "shots=2/2 commands=21 problems=1 failed=violation"),
    # --- 巡回：tour（回り切れなければ2。合格にしない） ---
    # ふつうの値を飛ばして、極端な値（命令は11）だけを回す。
    ("tour_one_variant_skipped", [rep(TOUR_APP_PY, TOUR_VARIANTS, TOUR_VARIANTS.replace("VARIANTS:", "VARIANTS[1:]:"))], TOUR, {2}, "shots=1/2 commands=11 problems=0 incomplete=missing_shot"),
    (
        "tour_exception_midway",
        [rep(TOUR_APP_PY, TOUR_VARIANTS, TOUR_VARIANTS + "            if variant == 'extreme':\n                raise RuntimeError('planted')\n")],
        TOUR, {2}, "reason=app_exit_code",
    ),
    ("tour_only_unknown_name", [], tool("tour", "--only", "nosuch"), {2}, "reason=unknown_screen"),
    ("tour_no_variants", [NO_VARIANTS], TOUR, {2}, "shots=0/0 commands=0 problems=0 reason=nothing_planned"),
    ("tour_screen_registered_without_fixtures", [SCREEN_WITHOUT_FIXTURES], TOUR, {2}, "reason=cannot_build"),
    # 画面の組み立てのモジュールが、読み込めない（構文の誤り）。アプリを回す前に、道具が止まる。
    ("tour_screen_module_cannot_be_loaded", [SCREENS_SYNTAX_ERROR], TOUR, {2}, "shots=0/0 commands=0 problems=0 reason=cannot_load"),
    # 巡回の口が、画面を回す前に止まる。時間切れ。
    ("tour_stall_hits_timeout", [rep(TOUR_APP_PY, TOUR_READY, TOUR_READY + "    time.sleep(3600)\n")], tool("tour", "--timeout", "4"), {2}, "reason=timeout timeout_s=4"),
    # 巡回の口が、結果ファイルに、JSONでない字を書く。
    ("tour_result_file_is_not_json", [rep(TOUR_APP_PY, TOUR_WRITE_RESULT, "        f.write('not json')\n")], TOUR, {2}, "reason=result_unreadable"),
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
        TOUR, {0}, "tour: OK shots=2/2 commands=21 problems=0",
    ),
    # --- 保存の口と保存する項目：test ---
    # 封筒のチェックサムを見ない。1ビットの違いを、壊れた値にしなくなる。
    ("test_envelope_checksum_is_not_checked", [rep(STORAGE_PY, CHECKSUM_CHECK, "    if False:\n")], TEST, {1}, "reason=failed"),
    # ファイルの保存先が、最後の1バイトを落として書く（run の側は run_file_backend_drops_the_last_byte）。
    ("test_file_backend_drops_the_last_byte", [FILE_DROPS_LAST_BYTE], TEST, {1}, "reason=failed"),
    # 設定の項目を1つ、保存の本体から落とす。
    ("test_settings_item_dropped_from_the_payload", [rep(PROFILE_PY, TO_PLAIN, TO_PLAIN.replace("(Settings)}", '(Settings) if name != "view"}'))], TEST, {1}, "reason=failed"),
    # 設定に項目を足して、保存する項目の一覧の写しを直さない。回すのは、一覧の写しのテスト1件だけ（道具の側は fingerprint_settings_item_added_without_the_snapshot）。
    ("test_settings_item_added_without_the_snapshot", [rep(PROFILE_PY, LAST_SETTING, LAST_SETTING + "    hud_visible: bool = True\n")], TEST_SCHEMA_SNAPSHOT, {1}, "reason=failed"),
    # 保存しない項目の一覧に、無い項目の名を足す。
    ("test_not_saved_list_names_an_item_that_does_not_exist", [rep(PROFILE_PY, "NOT_SAVED = {}\n", 'NOT_SAVED = {"Settings.no_such_item": "planted: an item that does not exist"}\n')], TEST, {1}, "reason=failed"),
    # 新しい形式バージョンの値を、読み込みが退避して、既定値で上書きする。
    ("test_load_sets_aside_a_newer_format_version", [rep(PROFILE_PY, LOAD_NEWER, "        return _set_aside(store)\n")], TEST, {1}, "reason=failed"),
    # 新しい形式バージョンの値がある鍵へ、put が上書きする（守りを外す）。
    ("test_put_overwrites_a_newer_format_version", [rep(STORAGE_PY, NEWER_GUARD, "            if False:\n")], TEST, {1}, "reason=failed"),
    # 読み込みが、保存先の例外を外へ出す。
    ("test_load_lets_a_backend_error_out", [rep(PROFILE_PY, LOAD_UNREADABLE, "    except StorageError:\n        raise\n")], TEST, {1}, "reason=failed"),
    # 読み込みが、退避の失敗のうち、容量超過（StorageFull）だけを捕まえる。退避の途中の、ほかの失敗（元の鍵の削除、退避のための読み直し）が
    # 外へ出て、起動のたびに止まる。回すのは、その道のテストだけ（ほかのテストは、捕まえる型を狭めても通る）。
    ("test_load_lets_a_set_aside_failure_that_is_not_full_out", SET_ASIDE_CATCHES_ONLY_FULL, TEST_SET_ASIDE_MIDWAY, {1}, "reason=failed"),
    # localStorage の保存先が、base64 として読めない値を例外にする。
    ("test_web_backend_raises_on_a_value_that_is_not_base64", [rep(WEB_STORAGE_PY, WEB_NOT_BASE64, "            raise\n")], TEST, {1}, "reason=failed"),
    # 知らせを、表示用の値へ渡さない。ふつうの起動では知らせが無いので、run も、web-smoke の probe も通る。守りのテストで拾う
    # （ブラウザ版で実際に落ちることは web_blocked_notice_is_not_passed_to_the_view）。
    ("test_notice_is_not_passed_to_the_view", [NO_NOTICE_IN_VIEW], TEST, {1}, "reason=failed"),
    # 保存する項目の一覧の写しを消す。黙って作り直さない。
    ("test_schema_snapshot_deleted", [rm(SCHEMA_JSON)], TEST, {1}, "reason=failed"),
    # 乱数の式を変える。
    ("test_rng_formula_changed", [RNG_FORMULA], tool("test", "-k", "rng"), {1}, "reason=failed"),
    # --- 指紋：test（指紋のテストだけに絞る）、fingerprint、run ---
    # 世界の式を変える（入力の要約値の畳み込みの定数）。参照（いまのコードで計算し直す値）との確かめは通り、指紋の写しとの確かめだけが落ちる。
    ("test_world_formula_changed", [WORLD_FORMULA], TEST_FINGERPRINT, {1}, "reason=failed"),
    # 問題は、筋書きごとに1件（入力の要約値）。筋書きは4本。
    ("fingerprint_world_formula_changed", [WORLD_FORMULA], FINGERPRINT, {1}, "scenarios=4 fields=6 problems=4 failed=world env="),
    ("run_world_formula_changed", [WORLD_FORMULA], RUN, {1}, "failed=fingerprint not_yet="),
    ("run_realtime_world_formula_changed", [WORLD_FORMULA], RUN_RT, {1}, "failed=fingerprint not_yet="),
    # 乱数の式を変える。流れの状態（要約の rng_ai）が変わる。
    ("fingerprint_rng_formula_changed", [RNG_FORMULA], FINGERPRINT, {1}, "problems=4 failed=world env="),
    # 世界の式を変え、指紋の写しの環境の値も違う。環境が変わったことを、最後の1行に出す（退行とは限らない）。
    ("fingerprint_world_and_environment_changed", [WORLD_FORMULA, *OTHER_ENVIRONMENT], FINGERPRINT, {1}, "problems=4 failed=world env=changed"),
    # 設定に項目を足して、保存する項目の一覧の写しを直さない。
    ("fingerprint_settings_item_added_without_the_snapshot", [rep(PROFILE_PY, LAST_SETTING, LAST_SETTING + "    hud_visible: bool = True\n")], FINGERPRINT, {1}, "problems=1 failed=schema env="),
    # 指紋の写しを消す。黙って作り直さない。
    ("test_fingerprint_snapshot_deleted", [rm(FINGERPRINT_JSON)], TEST, {1}, "reason=failed"),
    ("fingerprint_snapshot_deleted", [rm(FINGERPRINT_JSON)], FINGERPRINT, {2}, "reason=no_snapshot missing=fingerprint.json"),
    ("run_fingerprint_snapshot_deleted", [rm(FINGERPRINT_JSON)], RUN, {2}, "reason=no_fingerprint_snapshot"),
    ("fingerprint_schema_snapshot_deleted", [rm(SCHEMA_JSON)], FINGERPRINT, {2}, "reason=no_snapshot missing=profile_schema.json"),
    # 指紋の写しが、JSONとして読めない。
    ("fingerprint_snapshot_is_not_json", [first_char(FINGERPRINT_JSON)], FINGERPRINT, {2}, "reason=no_snapshot missing=fingerprint.json"),
    # 筋書きの台本が読めない。何も照らしていないので、合格にしない。
    ("fingerprint_script_file_is_not_a_script", [rep(SMOKE_SCRIPT_JSON, '"segments"', '"parts"')], FINGERPRINT, {2}, "reason=script_unreadable"),
    # 世界の要約が、文字列の集合を回した順に頼る（入力の量子化が、押しているボタンを、名の集合を回した順の番号の列で返す）。
    # 回すのは、ハッシュの種を変えた別プロセスどうしを比べるテストだけ。層の分離の検査（check）は、これを拾えない。
    ("test_summary_depends_on_the_order_of_a_set", [rep(FRAME_PY, HELD_BITS, HELD_IN_SET_ORDER)], TEST_HASH_SEED, {1}, "reason=failed"),
    ("control_check_passes_when_the_summary_depends_on_the_order_of_a_set", [rep(FRAME_PY, HELD_BITS, HELD_IN_SET_ORDER)], CHECK, {0}, "check: OK"),
    # アプリの世界の種が、筋書きの種（0）と違う。種と、流れの状態が、要約に入っている。
    ("run_world_seed_differs", [rep(APP_PY, "WORLD_SEED = 0\n", "WORLD_SEED = 1\n")], RUN, {1}, "failed=sim,fingerprint not_yet="),
    # --- 保存：run（保存のファイルの置き場を渡して回す。道具が、書かれたファイルを自分で読む） ---
    ("run_file_backend_drops_the_last_byte", [FILE_DROPS_LAST_BYTE], RUN, {1}, "failed=save,save_file not_yet="),
    # 保存の往復を、名前空間 main で回す。アプリの申告（往復が通った）は合っているので、道具が自分で見たファイルで落とす。
    ("run_round_trip_in_the_main_namespace", [ROUND_TRIP_IN_MAIN], RUN, {1}, "failed=save_file,save_main not_yet="),
    # アプリが、保存の往復を回さない。
    ("run_round_trip_is_not_run", [rep(APP_PY, SELFCHECK_CALL, "None")], RUN, {1}, "failed=save,save_file not_yet="),
    # 保存の往復の終わりに、既定値で書き直す。ファイルはあり、封筒も読める。落ちるのは、道具が本体を往復の見本と比べる所だけ
    # （ほかの save_file の件は、ファイルが無いか、封筒が読めないかで落ちる。「封筒が読めれば合格」の道具では、この件だけが通ってしまう）。
    ("run_round_trip_ends_with_the_defaults", [ROUND_TRIP_ENDS_WITH_DEFAULTS], RUN, {1}, "save=file checks=21 problems=1 failed=save_file not_yet="),
    # デスクトップ版が、保存のファイルの置き場を読まない（メモリの保存先になる）。
    ("run_save_directory_is_ignored", [rep(SELECT_PY, SAVE_DIR_READ, '    directory = ""\n')], RUN, {1}, "save=memory checks=21 problems=2 failed=save,save_file not_yet="),
    # 道具が、置き場を相対パスで渡す。アプリは、起動時に例外にする（pyxel.init が作業ディレクトリを変えるため）。
    ("run_save_directory_is_relative", [rep(RUN_TOOL_PY, SAVE_DIR_ENV_ARG, '**{storage_select.SAVE_DIR_ENV: "saves"})')], RUN, {1}, "reason=app_exit_code"),
    # 巡回の口でも、置き場の環境変数を読む（相対パスなら、起動時に例外）。
    ("tour_save_directory_is_relative", [rep(TOUR_TOOL_PY, TOUR_ENV, TOUR_ENV.replace("CP_TOUR_DIR=WORK", 'CP_TOUR_DIR=WORK, CP_SAVE_DIR="saves"'))], TOUR, {2}, "reason=app_exit_code"),
    # --- 保存：web-smoke の筋書き probe（保存先は localStorage） ---
    # localStorage の保存先が、読んだ値の最後の1バイトを落とす。書いた値は正しいので、道具が自分で読んだ値は合う。アプリの往復で落ちる。
    ("web_storage_read_drops_the_last_byte", [rep(WEB_STORAGE_PY, WEB_READ, WEB_READ.replace("validate=True)", "validate=True)[:-1]"))], WEB_PROBE, {1}, "failed=probe.storage_ok"),
    # 保存の往復を、名前空間 main で回す。アプリの申告は合っているので、道具が自分で読んだ localStorage の値で落とす。
    ("web_round_trip_in_the_main_namespace", [ROUND_TRIP_IN_MAIN], WEB_PROBE, {1}, "failed=probe.storage_value,probe.storage_main"),
    # --- 保存：web-smoke の筋書き shipped（ふつうの起動の後の localStorage に、このアプリの鍵が1つも無い） ---
    # 検証の口でなくても、保存の往復を回す。往復の鍵（clippingpoint/selfcheck.settings）が残る。run も、ほかの筋書きも通る。
    ("web_shipped_round_trip_runs_on_a_plain_start", [ROUND_TRIP_ON_EVERY_START], WEB_SHIPPED, {1}, "problems=1 failed=shipped.storage_empty"),
    # 試し書きが、試しの鍵（clippingpoint/storage-probe）を消さない。保存先は使えると判定されるので、ほかの筋書きは通る。
    ("web_shipped_probe_key_is_not_removed", [PROBE_KEY_NOT_REMOVED], WEB_SHIPPED, {1}, "problems=1 failed=shipped.storage_empty"),
    # ブラウザの実行役が、localStorage を読まない。鍵が0件で通す確かめなので、読めていないことを、鍵が無いことと取り違えて通さない。
    ("web_shipped_local_storage_is_not_read", [rep(WEBRUN_JS, "  if (opt.localStorage) {\n", "  if (false) {\n")], WEB_SHIPPED, {1}, "problems=1 failed=shipped.storage_empty"),
    # --- 保存：web-smoke の筋書き storage_blocked（localStorage に触れると例外） ---
    # 試し書きをせずに、localStorage を使う。保存先が切り替わらない。
    ("web_blocked_storage_is_used_without_a_probe", [NO_PROBE], WEB_BLOCKED, {1}, "failed=storage_blocked.storage_backend,storage_blocked.storage_ok,storage_blocked.storage_notice"),
    # 保存先を切り替えても、知らせを作らない。
    ("web_blocked_fallback_makes_no_notice", [rep(SELECT_PY, FALLBACK, FALLBACK.replace("NOTICE_MEMORY_FALLBACK", '""'))], WEB_BLOCKED, {1}, "failed=storage_blocked.storage_notice"),
    # 知らせを、表示用の値へ渡さない。結果の知らせは、表示用の値から取るので、空になる。
    ("web_blocked_notice_is_not_passed_to_the_view", [NO_NOTICE_IN_VIEW], WEB_BLOCKED, {1}, "failed=storage_blocked.storage_notice"),
    # 試し書きが、localStorage に触れたときの例外を、外へ出す。起動時に、Pythonの例外になる。
    ("web_blocked_probe_lets_the_error_out", [rep(WEB_STORAGE_PY, PROBE_TOUCH, PROBE_TOUCH.replace("return PROBE_UNAVAILABLE, describe(exc)", "raise"))], WEB_BLOCKED, {1}, "failed=storage_blocked.error_overlay"),
    # 差し込むスクリプトが無い。保存先を止めずに開いて、別の理由で落とさない。回り切れない（2）にする。
    ("web_block_storage_script_is_missing", [rm("tools/web/block_storage.js")], WEB_BLOCKED, {2}, "reason=no_block_storage"),
    # 差し込むスクリプトが、保存先を止めない（何もしない）。保存先が localStorage のままなので、落ちる（筋書きが、空振りで通らない）。
    ("web_block_storage_script_blocks_nothing", [rm("tools/web/block_storage.js"), add("tools/web/block_storage.js", "// does nothing\n")], WEB_BLOCKED, {1}, "failed=storage_blocked.storage_backend,storage_blocked.storage_notice"),
    # --- 定義データ：check --only data（出荷するデータを、1か所ずつ壊す。問題は1件。調べた組は2つのまま） ---
    # 知らない鍵（鍵の名の打ち間違い）。試験用データ（extreme）は、同じ id の項目を差し替えるので、重ねた組では、この問題は出ない。
    ("check_data_unknown_key", [DATA_UNKNOWN_KEY], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_missing_key", [rep(CARS_JSON, CAR_NAME, "")], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_value_out_of_range", [rep(CARS_JSON, CAR_VERSION, '"data_version": 0')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_name_not_ascii", [rep(CARS_JSON, CAR_NAME_VALUE, '"name": "カザネ"')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_name_of_15_characters", [rep(CARS_JSON, CAR_NAME_VALUE, '"name": "KAZANE RS TESTS"')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_duplicate_id", second_car_with_the_same_id(), CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_bool_where_an_integer_belongs", [rep(CARS_JSON, CAR_VERSION, '"data_version": true')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # JSONの文を読む所で見つかる問題。標準の読み方は、重複した鍵と NaN を、黙って通す。
    ("check_data_file_is_not_json", [first_char(CARS_JSON)], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_duplicate_key", [rep(CARS_JSON, CAR_NAME, CAR_NAME + CAR_NAME)], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # NaN は、規則の部品が見ない所（項目の中の、注の鍵の値）に置く。データの版の値に置くと、JSONの文を読む所の検査が無くても、
    # 整数の型の検査が、同じ語（problems=1）で落とす。注の鍵なら、その検査が無くなると、問題0件で通ってしまい、この件が拾う。
    ("check_data_nan", [DATA_NAN_IN_A_NOTE], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # ファイルの頭の形の誤り（表の鍵の名が違う）。知らない鍵と、表の鍵が無い、の2件。
    ("check_data_file_head_has_another_table_key", [rep(CARS_JSON, '  "cars": [', '  "car": [')], CHECK_DATA, {1}, "check: FAILED data=2 problems=2 failed=data"),
    # 1ファイル1項目のファイルが、項目そのものでない（並びで包んである）。
    ("check_data_entry_file_is_a_list", [rep(LOOP_JSON, '{\n  "_notes"', '[{\n  "_notes"'), app(LOOP_JSON, "]\n")], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_cars_file_deleted", [DATA_CARS_DELETED], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # コースのファイルの名と、中の id が違う。
    ("check_data_file_name_differs_from_the_id", loop_file_under_another_name(), CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # data/ に、表の定義に無いファイルを置く。黙って無視しない。
    ("check_data_file_that_no_table_reads", [add("clipping_point/data/sounds.json", '{"sounds": []}\n')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # --- 定義データ：check --only data（試験用データを壊す。出荷するデータの組は通り、重ねた組だけが落ちる） ---
    ("check_data_test_pack_broken", [PACK_NAME_TOO_LONG], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # 試験用データの置き場に、2つの形に当たらない名のファイルを置く。「重ねたつもりで、重なっていない」まま通さない。
    ("check_data_test_pack_has_a_file_that_no_table_reads", [add(f"{PACK_DIR}/notes.txt", "notes\n")], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("check_data_test_pack_has_a_table_file_in_the_other_shape", [add(f"{PACK_DIR}/tracks.json", '{"tracks": []}\n')], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # 試験用データの置き場が、空（ファイルが1つも無い）。重ねられないので、組に数えない（調べた組は1つ）。問題は1件。
    ("check_data_test_pack_directory_is_empty", [rm(PACK_CARS_JSON), rm(PACK_LOOP_JSON)], CHECK_DATA, {1}, "check: FAILED data=1 problems=1 failed=data"),
    # 節を絞らない check でも、落ちる（data の節が、全体の check に入っている）。
    ("check_all_sections_data_unknown_key", [DATA_UNKNOWN_KEY], CHECK, {1}, "data=2 problems=1 failed=data"),
    # --- 定義データ：起動時の読み込み検査（run、tour、export） ---
    # 出荷するデータに問題があると、アプリは、起動時に例外で止まる。巡回の口でも、定義データを読む。
    ("run_data_unknown_key", [DATA_UNKNOWN_KEY], RUN, {1}, "reason=app_exit_code"),
    ("run_realtime_data_unknown_key", [DATA_UNKNOWN_KEY], RUN_RT, {1}, "reason=app_exit_code"),
    ("tour_data_unknown_key", [DATA_UNKNOWN_KEY], TOUR, {2}, "reason=app_exit_code"),
    ("run_data_cars_file_deleted", [DATA_CARS_DELETED], RUN, {1}, "reason=app_exit_code"),
    # ソースから消すと、出荷物にも入らない（一覧は、両方に無くて同じ）。表の定義が求めるファイルが無い、で落とす。
    ("export_data_cars_file_deleted", [DATA_CARS_DELETED], EXPORT, {1}, "failed=missing"),
    # ソースの木にある定義データが、出荷物に入らない。pyxel package は、名が「.」で始まるファイルとディレクトリを入れない（実測）。
    # デスクトップ版は読めて、ブラウザ版には無い、という食い違いを、出荷物の一覧とソースの木の一覧を比べて拾う。
    ("export_data_file_left_out_by_the_packager", [add("clipping_point/data/tracks/.hidden_loop.json", '{"id": ".hidden_loop"}\n')], EXPORT, {1}, "failed=data_files"),
    # 試験用データが、出荷物に入る。
    ("export_test_pack_mixed_in", [add("clipping_point/testpacks/extreme/cars.json", '{"cars": []}\n')], EXPORT, {1}, "failed=forbidden"),
    # 起動時に、定義データを読まない（空の定義で起動する）。世界が、車の id を引けずに、起動時の例外で止まる。
    ("run_data_is_not_loaded_at_start", [rep(APP_PY, LOAD_DATA, NO_DATA_AT_START)], RUN, {1}, "reason=app_exit_code"),
    # アプリが読み込んだ定義に、ファイルに無い車が1台ある。起動して、最後まで回る。落ちるのは、表ごとの件数が、道具が、定義データの
    # ファイルを自分で読んで数えた件数と違う、という確かめだけ。
    ("run_data_tables_differ_from_the_files", [rep(APP_PY, LOAD_DATA, LOAD_DATA + ENTRY_NOT_ON_DISK)], RUN, {1}, "checks=21 problems=1 failed=data_tables not_yet="),
    # --- 試験用データを重ねて回す：run --pack extreme ---
    # 試験用データが壊れている。重ねない run は通り（上の check の件と対）、重ねた run は、起動時の例外で落ちる。
    ("control_run_passes_with_a_broken_test_pack", [PACK_NAME_TOO_LONG], RUN, {0}, "run: OK driver=flip input=script"),
    ("run_pack_test_pack_broken", [PACK_NAME_TOO_LONG], RUN_PACK, {1}, "reason=app_exit_code"),
    # デスクトップ版が、重ねる口（CP_DATA_PACK）を読まない。重ねていない結果が返る。
    ("run_pack_variable_is_not_read", [rep(DATA_FILES_PY, READ_PACK_ENV, '        name = ""\n')], RUN_PACK, {1}, "pack=none namespace=main save=file checks=20 problems=3 failed=data_tables,data_pack,data_namespace fingerprint=skipped"),
    # 重ねたのに、アプリが、設定を読む保存の口へ、名前空間を渡さない。結果の名前空間が main になる。段0の起動は、設定を書かないので、
    # 保存のファイルでは分からない（save_main は通る）。落ちるのは、結果の名前空間の確かめだけ。
    ("run_pack_namespace_is_not_passed_to_the_settings_store", [NAMESPACE_NOT_PASSED], RUN_PACK, {1}, "pack=extreme namespace=main save=file checks=20 problems=1 failed=data_namespace fingerprint=skipped"),
    # 上の件の対。同じ壊し方でも、重ねない run は通る（重ねて回す手順が要る理由）。守りのテスト（app.py のソースを読む）は落ちる。
    ("control_run_passes_when_the_namespace_is_not_passed", [NAMESPACE_NOT_PASSED], RUN, {0}, "pack=none namespace=main save=file checks=21 problems=0 not_yet="),
    ("test_app_does_not_pass_the_namespace_to_the_settings_store", [NAMESPACE_NOT_PASSED], tool("test", "-k", "data_files and namespace"), {1}, "reason=failed"),
    # 試験用データの置き場が無い、置き場にファイルが1つも無い、無い名。回り切れない（2）。重ねずに回して、合格にしない。
    ("run_pack_directory_deleted", [rm_tree(PACK_DIR)], RUN_PACK, {2}, "reason=no_such_pack"),
    ("run_pack_directory_is_empty", [rm(PACK_CARS_JSON), rm(PACK_LOOP_JSON)], RUN_PACK, {2}, "reason=no_such_pack"),
    ("run_pack_unknown_name", [], tool("run", "--pack", "nosuch"), {2}, "reason=no_such_pack"),
    # アプリが、何も回さずに終了コード0で終わる。前回の、重ねて回した合格の形の結果が残っていても、読まない。
    (
        "run_pack_stale_result_is_not_reused",
        [add("out/run/result.json", STALE_PACK_RESULT), add_bytes(STALE_SAVE_FILE, STALE_SAVE), rep(APP_PY, IN_UPDATE, QUIT_EARLY)],
        RUN_PACK, {2}, "reason=no_result_file",
    ),
    # --- 定義データ：test（読み込み検査と、道具の判定の関数。狙ったテストに絞る） ---
    # 読み込み検査が、知らない鍵を見ない。
    ("test_data_check_ignores_unknown_keys", [rep(DATADEFS_PY, UNKNOWN_KEY_FOUND, "        pass\n")], tool("test", "-k", "datadefs and broken_shipped"), {1}, "reason=failed"),
    # 読み込み検査が、最初の1件で止まる。
    ("test_data_check_stops_at_the_first_problem", [rep(DATADEFS_PY, RAISE_ALL, "        raise DataError(problems[:1])\n")], tool("test", "-k", "datadefs and three_planted"), {1}, "reason=failed"),
    # 読み込み検査が、警告（どこからも参照されていない定義）を数えない。
    ("test_data_check_counts_no_warnings", [rep(DATADEFS_PY, RETURN_DATA, "    return GameData(entries, (), pack_name)\n")], tool("test", "-k", "datadefs and unreferenced"), {1}, "reason=failed"),
    # 道具 check の data の節が、出荷するデータの警告を、問題に数えない。実物には参照が無い（警告は、どう壊しても0件）ので、
    # 節の関数のテスト（作り物の表の定義）で拾う。
    ("test_check_data_section_does_not_count_warnings", [rep(CHECK_TOOL_PY, SHIPPED_WARNINGS, "        pass\n")], tool("test", "-k", "check_tool and warning"), {1}, "reason=failed"),
    # 道具 check の data の節が、試験用データを重ねた組の警告を、問題に数えない。同じ試験用データで、check は通り、run --pack は
    # 警告0件を求めて落ちる、という食い違いになる。これも、節の関数のテスト（作り物の表の定義）で拾う。
    ("test_check_data_section_does_not_count_pack_warnings", [rep(CHECK_TOOL_PY, PACK_WARNINGS, "            pass\n")], tool("test", "-k", "check_tool and warning and pack"), {1}, "reason=failed"),
    # 道具が、外から入った CP_DATA_PACK を、子プロセスへ渡す。守りのテストで拾う。
    ("test_tools_pass_an_outside_data_pack_to_the_app", [rep(COMMON_PY, APP_ENV_LIST, APP_ENV_LIST.replace(', "CP_DATA")', ")"))], tool("test", "-k", "outside_data_pack"), {1}, "reason=failed"),
    # --- 定義データ：web-smoke（ブラウザ版） ---
    # ブラウザ版が、定義データを読めない（出荷物に、車の表のファイルが無い）。起動時の例外を、エラー表示として拾う。
    # 道具 export が、出荷物の中の定義データのファイルを調べる所を外して重ねる（外さないと、export が1になり、web-smoke は、
    # ページを開かずに2を返す）。
    ("web_data_file_is_not_in_the_shipped_html", [DATA_CARS_DELETED, rep(EXPORT_TOOL_PY, EXPORT_DATA_CHECK, "")], WEB_SHIPPED, {1}, "failed=shipped.error_overlay"),
    # 上の件の対。道具 export の検査を外さなければ、ページを開く前に、回り切れない（2）で止まる。
    ("web_data_file_deleted_stops_at_the_export", [DATA_CARS_DELETED], WEB_SHIPPED, {2}, "reason=export_failed"),
    # ブラウザ版でだけ、アプリが読み込んだ定義に、ファイルに無い車が1台ある。デスクトップ版の道具（run）は通る。
    # （空の定義で起動する形にしない。世界が、車の id を引けずに、起動時の例外になり、件数の確かめまで届かない。）
    (
        "web_probe_data_tables_differ_only_in_browser",
        [rep(APP_PY, LOAD_DATA, LOAD_DATA + "    if js is not None:\n    " + ENTRY_NOT_ON_DISK)],
        WEB_PROBE, {1}, "failed=probe.data_tables",
    ),
    # --- 車両モデル：test（狙ったテストに絞る） ---
    # 止める力の頭打ち（タイヤの制動力と横力）を外す。極低速で、ヨーレートが毎tick反転して、静止しない。
    (
        "test_vehicle_stop_clamp_removed", [rep(VEHICLE_PY, TIRE_BRAKE_CLAMP, ""), rep(VEHICLE_PY, TIRE_SIDE_CLAMP, "")],
        tool("test", "-k", "vehicle and coasting_with_full_lock"), {1}, "reason=failed",
    ),
    # 1 tickの中を、1回だけで積分する。数字で固定した参照値が、変わる。
    ("test_vehicle_one_substep", [rep(VEHICLE_PY, "SUBSTEPS = 2\n", "SUBSTEPS = 1\n")], tool("test", "-k", "vehicle and mixed_inputs"), {1}, "reason=failed"),
    # エンジンブレーキを、試作の形（負の駆動力）に戻す。前進のギアのまま後ろ向きに動くと、増速する。
    (
        "test_vehicle_engine_brake_as_negative_drive", [rep(VEHICLE_PY, ENGINE_BRAKE_BRANCH, "            if True:\n")],
        tool("test", "-k", "vehicle and rolling_backwards"), {1}, "reason=failed",
    ),
    # 車両モデルが、舵の速さを制限する（試作の形）。舵の速さを決めるのは、操作補正の1か所だけ。
    ("test_vehicle_rate_limits_the_steer", [rep(VEHICLE_PY, STEER_CLAMP, STEER_RATE_LIMITED)], tool("test", "-k", "vehicle and never_rate_limited"), {1}, "reason=failed"),
    # --- コース：test ---
    # 壁の押し戻しを外す（当たっていても、そのまま返す）。
    (
        "test_track_wall_does_not_push_out", [rep(TRACK_PY, WALL_NO_CONTACT, WALL_NO_CONTACT.replace("if side == 0:", "if True:"))],
        tool("test", "-k", "track and wall_takes_speed_away"), {1}, "reason=failed",
    ),
    # 照会が、前回の区間を使わずに、いつも区間0から探す。答えは同じで、毎回、全部を探して取り直す（遅くなるだけの退行）。
    (
        "test_track_query_ignores_the_previous_segment", [rep(TRACK_PY, QUERY_FROM_HINT, QUERY_FROM_HINT.replace("hint % n", "0"))],
        tool("test", "-k", "track and never_requeries"), {1}, "reason=failed",
    ),
    # 照会が、前回の区間の近くで探し当てられなかったときに、取り直さない（区間の端に寄せた、違う答えになる）。
    (
        "test_track_query_does_not_requery", [rep(TRACK_PY, QUERY_REQUERY, QUERY_REQUERY.replace("if not found:", "if not found and hint is None:"))],
        tool("test", "-k", "track and far_segment"), {1}, "reason=failed",
    ),
    # --- 操作補正：test ---
    # 後退に入らない（後退へ入る指示を、出さない）。壁に正面から当たって止まると、抜けられない（詰み）。
    ("test_controls_never_asks_for_reverse", [rep(CONTROLS_PY, ASK_REVERSE, NEVER_ASK_REVERSE)], tool("test", "-k", "controls and asks_for_reverse"), {1}, "reason=failed"),
    # 後退中に、ペダルを読み替えない（ブレーキの入力が、ブレーキのまま）。
    (
        "test_controls_pedals_are_not_swapped_in_reverse", [rep(CONTROLS_PY, REVERSE_PEDALS, "        return Command(steer, throttle_in, brake_in, shift)\n")],
        tool("test", "-k", "controls and pedals_swap"), {1}, "reason=failed",
    ),
    # 車速に応じた最大舵角を外す（いつも、車の最大舵角）。
    ("test_controls_steer_has_no_speed_limit", [rep(CONTROLS_PY, STEER_LIMIT_RESULT, "    return max_steer\n")], tool("test", "-k", "controls and steer_limit"), {1}, "reason=failed"),
    # --- 項目をまたぐ検査（車の値の矛盾、コースの形）：test ---
    # 読み込み検査が、項目をまたぐ検査を呼ばない。
    ("test_data_cross_check_is_never_called", [rep(DATADEFS_PY, CROSS_CHECK_CALL, "    if False:\n")], tool("test", "-k", "datadefs and cross_check_lines"), {1}, "reason=failed"),
    # 鍵ごとの規則を通らなかった項目にも、検査を呼ぶ（規則を通らない値で、計算を始める）。
    (
        "test_data_cross_check_runs_on_entries_that_fail_a_rule", [rep(DATADEFS_PY, CROSS_CHECK_CALL, "    if item.has_id and definition.check is not None:\n")],
        tool("test", "-k", "datadefs and called_only"), {1}, "reason=failed",
    ),
    # 検査の関数の例外を、問題の行に直さない（DataError のほかの例外が、外へ出る）。
    (
        "test_data_cross_check_exception_escapes", [rep(DATADEFS_PY, CROSS_CHECK_CATCH, "        except DataError as exc:\n")],
        tool("test", "-k", "datadefs and cross_check_that_raises"), {1}, "reason=failed",
    ),
    # --- 車とコースと操作補正の定義データ：check --only data（出荷するデータを、1か所ずつ壊す。調べた組は2つのまま） ---
    # 車の値の矛盾。5速の変速比が、4速より大きい。
    ("check_data_car_gear_ratios_do_not_fall", [rep(CARS_JSON, CAR_GEARS, CAR_GEARS.replace("0.86", "1.2"))], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # コースの形の誤り。制御点が、頭の40点だけ（末尾から頭へ、閉じていない）。
    ("check_data_track_is_not_closed", loop_with_only_the_first_points(40), CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # コースの形の誤り。直線の途中の制御点を、横へ8 m動かす。最小半径より小さく曲がり、内側の壁も折り返す（2件）。
    (
        "check_data_track_radius_too_small", [rep(LOOP_JSON, LOOP_POINT, LOOP_POINT.replace('"z_m": 0.0', '"z_m": 8.0'))],
        CHECK_DATA, {1}, "check: FAILED data=2 problems=2 failed=data",
    ),
    # 退化したコース。制御点が、全部同じ点。表を作る計算（0で割る）へ進まずに、問題にする（節が例外で止まって、2にならない）。
    # 問題は、制御点の間隔ごとに1件（72件）。
    ("check_data_track_every_point_is_the_same", loop_with_every_point_at_the_same_place(), CHECK_DATA, {1}, "check: FAILED data=2 problems=72 failed=data"),
    # 操作補正の値が、範囲の外（ペダルを押していると見る線が0。いつも押している扱いになり、後退へ入れない）。
    (
        "check_data_assist_press_line_is_zero", [rep(ASSISTS_JSON, '"pedal_press_min": 0.1', '"pedal_press_min": 0.0')],
        CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data",
    ),
    # 操作補正の表のファイルが無い。起動時にも、例外で止まる。
    ("check_data_assists_file_deleted", [rm(ASSISTS_JSON)], CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    ("run_data_assists_file_deleted", [rm(ASSISTS_JSON)], RUN, {1}, "reason=app_exit_code"),
    # 試験用データの車が、足した鍵を持たない（項目ごと差し替える重ね方なので、足りない鍵は、問題になる）。出荷するデータの組は通る。
    ("check_data_test_pack_car_leaves_a_group_out", pack_car_without_the_steering_group(), CHECK_DATA, {1}, "check: FAILED data=2 problems=1 failed=data"),
    # --- 作業の補助：仮の周回路の制御点を、式から作る（tools/claude/make_test_loop.py） ---
    ("control_make_test_loop_check", [], tool("claude/make_test_loop", "--check"), {0}, "make_test_loop: OK points=72"),
    # 制御点を、手で動かした。式から作った制御点と違う。
    (
        "make_test_loop_point_moved_by_hand", [rep(LOOP_JSON, LOOP_POINT, LOOP_POINT.replace('"z_m": 0.0', '"z_m": 0.5'))],
        tool("claude/make_test_loop", "--check"), {1}, "same=no",
    ),
    # --- 世界への組み込み（段0 区切り9）：test（狙ったテストに絞る） ---
    # 世界が、路面の種類を、次のtickの摩擦係数へ渡さない（芝へ出ても、舗装の値のまま）。
    ("test_sim_surface_grip_is_not_passed_on", [rep(SIM_PY, SIM_SURFACE_MU, "        pass\n")], tool("test", "-k", "sim and surface_grip_follows"), {1}, "reason=failed"),
    # 世界の要約から、車の項目を1つ落とす（位置の x）。指紋の写しとも、違う（筋書きごとに1件）。
    ("test_sim_summary_drops_a_car_item", [rep(SIM_PY, SIM_FIELD_X, "")], tool("test", "-k", "sim and field_table"), {1}, "reason=failed"),
    ("fingerprint_summary_drops_a_car_item", [rep(SIM_PY, SIM_FIELD_X, "")], FINGERPRINT, {1}, "scenarios=4 fields=6 problems=4 failed=world env="),
    # 要約に、小数をそのまま入れる（量子化しない）。
    (
        "test_sim_summary_holds_floats", [rep(SIM_PY, SIM_QUANTIZE, SIM_QUANTIZE.replace("round(values[name] * scale)", "values[name] * scale"))],
        tool("test", "-k", "sim and flat_integers"), {1}, "reason=failed",
    ),
    # 壁に当たった回数を、当たっているtickごとに数える（押し付けられている間も、増える）。
    ("test_sim_wall_hits_counted_on_every_tick", [rep(SIM_PY, SIM_WALL_HIT, "            self.wall_hits += 1\n")], tool("test", "-k", "sim and pressed_against"), {1}, "reason=failed"),
    # 進行距離から、後ろへ動いた分を引く。
    ("test_sim_distance_shrinks_when_backing_up", [rep(SIM_PY, SIM_ODOMETER, "        if moved <= ODOMETER_MAX_STEP_M:\n")], tool("test", "-k", "sim and backs_up"), {1}, "reason=failed"),
    # 壁に押し戻した後の位置で、照会し直さない（要約の横のずれが、押し戻す前の、壁の外の値のまま）。
    (
        "test_sim_summary_keeps_the_position_before_the_push_out", [rep(SIM_PY, SIM_QUERY_AFTER_PUSH, "            pass\n")],
        tool("test", "-k", "sim and after_the_wall_pushed"), {1}, "reason=failed",
    ),
    # 項目ごとの比べ方の表から、要約の項目が1つ漏れる（ブラウザ版の側は web_script_summary_field_without_a_compare_rule）。
    (
        "test_sim_summary_field_without_a_compare_rule", [rep(SIM_PY, SIM_COMPARE_RULES, SIM_COMPARE_RULES.replace("SUMMARY_FIELDS}", "SUMMARY_FIELDS[:-1]}"))],
        tool("test", "-k", "sim and summary_compare"), {1}, "reason=failed",
    ),
    # 仮の表示へ、進めている世界の車でない車の値を渡す（作ったばかりの世界の、止まった車）。道具は全部通る。守りのテストで拾う。
    (
        "test_app_draws_a_car_that_is_not_the_one_in_the_world",
        [rep(APP_PY, DRAW_FRAME, DRAW_FRAME.replace("car_view(self.sim)", "car_view(Sim(WORLD_SEED, self.data, CAR_ID, TRACK_ID))"))],
        tool("test", "-k", "screens and app_shows_the_car"), {1}, "reason=failed",
    ),
    # --- 世界への組み込み：fingerprint（指紋の写しと、筋書きの走行の下限） ---
    # 1 tickの中を、1回だけで積分する（test の側は test_vehicle_one_substep）。
    ("fingerprint_vehicle_one_substep", [rep(VEHICLE_PY, "SUBSTEPS = 2\n", "SUBSTEPS = 1\n")], FINGERPRINT, {1}, "failed=world"),
    # 壁の押し戻しを外す（test の側は test_track_wall_does_not_push_out）。壁の台本の下限（壁に当たった回数）も、満たさない。
    (
        "fingerprint_wall_does_not_push_out", [rep(TRACK_PY, WALL_NO_CONTACT, WALL_NO_CONTACT.replace("if side == 0:", "if True:"))],
        FINGERPRINT, {1}, "failed=world,floor env=",
    ),
    # 後退に入らない（test の側は test_controls_never_asks_for_reverse）。壁の台本の下限（後退に入った回数）も、満たさない。
    ("fingerprint_controls_never_asks_for_reverse", [rep(CONTROLS_PY, ASK_REVERSE, NEVER_ASK_REVERSE)], FINGERPRINT, {1}, "failed=world,floor env="),
    # 照会が、前回の区間を使わずに、いつも区間0から探す（test の側は test_track_query_ignores_the_previous_segment）。位置の答えは同じで、
    # 毎tick、全部を探して取り直す。走る台本の下限（照会を取り直した回数が0）を、満たさない。
    (
        "fingerprint_track_query_ignores_the_previous_segment", [rep(TRACK_PY, QUERY_FROM_HINT, QUERY_FROM_HINT.replace("hint % n", "0"))],
        FINGERPRINT, {1}, "failed=world,floor env=",
    ),
    # 走る台本を、アクセルを踏まない台本に替える。指紋の写しとも違い、走行の下限も満たさない。
    ("fingerprint_drive_script_does_not_drive", DRIVE_SCRIPT_DOES_NOT_DRIVE, FINGERPRINT, {1}, "failed=world,floor env="),
    # 同じ台本のまま、指紋の写しを取り直そうとする。走行が成り立っていない筋書きの要約を、写しにしない（何も書かずに、1）。
    ("fingerprint_update_refuses_a_script_that_does_not_drive", DRIVE_SCRIPT_DOES_NOT_DRIVE, tool("fingerprint", "--update"), {1}, "updated=0 reason=floor_not_met"),
    # 走行の下限を、届かない値に上げる。世界の要約は、指紋の写しと同じ。それでも、下限を満たさなければ、落とす。
    (
        "fingerprint_floor_not_met_with_the_same_snapshot", [rep(FINGERPRINT_PY, DRIVE_FLOOR_ODOMETER, '("odometer_mm", ">=", 999_000)')],
        FINGERPRINT, {1}, "scenarios=4 fields=6 problems=1 failed=floor env=",
    ),
    # 車の値を1つ変える（質量。走りに効く値）。道具 run は、参照（いまのデータで計算し直す値）とは合い、指紋の写しとの確かめだけが落ちる。
    ("fingerprint_car_value_changed", [rep(CARS_JSON, CAR_MASS, '"mass_kg": 1000.0')], FINGERPRINT, {1}, "failed=world"),
    ("run_car_value_changed", [rep(CARS_JSON, CAR_MASS, '"mass_kg": 1000.0')], RUN, {1}, "checks=21 problems=1 failed=fingerprint not_yet="),
    # コースの制御点を1つ動かす（1本目の直線の途中。走る台本が通る所）。読み込み検査は通る（check_data_track_radius_too_small は、8 m動かす）。
    ("fingerprint_track_point_moved", [rep(LOOP_JSON, LOOP_POINT, LOOP_POINT.replace('"z_m": 0.0', '"z_m": 0.5'))], FINGERPRINT, {1}, "failed=world"),
    ("control_check_data_passes_with_a_track_point_moved_a_little", [rep(LOOP_JSON, LOOP_POINT, LOOP_POINT.replace('"z_m": 0.0', '"z_m": 0.5'))], CHECK_DATA, {0}, "check: OK data=2 problems=0"),
    # --- 世界への組み込み：run（走る台本の回、壁の台本の回、車とコースの id） ---
    # 走る台本を、アクセルを踏まない台本に替える。アプリを通した回でも、指紋の写しと、走行の下限で落ちる。
    ("run_drive_script_does_not_drive", DRIVE_SCRIPT_DOES_NOT_DRIVE, RUN_DRIVE, {1}, "checks=22 problems=2 failed=fingerprint,floor not_yet="),
    # 試験用データを重ねた回は、指紋を照らさない。筋書きが同じなら、走行の下限は見る。
    ("run_pack_drive_script_does_not_drive", DRIVE_SCRIPT_DOES_NOT_DRIVE, RUN_PACK_DRIVE, {1}, "checks=21 problems=1 failed=floor fingerprint=skipped"),
    # アプリのコースの id を、試験用データ（extreme）にだけあるコースに変える。重ねた回は、起動して回る（コースの形は、同じ）。
    # 要約の、車とコースの id が、道具の既定と違う（参照と、アプリの世界が、別のコースで回っている）。
    (
        "run_pack_app_track_id_differs_from_the_tools", [rep(APP_PY, APP_TRACK_ID, 'TRACK_ID = "wide_test_loop"\n')],
        RUN_PACK, {1}, "checks=20 problems=2 failed=sim,sim_ids fingerprint=skipped",
    ),
    # 上の件の対。同じ id のまま、重ねずに回すと、その id のコースが無い。起動時に、例外で止まる（分かる文は tests/test_sim.py が見る）。
    ("run_app_track_id_is_not_in_the_data", [rep(APP_PY, APP_TRACK_ID, 'TRACK_ID = "wide_test_loop"\n')], RUN, {1}, "reason=app_exit_code"),
    # 仮の表示の車の値が、後退のギアを受けない。壁の台本の回だけが、後退に入ったtickの実描画で、例外になる（既定の run では、
    # 車が後退に入らないので、通る。壁の台本を、アプリに通す手順が要る理由）。
    (
        "run_wall_reverse_gear_breaks_the_placeholder", [rep(FLOW_PY, CAR_VIEW_GEAR_CHECK, CAR_VIEW_GEAR_CHECK.replace("== 0", "< 1"))],
        RUN_WALL, {1}, "reason=app_exit_code",
    ),
    (
        "control_run_passes_when_reverse_gear_breaks_the_placeholder", [rep(FLOW_PY, CAR_VIEW_GEAR_CHECK, CAR_VIEW_GEAR_CHECK.replace("== 0", "< 1"))],
        RUN, {0}, "run: OK driver=flip input=script",
    ),
    # --- 世界の要約の突き合わせ：web-smoke の筋書き script（デスクトップ版とブラウザ版。項目ごとの比べ方） ---
    # ブラウザ版でだけ、完全一致の項目（変速の回数）が、1つ違う。デスクトップ版のアプリとも、道具の参照とも合わない
    # （ブラウザ版の2回は、同じ値なので、sim_repeat は通る）。
    (
        "web_script_exact_field_differs_from_desktop", [rep(APP_PY, IN_UPDATE, IN_UPDATE + ONLY_ON_WEB + "            self.sim.shifts += 1\n")],
        WEB_SCRIPT, {1}, "problems=2 failed=script.sim,script.sim_reference",
    ),
    # ブラウザ版でだけ、許容差つきの項目（位置の x）が、2 mm違う（最後の更新の後に動かす）。許容差（量子化の刻みで±2）の内なので、通る。
    # 最後の1行の script_gap= に、差の最大（2）が出る。
    (
        "control_web_script_near_field_within_the_tolerance_passes",
        [rep(APP_PY, IN_UPDATE, IN_UPDATE + ONLY_ON_WEB_AT_THE_END + "            self.sim.car.x += 0.002\n")],
        WEB_SCRIPT, {0}, "script_gap=2 checks=",
    ),
    # 世界が、標準の乱数を読む。同じ台本でも、回すたびに、要約が変わる。ブラウザ版の2回の要約が違う（デスクトップ版とも、参照とも違う）。
    ("web_script_world_reads_the_standard_random", [rep(SIM_PY, SIM_TICK, SIM_READS_RANDOM)], WEB_SCRIPT, {1}, "failed=script.sim,script.sim_reference,script.sim_repeat"),
    # 項目ごとの比べ方の表から、要約の項目が1つ漏れる。見ずに通さない（回り切れない）。
    (
        "web_script_summary_field_without_a_compare_rule", [rep(SIM_PY, SIM_COMPARE_RULES, SIM_COMPARE_RULES.replace("SUMMARY_FIELDS}", "SUMMARY_FIELDS[:-1]}"))],
        WEB_SCRIPT, {2}, "incomplete=script.summary_field_without_rule",
    ),
    # --- この道具の、件の回し方（時間に頼る件は、1件ずつ。tests/test_selftest_tool.py） ---
    # 時間に頼る件の判定が、いつも「頼らない」と答える。ブラウザ版の煙テストや全体の検証が、並列に回ってしまう。
    ("test_selftest_timed_cases_are_not_told_apart", [rep(SELFTEST_PY, SELFTEST_IS_TIMED, "    return False\n")], TEST_SELFTEST_TOOL, {1}, "reason=failed"),
    # 時間に頼る件を、並列の件と一緒に、まとめて回す（1件ずつにしない）。
    ("test_selftest_timed_cases_run_in_the_pool", [rep(SELFTEST_PY, SELFTEST_SPLIT, "    return cases, []\n")], TEST_SELFTEST_TOOL, {1}, "reason=failed"),
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
        elif kind == "delete_tree":
            if not target.is_dir() or target.is_symlink():
                raise RuntimeError(f"{path}: 消すはずのディレクトリが無い")
            shutil.rmtree(target)
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


PLANT_ERROR = "plant-error"  # 壊す所が見つからなかった件の、終了コードの欄に入れる語
VERDICT_OK = "ok"
VERDICT_PLANT_ERROR = "COULD NOT PLANT"


def is_timed(cmd) -> bool:
    """時間に頼る件か。ブラウザ版の煙テスト、本番と同じ経路の run（--realtime）、全体の検証（どちらも含む）。

    時間に頼る件は、1件ずつ回す。並列に回すと、毎秒の回数や、処理時間の線が揺れて、壊さない件が落ちる。
    """
    words = [Path(str(word)).name for word in cmd]
    return "web_smoke.py" in words or "verify.py" in words or "--realtime" in words


def run_case(case) -> dict:
    """件を1つ回して、結果の行を返す。自分の複製（out/selftest/<名>-<乱数>/repo）の中だけを書く。"""
    name, faults, cmd, expected, needle = case
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(dir=SCRATCH, prefix=name + "-") as tmp:
        work = Path(tmp) / "repo"
        copy_repo(work)
        try:
            plant(work, faults)
        except (RuntimeError, OSError) as exc:
            code, line = PLANT_ERROR, str(exc)
        else:
            code, out, err = run(cmd, timeout=CASE_TIMEOUT_S, cwd=work, env=child_env())
            line = last_line(out, err)
    if code == PLANT_ERROR:
        verdict = VERDICT_PLANT_ERROR
    elif code not in expected:
        verdict = "CONTROL FAILED" if expected == {0} else "NOT CAUGHT"
    elif needle not in line:
        verdict = "WRONG REASON"
    else:
        verdict = VERDICT_OK
    return {
        "case": name, "command": " ".join(c.replace(PY, "python3") for c in cmd), "expected_exit": sorted(expected),
        "expected_word": needle, "exit": code, "verdict": verdict, "seconds": round(time.perf_counter() - started, 2),
        "last_line": line[:300],
    }


def split_cases(cases: list) -> tuple:
    """件を、(並列に回す件, 1件ずつ回す件) に分ける。並びは、どちらも、元の順。"""
    return [case for case in cases if not is_timed(case[2])], [case for case in cases if is_timed(case[2])]


def run_cases(cases: list, jobs: int, runner=run_case, report=None) -> list:
    """件を全部回して、結果の行を、元の順で返す。時間に頼らない件を、同時に jobs 件ずつ。時間に頼る件は、その後に、1件ずつ。

    並列の件が全部終わってから、時間に頼る件を始める（重ねない）。report は、行が1つ出るたびに呼ぶ（進み具合の表示）。
    """
    free, timed = split_cases(cases)
    rows = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for case, row in zip(free, pool.map(runner, free)):
            rows[case[0]] = row
            if report:
                report(row)
    for case in timed:
        rows[case[0]] = row = runner(case)
        if report:
            report(row)
    return [rows[case[0]] for case in cases]


def print_row(row: dict) -> None:
    print(f"[{row['verdict']}] {row['case']:40s} exit={row['exit']} expected={row['expected_exit']}  {row['last_line'][:150]}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="道具と検査をわざと壊して、落ちることを確かめる")
    ap.add_argument("--only", default="", metavar="PREFIX", help="名前がこの語で始まる件だけ回す")
    ap.add_argument("--jobs", type=int, default=None, metavar="N", help="時間に頼らない件を、同時に回す数（既定は tools/budgets.json の selftest_jobs）")
    args = ap.parse_args()
    cases = [case for case in CASES if case[0].startswith(args.only)]
    if not cases:
        return finish("selftest_break", INCOMPLETE, f"cases=0 only={args.only!r}")
    if len({case[0] for case in cases}) != len(cases):
        return finish("selftest_break", INCOMPLETE, "cases=0 reason=duplicate_case_names")
    jobs = int(load_budgets()["selftest_jobs"]) if args.jobs is None else args.jobs
    if jobs < 1:
        return finish("selftest_break", INCOMPLETE, f"cases=0 jobs={jobs}")
    missing = [item for item in COPY_ITEMS if not (ROOT / item).exists()]
    if missing:
        return finish("selftest_break", INCOMPLETE, f"cases=0 missing={','.join(missing)}")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    free, timed = split_cases(cases)
    print(f"  selftest_break: jobs={jobs} parallel_cases={len(free)} one_by_one_cases={len(timed)}", flush=True)
    rows = run_cases(cases, jobs, report=print_row)
    wrong = sum(1 for row in rows if row["verdict"] not in (VERDICT_OK, VERDICT_PLANT_ERROR))
    plant_errors = sum(1 for row in rows if row["verdict"] == VERDICT_PLANT_ERROR)
    (SCRATCH / "break_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    controls = sum(1 for row in rows if row["expected_exit"] == [0])
    summary = f"cases={len(rows)} planted={len(rows) - controls} controls={controls} wrong={wrong} plant_errors={plant_errors}"
    return finish("selftest_break", FAIL if wrong else INCOMPLETE if plant_errors else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
