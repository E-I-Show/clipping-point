"""道具 screen-check（tools/screen_check.py）と tour（tools/tour.py）の、判定の関数のテスト。Pyxelは使わない。

アプリを別プロセスで回すこと（終了コード、結果ファイルの有無、古い結果）は、道具 selftest-break が見る。
ここでは、予定の作り方、調べられなかった件の数え方、結果ファイルと画像の欠けの読み方を見る。
"""
import struct
import sys

import pytest

import _common
import screen_check
import tour as tour_tool
from cp_app import tour as app_tour
from cp_ui import fixtures
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.check import find_violations
from cp_ui.screens import SCREENS

OK, FAIL, INCOMPLETE = 0, 1, 2
VARIANTS = ("typical", "extreme")


# --- screen-check：予定 ---
def test_screen_check_plan_is_every_screen_in_every_variant():
    assert screen_check.plan({"a": None, "b": None}, VARIANTS) == [("a", "typical"), ("a", "extreme"), ("b", "typical"), ("b", "extreme")]


def test_screen_check_plan_can_be_limited_to_one_screen():
    assert screen_check.plan({"a": None, "b": None}, VARIANTS, "b") == [("b", "typical"), ("b", "extreme")]


def test_screen_check_plan_is_empty_without_variants_or_screens():
    assert screen_check.plan({"a": None}, ()) == []
    assert screen_check.plan({}, VARIANTS) == []


def test_screen_check_loads_the_shipped_registry_and_fixtures():
    screens, variants, build, canvas_type, check = screen_check.load_ui()
    assert screens is SCREENS and variants == fixtures.VARIANTS
    assert build is fixtures.build and canvas_type is Canvas and check is find_violations


def test_screen_check_does_not_write_bytecode_into_the_shipped_tree(monkeypatch):
    # 道具は、出荷するコードを自分のプロセスでimportする。clipping_point/ に __pycache__ を作らせない。
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    screen_check.load_ui()
    assert sys.dont_write_bytecode is True


# --- screen-check：件ごとの組み立てと、調べられなかった件 ---
def fits(canvas, view):
    with canvas.box("status", 2, 18, 64, 18):
        canvas.text(4, 20, f"RENDER {view}", 7)


def narrow(canvas, view):
    """囲みが狭い。ふつうの値では収まり、極端な値でだけ、はみ出す。"""
    with canvas.box("status", 2, 18, 48, 18):
        canvas.text(4, 20, f"RENDER {view}", 7)


def raises(canvas, view):
    raise RuntimeError("planted")


def silent(canvas, view):
    with canvas.box("panel", 0, 0, 10, 10):  # 囲みだけ。描画命令は残さない
        pass


def number(screen, variant):
    return {"typical": 60, "extreme": 9999999}[variant]


def check(screens, variants=VARIANTS, build=number, only=""):
    planned = screen_check.plan(screens, variants, only)
    rows, not_checked = screen_check.check_screens(planned, screens, build, Canvas, find_violations)
    return planned, rows, not_checked


def test_screen_check_clean_screens_pass():
    planned, rows, not_checked = check({"fits": fits})
    assert [(row["screen"], row["variant"], row["commands"]) for row in rows] == [("fits", "typical", 1), ("fits", "extreme", 1)]
    assert not_checked == [] and all(row["violations"] == [] for row in rows)
    assert screen_check.summarize(planned, rows, not_checked) == (OK, "screens=2/2 violations=0 not_checked=0")


def test_screen_check_overflow_that_only_the_extreme_variant_shows():
    # ふつうの値だけなら通る。極端な値でも回さないと、見つからない。
    planned, rows, not_checked = check({"narrow": narrow})
    assert [len(row["violations"]) for row in rows] == [0, 1]
    assert rows[1]["violations"][0].kind == "out_of_box"
    assert screen_check.summarize(planned, rows, not_checked) == (FAIL, "screens=2/2 violations=1 not_checked=0 failed=narrow/extreme kinds=out_of_box")
    typical_only = check({"narrow": narrow}, variants=("typical",))
    assert screen_check.summarize(*typical_only) == (OK, "screens=1/1 violations=0 not_checked=0")


def test_screen_check_summary_names_every_failed_screen_and_kind():
    def off_screen(canvas, view):
        canvas.text(300, 3, "CLIPPING POINT", 7)
        canvas.text(4, 20, "ティック", 7)

    planned, rows, not_checked = check({"fits": fits, "bad": off_screen, "narrow": narrow})
    code, summary = screen_check.summarize(planned, rows, not_checked)
    assert code == FAIL
    assert summary == "screens=6/6 violations=5 not_checked=0 failed=bad/typical,bad/extreme,narrow/extreme kinds=bad_char,off_screen,out_of_box"


def test_screen_check_a_screen_that_raises_is_not_checked():
    planned, rows, not_checked = check({"fits": fits, "raises": raises})
    assert [row["screen"] for row in rows] == ["fits", "fits"]
    assert not_checked == ["raises/typical: RuntimeError: planted", "raises/extreme: RuntimeError: planted"]
    assert screen_check.summarize(planned, rows, not_checked) == (INCOMPLETE, "screens=2/4 violations=0 not_checked=2")


def test_screen_check_a_screen_without_fixtures_is_not_checked():
    def build(screen, variant):
        return {"fits": number}[screen](screen, variant)

    planned, rows, not_checked = check({"fits": fits, "new": fits}, build=build)
    assert len(rows) == 2 and [line.split(":")[0] for line in not_checked] == ["new/typical", "new/extreme"]
    assert "KeyError" in not_checked[0]
    assert screen_check.summarize(planned, rows, not_checked)[0] == INCOMPLETE


def test_screen_check_a_screen_that_leaves_no_command_is_not_checked():
    planned, rows, not_checked = check({"silent": silent})
    assert rows == [] and len(not_checked) == 2
    assert screen_check.summarize(planned, rows, not_checked) == (INCOMPLETE, "screens=0/2 violations=0 not_checked=2")


def test_screen_check_nothing_planned_is_not_a_pass():
    planned, rows, not_checked = check({"fits": fits}, variants=())
    assert screen_check.summarize(planned, rows, not_checked) == (INCOMPLETE, "screens=0/0 violations=0 not_checked=0 reason=nothing_planned")


def test_screen_check_fewer_rows_than_planned_is_not_a_pass():
    planned, rows, _ = check({"fits": fits})
    assert screen_check.summarize(planned, rows[:1], [])[0] == INCOMPLETE


def test_screen_check_violations_do_not_hide_a_screen_that_was_not_checked():
    planned, rows, not_checked = check({"narrow": narrow, "raises": raises})
    code, summary = screen_check.summarize(planned, rows, not_checked)
    assert code == INCOMPLETE and "violations=1" in summary and "not_checked=2" in summary


def test_screen_check_the_shipped_screens_pass():
    screens, variants, build, canvas_type, check_canvas = screen_check.load_ui()
    planned = screen_check.plan(screens, variants)
    rows, not_checked = screen_check.check_screens(planned, screens, build, canvas_type, check_canvas)
    code, summary = screen_check.summarize(planned, rows, not_checked)
    assert code == OK, summary
    assert len(rows) == len(planned) == len(SCREENS) * len(fixtures.VARIANTS)


# --- tour：画像の大きさ ---
def png_bytes(width: int, height: int) -> bytes:
    """頭（署名と、幅と高さの入った最初のチャンク）だけが本物のPNG。"""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def test_tour_tool_reads_the_size_from_the_head_of_a_png(tmp_path):
    (tmp_path / "shot.png").write_bytes(png_bytes(640, 480))
    (tmp_path / "big.png").write_bytes(png_bytes(704, 544))
    assert tour_tool.png_size(tmp_path / "shot.png") == (640, 480)
    assert tour_tool.png_size(tmp_path / "big.png") == (704, 544)


def test_tour_tool_a_missing_or_broken_image_has_no_size(tmp_path):
    (tmp_path / "text.png").write_text("not a png, just a long enough line of text\n", encoding="utf-8")
    (tmp_path / "short.png").write_bytes(png_bytes(640, 480)[:20])
    (tmp_path / "empty.png").write_bytes(b"")
    (tmp_path / "other_chunk.png").write_bytes(png_bytes(640, 480).replace(b"IHDR", b"IDAT"))
    for name in ("no_such.png", "text.png", "short.png", "empty.png", "other_chunk.png"):
        assert tour_tool.png_size(tmp_path / name) is None, name
    assert tour_tool.png_size(tmp_path) is None  # ディレクトリ


def test_tour_tool_expects_the_screen_at_twice_its_size():
    assert tour_tool.IMAGE_SIZE == (640, 480)
    assert tour_tool.IMAGE_SIZE == (SCREEN_W * app_tour.SHOT_SCALE, SCREEN_H * app_tour.SHOT_SCALE)


# --- tour：結果ファイルの判定 ---
PLANNED = [("placeholder", "typical"), ("placeholder", "extreme")]
WANT = {key: 8 for key in PLANNED}
SIZES = {key: (640, 480) for key in PLANNED}


def shot(variant: str = "typical", **changes) -> dict:
    """問題の無い、結果ファイルの1件。"""
    base = {
        "screen": "placeholder", "variant": variant, "file": f"placeholder_{variant}.png", "commands": 8, "checked": 8,
        "margin_ink": 0, "screen_ink": 5417, "command_problems": [], "violations": [], "check_ms": 0.7,
    }
    return {**base, **changes}


def result(*shots) -> dict:
    return {"shots": list(shots) if shots else [shot("typical"), shot("extreme")], "margin": 16, "scale": 2, "wall_s": 0.13}


def kinds(entries: list) -> list:
    return [kind for kind, _ in entries]


def test_tour_tool_clean_result_passes():
    assert tour_tool.judge(PLANNED, WANT, result(), SIZES) == ([], [], 2, 16)


def test_tour_tool_planned_shot_missing_from_the_result_is_incomplete():
    # 予定の欠け。巡回が、画面か変種を1つ飛ばした。
    incomplete, problems, done, checked = tour_tool.judge(PLANNED, WANT, result(shot("typical")), SIZES)
    assert kinds(incomplete) == ["missing_shot"] and "placeholder/extreme" in incomplete[0][1]
    assert (problems, done, checked) == ([], 1, 8)


@pytest.mark.parametrize("data", [None, [], "text", {}, {"shots": None}, {"shots": {"placeholder": {}}}])
def test_tour_tool_result_without_a_list_of_shots_is_incomplete(data):
    # 結果ファイルの欠け。
    incomplete, problems, done, checked = tour_tool.judge(PLANNED, WANT, data, SIZES)
    assert kinds(incomplete) == ["result_shape"] and (problems, done, checked) == ([], 0, 0)


def test_tour_tool_empty_result_misses_every_planned_shot():
    incomplete, _, done, _ = tour_tool.judge(PLANNED, WANT, {"shots": []}, SIZES)
    assert kinds(incomplete) == ["missing_shot", "missing_shot"] and done == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"checked": None}, {"checked": "8"}, {"checked": 8.0}, {"checked": True}, {"screen_ink": None}, {"margin_ink": "0"},
        {"command_problems": None}, {"violations": 0},
    ],
)
def test_tour_tool_entry_of_another_shape_is_incomplete(changes):
    incomplete, _, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", **changes), shot("extreme")), SIZES)
    assert kinds(incomplete) == ["result_shape"] and done == 1


def test_tour_tool_entry_with_a_missing_field_is_incomplete():
    entry = shot("typical")
    del entry["checked"]
    assert kinds(tour_tool.judge(PLANNED, WANT, result(entry, shot("extreme")), SIZES)[0]) == ["result_shape"]
    assert kinds(tour_tool.judge(PLANNED, WANT, result("not a dict", shot("extreme")), SIZES)[0]) == ["missing_shot"]


def test_tour_tool_missing_image_is_incomplete():
    sizes = {**SIZES, ("placeholder", "extreme"): None}
    incomplete, _, done, checked = tour_tool.judge(PLANNED, WANT, result(), sizes)
    assert kinds(incomplete) == ["no_image"] and (done, checked) == (1, 8)
    assert kinds(tour_tool.judge(PLANNED, WANT, result(), {})[0]) == ["no_image", "no_image"]


def test_tour_tool_image_of_another_size_is_incomplete():
    # 全体の絵でない絵を保存した（余白ごとの大きさ）。
    sizes = {**SIZES, ("placeholder", "typical"): (704, 544)}
    incomplete, _, done, _ = tour_tool.judge(PLANNED, WANT, result(), sizes)
    assert kinds(incomplete) == ["image_size"] and "704x544" in incomplete[0][1] and done == 1


def test_tour_tool_blank_screen_is_incomplete():
    incomplete, _, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", screen_ink=0), shot("extreme")), SIZES)
    assert kinds(incomplete) == ["blank_screen"] and done == 1


@pytest.mark.parametrize("checked", [0, 7, 9, -1])
def test_tour_tool_checked_commands_must_match_the_count_built_without_pyxel(checked):
    # 巡回が、命令ごとの照合を飛ばした。照らした命令の数が、道具が組み立てた命令の数と違う。
    incomplete, _, done, total = tour_tool.judge(PLANNED, WANT, result(shot("typical", checked=checked), shot("extreme")), SIZES)
    assert kinds(incomplete) == ["commands_checked"] and (done, total) == (1, 8)


def test_tour_tool_checked_commands_are_compared_per_shot():
    want = {("placeholder", "typical"): 8, ("placeholder", "extreme"): 12}
    assert kinds(tour_tool.judge(PLANNED, want, result(), SIZES)[0]) == ["commands_checked"]
    assert tour_tool.judge(PLANNED, want, result(shot("typical"), shot("extreme", checked=12)), SIZES) == ([], [], 2, 20)
    assert kinds(tour_tool.judge(PLANNED, {}, result(), SIZES)[0]) == ["commands_checked", "commands_checked"]


def test_tour_tool_one_shot_can_have_several_gaps():
    sizes = {**SIZES, ("placeholder", "typical"): None}
    incomplete, _, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", screen_ink=0, checked=0), shot("extreme")), sizes)
    assert kinds(incomplete) == ["no_image", "blank_screen", "commands_checked"] and done == 1


def test_tour_tool_ink_in_the_margin_is_a_problem():
    incomplete, problems, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", margin_ink=40), shot("extreme")), SIZES)
    assert incomplete == [] and kinds(problems) == ["margin_ink"] and done == 2


def test_tour_tool_command_problems_are_problems_of_their_kind():
    entries = [
        {"index": 6, "kind": "rectb", "problem": "ink_outside", "outside": 40, "inside": 666, "bounds": [2, 38, 316, 19], "text": ""},
        {"index": 1, "kind": "text", "problem": "no_ink", "outside": 0, "inside": 0, "bounds": [4, 3, 55, 5], "text": "CLIPPING POINT"},
    ]
    incomplete, problems, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", command_problems=entries), shot("extreme")), SIZES)
    assert incomplete == [] and done == 2
    assert kinds(problems) == ["ink_outside", "no_ink"]
    assert "#6 rectb" in problems[0][1] and "[2, 38, 316, 19]" in problems[0][1]
    assert "'CLIPPING POINT'" in problems[1][1]
    # 形の崩れた件も、問題として数える（黙って落とさない）。
    assert kinds(tour_tool.judge(PLANNED, WANT, result(shot("typical", command_problems=["x"]), shot("extreme")), SIZES)[1]) == ["command_problem"]


def test_tour_tool_violations_are_problems():
    found = [{"kind": "out_of_box", "text": "command #3 text 'RENDER 9999999' at (4,28) 55x5 leaves box #1 'status' at (2,18) 48x18"}]
    incomplete, problems, _, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical"), shot("extreme", violations=found)), SIZES)
    assert incomplete == [] and kinds(problems) == ["violation"]
    assert "placeholder/extreme" in problems[0][1] and "out_of_box" in problems[0][1] and "RENDER 9999999" in problems[0][1]


def test_tour_tool_problems_are_still_listed_for_a_shot_with_gaps():
    sizes = {**SIZES, ("placeholder", "typical"): None}
    incomplete, problems, done, _ = tour_tool.judge(PLANNED, WANT, result(shot("typical", margin_ink=3), shot("extreme")), sizes)
    assert kinds(incomplete) == ["no_image"] and kinds(problems) == ["margin_ink"] and done == 1


def test_tour_tool_shots_that_were_not_planned_are_ignored():
    extra = shot("typical", screen="other", margin_ink=99)
    assert tour_tool.judge(PLANNED, WANT, result(shot("typical"), shot("extreme"), extra), SIZES) == ([], [], 2, 16)


def test_tour_tool_kinds_are_listed_once_in_the_order_they_appear():
    assert tour_tool.kinds_of([("no_ink", "a"), ("ink_outside", "b"), ("no_ink", "c")]) == "no_ink,ink_outside"
    assert tour_tool.kinds_of([]) == ""


# --- tour：3Dの絵の判定 ---
SCENE_NAMES = ["straight", "corner", "wall"]
SCENE_SIZES = {name: (640, 480) for name in SCENE_NAMES}
TOOL_BUDGETS = _common.load_budgets()
PALETTE = tour_tool.scene_reference.expected_palette()[0]
# 実物のアプリの、巡回の値（スタート位置）。2Dの描画命令は、重ねていない（矩形の内も外も、違う画素は0）。
SCENE = {
    "sky": 24565, "track": 43207, "car": 5082, "ink_inside": 0, "ink_outside": 0,
    "probes": {
        "pillar_left": {"pixels": 229, "x10": 1138}, "pillar_right": {"pixels": 211, "x10": 2052},
        "mark_right": {"pixels": 292, "x10": 2111}, "mark_nose": {"pixels": 132, "x10": 1595},
    },
    "palette": list(PALETTE), "digest": 3123312044,
}


def scene_entry(name: str = "straight", **changes) -> dict:
    """問題の無い、結果ファイルの、3Dの絵の1件。changes は、判定用の実描画の値（scene）を置き換える。"""
    return {"name": name, "file": f"scene_{name}.png", "x_mm": 60000, "z_mm": 0, "heading_mrad": 0, "scene": {**SCENE, **changes}}


def scene_result(*entries) -> dict:
    return {"shots": [], "scenes": list(entries) if entries else [scene_entry(name) for name in SCENE_NAMES]}


def judge_scenes(data, planned=SCENE_NAMES, sizes=SCENE_SIZES, want_palette=PALETTE) -> tuple:
    return tour_tool.judge_scenes(planned, data, sizes, TOOL_BUDGETS, want_palette)


def test_tour_tool_scene_plan_comes_from_the_tour_port_of_the_app():
    names, only, head = tour_tool.load_scene_plan()
    assert list(names) == SCENE_NAMES == [sample[0] for sample in app_tour.SCENE_SHOTS]
    assert (only, head) == (app_tour.SCENE_ONLY, app_tour.SCENE_FILE_HEAD) == ("scene", "scene_")
    assert only not in SCREENS  # 画面の名と、重ならない


def test_tour_tool_scene_shots_skip_only_the_check_that_needs_2d_commands():
    # 3Dの絵には、2Dの描画命令を重ねない。周期の中の実描画も、無い。矩形の内の画素（back_ink）と、描き直す前の裏画面（back_live）
    # だけを外す。scene_same は、回す（保存した絵が、判定用の3枚目と同じ＝ふだんの描く道が、判定と同じ3Dを描いている）。
    assert tour_tool.SCENE_SHOT_CHECKS == ("backdrop", "scene3d", "mirror", "palette", "scene_same")
    assert set(tour_tool.scene_reference.SCENE_CHECKS) - set(tour_tool.SCENE_SHOT_CHECKS) == set(tour_tool.scene_reference.NOT_FOR_SHOTS)
    assert set(tour_tool.SCENE_SHOT_CHECKS) < set(tour_tool.scene_reference.SCENE_CHECKS)


def test_tour_tool_clean_scenes_pass():
    assert judge_scenes(scene_result()) == ([], [], 3)
    assert judge_scenes(scene_result(), planned=[]) == ([], [], 0)


@pytest.mark.parametrize(
    "changes, kind",
    [
        ({"sky": 960}, "backdrop"),
        ({"track": 0}, "scene3d"),
        ({"car": 0}, "scene3d"),
        ({"probes": {**SCENE["probes"], "mark_right": {"pixels": 292, "x10": 1300}}}, "mirror"),  # 車の向きの符号が逆（模型の右の印が、左に写る）
        ({"probes": {**SCENE["probes"], "mark_nose": {"pixels": 0, "x10": 0}}}, "mirror"),
        ({"palette": [0] * 32}, "palette"),
        ({"ink_outside": 12}, "scene_same"),
    ],
)
def test_tour_tool_a_broken_scene_is_a_problem_under_the_name_of_its_check(changes, kind):
    incomplete, problems, done = judge_scenes(scene_result(scene_entry("straight"), scene_entry("corner", **changes), scene_entry("wall")))
    assert incomplete == [] and kinds(problems) == [kind] and done == 3
    assert problems[0][1].startswith("scene/corner: ")


def test_tour_tool_scene_without_2d_commands_does_not_fail_on_the_ink_inside():
    assert judge_scenes(scene_result(*(scene_entry(name, ink_inside=0) for name in SCENE_NAMES))) == ([], [], 3)


def test_tour_tool_planned_scene_missing_from_the_result_is_incomplete():
    incomplete, problems, done = judge_scenes(scene_result(scene_entry("straight"), scene_entry("wall")))
    assert kinds(incomplete) == ["missing_shot"] and problems == [] and done == 2
    assert "scene/corner" in incomplete[0][1]


@pytest.mark.parametrize("data", [None, [], {}, {"shots": []}, {"scenes": None}, {"scenes": {"straight": {}}}])
def test_tour_tool_result_without_a_list_of_scenes_is_incomplete(data):
    incomplete, problems, done = judge_scenes(data)
    assert kinds(incomplete) == ["result_shape"] and problems == [] and done == 0
    # 3Dの絵を回さない予定（--only 画面の名）なら、一覧が無くても、欠けにしない。
    assert judge_scenes(data, planned=[]) == ([], [], 0)


@pytest.mark.parametrize("scene", [None, [], "scene", 5])
def test_tour_tool_scene_entry_without_the_judged_values_is_incomplete(scene):
    broken = {**scene_entry("corner"), "scene": scene}
    incomplete, problems, done = judge_scenes(scene_result(scene_entry("straight"), broken, scene_entry("wall")))
    assert kinds(incomplete) == ["result_shape"] and problems == [] and done == 2


def test_tour_tool_scene_image_that_is_missing_or_of_another_size_is_incomplete():
    incomplete, problems, done = judge_scenes(scene_result(), sizes={**SCENE_SIZES, "corner": None})
    assert kinds(incomplete) == ["no_image"] and problems == [] and done == 2
    incomplete, _, done = judge_scenes(scene_result(), sizes={**SCENE_SIZES, "wall": (704, 544)})
    assert kinds(incomplete) == ["image_size"] and done == 2
    # 画像が欠けていても、その絵の問題は、並べる。
    incomplete, problems, done = judge_scenes(scene_result(scene_entry("straight", track=0), scene_entry("corner"), scene_entry("wall")), sizes={**SCENE_SIZES, "straight": None})
    assert kinds(incomplete) == ["no_image"] and kinds(problems) == ["scene3d"] and done == 2


def test_tour_tool_palette_that_the_tool_could_not_read_fails_every_scene():
    incomplete, problems, done = judge_scenes(scene_result(), want_palette=None)
    assert incomplete == [] and kinds(problems) == ["palette"] * 3 and done == 3


def test_tour_tool_scenes_that_were_not_planned_are_ignored():
    extra = scene_entry("somewhere_else", track=0)
    assert judge_scenes(scene_result(*(scene_entry(name) for name in SCENE_NAMES), extra)) == ([], [], 3)


# --- 子プロセスの環境 ---
def test_tools_child_env_drops_the_app_switches_that_came_from_outside(monkeypatch):
    for name in ("CP_SMOKE", "CP_SMOKE_TICKS", "CP_SMOKE_SCRIPT", "CP_TOUR", "CP_TOUR_DIR", "CP_TOUR_ONLY"):
        monkeypatch.setenv(name, "/outside/value")
    monkeypatch.setenv("CP_OTHER", "kept")
    env = _common.child_env()
    assert not [name for name in env if name.startswith(("CP_SMOKE", "CP_TOUR"))]
    assert env["CP_OTHER"] == "kept"


def test_tools_child_env_keeps_the_switches_the_tool_sets_itself(monkeypatch, tmp_path):
    monkeypatch.setenv("CP_TOUR", "/outside/value")
    monkeypatch.setenv("CP_TOUR_ONLY", "outside_screen")
    env = _common.child_env(CP_TOUR=tmp_path / "result.json", CP_TOUR_DIR=tmp_path)
    assert env["CP_TOUR"] == str(tmp_path / "result.json") and env["CP_TOUR_DIR"] == str(tmp_path)
    assert "CP_TOUR_ONLY" not in env
