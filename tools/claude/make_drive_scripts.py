"""走る台本（tools/input_script_drive.json）と、壁の台本（tools/input_script_wall.json）を作る。作業用のスクリプト。

  python3 tools/claude/make_drive_scripts.py           作って、走りの跡と要約を出す（ファイルは書かない）
  python3 tools/claude/make_drive_scripts.py --write   2つの台本のファイルを書く
  python3 tools/claude/make_drive_scripts.py --lap     簡単な追従で、1周を回して、かかったtickを出す（台本には、しない）

台本は、出来上がった入力だけを持つ（区間の並び）。道具、テスト、出荷するコードは、このスクリプトを読まない。
世界の式か、車、コース、操作補正の値を変えて、台本が成り立たなくなった時（指紋の筋書きの、走行の下限を満たさない）に、作り直す。
作り直したら、指紋の写しを取り直す（単独のコミット）。自動の運転役（段1）の先取りではない。段1で、運転役の周回に置き換える。
走る台本（900 tick）：簡単な追従で、世界を回しながら作る。
  舵       中心線からのずれと、向きの差と、先の曲率から、舵角を決めて、操作補正の舵の上限で割って、舵のアナログ値にする
  ペダル   先の曲率から、曲がれる速さを決めて、そこまでに落とせる速さを超えていれば、ブレーキ。足りなければ、アクセル
  入力は、STEP_TICKS ごとに決め、舵は STEER_STEP、ペダルは PEDAL_STEP の段に丸める。丸めは、回しながら掛ける
  （世界へ渡すのは、丸めた後の入力。回した後で丸めると、書き出した台本は、別の走りになる）。
壁の台本：決めた区間の並び（WALL_PHASES）。スタートから、左へ切りながら加速して、左の壁に当たり、ブレーキで止まって、後退に入り、
  後ろへ進みながら向きを変え、アクセルで止まって、前進へ戻り、コースへ戻る。
どちらも、書き出す区間の並びを、台本として読み直して回し、作ったときと同じ要約になることを確かめる（違えば1）。
終了コード：0＝作れた、1＝読み直した要約が違う・走行の下限（tools/fingerprint.py の筋書き）を満たさない、2＝定義データが読めない。
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

import fingerprint  # noqa: E402
import input_reference  # noqa: E402
from _common import FAIL, INCOMPLETE, OK, finish  # noqa: E402

from cp_core import controls, input_script  # noqa: E402 - cp_core への道は、input_reference が足す
from cp_core.input_frame import InputFrame  # noqa: E402
from cp_core.vehicle import GRAVITY, REVERSE  # noqa: E402

DRIVE_TICKS = 900  # 走る台本の長さ
STEP_TICKS = 6  # 入力を決め直す間隔（tick）
STEER_STEP = 0.05  # 舵のアナログ値の段
PEDAL_STEP = 0.1  # ペダルのアナログ値の段
LATERAL_GAIN = 0.9  # 中心線からのずれ（m）を、舵角へ直す強さ（速さで割る）
LATERAL_SPEED_FLOOR_M_S = 4.0  # ずれの項で、速さをこれ未満にしない
HEADING_GAIN = 1.0  # 向きの差（rad）を、舵角へ直す強さ
PREVIEW_S = 0.25  # 先の曲率を見る時間（秒）。この時間で進む所の曲率を、舵に足す
CORNER_G = 0.62  # 曲がれる速さを決める、横加速度（g）。タイヤの限界（約0.91 g）より、余裕を見る
BRAKE_G = 0.4  # そこまでに落とせる速さを決める、減速（g）
LOOK_AHEAD_M = 140.0  # 曲がれる速さを、この先まで見る
SPEED_CAP_M_S = 38.0  # 直線での速さの上限（時速約137 km）
BRAKE_GAIN = 0.25  # 速すぎる分（m/s）を、ブレーキへ直す強さ
BRAKE_CAP_IN_A_BEND = 0.3  # 曲がっている間の、ブレーキの上限（強く踏むと、後ろが出て回る）
BEND_MIN = 0.004  # 「曲がっている」と見る、いまの所の曲率（1/m）
THROTTLE_GAIN = 0.4  # 足りない分（m/s）を、アクセルへ直す強さ
THROTTLE_HOLD = 0.2  # 曲がれる速さちょうどで走るときの、アクセル（速さを保つ分）
LAP_MAX_TICKS = 6000  # --lap で、1周を待つtickの上限
# 壁の台本の区間。(tick数, 入力フレームの値)。デジタル操作で書く（走る台本は、アナログ操作）。
WALL_PHASES = (
    (30, {}),
    (50, {"throttle_analog": 0.5}),  # 発進して、まっすぐ進む
    (105, {"throttle_analog": 0.4, "steer_digital": 1}),  # 左へ切って、左の壁のほうを向く（向きが、約90度変わる）
    (70, {"throttle_analog": 0.5}),  # そのまま、芝を渡って、壁に正面から当たる
    (40, {"brake_digital": 1}),  # 止まる
    (45, {"brake_digital": 1}),  # 止まったまま、ブレーキを押し続けて、後退に入る
    (140, {"brake_digital": 1, "steer_digital": 1}),  # 後ろへ進みながら、左へ切る（車体の向きは、右へ回って、コースの向きへ戻る）
    (60, {"throttle_digital": 1}),  # アクセルで止まって、前進へ戻る
    (60, {"throttle_analog": 0.5, "steer_analog": -0.2}),  # 少し右へ切って、向きを合わせる
    (180, {"throttle_analog": 0.8}),  # コースを、前へ進む
)


def wrap_pi(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    return angle


def stepped(value: float, step: float, low: float, high: float) -> float:
    """value を、step の段に丸めて、low〜high に収める。"""
    return min(high, max(low, round(round(value / step) * step, 6)))


def curvature_at(course, s: float) -> float:
    return course.sample(int((s % course.length) / course.ds) % course.n)[3]


def follow(sim) -> dict:
    """いまの世界の状態から、次の区間の入力（入力フレームの値の辞書）を決める。簡単な追従。"""
    car, course, spec, params = sim.car, sim.track, sim.spec, sim.control_params
    speed = car.speed
    here = course.query(car.x, car.z, sim.segment)
    # --- 舵 ---
    ahead = curvature_at(course, here.s + PREVIEW_S * speed)
    angle = (
        -HEADING_GAIN * wrap_pi(car.heading - here.heading)
        - math.atan(LATERAL_GAIN * here.lateral / max(speed, LATERAL_SPEED_FLOOR_M_S))
        + spec.wheelbase * ahead
    )
    limit = controls.steer_limit(params.analog_ka, params.analog_km, params, speed, spec.max_steer, spec.wheelbase, spec.peak_slip, spec.tire_mu, sim.mu)
    steer = stepped(angle / limit, STEER_STEP, -1.0, 1.0)
    # --- ペダル ---
    allowed = SPEED_CAP_M_S
    distance = 0.0
    while distance <= LOOK_AHEAD_M:
        bend = abs(curvature_at(course, here.s + distance))
        if bend > 1e-6:
            corner = math.sqrt(CORNER_G * GRAVITY / bend)
            allowed = min(allowed, math.sqrt(corner * corner + 2.0 * BRAKE_G * GRAVITY * distance))
        distance += course.ds
    in_a_bend = abs(here.curvature) > BEND_MIN
    throttle = stepped(THROTTLE_HOLD + THROTTLE_GAIN * (allowed - speed), PEDAL_STEP, 0.0, 1.0)
    brake = stepped(BRAKE_GAIN * (speed - allowed), PEDAL_STEP, 0.0, BRAKE_CAP_IN_A_BEND if in_a_bend else 1.0)
    if brake:
        throttle = 0.0  # 両方のペダルを、同時に踏まない
    values = {}
    if steer:
        values["steer_analog"] = steer
    if throttle:
        values["throttle_analog"] = throttle
    if brake:
        values["brake_analog"] = brake
    return values


def merged(segments: list) -> list:
    """同じ入力が続く区間を、1つにまとめる。"""
    out = []
    for ticks, values in segments:
        if out and out[-1][1] == values:
            out[-1] = (out[-1][0] + ticks, values)
        else:
            out.append((ticks, values))
    return out


def script_value(segments: list) -> dict:
    return {"segments": [{"ticks": ticks, **values} for ticks, values in segments]}


def script_text(value: dict) -> str:
    """台本のファイルの文。1行に1区間。"""
    lines = [json.dumps(segment) for segment in value["segments"]]
    return '{\n  "segments": [\n' + ",\n".join(f"    {line}" for line in lines) + "\n  ]\n}\n"


def drive_with_the_follower(ticks: int) -> tuple:
    """簡単な追従で、世界を ticks 回す。返すのは (区間の並び, 世界, 走りの跡の行)。"""
    sim = input_reference.make_sim()
    segments, trail = [], []
    while sim.tick < ticks:
        values = follow(sim)
        frame = InputFrame(**values)
        count = min(STEP_TICKS, ticks - sim.tick)
        for _ in range(count):
            sim.step(frame)
        segments.append((count, values))
        if sim.tick % 60 == 0 or sim.tick == ticks:
            trail.append(trail_line(sim))
    return merged(segments), sim, trail


def drive_the_phases(phases) -> tuple:
    """決めた区間の並びで、世界を回す。返すのは (区間の並び, 世界, 走りの跡の行)。"""
    sim = input_reference.make_sim()
    trail = []
    for count, values in phases:
        frame = InputFrame(**values)
        for _ in range(count):
            gear, on_wall = sim.car.gear, sim.on_wall
            sim.step(frame)
            if sim.car.gear != gear or (sim.on_wall and not on_wall):
                trail.append(trail_line(sim))
        trail.append(trail_line(sim) + "  <- end of a phase")
    return merged([(count, dict(values)) for count, values in phases]), sim, trail


def trail_line(sim) -> str:
    car = sim.car
    gear = "R" if car.gear == REVERSE else car.gear
    return (
        f"  tick {sim.tick:4d}  s {sim.s:7.1f}  lateral {sim.lateral:+6.2f}  {car.speed * 3.6:6.1f} km/h  gear {gear}  "
        f"heading {math.degrees(car.heading):+7.1f}  {sim.surface:7s}  wall_hits {sim.wall_hits}  odometer {sim.odometer:6.1f}"
    )


def replay(value: dict, ticks: int) -> dict:
    """区間の並びを、台本として読み直して、道具の参照と同じ道で回した要約。"""
    return input_reference.sim_summary(input_script.parse(json.loads(script_text(value))), ticks)


def lap() -> int:
    """簡単な追従で、1周を回す。スタートの所を、もう1度通るまでのtick。"""
    sim = input_reference.make_sim()
    length = sim.track.length
    while sim.tick < LAP_MAX_TICKS and sim.odometer < length:
        frame = InputFrame(**follow(sim))
        for _ in range(STEP_TICKS):
            sim.step(frame)
            if sim.odometer >= length:
                break
    done = sim.odometer >= length
    print(trail_line(sim))
    summary = sim.summary()
    detail = f"lap_ticks={sim.tick} lap_s={sim.tick / 60.0:.2f} top_speed_kmh={sim.top_speed * 3.6:.1f} wall_hits={summary['wall_hits']} requery_count={summary['requery_count']}"
    return finish("make_drive_scripts", OK if done and summary["wall_hits"] == 0 else FAIL, f"mode=lap {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(description="走る台本と、壁の台本を作る")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="2つの台本のファイルを書く")
    mode.add_argument("--lap", action="store_true", help="簡単な追従で、1周を回して、かかったtickを出す")
    args = ap.parse_args()
    try:
        input_reference.load_data()
    except ValueError as exc:
        print(f"  make_drive_scripts: 定義データが読めない：{exc}")
        return finish("make_drive_scripts", INCOMPLETE, "reason=cannot_load_data")
    if args.lap:
        return lap()
    scenarios = {scenario.name: scenario for scenario in fingerprint.SCENARIOS}
    made = (
        ("drive_900", input_reference.DRIVE_SCRIPT, drive_with_the_follower(DRIVE_TICKS)),
        ("wall_780", input_reference.WALL_SCRIPT, drive_the_phases(WALL_PHASES)),
    )
    problems, facts = 0, []
    for name, path, (segments, sim, trail) in made:
        value = script_value(segments)
        ticks = sum(count for count, _ in segments)
        print(f"  make_drive_scripts: {name}（{len(segments)} 区間、{ticks} tick）")
        print("\n".join(trail))
        summary = sim.summary()
        if replay(value, ticks) != summary:
            print(f"  make_drive_scripts: {name}: 台本として読み直して回した要約が、作ったときの要約と違う")
            problems += 1
        scenario = scenarios.get(name)
        lines = [f"筋書き {name} が、tools/fingerprint.py に無い"] if scenario is None else fingerprint.floor_problems(scenario, summary)
        if scenario is not None and scenario.ticks != ticks:
            lines.append(f"筋書き {name} のtick数が {scenario.ticks}（作った台本は {ticks}）")
        for line in lines:
            print(f"  make_drive_scripts: {name}: {line}")
        problems += len(lines)
        facts.append(f"{name}={len(segments)}segments/{ticks}ticks")
        if args.write and not problems:
            path.write_text(script_text(value), encoding="utf-8")
            print(f"  make_drive_scripts: {path.name} を書いた")
    summary = " ".join(facts) + f" written={'yes' if args.write and not problems else 'no'} problems={problems}"
    return finish("make_drive_scripts", FAIL if problems else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
