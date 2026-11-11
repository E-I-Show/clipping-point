"""全体の検証の道具（tools/verify.py）のテスト。ファイルから分野を引く所、回す手順の決め方、落ちた手順の数え方。

道具を実際に順に回すこと（1本落ちると verify が1になること）は、道具 selftest-break が見る。
"""
import verify
from conftest import ROOT

UI = "画面（2D）"
WEB = "ブラウザ連携"
LOOP = "メインループと世界の状態"
TOOLS_AREA = "検証の道具と検査の決まり"
FULL_STEPS = ["check", "test", "run", "run-realtime", "export", "web-smoke"]


def names_of(path):
    return [area.name for area in verify.areas_of(path)]


def area(name):
    return next(a for a in verify.AREAS if a.name == name)


def step_names(plan):
    return [name for name, _ in plan]


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


def test_verify_file_outside_every_area_is_unknown():
    assert names_of("clipping_point/cp_core/vehicle.py") == []
    assert names_of("tests/test_vehicle.py") == []
    areas, unknown = verify.areas_for(["clipping_point/cp_core/vehicle.py", "docs/plan.md", "tests/test_canvas.py"])
    assert [a.name for a in areas] == [UI]
    assert unknown == ["clipping_point/cp_core/vehicle.py", "docs/plan.md"]


def test_verify_touched_areas_come_in_table_order_without_repeats():
    files = ["tools/run.py", "tests/test_web_bridge.py", "clipping_point/cp_ui/screens.py", "clipping_point/cp_ui/canvas.py"]
    areas, unknown = verify.areas_for(files)
    assert [a.name for a in areas] == [UI, WEB, TOOLS_AREA]
    assert unknown == []


def test_verify_unassigned_file_in_a_repository_is_reported(tmp_path):
    for rel in ("clipping_point/cp_core/sim.py", "clipping_point/cp_core/vehicle.py", "tests/test_sim.py", "tests/__pycache__/x.pyc"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    count, problems = verify.unassigned_files(tmp_path)
    assert count == 3  # __pycache__ の中は数えない
    assert len(problems) == 1 and "clipping_point/cp_core/vehicle.py" in problems[0]


def test_verify_full_plan_runs_every_step_in_the_fixed_order():
    plan, kind, not_yet = verify.plan_for([], [], focused=False)
    assert step_names(plan) == FULL_STEPS
    assert kind == "full"
    assert not_yet == list(verify.NOT_YET)


def test_verify_any_area_runs_everything_while_focus_is_off():
    # 全体の検証が3分を超えるまでは、どの分野でも全体を回す。
    assert verify.FOCUS_ENABLED is False
    plan, kind, _ = verify.plan_for([area(UI)], [])
    assert step_names(plan) == FULL_STEPS and kind == "full"


def test_verify_focused_plan_for_one_area():
    plan, kind, not_yet = verify.plan_for([area(UI)], [], focused=True)
    assert kind == "focused"
    assert step_names(plan) == ["check", "test", "run"]
    assert plan[1][1][-2:] == ["-k", "canvas or screens"]
    assert not_yet == ["screen-check", "tour"]


def test_verify_focused_plan_joins_areas_in_the_fixed_order():
    plan, kind, _ = verify.plan_for([area(UI), area(WEB)], [], focused=True)
    assert kind == "focused"
    assert step_names(plan) == ["check", "test", "run", "web-smoke"]
    assert plan[1][1][-2:] == ["-k", "canvas or screens or web_bridge"]


def test_verify_focused_plan_falls_back_to_everything():
    assert verify.plan_for([area(UI), area(LOOP)], [], focused=True)[1] == "full"  # 「全体の検証」の分野
    assert verify.plan_for([area(UI)], ["docs/plan.md"], focused=True)[1] == "full"  # どの分野にも当たらないファイル
    assert verify.plan_for([], [], focused=True)[1] == "full"  # 分野が無い


def test_verify_selftest_is_added_last_on_request_and_for_the_tools_area():
    assert step_names(verify.plan_for([], [])[0]) == FULL_STEPS
    assert step_names(verify.plan_for([], [], selftest=True)[0]) == [*FULL_STEPS, verify.SELFTEST]
    assert step_names(verify.plan_for([area(TOOLS_AREA)], [])[0]) == [*FULL_STEPS, verify.SELFTEST]
    assert step_names(verify.plan_for([area(UI)], [], focused=True, selftest=True)[0])[-1] == verify.SELFTEST


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
