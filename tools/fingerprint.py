"""指紋の照合。決まった筋書きで世界を回した要約（指紋）と、保存する項目の一覧を、ふるまいの写しと照らす。

  python3 tools/fingerprint.py            2つのふるまいの写しと照らす
  python3 tools/fingerprint.py --update   2つのふるまいの写しを取り直す

ふるまいの写しは2つ。取り直す口は、ここの --update だけ（2つとも書き、変わったほうの名を出す）。
取り直しは、単独のコミットで、理由を添える（cp_core や cp_ui の変更と、同じコミットにしない）。
  tests/snapshots/fingerprint.json     指紋の写し。筋書きごとの世界の要約と、環境の値（Pythonの版、数学関数の試し値）
  tests/snapshots/profile_schema.json  保存する項目の一覧の写し（cp_core/profile.py の schema()）
筋書きは、名、台本、回すtick数、種の組（SCENARIOS）。いまは2本で、全体の検証の run と run --realtime が回す形と同じ
（tools/run.py が、どちらの回でも、アプリの世界の要約を、指紋の写しと照らす）。長い筋書きは、車が入る段0 区切り9で足す。
世界は、純Pythonで回す（cp_core だけを読む。pyxel は読み込まない）。
終了コード：0＝ふるまいの写しと同じ、1＝違う（どの筋書きの、どの項目が、何から何へ変わったか。保存する項目の一覧なら、どの項目が変わったか）、
2＝ふるまいの写しが無い・読めない、筋書きが0本、台本が読めない。無いときに、黙って作らない。
合否は、世界の要約と、保存する項目の一覧だけで決める。環境の値は、合否を変えず、最後の1行に env=same か env=changed で出す。
要約が違い、環境の値も違えば、「環境が変わった」と先に出す（退行ではなく、Pythonか数学関数が変わったのかもしれない）。
数学関数の試し値は、sin、cos、tan、atan2、exp、sqrt、hypot を、決まった入力の列で回した結果の要約値（関数ごと）。
車が入る段0 区切り9から、世界の要約が、浮動小数の計算の結果を量子化した整数で決まるようになる
（要約そのものは、整数と文字列だけのまま。小数は入れない）。その時に、環境の違いと退行を見分けるための値。
"""
import argparse
import hashlib
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import input_reference
from _common import FAIL, INCOMPLETE, OK, ROOT, finish

from cp_core import profile  # noqa: E402 - cp_core への道は、input_reference が足す

FINGERPRINT_SNAPSHOT = "tests/snapshots/fingerprint.json"
SCHEMA_SNAPSHOT = "tests/snapshots/profile_schema.json"
MATH_PROBE_COUNT = 20000  # 数学関数の試し値の、入力の数（関数ごと）
DIGEST_CHARS = 16  # 試し値の要約値の長さ（sha256 の16進の頭）
FINGERPRINT_NOTE = (
    "指紋の写し。決まった筋書き（台本、回すtick数、種）で世界を回した要約。tools/fingerprint.py、tools/run.py、守りのテストが照らす。"
    "environment（Pythonの版と、数学関数の試し値）は、合否に使わない（環境が変わったことと、退行を見分けるための値）。"
    "取り直しは python3 tools/fingerprint.py --update。単独のコミットで、理由を添える。"
)
SCHEMA_NOTE = (
    "保存する項目の一覧の写し（cp_core/profile.py の schema()）。項目を足す、消す、型を変えると、tools/fingerprint.py と守りのテストが落ちる。"
    "形式バージョンを上げるか（移行を書くのは、公開の後から）、NOT_SAVED に理由つきで入れるかを決めてから、python3 tools/fingerprint.py --update で取り直す"
    "（単独のコミットで、理由を添える）。"
)


@dataclass(frozen=True)
class Scenario:
    """筋書き。"""

    name: str
    script: Path | None  # 台本のファイル。None なら、台本なし（何も押していない入力）
    ticks: int  # 回すtick数
    seed: int  # 世界の種


# 筋書きの一覧。足すときは、末尾に足して、指紋の写しを取り直す。
SCENARIOS = (
    Scenario("script_120", input_reference.SMOKE_SCRIPT, 120, 0),  # run の既定（道具の台本を渡す）と同じ
    Scenario("no_script_120", None, 120, 0),  # run --realtime の既定（台本を渡さない）と同じ
)


def script_name(scenario: Scenario):
    """指紋の写しに書く、台本の名。根からの相対パス（/ 区切り）。台本なしなら None。"""
    if scenario.script is None:
        return None
    path = Path(scenario.script).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


def load_scenario_script(scenario: Scenario) -> tuple:
    """筋書きの台本を読む。返すのは (台本の辞書, 検査済みの台本)。台本なしなら (None, None)。読めなければ ValueError。"""
    return (None, None) if scenario.script is None else input_reference.load_script(scenario.script)


def summary_of(scenario: Scenario) -> dict:
    """筋書きを回した、世界の要約（指紋）。台本が読めなければ ValueError。"""
    _, script = load_scenario_script(scenario)
    return input_reference.sim_summary(script, scenario.ticks, scenario.seed)


def scenario_for(script_value, ticks: int, scenarios=SCENARIOS):
    """台本（辞書。台本なしなら None）と、回すtick数が同じ筋書き。無ければ None。台本は、中身で比べる。"""
    for scenario in scenarios:
        if scenario.ticks == ticks and load_scenario_script(scenario)[0] == script_value:
            return scenario
    return None


# --- 環境の値 ---
def digest_of(values: list) -> str:
    """小数の並びを、並べたバイト列（倍精度、リトルエンディアン）の要約値。"""
    return hashlib.sha256(struct.pack(f"<{len(values)}d", *values)).hexdigest()[:DIGEST_CHARS]


def math_probes(count: int = MATH_PROBE_COUNT) -> dict:
    """数学関数の試し値。{関数の名: 要約値}。入力の列は、番号から掛け算と足し算だけで作る（どの環境でも同じ入力になる）。"""
    numbers = range(count)
    return {
        "sin": digest_of([math.sin(-50.0 + i * 0.005) for i in numbers]),
        "cos": digest_of([math.cos(-50.0 + i * 0.005) for i in numbers]),
        "tan": digest_of([math.tan(-1.5 + i * 0.00015) for i in numbers]),
        "atan2": digest_of([math.atan2(-3.0 + i * 0.0003, 1.0 + (i % 97) * 0.11 - 5.0) for i in numbers]),
        "exp": digest_of([math.exp(-20.0 + i * 0.002) for i in numbers]),
        "sqrt": digest_of([math.sqrt(0.001 + i * 0.37) for i in numbers]),
        "hypot": digest_of([math.hypot(-3.0 + i * 0.0003, (i % 97) * 0.11) for i in numbers]),
    }


def environment() -> dict:
    """環境の値。Pythonの版（3.13.5 の形の3つの数）と、数学関数の試し値。"""
    return {"python": ".".join(str(part) for part in sys.version_info[:3]), "math": math_probes()}


# --- いまの値 ---
def current_scenarios(scenarios=SCENARIOS) -> dict:
    """いまのコードで回した、筋書きごとの値。{名: {script, ticks, seed, summary}}。台本が読めなければ ValueError。"""
    return {
        scenario.name: {"script": script_name(scenario), "ticks": scenario.ticks, "seed": scenario.seed, "summary": summary_of(scenario)}
        for scenario in scenarios
    }


def current_schema() -> dict:
    """いまのコードの、保存する項目の一覧。"""
    return profile.schema()


# --- ふるまいの写しを読む ---
def read_json(path: Path):
    """JSONのファイルを読む。無いか、読めなければ None。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_fingerprint_snapshot(root: Path = ROOT):
    """指紋の写しを読む。返すのは {"environment": …, "scenarios": {名: {script, ticks, seed, summary}}}。無いか、形が違えば None。"""
    data = read_json(Path(root) / FINGERPRINT_SNAPSHOT)
    if not isinstance(data, dict) or not isinstance(data.get("environment"), dict) or not isinstance(data.get("scenarios"), dict):
        return None
    for entry in data["scenarios"].values():
        if not isinstance(entry, dict) or not isinstance(entry.get("summary"), dict):
            return None
    return {"environment": data["environment"], "scenarios": data["scenarios"]}


def read_schema_snapshot(root: Path = ROOT):
    """保存する項目の一覧の写しを読む。返すのは {"version": …, "fields": {…}}。無いか、形が違えば None。"""
    data = read_json(Path(root) / SCHEMA_SNAPSHOT)
    if not isinstance(data, dict) or type(data.get("version")) is not int or not isinstance(data.get("fields"), dict):
        return None
    return {"version": data["version"], "fields": data["fields"]}


def recorded_summary(snapshot: dict, scenario: Scenario):
    """指紋の写しの中の、筋書きの世界の要約。その筋書きが、指紋の写しに無ければ None。"""
    entry = snapshot["scenarios"].get(scenario.name)
    return entry["summary"] if entry is not None else None


# --- 比べる ---
def diff_values(recorded: dict, current: dict, where: str) -> list:
    """2つの辞書（ふるまいの写しの値と、いまの値）の、項目ごとの違い。返すのは、文の一覧（同じなら空）。"""
    lines = []
    for key in sorted(set(recorded) | set(current)):
        if key not in recorded:
            lines.append(f"{where}.{key}: ふるまいの写しに無い項目（いま {current[key]!r}）")
        elif key not in current:
            lines.append(f"{where}.{key}: ふるまいの写しにあるが、いまは無い項目（ふるまいの写しは {recorded[key]!r}）")
        elif recorded[key] != current[key] or type(recorded[key]) is not type(current[key]):
            lines.append(f"{where}.{key}: {recorded[key]!r} から {current[key]!r} へ変わった")
    return lines


def compare_scenarios(recorded: dict, current: dict) -> list:
    """指紋の写しの筋書きと、いまの筋書きの違い。返すのは、文の一覧（同じなら空）。"""
    lines = []
    for name in sorted(set(recorded) | set(current)):
        if name not in recorded:
            lines.append(f"筋書き {name}: 指紋の写しに無い（筋書きを足したら、指紋の写しを取り直す）")
        elif name not in current:
            lines.append(f"筋書き {name}: 指紋の写しにあるが、いまは無い")
        else:
            old, new = recorded[name], current[name]
            lines += diff_values({key: old.get(key) for key in ("script", "ticks", "seed")}, {key: new[key] for key in ("script", "ticks", "seed")}, f"筋書き {name}")
            lines += diff_values(old["summary"], new["summary"], f"筋書き {name} の要約")
    return lines


def compare_schema(recorded: dict, current: dict) -> list:
    """保存する項目の一覧の違い。返すのは、文の一覧（同じなら空）。"""
    lines = diff_values({"version": recorded["version"]}, {"version": current["version"]}, "保存する項目の一覧")
    return lines + diff_values(recorded["fields"], current["fields"], "保存する項目")


def environment_changed(recorded: dict, current: dict) -> list:
    """環境の値の違い。返すのは、文の一覧（同じなら空）。合否には使わない。"""
    lines = diff_values({"python": recorded.get("python")}, {"python": current["python"]}, "環境")
    recorded_math = recorded.get("math") if isinstance(recorded.get("math"), dict) else {}
    return lines + diff_values(recorded_math, current["math"], "数学関数の試し値")


# --- ふるまいの写しを書く ---
def snapshot_text(note: str, body: dict) -> str:
    return json.dumps({"_notes": note, **body}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def update(root: Path = ROOT) -> int:
    """2つのふるまいの写しを書く。変わったほうの名を出す。"""
    try:
        scenarios = current_scenarios()
    except ValueError as exc:
        print(f"  fingerprint: 台本が読めない：{exc}")
        return finish("fingerprint", INCOMPLETE, "updated=0 reason=script_unreadable")
    if not scenarios:
        return finish("fingerprint", INCOMPLETE, "updated=0 reason=no_scenarios")
    texts = {
        FINGERPRINT_SNAPSHOT: snapshot_text(FINGERPRINT_NOTE, {"environment": environment(), "scenarios": scenarios}),
        SCHEMA_SNAPSHOT: snapshot_text(SCHEMA_NOTE, current_schema()),
    }
    changed = []
    for rel, text in texts.items():
        path = Path(root) / rel
        try:
            before = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            before = None
        if before != text:
            changed.append(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel in texts:
        print(f"  fingerprint: {rel}: {'変わった' if rel in changed else '変わっていない'}")
    names = ",".join(Path(rel).name for rel in changed) or "none"
    return finish("fingerprint", OK, f"updated={len(texts)} changed={names}")


def check(root: Path = ROOT) -> int:
    """2つのふるまいの写しと照らす。"""
    snapshot, schema = read_fingerprint_snapshot(root), read_schema_snapshot(root)
    missing = [Path(rel).name for rel, value in ((FINGERPRINT_SNAPSHOT, snapshot), (SCHEMA_SNAPSHOT, schema)) if value is None]
    if missing:
        for name in missing:
            print(f"  fingerprint: ふるまいの写し（tests/snapshots/{name}）が無いか、読めない。黙って作らない。取り直す口は --update")
        return finish("fingerprint", INCOMPLETE, f"scenarios=0 fields=0 reason=no_snapshot missing={','.join(missing)}")
    try:
        scenarios = current_scenarios()
    except ValueError as exc:
        print(f"  fingerprint: 台本が読めない：{exc}")
        return finish("fingerprint", INCOMPLETE, "scenarios=0 fields=0 reason=script_unreadable")
    if not scenarios:
        return finish("fingerprint", INCOMPLETE, "scenarios=0 fields=0 reason=no_scenarios")
    fields = current_schema()
    world_lines = compare_scenarios(snapshot["scenarios"], scenarios)
    schema_lines = compare_schema(schema, fields)
    env_lines = environment_changed(snapshot["environment"], environment())
    if world_lines and env_lines:
        # 先に出す。世界の要約の違いは、退行ではなく、環境が変わったためかもしれない。
        print("  fingerprint: 環境が変わった（Pythonの版か、数学関数の結果が、指紋の写しを取ったときと違う）。下の違いは、退行とは限らない。")
    for line in env_lines:
        print(f"  fingerprint: 環境：{line}")
    for line in world_lines + schema_lines:
        print(f"  fingerprint: {line}")
    problems = len(world_lines) + len(schema_lines)
    summary = f"scenarios={len(scenarios)} fields={len(fields['fields'])} problems={problems}"
    failed = [name for name, lines in (("world", world_lines), ("schema", schema_lines)) if lines]
    if failed:
        summary += " failed=" + ",".join(failed)
    summary += f" env={'changed' if env_lines else 'same'}"
    return finish("fingerprint", FAIL if problems else OK, summary)


def main() -> int:
    ap = argparse.ArgumentParser(description="指紋と、保存する項目の一覧を、ふるまいの写しと照らす")
    ap.add_argument("--update", action="store_true", help="2つのふるまいの写しを取り直す（単独のコミットで、理由を添える）")
    args = ap.parse_args()
    return update() if args.update else check()


if __name__ == "__main__":
    sys.exit(main())
