"""指紋テスト（守りのテスト）。決まった筋書きで世界を回した要約（指紋）を、ふるまいの写し（tests/snapshots/fingerprint.json）と比べる。

道具 `python3 tools/fingerprint.py` と同じ関数で照らす。指紋の写しが無ければ、失敗にする（黙って作らない）。
指紋の写しを取り直す口は `python3 tools/fingerprint.py --update` だけ。取り直しは、単独のコミットで、理由を添える。
合否は、世界の要約だけで決める。環境の値（Pythonの版、数学関数の試し値）が、指紋の写しと違っても、ここでは落とさない。
文字列の集合の順に頼っていないことは、ハッシュの種（PYTHONHASHSEED）を変えた別プロセスで回して見る。
保存する項目の一覧の写しのテストは tests/test_profile.py。
走行の下限（筋書きの、走行が成り立っていることの確かめ）も、ここで見る。満たさなければ、道具は1で、--update は、何も書かない。
"""
import dataclasses
import functools
import json
import os
import subprocess
import sys

import pytest

import fingerprint
import input_reference
from conftest import ROOT
from cp_core.input_frame import BUTTONS, NEUTRAL, InputFrame

SCRIPT_SCENARIO = fingerprint.SCENARIOS[0]  # 道具の台本を回す筋書き。ボタンを2個押す区間を通る
NO_SCRIPT_SCENARIO = fingerprint.SCENARIOS[1]  # 台本なしの筋書き。車は、止まったまま
DRIVE_SCENARIO = fingerprint.SCENARIOS[2]  # 走る台本の筋書き
WALL_SCENARIO = fingerprint.SCENARIOS[3]  # 壁の台本の筋書き
HASH_SEEDS = ("0", "1", "12345")
# 別プロセスで回すコード。筋書きの要約と、文字列の集合（ボタンの名の集合）を回した順と、受け取ったハッシュの種を返す。
CHILD_CODE = (
    "import json, os, sys\n"
    "sys.dont_write_bytecode = True\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import fingerprint\n"
    "from cp_core.input_frame import BUTTONS\n"
    "print(json.dumps({\n"
    "    'hash_seed': os.environ.get('PYTHONHASHSEED'),\n"
    "    'set_order': list(frozenset(BUTTONS)),\n"
    "    'summaries': {scenario.name: fingerprint.summary_of(scenario) for scenario in fingerprint.SCENARIOS},\n"
    "}))\n"
)


def snapshot() -> dict:
    recorded = fingerprint.read_fingerprint_snapshot(ROOT)
    assert recorded is not None, f"指紋の写し（{fingerprint.FINGERPRINT_SNAPSHOT}）が無いか、読めない。黙って作らない"
    return recorded


def run_scenario(scenario, extra_ticks: int = 0, seed=None, change_tick=None) -> dict:
    """筋書きを、手で回す。extra_ticks は、余分に回すtick数。change_tick は、入力を1つ変えるtick。"""
    _, script = fingerprint.load_scenario_script(scenario)
    sim = input_reference.make_sim(scenario.seed if seed is None else seed, None, scenario.car, scenario.track)
    for tick in range(scenario.ticks + extra_ticks):
        frame = input_reference.frame_at(script, tick)
        if tick == change_tick:
            frame = InputFrame(throttle_digital=1 - frame.throttle_digital)
        sim.step(frame)
    return sim.summary()


# --- 指紋の写しと同じこと ---
@pytest.mark.parametrize("scenario", fingerprint.SCENARIOS, ids=[scenario.name for scenario in fingerprint.SCENARIOS])
def test_fingerprint_world_summary_matches_the_snapshot(scenario):
    # 世界の式を変えると、ここが落ちる。意図した変更なら、単独のコミットで、理由を添えて、指紋の写しを取り直す。
    recorded = fingerprint.recorded_summary(snapshot(), scenario)
    assert recorded is not None, f"筋書き {scenario.name} が、指紋の写しに無い"
    current = fingerprint.summary_of(scenario)
    assert current["tick"] == scenario.ticks > 0
    assert fingerprint.diff_values(recorded, current, scenario.name) == []
    assert current == recorded


def test_fingerprint_snapshot_and_the_code_name_the_same_scenarios():
    recorded = snapshot()
    assert fingerprint.compare_scenarios(recorded["scenarios"], fingerprint.current_scenarios()) == []
    assert sorted(recorded["scenarios"]) == sorted(scenario.name for scenario in fingerprint.SCENARIOS)


def test_fingerprint_snapshot_carries_the_python_version_and_the_math_probes():
    # 合否には使わない。環境が変わったことと、退行を見分けるための値。
    environment = snapshot()["environment"]
    parts = environment["python"].split(".")
    assert len(parts) == 3 and all(part.isdigit() for part in parts)  # 3.13.5 の形の、3つの数
    assert sorted(environment["math"]) == ["atan2", "cos", "exp", "hypot", "sin", "sqrt", "tan"]
    assert all(type(value) is str and len(value) == 16 and int(value, 16) >= 0 for value in environment["math"].values())


def test_fingerprint_environment_differences_do_not_fail_the_world_comparison():
    recorded = snapshot()
    # 比べる相手は、いまの環境の値から作る（Pythonの版と、sin だけを置き換える）。指紋の写しの環境の値からは作らない。
    # 指紋の写しから作ると、指紋の写しといまの環境で、ほかの試し値（cos など）が違うだけで、返る行が増えて、ここが落ちる。
    current = fingerprint.environment()
    other = {"python": "9.9.9", "math": {**current["math"], "sin": "0" * 16}}
    lines = fingerprint.environment_changed(other, current)
    assert len(lines) == 2 and "python" in lines[0] and "sin" in lines[1]
    # 環境の値は、筋書きの比べ方に入っていない。
    assert fingerprint.compare_scenarios(recorded["scenarios"], fingerprint.current_scenarios()) == []
    assert fingerprint.environment_changed(fingerprint.environment(), fingerprint.environment()) == []


# --- 筋書き ---
def test_fingerprint_scenarios_are_the_two_runs_of_the_full_verification():
    script, no_script = fingerprint.SCENARIOS[:2]
    assert (script.name, script.script, script.ticks, script.seed) == ("script_120", input_reference.SMOKE_SCRIPT, 120, 0)
    assert (no_script.name, no_script.script, no_script.ticks, no_script.seed) == ("no_script_120", None, 120, 0)
    assert fingerprint.script_name(script) == "tools/input_script_smoke.json" and fingerprint.script_name(no_script) is None
    # run の既定（道具の台本、120 tick）と、run --realtime の既定（台本なし、120 tick）が、どちらも筋書きに当たる。
    script_value, _ = input_reference.load_script(input_reference.SMOKE_SCRIPT)
    assert fingerprint.scenario_for(script_value, 120) is script
    assert fingerprint.scenario_for(None, 120) is no_script
    # 同じ筋書きが無い回し方。
    assert fingerprint.scenario_for(script_value, 200) is None and fingerprint.scenario_for(None, 121) is None
    assert fingerprint.scenario_for({"segments": [{"ticks": 3}]}, 120) is None
    assert script.floors == () and no_script.floors == ()  # 車が、ほとんど動かない筋書き。走行の下限は、持たない


def test_fingerprint_drive_and_wall_scenarios_come_last_and_are_the_two_script_runs_of_the_full_verification():
    import verify

    assert [scenario.name for scenario in fingerprint.SCENARIOS] == ["script_120", "no_script_120", "drive_900", "wall_780"]
    assert (DRIVE_SCENARIO.script, DRIVE_SCENARIO.ticks, DRIVE_SCENARIO.seed) == (input_reference.DRIVE_SCRIPT, 900, 0)
    assert (WALL_SCENARIO.script, WALL_SCENARIO.ticks, WALL_SCENARIO.seed) == (input_reference.WALL_SCRIPT, 780, 0)
    assert fingerprint.script_name(DRIVE_SCENARIO) == "tools/input_script_drive.json"
    assert fingerprint.script_name(WALL_SCENARIO) == "tools/input_script_wall.json"
    for scenario, step in ((DRIVE_SCENARIO, "run-drive"), (WALL_SCENARIO, "run-wall")):
        value, script = fingerprint.load_scenario_script(scenario)
        assert script.total_ticks == scenario.ticks  # 台本の終わりまで、回す
        assert fingerprint.scenario_for(value, scenario.ticks) is scenario
        # 全体の検証の手順が、同じ台本を、同じtick数で、アプリに通す（道具 run が、指紋の写しと、走行の下限を照らす）。
        words = [str(part) for part in verify.STEPS[step][1:]]
        assert words == [str(ROOT / "tools" / "run.py"), "--script", str(scenario.script), "--ticks", str(scenario.ticks)]


def test_fingerprint_every_scenario_names_the_car_and_the_track_of_the_one_place_in_the_tools():
    for scenario in fingerprint.SCENARIOS:
        assert (scenario.car, scenario.track) == (input_reference.CAR_ID, input_reference.TRACK_ID) == ("kazane", "test_loop")
        summary = fingerprint.summary_of(scenario)
        assert (summary["car"], summary["track"]) == (scenario.car, scenario.track)  # 要約だけで、どの車とコースで回ったかを照らせる
    other = dataclasses.replace(NO_SCRIPT_SCENARIO, car="no_such_car")
    with pytest.raises(ValueError):
        fingerprint.summary_of(other)


# --- 走行の下限 ---
def test_fingerprint_drive_and_wall_scenarios_meet_their_floors():
    for scenario in (DRIVE_SCENARIO, WALL_SCENARIO):
        assert scenario.floors and fingerprint.floor_problems(scenario, fingerprint.summary_of(scenario)) == []
    assert fingerprint.floor_lines(fingerprint.current_scenarios()) == []
    # 走る台本：進行距離、最高速、変速の回数、最後に舗装の上、壁に当たっていない、照会を取り直していない。
    assert {name for name, _, _ in DRIVE_SCENARIO.floors} == {"odometer_mm", "top_speed_mm_s", "shifts", "surface", "wall_hits", "requery_count"}
    assert ("requery_count", "==", 0) in DRIVE_SCENARIO.floors and ("wall_hits", "==", 0) in DRIVE_SCENARIO.floors
    # 壁の台本：壁に当たった回数、後退に入った回数、最後に前進に戻っている、最後の進行距離。
    assert {name for name, _, _ in WALL_SCENARIO.floors} == {"wall_hits", "reverse_count", "gear", "odometer_mm"}
    # 下限は、要約の項目の名で書いてある。
    names = set(fingerprint.summary_of(NO_SCRIPT_SCENARIO))
    assert all(name in names and op in fingerprint.FLOOR_OPS for scenario in fingerprint.SCENARIOS for name, op, _ in scenario.floors)


def test_fingerprint_floors_are_real_bounds_not_the_values_of_a_car_that_stands_still():
    # 止まったままの車の要約（台本なしの筋書き）は、走る台本の下限も、壁の台本の下限も、満たさない。
    still = fingerprint.summary_of(NO_SCRIPT_SCENARIO)
    drive_lines = fingerprint.floor_problems(DRIVE_SCENARIO, still)
    assert len(drive_lines) == 3 and all("drive_900" in line for line in drive_lines)
    assert [line.split("：")[1].split(" ")[0] for line in drive_lines] == ["odometer_mm", "top_speed_mm_s", "shifts"]
    assert len(fingerprint.floor_problems(WALL_SCENARIO, still)) == 3  # 壁に当たっていない、後退に入っていない、進んでいない
    # 走る台本の要約は、壁の台本の下限を満たさない（逆も）。
    drive, wall = fingerprint.summary_of(DRIVE_SCENARIO), fingerprint.summary_of(WALL_SCENARIO)
    assert fingerprint.floor_problems(WALL_SCENARIO, drive) and fingerprint.floor_problems(DRIVE_SCENARIO, wall)


@pytest.mark.parametrize(
    "change, name",
    [
        ({"odometer_mm": 229_999}, "odometer_mm"),
        ({"top_speed_mm_s": 23_999}, "top_speed_mm_s"),
        ({"shifts": 1}, "shifts"),
        ({"surface": "grass"}, "surface"),
        ({"wall_hits": 1}, "wall_hits"),
        ({"requery_count": 1}, "requery_count"),  # 照会を、1度でも取り直した
        ({"requery_count": 900}, "requery_count"),  # 毎tick、全部を探した（答えは同じで、遅いだけの退行）
        ({"odometer_mm": 258687.0}, "odometer_mm"),  # 小数は、満たさない（要約は、整数と文字列だけ）
        ({"shifts": True}, "shifts"),
        ({"wall_hits": False}, "wall_hits"),  # 0 と false を、同じに見ない
        ({"surface": None}, "surface"),
    ],
)
def test_fingerprint_each_drive_floor_fails_under_the_name_of_its_item(change, name):
    summary = {**fingerprint.summary_of(DRIVE_SCENARIO), **change}
    lines = fingerprint.floor_problems(DRIVE_SCENARIO, summary)
    assert len(lines) == 1 and f"：{name} が" in lines[0] and "drive_900" in lines[0]


def test_fingerprint_floor_of_a_missing_item_or_of_no_summary_is_not_met():
    summary = fingerprint.summary_of(WALL_SCENARIO)
    without = {key: value for key, value in summary.items() if key != "reverse_count"}
    assert len(fingerprint.floor_problems(WALL_SCENARIO, without)) == 1
    for nothing in (None, [], "summary", {}):
        assert len(fingerprint.floor_problems(WALL_SCENARIO, nothing)) == len(WALL_SCENARIO.floors)
    assert fingerprint.floor_problems(NO_SCRIPT_SCENARIO, None) == []  # 下限の無い筋書き


def test_fingerprint_script_scenario_goes_through_segments_with_two_buttons_held():
    # 文字列の集合の順が効きうる所（2個以上のボタンを、同時に押している区間）を、筋書きが通っていること。
    _, script = fingerprint.load_scenario_script(SCRIPT_SCENARIO)
    held_sizes = [len(script.frame_at(tick).held) for tick in range(SCRIPT_SCENARIO.ticks)]
    assert held_sizes.count(2) >= 20 and SCRIPT_SCENARIO.ticks >= script.total_ticks


def test_fingerprint_summary_is_repeatable_in_one_process():
    for scenario in fingerprint.SCENARIOS:
        assert fingerprint.summary_of(scenario) == fingerprint.summary_of(scenario) == run_scenario(scenario)


# --- 指紋が、変化を拾うこと ---
@pytest.mark.parametrize("scenario", fingerprint.SCENARIOS, ids=[scenario.name for scenario in fingerprint.SCENARIOS])
def test_fingerprint_one_more_tick_changes_the_summary(scenario):
    base, longer = run_scenario(scenario), run_scenario(scenario, extra_ticks=1)
    assert base != longer
    assert base["tick"] + 1 == longer["tick"] and base["input_digest"] != longer["input_digest"]


@pytest.mark.parametrize("scenario", fingerprint.SCENARIOS, ids=[scenario.name for scenario in fingerprint.SCENARIOS])
@pytest.mark.parametrize("tick", [0, 37, 119])
def test_fingerprint_one_changed_input_changes_the_summary(scenario, tick):
    base, changed = run_scenario(scenario), run_scenario(scenario, change_tick=tick)
    assert base["tick"] == changed["tick"]
    assert base["input_digest"] != changed["input_digest"]


def test_fingerprint_another_seed_changes_the_stream_states():
    base, other = run_scenario(SCRIPT_SCENARIO), run_scenario(SCRIPT_SCENARIO, seed=1)
    assert base["seed"] == 0 and other["seed"] == 1
    assert base["rng_ai"] != other["rng_ai"]
    assert base["tick"] == other["tick"] and base["input_digest"] == other["input_digest"]  # 入力の側は、種に頼らない


def test_fingerprint_the_scenarios_have_different_summaries():
    script, no_script, drive, wall = (fingerprint.summary_of(scenario) for scenario in fingerprint.SCENARIOS)
    assert len({summary["input_digest"] for summary in (script, no_script, drive, wall)}) == 4
    assert no_script == input_reference.sim_summary(None, 120)
    neutral = input_reference.make_sim()
    for _ in range(120):
        neutral.step(NEUTRAL)
    assert no_script == neutral.summary()
    # 台本なしの筋書きでは、車は、スタート位置から動かない。走る台本と壁の台本では、車の項目が、大きく動く。
    assert (no_script["x_mm"], no_script["odometer_mm"], no_script["top_speed_mm_s"]) == (60000, 0, 0)
    assert drive["odometer_mm"] > 200_000 and drive["z_mm"] > 50_000 and wall["reverse_count"] == 1


def test_fingerprint_a_changed_input_moves_the_car_items_of_the_drive_scenario():
    # 走る台本の途中で、入力を1つ変える（コーナーの手前の、ブレーキの1 tickを、全開のアクセルに替える）。入力の要約値だけでなく、
    # 車の項目も変わる（止まったままの筋書きでは、何を変えても、車の項目が動かない）。
    _, script = fingerprint.load_scenario_script(DRIVE_SCENARIO)
    assert script.frame_at(500).brake_analog > 0.0
    base, changed = run_scenario(DRIVE_SCENARIO), run_scenario(DRIVE_SCENARIO, change_tick=500)
    moved = {name for name in base if base[name] != changed[name]}
    assert {"input_digest", "x_mm", "z_mm", "s_mm", "odometer_mm"} <= moved


# --- 比べ方 ---
def test_fingerprint_diff_names_the_item_and_the_old_and_new_values():
    recorded = {"tick": 120, "input_digest": 5, "seed": 0, "rng_ai": "00000000000000aa"}
    assert fingerprint.diff_values(recorded, dict(recorded), "s") == []
    lines = fingerprint.diff_values(recorded, {**recorded, "input_digest": 6}, "筋書き script_120 の要約")
    assert lines == ["筋書き script_120 の要約.input_digest: 5 から 6 へ変わった"]
    assert len(fingerprint.diff_values(recorded, {**recorded, "cars": 1}, "s")) == 1  # 足した項目
    assert len(fingerprint.diff_values(recorded, {"tick": 120}, "s")) == 3  # 消えた項目
    assert len(fingerprint.diff_values({"flag": 1}, {"flag": True}, "s")) == 1  # 1 と true を、同じに見ない


def test_fingerprint_scenario_comparison_reports_added_removed_and_changed_scenarios():
    current = fingerprint.current_scenarios()
    name = SCRIPT_SCENARIO.name
    assert fingerprint.compare_scenarios(current, current) == []
    assert len(fingerprint.compare_scenarios({key: value for key, value in current.items() if key != name}, current)) == 1
    assert len(fingerprint.compare_scenarios({**current, "extra": current[name]}, current)) == 1
    longer = {**current, name: {**current[name], "ticks": 121}}
    assert any("ticks" in line for line in fingerprint.compare_scenarios(longer, current))
    moved = {**current, name: {**current[name], "summary": {**current[name]["summary"], "rng_ai": "0" * 16}}}
    lines = fingerprint.compare_scenarios(moved, current)
    assert len(lines) == 1 and name in lines[0] and "rng_ai" in lines[0]


# --- ふるまいの写しの読み書き（一時の置き場で） ---
def write_snapshots(root, fingerprint_text=None, schema_text=None) -> None:
    folder = root / "tests" / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    if fingerprint_text is not None:
        (folder / "fingerprint.json").write_text(fingerprint_text, encoding="utf-8")
    if schema_text is not None:
        (folder / "profile_schema.json").write_text(schema_text, encoding="utf-8")


def last_line(capsys) -> str:
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_fingerprint_update_writes_both_snapshots_and_names_what_changed(tmp_path, capsys):
    assert fingerprint.update(tmp_path) == 0
    assert "updated=2 changed=fingerprint.json,profile_schema.json" in last_line(capsys)
    written = fingerprint.read_fingerprint_snapshot(tmp_path)
    assert written["scenarios"] == fingerprint.current_scenarios() and written["environment"] == fingerprint.environment()
    assert fingerprint.read_schema_snapshot(tmp_path) == fingerprint.current_schema()
    # もう一度書いても、変わらない。
    assert fingerprint.update(tmp_path) == 0
    assert "updated=2 changed=none" in last_line(capsys)
    # 片方だけが古ければ、その名だけを出す。
    write_snapshots(tmp_path, schema_text=json.dumps({"version": 1, "fields": {}}))
    assert fingerprint.update(tmp_path) == 0
    assert "updated=2 changed=profile_schema.json" in last_line(capsys)
    assert fingerprint.check(tmp_path) == 0
    assert "problems=0 env=same" in last_line(capsys)


def test_fingerprint_snapshot_files_explain_themselves(tmp_path, capsys):
    fingerprint.update(tmp_path)
    capsys.readouterr()
    for rel in (fingerprint.FINGERPRINT_SNAPSHOT, fingerprint.SCHEMA_SNAPSHOT):
        data = json.loads((tmp_path / rel).read_text(encoding="utf-8"))
        assert "tools/fingerprint.py --update" in data["_notes"] and "単独のコミット" in data["_notes"]


@pytest.mark.parametrize("missing", ["fingerprint.json", "profile_schema.json"])
def test_fingerprint_check_with_a_missing_snapshot_is_2_and_writes_nothing(tmp_path, capsys, missing):
    fingerprint.update(tmp_path)
    (tmp_path / "tests" / "snapshots" / missing).unlink()
    assert fingerprint.check(tmp_path) == 2
    line = last_line(capsys)
    assert "reason=no_snapshot" in line and f"missing={missing}" in line
    assert not (tmp_path / "tests" / "snapshots" / missing).exists()  # 黙って作らない


@pytest.mark.parametrize("text", ["{not json", "[]", "{}", '{"environment": {}, "scenarios": []}', '{"environment": {}, "scenarios": {"a": 1}}'])
def test_fingerprint_unreadable_fingerprint_snapshot_reads_as_none(tmp_path, text):
    write_snapshots(tmp_path, fingerprint_text=text)
    assert fingerprint.read_fingerprint_snapshot(tmp_path) is None


@pytest.mark.parametrize("text", ["{not json", "[]", "{}", '{"version": "1", "fields": {}}', '{"version": 1, "fields": []}', '{"version": true, "fields": {}}'])
def test_fingerprint_unreadable_schema_snapshot_reads_as_none(tmp_path, text):
    write_snapshots(tmp_path, schema_text=text)
    assert fingerprint.read_schema_snapshot(tmp_path) is None


def test_fingerprint_check_fails_on_a_world_change_and_names_it(tmp_path, capsys):
    fingerprint.update(tmp_path)
    path = tmp_path / fingerprint.FINGERPRINT_SNAPSHOT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenarios"]["script_120"]["summary"]["input_digest"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert fingerprint.check(tmp_path) == 1
    out = capsys.readouterr().out
    assert "筋書き script_120 の要約.input_digest" in out and "環境が変わった" not in out
    assert "problems=1 failed=world env=same" in out.strip().splitlines()[-1]


def test_fingerprint_check_fails_on_a_schema_change_and_names_it(tmp_path, capsys):
    fingerprint.update(tmp_path)
    path = tmp_path / fingerprint.SCHEMA_SNAPSHOT
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["fields"]["Settings.view"]
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert fingerprint.check(tmp_path) == 1
    out = capsys.readouterr().out
    assert "Settings.view" in out
    assert "problems=1 failed=schema env=same" in out.strip().splitlines()[-1]


def test_fingerprint_check_passes_when_only_the_environment_changed(tmp_path, capsys):
    fingerprint.update(tmp_path)
    path = tmp_path / fingerprint.FINGERPRINT_SNAPSHOT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["environment"]["python"] = "3.12.0"
    data["environment"]["math"]["atan2"] = "f" * 16
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert fingerprint.check(tmp_path) == 0  # 環境の値だけの違いでは、落とさない
    out = capsys.readouterr().out
    assert "problems=0 env=changed" in out.strip().splitlines()[-1]
    assert "環境：" in out and "環境が変わった" not in out  # 何が違うかは出す


def test_fingerprint_check_says_the_environment_changed_first_when_the_world_differs_too(tmp_path, capsys):
    fingerprint.update(tmp_path)
    path = tmp_path / fingerprint.FINGERPRINT_SNAPSHOT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["environment"]["math"]["sin"] = "0" * 16
    data["scenarios"]["no_script_120"]["summary"]["input_digest"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert fingerprint.check(tmp_path) == 1
    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line.strip()]
    assert "環境が変わった" in lines[0]  # 先に出す
    assert any("筋書き no_script_120 の要約.input_digest" in line for line in lines[1:])
    assert "problems=1 failed=world env=changed" in lines[-1]


def with_an_unmet_floor() -> tuple:
    """筋書きの一覧の、台本なしの筋書きに、満たせない下限（止まったままの車に、進行距離1 mm以上）を足したもの。"""
    stuck = dataclasses.replace(NO_SCRIPT_SCENARIO, floors=(("odometer_mm", ">=", 1),))
    return tuple(stuck if scenario is NO_SCRIPT_SCENARIO else scenario for scenario in fingerprint.SCENARIOS)


def test_fingerprint_check_fails_on_an_unmet_floor_even_when_the_snapshot_is_the_same(tmp_path, capsys):
    fingerprint.update(tmp_path)
    capsys.readouterr()
    assert fingerprint.check(tmp_path) == 0
    assert fingerprint.check(tmp_path, with_an_unmet_floor()) == 1  # 写しと同じでも、走行が成り立っていなければ、落とす
    out = capsys.readouterr().out
    assert "筋書き no_script_120 の走行の下限：odometer_mm が 0（>= 1 のはず）" in out
    assert "scenarios=4 fields=6 problems=1 failed=floor env=same" in out.strip().splitlines()[-1]


def test_fingerprint_update_writes_nothing_when_a_floor_is_not_met(tmp_path, capsys):
    # 走行が成り立っていない筋書きの要約を、写しにしない。何も書かずに、1。
    assert fingerprint.update(tmp_path, with_an_unmet_floor()) == 1
    out = capsys.readouterr().out
    assert "updated=0 reason=floor_not_met floors=1" in out.strip().splitlines()[-1] and "no_script_120" in out
    assert not (tmp_path / "tests").exists()
    # 前の写しがあれば、そのまま残す（2つとも、書き換えない）。
    assert fingerprint.update(tmp_path) == 0
    before = {rel: (tmp_path / rel).read_bytes() for rel in (fingerprint.FINGERPRINT_SNAPSHOT, fingerprint.SCHEMA_SNAPSHOT)}
    (tmp_path / fingerprint.SCHEMA_SNAPSHOT).write_text(json.dumps({"version": 1, "fields": {}}), encoding="utf-8")
    stale = (tmp_path / fingerprint.SCHEMA_SNAPSHOT).read_bytes()
    capsys.readouterr()
    assert fingerprint.update(tmp_path, with_an_unmet_floor()) == 1
    assert "reason=floor_not_met" in last_line(capsys)
    assert (tmp_path / fingerprint.FINGERPRINT_SNAPSHOT).read_bytes() == before[fingerprint.FINGERPRINT_SNAPSHOT]
    assert (tmp_path / fingerprint.SCHEMA_SNAPSHOT).read_bytes() == stale  # 保存する項目の一覧の写しも、書かない


def test_fingerprint_check_never_rewrites_the_snapshots(tmp_path, capsys):
    fingerprint.update(tmp_path)
    path = tmp_path / fingerprint.FINGERPRINT_SNAPSHOT
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scenarios"]["script_120"]["summary"]["tick"] = 119
    path.write_text(json.dumps(data), encoding="utf-8")
    before = {rel: (tmp_path / rel).read_bytes() for rel in (fingerprint.FINGERPRINT_SNAPSHOT, fingerprint.SCHEMA_SNAPSHOT)}
    assert fingerprint.check(tmp_path) == 1
    capsys.readouterr()
    assert {rel: (tmp_path / rel).read_bytes() for rel in before} == before


def test_fingerprint_tool_has_one_update_switch_and_check_does_not_take_it(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(fingerprint, "update", lambda: calls.append("update") or 0)
    monkeypatch.setattr(fingerprint, "check", lambda: calls.append("check") or 0)
    monkeypatch.setattr(sys, "argv", ["fingerprint.py"])
    assert fingerprint.main() == 0
    monkeypatch.setattr(sys, "argv", ["fingerprint.py", "--update"])
    assert fingerprint.main() == 0
    assert calls == ["check", "update"]


# --- 数学関数の試し値 ---
def test_fingerprint_math_probes_are_one_digest_per_function_and_repeatable():
    probes = fingerprint.math_probes()
    assert sorted(probes) == ["atan2", "cos", "exp", "hypot", "sin", "sqrt", "tan"]
    assert probes == fingerprint.math_probes()
    assert len(set(probes.values())) == 7
    assert fingerprint.math_probes(100) != fingerprint.math_probes(101)  # 入力の数を変えると、値が変わる


def test_fingerprint_digest_sees_the_last_bit_of_a_float():
    values = [0.1, 0.2, 0.30000000000000004]
    assert fingerprint.digest_of(values) == fingerprint.digest_of(list(values))
    assert fingerprint.digest_of(values) != fingerprint.digest_of([0.1, 0.2, 0.3])  # 最下位の1ビットの違い
    assert len(fingerprint.digest_of(values)) == 16


def test_fingerprint_environment_python_version_is_three_numbers():
    assert fingerprint.environment()["python"] == ".".join(str(part) for part in sys.version_info[:3])


# --- 文字列の集合の順に頼っていないこと（ハッシュの種を変えた別プロセス） ---
@functools.cache
def run_child(hash_seed: str) -> dict:
    """ハッシュの種を決めた別プロセスで、筋書きを回す。同じ種の結果は、使い回す。"""
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", CHILD_CODE, str(ROOT / "tools")], capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def test_fingerprint_does_not_depend_on_the_hash_seed():
    # 層の分離の検査は、集合の順への頼りを拾えない。文字列の集合を回した順は、ハッシュの種ごとに変わる。
    # ここで見るのは、別プロセスどうしの比べだけ（指紋の写しとは比べない。比べるのは、下のテスト）。
    results = {seed: run_child(seed) for seed in HASH_SEEDS}
    # (1) 環境変数が、別プロセスへ届いている。
    assert {seed: result["hash_seed"] for seed, result in results.items()} == {seed: seed for seed in HASH_SEEDS}
    # (2) 文字列の集合を回した順が、3通りの間で実際に違う（種が効いている。順が同じなら、下の (3) は何も見ていない）。
    orders = [tuple(results[seed]["set_order"]) for seed in HASH_SEEDS]
    assert all(sorted(order) == sorted(BUTTONS) for order in orders)
    assert len(set(orders)) == len(HASH_SEEDS), f"集合を回した順が、ハッシュの種を変えても同じ：{orders}"
    # (3) それでも、世界の要約は同じ。筋書きは、全部（道具の台本はボタンの集合を通り、走る台本と壁の台本は、変速、後退、壁、芝を通る）。
    summaries = [results[seed]["summaries"] for seed in HASH_SEEDS]
    assert list(summaries[0]) == [scenario.name for scenario in fingerprint.SCENARIOS]
    for name in summaries[0]:
        assert summaries[0][name] == summaries[1][name] == summaries[2][name], f"{name}: 世界の要約が、ハッシュの種で変わる（文字列の集合を回した順に頼っている）"


def test_fingerprint_of_another_process_matches_the_snapshot():
    # 別プロセスで回した要約が、指紋の写しとも、このプロセスで回した要約とも同じ。筋書きは、全部。
    summaries = run_child(HASH_SEEDS[0])["summaries"]
    assert len(summaries) == len(fingerprint.SCENARIOS) == 4
    for scenario in fingerprint.SCENARIOS:
        assert summaries[scenario.name] == fingerprint.recorded_summary(snapshot(), scenario), scenario.name
        assert summaries[scenario.name] == fingerprint.summary_of(scenario), scenario.name
