"""指紋テスト（守りのテスト）。決まった筋書きで世界を回した要約（指紋）を、ふるまいの写し（tests/snapshots/fingerprint.json）と比べる。

道具 `python3 tools/fingerprint.py` と同じ関数で照らす。指紋の写しが無ければ、失敗にする（黙って作らない）。
指紋の写しを取り直す口は `python3 tools/fingerprint.py --update` だけ。取り直しは、単独のコミットで、理由を添える。
合否は、世界の要約だけで決める。環境の値（Pythonの版、数学関数の試し値）が、指紋の写しと違っても、ここでは落とさない。
文字列の集合の順に頼っていないことは、ハッシュの種（PYTHONHASHSEED）を変えた別プロセスで回して見る。
保存する項目の一覧の写しのテストは tests/test_profile.py。
"""
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
from cp_core.sim import Sim

SCRIPT_SCENARIO = fingerprint.SCENARIOS[0]  # 道具の台本を回す筋書き。ボタンを2個押す区間を通る
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
    "    'summary': fingerprint.summary_of(fingerprint.SCENARIOS[0]),\n"
    "}))\n"
)


def snapshot() -> dict:
    recorded = fingerprint.read_fingerprint_snapshot(ROOT)
    assert recorded is not None, f"指紋の写し（{fingerprint.FINGERPRINT_SNAPSHOT}）が無いか、読めない。黙って作らない"
    return recorded


def run_scenario(scenario, extra_ticks: int = 0, seed=None, change_tick=None) -> dict:
    """筋書きを、手で回す。extra_ticks は、余分に回すtick数。change_tick は、入力を1つ変えるtick。"""
    _, script = fingerprint.load_scenario_script(scenario)
    sim = Sim(scenario.seed if seed is None else seed)
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
    other = {"python": "9.9.9", "math": {**recorded["environment"]["math"], "sin": "0" * 16}}
    lines = fingerprint.environment_changed(other, fingerprint.environment())
    assert len(lines) == 2 and "python" in lines[0] and "sin" in lines[1]
    # 環境の値は、筋書きの比べ方に入っていない。
    assert fingerprint.compare_scenarios(recorded["scenarios"], fingerprint.current_scenarios()) == []
    assert fingerprint.environment_changed(fingerprint.environment(), fingerprint.environment()) == []


# --- 筋書き ---
def test_fingerprint_scenarios_are_the_two_runs_of_the_full_verification():
    script, no_script = fingerprint.SCENARIOS
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


def test_fingerprint_the_two_scenarios_have_different_summaries():
    script, no_script = (fingerprint.summary_of(scenario) for scenario in fingerprint.SCENARIOS)
    assert script["input_digest"] != no_script["input_digest"]
    assert no_script == input_reference.sim_summary(None, 120)
    neutral = Sim()
    for _ in range(120):
        neutral.step(NEUTRAL)
    assert no_script == neutral.summary()


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
    # (3) それでも、世界の要約は同じ。
    summaries = [results[seed]["summary"] for seed in HASH_SEEDS]
    assert summaries[0] == summaries[1] == summaries[2], "世界の要約が、ハッシュの種で変わる（文字列の集合を回した順に頼っている）"


def test_fingerprint_of_another_process_matches_the_snapshot():
    # 別プロセスで回した要約が、指紋の写しとも、このプロセスで回した要約とも同じ。
    summary = run_child(HASH_SEEDS[0])["summary"]
    assert summary == fingerprint.recorded_summary(snapshot(), SCRIPT_SCENARIO)
    assert summary == fingerprint.summary_of(SCRIPT_SCENARIO)
