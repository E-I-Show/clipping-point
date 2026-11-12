"""全体の検証の道具（tools/verify.py）のテスト。ファイルから分野を引く所、回す手順の決め方、落ちた手順の数え方、
変更したファイルをgitから読む所。

道具を実際に順に回すこと（1本落ちると verify が1になること）は、道具 selftest-break が見る。
gitを使うテストは、一時のリポジトリ（tmp_path）の中だけで回す。ネットワークは使わない。
"""
import ast
import os
import re
import subprocess

import pytest

import verify
from conftest import ROOT

VEHICLE = "車両"
TRACK = "コース"
INPUT = "操作補正と入力"
FLOW = "カメラと画面の状態"
UI = "画面（2D）"
WEB = "ブラウザ連携"
LOOP = "メインループと世界の状態"
TOOLS_AREA = "検証の道具と検査の決まり"
FULL_STEPS = ["check", "test", "fingerprint", "screen-check", "run", "run-realtime", "run-pack", "tour", "export", "web-smoke"]
UI_WORDS = "canvas or screens or ui_check or fixtures or tour"
FLOW_WORDS = "flow or fixtures or screens or fingerprint"
INPUT_WORDS = "input_frame or input_script or input_pyxel or input_trace or controls or profile"
VEHICLE_WORDS = "vehicle or sim or fingerprint"
TRACK_WORDS = "track or sim or fingerprint or datadefs or data_files"
WEB_WORDS = "web_bridge or input_web or storage or profile"
# どの分野にも当たらない見本。設計のモジュールの表に出てこない名前にする（本物のファイルと重ならないように）。
NO_AREA_CODE = "clipping_point/cp_core/zz_no_area.py"
NO_AREA_TEST = "tests/test_zz_no_area.py"
# 一時のリポジトリでgitを回すときの環境。この環境のgitの設定（署名、フックなど）を読ませない。
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.com",
    "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.com",
}


def names_of(path):
    return [area.name for area in verify.areas_of(path)]


def area(name):
    return next(a for a in verify.AREAS if a.name == name)


def step_names(plan):
    return [name for name, _ in plan]


# --- ファイルから分野を引く ---
def test_verify_watched_files_are_the_shipped_code_and_the_tests():
    # いまのリポジトリの全ファイルが分野に当たることは、ここでは見ない。見張るのは tools/check.py の areas の節。
    # ここで見ると、テストのファイルを足して確かめる selftest-break の件が、別の理由で落ちてしまう。
    files = verify.watched_files(ROOT)
    assert "clipping_point/main.py" in files and "tests/conftest.py" in files
    assert all(path.startswith(("clipping_point/", "tests/")) for path in files)
    assert not any("__pycache__" in path for path in files)


def test_verify_files_map_to_their_areas():
    assert names_of("clipping_point/cp_ui/canvas.py") == [UI]
    assert names_of("clipping_point/cp_app/canvas_pyxel.py") == [UI]
    assert names_of("tests/test_screens.py") == [UI]
    assert names_of("clipping_point/cp_app/web_bridge.py") == [WEB]
    assert names_of("tests/test_web_bridge.py") == [WEB]
    assert names_of("clipping_point/cp_core/sim.py") == [LOOP]
    assert names_of("clipping_point/cp_app/app.py") == [LOOP]
    assert names_of("tools/web/webrun.js") == [TOOLS_AREA]
    assert names_of("tests/snapshots/canon_digest.json") == [TOOLS_AREA]


def test_verify_screen_files_map_to_the_ui_area_and_the_checks_also_to_the_tools_area():
    # 描画命令の層、画面の組み立て、巡回の口は、画面（2D）。
    for path in (
        "clipping_point/cp_ui/canvas.py", "clipping_point/cp_ui/screens.py", "clipping_point/cp_app/canvas_pyxel.py",
        "clipping_point/cp_app/tour.py", "tests/test_canvas.py", "tests/test_screens.py", "tests/test_tour.py",
    ):
        assert names_of(path) == [UI], path
    # はみ出しの検査と見本データは、計画の表で selftest-break つきの分野（検査の決まり）でもある。
    for path in ("clipping_point/cp_ui/check.py", "clipping_point/cp_ui/fixtures.py", "tests/test_ui_check.py", "tests/test_fixtures.py"):
        assert names_of(path) == [UI, TOOLS_AREA], path
    assert area(TOOLS_AREA).selftest is True and area(UI).selftest is False
    # 道具の側（screen-check、tour と、その判定の関数のテスト）は、道具の分野。
    for path in ("tools/screen_check.py", "tools/tour.py", "tests/test_screen_tools.py"):
        assert names_of(path) == [TOOLS_AREA], path


def test_verify_flow_files_map_to_the_camera_and_screen_state_area():
    assert names_of("clipping_point/cp_core/flow.py") == [FLOW]
    assert names_of("tests/test_flow.py") == [FLOW]
    # 計画の表の「カメラと画面の状態」：run、screen-check。
    plan, kind, not_yet = verify.plan_for([area(FLOW)], [], focused=True)
    assert kind == "focused"
    assert step_names(plan) == ["check", "test", "screen-check", "run"]
    # 計画の表に無い fixtures と screens を足してある（突き合わせのテストを選ぶため。理由は AREAS の行の注）。
    assert plan[1][1][-2:] == ["-k", FLOW_WORDS]
    assert not_yet == []


def readers_of(needle: str) -> list:
    """tests/ のテストのうち、関数の中に needle が出てくるもの。返すのは (ファイルの名, 関数の名) の一覧。"""
    found = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and needle in ast.get_source_segment(text, node):
                found.append((path.name, node.name))
    return found


def selected_by(expression: str, file_name: str, test_name: str) -> bool:
    """`-k` の式（語を or でつないだ形）が、テストに当たるか。pytest は、語を、ファイルの名と関数の名に、部分一致で当てる。"""
    return any(word.lower() in file_name.lower() or word.lower() in test_name.lower() for word in expression.split(" or "))


def test_verify_flow_area_selects_the_tests_that_compare_the_screen_names():
    # flow.py だけに触れたときの、絞った検証の `-k` の式。ロジックが持つ画面の名（cp_core.flow の、画面の名の並び）を見る
    # テストは、どれも選ばれること。選ばれないと、flow.py にだけ画面の名を足して、画面の登録と見本データへ足し忘れても、通る。
    areas, unknown = verify.areas_for(["clipping_point/cp_core/flow.py"])
    assert [a.name for a in areas] == [FLOW] and unknown == []
    plan, kind, _ = verify.plan_for(areas, unknown, focused=True)
    assert kind == "focused" and plan[1][1][-2] == "-k"
    expression = plan[1][1][-1]
    readers = readers_of("SCREEN" + "_NAMES")  # 名を割って書く。このテスト自身を、読むテストに数えないため
    # 突き合わせのテスト（画面の登録と見本データを、ロジックの画面の名と照らす）が、読むテストの中にあること。
    assert ("test_fixtures.py", "test_fixtures_logic_screens_registry_and_fixtures_name_the_same_screens") in readers
    assert ("test_screens.py", "test_screens_registry_has_the_same_names_as_the_logic") in readers
    missed = [f"{file_name}::{test_name}" for file_name, test_name in readers if not selected_by(expression, file_name, test_name)]
    assert missed == [], f"`-k {expression!r}` が当たらない：{missed}"
    # 語が flow だけだと、突き合わせのテストは選ばれない（この守りが、何でも通す形でないことの確かめ）。
    assert not selected_by("flow", "test_fixtures.py", "test_fixtures_logic_screens_registry_and_fixtures_name_the_same_screens")
    assert not selected_by("flow", "test_screens.py", "test_screens_registry_has_the_same_names_as_the_logic")


def test_verify_touching_only_the_overflow_check_runs_selftest_break():
    # はみ出しの検査か見本データの判定だけを変えた区切りでも、selftest-break が回る。
    for path in ("clipping_point/cp_ui/check.py", "clipping_point/cp_ui/fixtures.py"):
        areas, unknown = verify.areas_for([path])
        assert unknown == []
        assert step_names(verify.plan_for(areas, unknown)[0])[-1] == verify.SELFTEST
    areas, _ = verify.areas_for(["clipping_point/cp_ui/screens.py"])
    assert verify.SELFTEST not in step_names(verify.plan_for(areas, [])[0])


def test_verify_input_files_map_to_the_input_area_and_the_direct_read_to_the_web_area():
    for path in (
        "clipping_point/cp_core/input_frame.py", "clipping_point/cp_core/input_script.py", "clipping_point/cp_app/input_pyxel.py",
        "clipping_point/cp_app/input_trace.py", "tests/test_input_frame.py", "tests/test_input_script.py",
        "tests/test_input_pyxel.py", "tests/test_input_trace.py",
        "clipping_point/cp_core/controls.py", "tests/test_controls.py",  # 操作補正の最小版（段0 区切り9）
    ):
        assert names_of(path) == [INPUT], path
    # 直読みは、計画の表の「ブラウザ連携（入力の直読み、保存先、ファイルの受け渡し）」。
    assert names_of("clipping_point/cp_app/input_web.py") == [WEB]
    assert names_of("tests/test_input_web.py") == [WEB]
    # 道具の側（台本、参照、偽のコントローラー）は、道具の分野。
    for path in ("tools/input_script_smoke.json", "tools/input_reference.py", "tools/web/fake_gamepad.js"):
        assert names_of(path) == [TOOLS_AREA], path


def test_verify_focused_plan_for_the_input_area_follows_the_plan_table():
    # 計画の表の「操作補正と入力」：run、drive、web-smoke。drive は、まだ無い手順。
    plan, kind, not_yet = verify.plan_for([area(INPUT)], [], focused=True)
    assert kind == "focused"
    assert step_names(plan) == ["check", "test", "run", "web-smoke"]
    # 計画の表の「操作補正、保存する項目、セッティングの順」のうち、操作補正（controls）と、保存する項目（profile）まで入っている。
    assert plan[1][1][-2:] == ["-k", INPUT_WORDS]
    assert not_yet == ["drive"]


def test_verify_vehicle_and_track_files_map_to_their_areas_and_follow_the_plan_table():
    # 計画の表の「車両」：テストの絞りは、車両、世界、指紋（セッティングの順は、まだ無い）。足す手順は run、drive。
    for path in ("clipping_point/cp_core/vehicle.py", "tests/test_vehicle.py"):
        assert names_of(path) == [VEHICLE], path
    plan, kind, not_yet = verify.plan_for([area(VEHICLE)], [], focused=True)
    assert kind == "focused" and step_names(plan) == ["check", "test", "run"] and not_yet == ["drive"]
    assert plan[1][1][-2:] == ["-k", VEHICLE_WORDS]
    # 計画の表の「コース」：テストの絞りは、コース、世界、指紋、データ。足す手順は run、tour、drive。
    for path in ("clipping_point/cp_core/track.py", "tests/test_track.py"):
        assert names_of(path) == [TRACK], path
    plan, kind, not_yet = verify.plan_for([area(TRACK)], [], focused=True)
    assert kind == "focused" and step_names(plan) == ["check", "test", "run", "tour"] and not_yet == ["drive"]
    assert plan[1][1][-2:] == ["-k", TRACK_WORDS]
    # 並びは、計画の表の順（車両、コース、操作補正と入力、…）。
    assert [a.name for a in verify.AREAS][:3] == [VEHICLE, TRACK, INPUT]
    areas, unknown = verify.areas_for(["tests/test_controls.py", "clipping_point/cp_core/track.py", "clipping_point/cp_core/vehicle.py"])
    assert [a.name for a in areas] == [VEHICLE, TRACK, INPUT] and unknown == []


def test_verify_save_and_rng_files_map_to_the_main_loop_area_and_the_browser_backends_to_the_web_area():
    # 計画の表の「保存、データの検査、乱数、メインループ、世界の状態」：全部を回す。
    for path in (
        "clipping_point/cp_core/storage.py", "clipping_point/cp_core/profile.py", "clipping_point/cp_core/rng.py",
        "clipping_point/cp_app/storage_file.py", "tests/test_storage.py", "tests/test_profile.py", "tests/test_rng.py",
        "tests/test_storage_file.py",
    ):
        assert names_of(path) == [LOOP], path
    assert area(LOOP).tests == verify.ALL and area(LOOP).steps == verify.ALL
    # 計画の表の「ブラウザ連携（入力の直読み、保存先、ファイルの受け渡し）」：localStorage の保存先と、保存先を選ぶ所。
    for path in (
        "clipping_point/cp_app/storage_web.py", "clipping_point/cp_app/storage_select.py",
        "tests/test_storage_web.py", "tests/test_storage_select.py",
    ):
        assert names_of(path) == [WEB], path
    plan, kind, not_yet = verify.plan_for([area(WEB)], [], focused=True)
    assert kind == "focused" and step_names(plan) == ["check", "test", "web-smoke"]
    assert plan[1][1][-2:] == ["-k", WEB_WORDS]  # 計画の表のテストの絞り「保存」（storage と profile）を足してある
    assert not_yet == []


def test_verify_fingerprint_files_map_to_the_tools_area_and_the_test_to_the_world_area_too():
    # 道具、ふるまいの写し、差し込むスクリプトは、道具の分野（selftest-break も回す）。
    for path in (
        "tools/fingerprint.py", "tests/snapshots/fingerprint.json", "tests/snapshots/profile_schema.json", "tools/web/block_storage.js",
    ):
        assert names_of(path) == [TOOLS_AREA], path
    # 指紋のテストは、世界の決定性と、道具の関数の両方を見る。
    assert names_of("tests/test_fingerprint.py") == [LOOP, TOOLS_AREA]
    areas, unknown = verify.areas_for(["tests/snapshots/fingerprint.json"])
    assert unknown == [] and step_names(verify.plan_for(areas, unknown)[0])[-1] == verify.SELFTEST


def test_verify_data_files_map_to_the_main_loop_area_and_the_load_checks_to_the_tools_area_too():
    # 計画の表の「保存、データの検査、乱数、メインループ、世界の状態」：全部を回す。ファイルを読む所、実物の定義データ、試験用データ。
    for path in (
        "clipping_point/cp_app/data_files.py", "clipping_point/data/cars.json", "clipping_point/data/tracks/test_loop.json",
        "clipping_point/data/assists.json",
        "testpacks/extreme/cars.json", "testpacks/extreme/tracks/wide_test_loop.json", "testpacks/another/cars.json",
        "tests/test_data_files.py",
    ):
        assert names_of(path) == [LOOP], path  # 中身が、車の値、コースの形、操作補正の値でも、実物の定義データは、ここ（全部を回す）
    # 読み込み検査の決まり（検査と重ね方）は、計画の表で selftest-break つきの分野（検査の決まり）でもある。
    for path in ("clipping_point/cp_core/datadefs.py", "tests/test_datadefs.py"):
        assert names_of(path) == [LOOP, TOOLS_AREA], path
        areas, unknown = verify.areas_for([path])
        assert unknown == [] and step_names(verify.plan_for(areas, unknown)[0])[-1] == verify.SELFTEST
    # 道具の側（数える所、節の関数のテスト）は、道具の分野。
    for path in ("tools/data_reference.py", "tests/test_check_tool.py", "tests/test_data_reference.py"):
        assert names_of(path) == [TOOLS_AREA], path
    # 実物の定義データは、1つずつ並べてある。新しいファイルは、分野を決めるまで当たらない（check の areas の節が落ちる）。
    assert names_of("clipping_point/data/tracks/zz_no_area.json") == []
    assert names_of("clipping_point/data/zz_no_area.json") == []
    # 実物の定義データの値を変えただけでは、selftest-break を回さない。
    areas, unknown = verify.areas_for(["clipping_point/data/cars.json", "testpacks/extreme/cars.json"])
    assert unknown == [] and verify.SELFTEST not in step_names(verify.plan_for(areas, unknown)[0])


def test_verify_run_with_the_test_pack_is_a_step_of_the_full_verification_right_after_the_realtime_run():
    # 試験用データを重ねて回す手順。重ねる口と、保存の名前空間の切り替えを、毎回通す。
    names = list(verify.STEPS)
    assert names[names.index("run-realtime") + 1] == "run-pack" and "run-pack" not in verify.NOT_YET
    assert [str(part) for part in verify.STEPS["run-pack"][1:]] == [str(ROOT / "tools" / "run.py"), "--pack", "extreme"]
    assert (ROOT / "testpacks" / "extreme").is_dir()  # 手順が渡す名の、試験用データがある


def test_verify_fingerprint_is_a_step_of_the_full_verification_right_after_the_tests():
    assert list(verify.STEPS)[:3] == ["check", "test", "fingerprint"]
    assert [str(part) for part in verify.STEPS["fingerprint"][1:]] == [str(ROOT / "tools" / "fingerprint.py")]  # --update は付けない
    assert "fingerprint" not in verify.NOT_YET


def test_verify_file_outside_every_area_is_unknown():
    assert names_of(NO_AREA_CODE) == []
    assert names_of(NO_AREA_TEST) == []
    areas, unknown = verify.areas_for([NO_AREA_CODE, "docs/plan.md", "tests/test_canvas.py"])
    assert [a.name for a in areas] == [UI]
    assert unknown == [NO_AREA_CODE, "docs/plan.md"]


def test_verify_new_file_next_to_listed_files_is_unknown():
    # 出荷するコードは1つずつ並べてある。同じディレクトリの新しいファイルは、分野を決めるまで当たらない。
    assert names_of("clipping_point/cp_ui/zz_no_area.py") == []
    assert names_of("clipping_point/cp_app/zz_no_area.py") == []


def test_verify_touched_areas_come_in_table_order_without_repeats():
    files = ["tools/run.py", "tests/test_web_bridge.py", "clipping_point/cp_ui/screens.py", "clipping_point/cp_ui/canvas.py"]
    areas, unknown = verify.areas_for(files)
    assert [a.name for a in areas] == [UI, WEB, TOOLS_AREA]
    assert unknown == []


def test_verify_file_that_hits_two_areas_touches_both():
    wide = verify.Area("wide", ("a/**",), "x", ("run",))
    narrow = verify.Area("narrow", ("a/x.py",), "y", ("web-smoke",))
    areas, unknown = verify.areas_for(["a/x.py"], areas=(wide, narrow))
    assert areas == [wide, narrow] and unknown == []


def test_verify_unassigned_file_in_a_repository_is_reported(tmp_path):
    for rel in ("clipping_point/cp_core/sim.py", NO_AREA_CODE, "tests/test_sim.py", "tests/__pycache__/x.pyc"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    count, problems = verify.unassigned_files(tmp_path)
    assert count == 3  # __pycache__ の中は数えない
    assert len(problems) == 1 and NO_AREA_CODE in problems[0]


# --- 分野ごとの組の表の中身 ---
def test_verify_every_step_name_in_the_table_is_known():
    known = set(verify.STEPS) | set(verify.NOT_YET)
    for a in verify.AREAS:
        if a.steps != verify.ALL:
            assert set(a.steps) <= known, a.name


def test_verify_every_test_word_in_the_table_matches_a_test_name():
    # tools/test.py の -k は、語がどのテスト名にも当たらないと2にする。絞った検証に切り替えた日に、まとめて出ないように。
    names = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        names.append(path.name.lower())
        names += [name.lower() for name in re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.M)]
    assert names
    for a in verify.AREAS:
        if a.tests != verify.ALL:
            for word in a.tests.split(" or "):
                assert any(word.lower() in name for name in names), f"{a.name}: {word}"


def test_verify_unknown_step_name_is_an_error_not_a_silent_drop():
    typo = verify.Area("typo", ("a/**",), "x", ("run", "web_smoke"))
    for focused in (False, True):
        with pytest.raises(ValueError):
            verify.plan_for([typo], [], focused=focused)


# --- 回す手順の決め方 ---
def test_verify_full_plan_runs_every_step_in_the_fixed_order():
    plan, kind, not_yet = verify.plan_for([], [], focused=False)
    assert step_names(plan) == FULL_STEPS
    assert kind == "full"
    assert not_yet == list(verify.NOT_YET)


def test_verify_any_area_runs_everything_while_focus_is_off():
    # 全体の検証が絞り始める目安を超えるまでは、どの分野でも全体を回す。
    assert verify.FOCUS_ENABLED is False
    plan, kind, _ = verify.plan_for([area(UI)], [])
    assert step_names(plan) == FULL_STEPS and kind == "full"


def test_verify_focused_plan_for_one_area():
    plan, kind, not_yet = verify.plan_for([area(UI)], [], focused=True)
    assert kind == "focused"
    # 手順は、全体の検証と同じ順に並ぶ（分野の行に書いた順ではない）。
    assert step_names(plan) == ["check", "test", "screen-check", "run", "tour"]
    assert plan[1][1][-2:] == ["-k", UI_WORDS]
    assert not_yet == []


def test_verify_focused_plan_joins_areas_in_the_fixed_order():
    plan, kind, _ = verify.plan_for([area(UI), area(WEB)], [], focused=True)
    assert kind == "focused"
    assert step_names(plan) == ["check", "test", "screen-check", "run", "tour", "web-smoke"]
    # 語は、分野の順に並べる。
    assert plan[1][1][-2:] == ["-k", f"{UI_WORDS} or {WEB_WORDS}"]


def test_verify_focused_plan_does_not_repeat_a_word_two_areas_share():
    plan, _, _ = verify.plan_for([area(INPUT), area(WEB)], [], focused=True)
    words = plan[1][1][-1].split(" or ")
    assert words == [*INPUT_WORDS.split(" or "), "web_bridge", "input_web", "storage"]  # profile は、1度だけ
    assert len(words) == len(set(words))


def test_verify_screen_check_and_tour_are_no_longer_waiting_to_be_built():
    assert "screen-check" in verify.STEPS and "tour" in verify.STEPS
    assert "screen-check" not in verify.NOT_YET and "tour" not in verify.NOT_YET
    # 全体の検証での順：check → test → fingerprint → screen-check → run → run-realtime → run-pack → tour → export → web-smoke。
    assert list(verify.STEPS) == FULL_STEPS


def test_verify_focused_plan_falls_back_to_everything():
    assert verify.plan_for([area(UI), area(LOOP)], [], focused=True)[1] == "full"  # 「全体の検証」の分野
    assert verify.plan_for([area(UI)], ["docs/plan.md"], focused=True)[1] == "full"  # どの分野にも当たらないファイル
    assert verify.plan_for([], [], focused=True)[1] == "full"  # 分野が無い


def test_verify_selftest_is_added_last_on_request_and_for_the_tools_area():
    assert step_names(verify.plan_for([], [])[0]) == FULL_STEPS
    assert step_names(verify.plan_for([], [], selftest=True)[0]) == [*FULL_STEPS, verify.SELFTEST]
    assert step_names(verify.plan_for([area(TOOLS_AREA)], [])[0]) == [*FULL_STEPS, verify.SELFTEST]
    assert step_names(verify.plan_for([area(UI)], [], focused=True, selftest=True)[0])[-1] == verify.SELFTEST


# --- 落ちた手順の数え方 ---
def test_verify_keeps_going_after_a_failed_step_and_counts_it(capsys):
    calls = []

    def runner(cmd, timeout):
        calls.append(cmd[0])
        return {"bad": (1, "bad: FAILED x=1\n", ""), "stuck": (None, "", "")}.get(cmd[0], (0, f"{cmd[0]}: OK\n", ""))

    plan = [("a", ["good"]), ("b", ["bad"]), ("c", ["stuck"]), ("d", ["good"])]
    rows = verify.run_plan(plan, runner=runner)
    capsys.readouterr()
    assert calls == ["good", "bad", "stuck", "good"]  # 落ちても最後まで回す
    assert [row["exit"] for row in rows] == [0, 1, "timeout", 0]
    assert rows[1]["summary"] == "bad: FAILED x=1"
    assert verify.failed_steps(plan, rows) == ["b", "c"]


def test_verify_step_that_cannot_start_counts_as_failed(capsys):
    def runner(cmd, timeout):
        raise FileNotFoundError(cmd[0])

    plan = [("a", ["no-such-command"])]
    rows = verify.run_plan(plan, runner=runner)
    capsys.readouterr()
    assert rows[0]["exit"] == "not-run"
    assert verify.failed_steps(plan, rows) == ["a"]


def test_verify_planned_step_without_a_row_counts_as_failed():
    plan = [("a", ["x"]), ("b", ["y"])]
    assert verify.failed_steps(plan, [{"step": "a", "exit": 0}]) == ["b"]
    assert verify.failed_steps(plan, [{"step": "a", "exit": 0}, {"step": "b", "exit": 0}]) == []


def test_verify_exit_2_of_a_step_is_not_a_pass():
    plan = [("web-smoke", ["x"])]
    assert verify.failed_steps(plan, [{"step": "web-smoke", "exit": 2}]) == ["web-smoke"]


def test_verify_last_line_prefers_stdout_then_stderr():
    assert verify.last_line("a\nb: OK\n\n", "noise") == "b: OK"
    assert verify.last_line("", "python3: can't open file\n") == "python3: can't open file"
    assert verify.last_line("", "") == "(no output)"


# --- 基点を選ぶ ---
def test_verify_base_is_the_latest_step_commit_not_a_midway_one():
    log = (
        "aaa 段0 区切り3（途中）：実装を退避\n"
        "bbb 進捗レポート：2026-11-11\n"
        "ccc 段0 区切り3（写しの取り直し）：理由\n"
        "ddd 段0 区切り2：骨組みと道具\n"
        "eee 段0 区切り1：文書の器\n"
    )
    assert verify.pick_base(log) == "ddd"


def test_verify_base_needs_the_subject_to_start_with_the_step_form():
    assert verify.pick_base("aaa 修正 段0 区切り2：骨組み\nbbb 段0 設計：下書き\nccc 改訂案0001：題\n") is None
    assert verify.pick_base("aaa 段0 区切り2：名前に（途中）を含む\n") is None
    assert verify.pick_base("aaa 段10 区切り12：二桁\n") == "aaa"
    assert verify.pick_base("") is None


# --- gitの出力を読む ---
def test_verify_changed_files_come_from_the_diff_and_the_untracked_entries():
    diff = "tools/run.py\0docs/a b.md\0tools/old.py\0tools/new.py\0"
    status = " M tools/run.py\0?? tests/test new.py\0R  tools/new.py\0tools/old.py\0D  docs/a b.md\0?? out put/x\0"
    assert verify.parse_changed(diff, status) == [
        "docs/a b.md", "out put/x", "tests/test new.py", "tools/new.py", "tools/old.py", "tools/run.py",
    ]


def test_verify_untracked_names_keep_their_first_character():
    assert verify.parse_changed("", "?? a\0?? tools/b.py\0") == ["a", "tools/b.py"]


def test_verify_old_name_of_a_rename_is_not_read_as_an_entry():
    # 名前の変更の項目の次の区切りは、元の名前。「?? 」で始まる名前でも、新しいファイルとして読まない。
    assert verify.parse_changed("", "R  new.py\0?? tricky\0") == []
    assert verify.parse_changed("", "R  new.py\0old.py\0?? real.py\0") == ["real.py"]


def test_verify_nothing_changed_reads_as_an_empty_list():
    assert verify.parse_changed("", "") == []
    assert verify.parse_changed("", " M tools/run.py\0") == []  # 管理下の変更は、diff の側から読む


# --- 一時のリポジトリで、gitを通して読む ---
def git(root, *args) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    return done.stdout.strip()


def write(root, rel, text):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def make_repo(tmp_path):
    """区切りのコミット、途中のコミット、未コミットの変更を持つ、一時のリポジトリ。返すのは (根, 区切りのコミット)。"""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    for rel in ("tools/run.py", "tools/old name.py", "clipping_point/cp_ui/canvas.py", "docs/a.md", "keep.txt"):
        write(root, rel, "one\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "段0 区切り2：骨組みと道具")
    step = git(root, "rev-parse", "HEAD")
    write(root, "tools/run.py", "two\n")
    git(root, "commit", "-q", "-am", "段0 区切り3（途中）：実装を退避")
    write(root, "clipping_point/cp_ui/canvas.py", "two\n")  # 未コミットの変更
    write(root, "tests/test new.py", "new\n")  # gitの管理に入っていない新しいファイル（名前に空白）
    (root / "docs/a.md").unlink()  # 消したファイル
    git(root, "mv", "tools/old name.py", "tools/new_name.py")  # 名前の変更
    return root, step


def test_verify_default_base_skips_midway_commits_in_a_real_repository(tmp_path):
    root, step = make_repo(tmp_path)
    assert verify.find_base(root) == step
    assert git(root, "rev-parse", "HEAD") != step


def test_verify_changed_files_since_the_step_commit_include_the_midway_commit(tmp_path):
    root, step = make_repo(tmp_path)
    assert verify.changed_files(step, root) == [
        "clipping_point/cp_ui/canvas.py", "docs/a.md", "tests/test new.py", "tools/new_name.py", "tools/old name.py", "tools/run.py",
    ]
    # HEAD を基点にすると、途中のコミットに入った変更（tools/run.py）が出ない。既定を HEAD にしない理由。
    assert "tools/run.py" not in verify.changed_files("HEAD", root)


def test_verify_repository_without_a_step_commit_has_no_base(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    write(root, "a.txt", "one\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "段0 区切り1（途中）：まだ途中")
    assert verify.find_base(root) is None


def test_verify_git_failures_read_as_none_not_as_no_changes(tmp_path):
    root, _ = make_repo(tmp_path)
    assert verify.changed_files("NO_SUCH_REV", root) is None
    assert verify.is_work_tree_root(root) is True
    assert verify.is_work_tree_root(root / "tools") is False  # 作業ツリーの根でない所
    outside = tmp_path / "plain"
    outside.mkdir()
    assert verify.is_work_tree_root(outside) is False
    assert verify.find_base(outside) is None
