"""操作補正の最小版（cp_core.controls）のテスト。pyxel は読み込まない。

操作補正の値は、実物の定義データ（clipping_point/data/assists.json の default）を、アプリと同じ読み方で読んで作る。
車の値は、実物の車（kazane）の値。舵の上限の式は、設計の「調整項目」の表（シロガネの、SPEED LOCK の段階ごとの最大舵角）とも照らす。
後退は、操作補正だけの確かめ（指示が出る条件）と、車両モデルとつないだ確かめ（実際に後ろへ進み、前進へ戻る）の両方で見る。
"""
import dataclasses
import functools
import math

import pytest

from cp_app import data_files
from cp_core import controls, vehicle
from cp_core.controls import SHIFT_NONE, SHIFT_TO_FORWARD, SHIFT_TO_REVERSE, Command, ControlParams, ControlState
from cp_core.input_frame import NEUTRAL, InputFrame
from cp_core.vehicle import DT, GRAVITY, REVERSE, Car

KMH = 3.6
HOLD_TICKS = 30  # ブレーキを0.5秒
BRAKE = InputFrame(brake_digital=1)
GAS = InputFrame(throttle_digital=1)
BOTH = InputFrame(throttle_digital=1, brake_digital=1)
LEFT_FULL = InputFrame(steer_analog=1.0)
LEFT_KEY = InputFrame(steer_digital=1)


@functools.cache
def game_data():
    return data_files.load({}, None)


@functools.cache
def params() -> ControlParams:
    return controls.params_from_entry(game_data().entry("assists", controls.DEFAULT_SET))


@functools.cache
def spec() -> vehicle.CarSpec:
    return vehicle.spec_from_entry(game_data().entry("cars", "kazane"))


def run(state: ControlState, frame: InputFrame, speed: float = 0.0, gear: int = 1, surface_mu: float = 1.0) -> Command:
    car = spec()
    return controls.step(params(), state, frame, speed, gear, car.max_steer, car.wheelbase, car.peak_slip, car.tire_mu, surface_mu)


def limit_of(kind: str, speed: float, surface_mu: float = 1.0) -> float:
    """実物の車の、舵の上限（rad）。kind は analog か digital。"""
    car, values = spec(), params()
    ka, km = (values.analog_ka, values.analog_km) if kind == "analog" else (values.digital_ka, values.digital_km)
    return controls.steer_limit(ka, km, values, speed, car.max_steer, car.wheelbase, car.peak_slip, car.tire_mu, surface_mu)


# --- 操作補正の値 ---
def test_controls_params_come_from_the_shipped_entry_and_cannot_be_changed():
    values = params()
    assert type(values) is ControlParams and controls.DEFAULT_SET == "default"
    assert (values.analog_ka, values.analog_km, values.analog_full_time) == (1.0, 0.2, 0.09)  # 設計の、アナログ操作の既定の段階
    assert (values.digital_ka, values.digital_km, values.digital_full_time) == (0.92, 0.12, 0.32)  # デジタル操作の既定の段階
    assert (values.limit_mu_min, values.limit_min_speed) == (0.5, 1.0)
    assert (values.stop_speed, values.brake_hold_ticks, values.pedal_press_min) == (0.5, HOLD_TICKS, 0.1)
    assert type(values.brake_hold_ticks) is int
    with pytest.raises(AttributeError):
        values.stop_speed = 9.0


def test_controls_result_is_a_command_of_four_and_the_state_starts_empty():
    state = ControlState()
    assert (state.steer, state.brake_hold_ticks) == (0.0, 0)
    command = run(state, NEUTRAL)
    assert type(command) is Command and command == (0.0, 0.0, 0.0, SHIFT_NONE)
    assert Command._fields == ("steer", "throttle", "brake", "shift")
    assert len({SHIFT_NONE, SHIFT_TO_REVERSE, SHIFT_TO_FORWARD}) == 3
    with pytest.raises(AttributeError):
        state.reversing = True  # 後退中かは、持たない（車のギアから引く）


# --- 入力の合成 ---
def test_controls_digital_value_wins_whenever_it_is_not_zero():
    # アナログ0.01とデジタル1が同時なら、デジタル。舵、アクセル、ブレーキのそれぞれで決める。
    frame = InputFrame(steer_analog=0.01, steer_digital=-1, throttle_analog=0.01, throttle_digital=1, brake_analog=0.01, brake_digital=1)
    assert controls.combine(frame) == (-1.0, 1.0, 1.0, True)
    frame = InputFrame(steer_analog=-0.4, throttle_analog=0.3, brake_analog=0.7)
    assert controls.combine(frame) == (-0.4, 0.3, 0.7, False)
    # 混ぜてもよい。舵はアナログ、アクセルはデジタル、ブレーキはアナログ。
    frame = InputFrame(steer_analog=0.25, throttle_analog=0.9, throttle_digital=1, brake_analog=0.5)
    assert controls.combine(frame) == (0.25, 1.0, 0.5, False)
    assert controls.combine(NEUTRAL) == (0.0, 0.0, 0.0, False)
    assert all(type(value) is float for value in controls.combine(InputFrame(steer_digital=1, throttle_digital=1, brake_digital=1))[:3])


def test_controls_pedals_pass_through_in_a_forward_gear():
    state = ControlState()
    for gear in (1, 3, 5):
        assert run(state, InputFrame(throttle_analog=0.37, brake_analog=0.02), 20.0, gear)[1:] == (0.37, 0.02, SHIFT_NONE)
        assert run(state, BOTH, 20.0, gear)[1:] == (1.0, 1.0, SHIFT_NONE)


# --- 車速に応じた最大舵角 ---
def test_controls_steer_limit_is_the_full_lock_at_low_speed_and_shrinks_with_speed():
    lock = spec().max_steer
    for kind in ("analog", "digital"):
        assert limit_of(kind, 0.0) == limit_of(kind, 0.99) == lock  # 毎秒1 m未満は、車の最大舵角
        assert limit_of(kind, 20.0 / KMH) == lock  # 時速20 km以下は、式の値が、車の最大舵角を超える
        limits = [limit_of(kind, kmh / KMH) for kmh in (40.0, 60.0, 100.0, 140.0, 180.0)]
        assert limits == sorted(limits, reverse=True) and limits[0] < lock and limits[-1] > 0.0  # 速いほど、小さい
    assert limit_of("digital", 100.0 / KMH) < limit_of("analog", 100.0 / KMH)  # デジタル操作のほうが、きつい


def test_controls_steer_limit_follows_the_formula_of_the_design():
    # 上限 = ka × L × a ÷ v² + km × αp。a = 路面の摩擦係数（下限0.5）× タイヤの摩擦係数 × 重力加速度。
    car, values = spec(), params()
    speed = 100.0 / KMH
    want = 1.0 * car.wheelbase * (1.0 * car.tire_mu * GRAVITY) / speed ** 2 + 0.2 * math.radians(7.5)
    assert limit_of("analog", speed) == pytest.approx(want) == pytest.approx(0.0550, abs=1e-4)
    want = 0.92 * car.wheelbase * (1.0 * car.tire_mu * GRAVITY) / speed ** 2 + 0.12 * math.radians(7.5)
    assert limit_of("digital", speed) == pytest.approx(want)
    # 路面の摩擦係数が小さいと、上限も小さい。0.5より下は、0.5として扱う。
    assert limit_of("analog", speed, 0.55) < limit_of("analog", speed, 1.0)
    assert limit_of("analog", speed, 0.1) == limit_of("analog", speed, 0.5) < limit_of("analog", speed, 0.55)
    assert values.limit_mu_min == 0.5


@pytest.mark.parametrize(
    "ka, km, degrees",
    [
        (1.00, 0.20, {20.0: 31.5, 40.0: 14.3, 60.0: 7.2, 100.0: 3.5, 180.0: 2.1}),  # SPEED LOCK の段階3（アナログ操作の既定）
        (0.92, 0.12, {20.0: 31.5, 40.0: 12.6, 60.0: 6.1, 100.0: 2.8, 180.0: 1.5}),  # 段階4（デジタル操作の既定）
    ],
)
def test_controls_steer_limit_reproduces_the_table_of_the_design(ka, km, degrees):
    # 設計の「調整項目」の、シロガネの最大舵角の表（ホイールベース2.67 m、タイヤの摩擦係数1.05、最大グリップの滑り角7.5度）。
    for kmh, want in degrees.items():
        limit = controls.steer_limit(ka, km, params(), kmh / KMH, 0.55, 2.67, math.radians(7.5), 1.05, 1.0)
        assert math.degrees(limit) == pytest.approx(want, abs=0.06), kmh


def test_controls_full_stick_and_a_held_key_end_at_the_limit_not_at_the_full_lock():
    speed = 100.0 / KMH
    for frame, kind in ((LEFT_FULL, "analog"), (LEFT_KEY, "digital")):
        state = ControlState()
        for _ in range(60):
            command = run(state, frame, speed)
        assert command.steer == state.steer == pytest.approx(limit_of(kind, speed)) and command.steer < 0.06
        # 右は負。大きさは同じ。
        mirrored = ControlState()
        other = InputFrame(steer_analog=-1.0) if kind == "analog" else InputFrame(steer_digital=-1)
        for _ in range(60):
            run(mirrored, other, speed)
        assert mirrored.steer == pytest.approx(-state.steer)
    # 半分倒すと、上限の半分。
    state = ControlState()
    for _ in range(60):
        run(state, InputFrame(steer_analog=0.5), speed)
    assert state.steer == pytest.approx(0.5 * limit_of("analog", speed))
    # 止まっていれば、車の最大舵角まで切れる。それを超える指令は、出ない。
    state = ControlState()
    assert max(run(state, LEFT_FULL, 0.0).steer for _ in range(60)) == pytest.approx(spec().max_steer)


# --- 切る速さ ---
def test_controls_steer_moves_at_a_share_of_the_limit_per_second():
    speed = 60.0 / KMH
    # アナログ操作は、上限いっぱいを0.09秒（5.4 tick）で動く。
    state, limit = ControlState(), limit_of("analog", speed)
    steps = [run(state, LEFT_FULL, speed).steer for _ in range(8)]
    assert steps[0] == pytest.approx(limit / 0.09 * DT)
    assert steps[4] == pytest.approx(5.0 * limit / 0.09 * DT) and steps[4] < limit
    assert steps[5] == steps[6] == steps[7] == pytest.approx(limit)  # 6 tick目で届き、行き過ぎない
    # デジタル操作は、0.32秒（19.2 tick）。
    state, limit = ControlState(), limit_of("digital", speed)
    steps = [run(state, LEFT_KEY, speed).steer for _ in range(24)]
    assert steps[0] == pytest.approx(limit / 0.32 * DT) and steps[18] == pytest.approx(19.0 * limit / 0.32 * DT) and steps[18] < limit
    assert steps[19] == steps[23] == pytest.approx(limit)
    # 離すと、同じ速さの決め方で、0へ戻る（何も押していない入力は、アナログ操作として扱う）。
    back = [run(state, NEUTRAL, speed).steer for _ in range(8)]
    assert back[0] == pytest.approx(limit - limit_of("analog", speed) / 0.09 * DT) and back[7] == 0.0
    assert all(a > b or b == 0.0 for a, b in zip(back, back[1:]))


def test_controls_steer_comes_back_when_the_limit_shrinks_under_the_current_angle():
    # 低速で大きく切ったまま、速くなる。上限が、いまの舵角より小さくなると、舵角の指令は、上限へ向かって戻る。
    state = ControlState()
    for _ in range(30):
        run(state, LEFT_FULL, 5.0)
    wide = state.steer
    assert wide == pytest.approx(limit_of("analog", 5.0)) and wide > 0.4
    fast, limit = 100.0 / KMH, limit_of("analog", 100.0 / KMH)
    first = run(state, LEFT_FULL, fast).steer
    assert first == pytest.approx(wide - wide / 0.09 * DT)  # 戻る速さは、いまの舵角（上限より大きい）に対する割合
    for _ in range(30):
        run(state, LEFT_FULL, fast)
    assert state.steer == pytest.approx(limit)


# --- 後退 ---
def hold(state: ControlState, frame: InputFrame, ticks: int, speed: float = 0.0, gear: int = 1) -> list:
    return [run(state, frame, speed, gear).shift for _ in range(ticks)]


def test_controls_brake_held_for_half_a_second_at_a_stop_asks_for_reverse():
    state = ControlState()
    shifts = hold(state, BRAKE, HOLD_TICKS + 5, speed=0.3)
    assert shifts[:HOLD_TICKS - 1] == [SHIFT_NONE] * (HOLD_TICKS - 1)
    # 30 tick目から、指示が出る。車が受けなければ（ギアが1のまま）、条件が続く間、毎tick出る。
    assert shifts[HOLD_TICKS - 1:] == [SHIFT_TO_REVERSE] * 6
    assert run(state, BRAKE, 0.3).brake == 1.0  # 後退に入るまでは、ブレーキはブレーキ
    # アナログのブレーキでも、同じ。線（0.1）ちょうどは、押している。
    for amount in (0.1, 0.5, 1.0):
        assert hold(ControlState(), InputFrame(brake_analog=amount), HOLD_TICKS, speed=0.0)[-1] == SHIFT_TO_REVERSE


@pytest.mark.parametrize(
    "frame, speed, gear",
    [
        (BRAKE, 0.5, 1),  # 毎秒0.5 mは、「ほぼ止まった」に入らない
        (BRAKE, 10.0, 1),  # 走りながらのブレーキ
        (InputFrame(brake_analog=0.09), 0.0, 1),  # 線より下
        (BOTH, 0.0, 1),  # アクセルを押している間は、数えない
        (InputFrame(throttle_analog=0.1, brake_digital=1), 0.0, 1),  # アクセルが、線ちょうど
        (GAS, 0.0, 1),
        (NEUTRAL, 0.0, 1),
    ],
)
def test_controls_reverse_is_not_asked_for_while_a_condition_is_missing(frame, speed, gear):
    state = ControlState()
    assert hold(state, frame, 300, speed, gear) == [SHIFT_NONE] * 300
    assert state.brake_hold_ticks == 0


def test_controls_reverse_is_only_asked_for_on_a_tick_where_the_conditions_hold_even_with_no_hold_time():
    # 押し続ける長さが0の値（定義データの範囲の下の端）。条件がそろったtickに、すぐ出る。条件の無いtickには、出ない
    # （「数が、線以上」だけで決めると、何も押していなくても、毎tick、後退へ入る指示が出る）。
    car, quick = spec(), dataclasses.replace(params(), brake_hold_ticks=0)

    def ask(state: ControlState, frame: InputFrame, speed: float) -> str:
        return controls.step(quick, state, frame, speed, 1, car.max_steer, car.wheelbase, car.peak_slip, car.tire_mu, 1.0).shift

    state = ControlState()
    assert [ask(state, frame, speed) for frame, speed in ((NEUTRAL, 0.0), (GAS, 0.0), (BOTH, 0.0), (BRAKE, 20.0))] == [SHIFT_NONE] * 4
    assert ask(state, BRAKE, 0.0) == SHIFT_TO_REVERSE and ask(state, NEUTRAL, 0.0) == SHIFT_NONE


def test_controls_the_brake_count_starts_over_when_the_hold_is_broken():
    for breaker, speed in ((NEUTRAL, 0.0), (BOTH, 0.0), (BRAKE, 2.0)):  # 離す、アクセルも押す、動く
        state = ControlState()
        assert hold(state, BRAKE, HOLD_TICKS - 1) == [SHIFT_NONE] * (HOLD_TICKS - 1) and state.brake_hold_ticks == HOLD_TICKS - 1
        assert run(state, breaker, speed).shift == SHIFT_NONE and state.brake_hold_ticks == 0
        assert hold(state, BRAKE, HOLD_TICKS - 1) == [SHIFT_NONE] * (HOLD_TICKS - 1)  # 数え直し
        assert run(state, BRAKE).shift == SHIFT_TO_REVERSE


def test_controls_in_reverse_the_pedals_swap_and_the_steer_keeps_its_direction():
    state = ControlState()
    command = run(state, InputFrame(steer_analog=1.0, throttle_analog=0.3, brake_analog=0.8), 2.0, REVERSE)
    assert (command.throttle, command.brake) == (0.8, 0.3)  # ブレーキの入力が後退の駆動、アクセルの入力が制動
    assert command.steer > 0.0 and command.shift == SHIFT_NONE  # 左へ切れば、舵角の指令は左（正）のまま
    assert run(ControlState(), InputFrame(steer_digital=-1, brake_digital=1), 2.0, REVERSE)[:3] == (pytest.approx(-0.55 / 0.32 * DT), 1.0, 0.0)
    # 後退中は、ブレーキを押し続けても、数えない。
    assert hold(state, BRAKE, 100, 0.0, REVERSE) == [SHIFT_NONE] * 100 and state.brake_hold_ticks == 0


def test_controls_in_reverse_the_throttle_at_a_stop_asks_for_forward():
    state = ControlState()
    assert run(state, GAS, 0.49, REVERSE).shift == SHIFT_TO_FORWARD
    assert run(state, InputFrame(throttle_analog=0.1), 0.0, REVERSE).shift == SHIFT_TO_FORWARD  # 線ちょうどは、押している
    assert run(state, BOTH, 0.0, REVERSE).shift == SHIFT_TO_FORWARD  # ブレーキも押していても、アクセルを押していれば戻る
    assert run(state, GAS, 0.5, REVERSE).shift == SHIFT_NONE  # まだ動いている。アクセルは、制動として働く
    assert run(state, GAS, 6.0, REVERSE)[1:] == (0.0, 1.0, SHIFT_NONE)
    assert run(state, InputFrame(throttle_analog=0.09), 0.0, REVERSE).shift == SHIFT_NONE  # 線より下
    assert run(state, BRAKE, 0.0, REVERSE).shift == SHIFT_NONE and run(state, NEUTRAL, 0.0, REVERSE).shift == SHIFT_NONE


# --- 操作補正と車両モデルをつなぐ（世界がする形）。指示を、車の変速の口へ渡す ---
def drive(car: Car, state: ControlState, frame: InputFrame, ticks: int, surface_mu: float = 1.0) -> list:
    """入力フレームを ticks 回流す。返すのは、tickごとの (ギア, 車体座標の前後の速度, 出た指示)。"""
    made, values, rows = car.spec, params(), []
    for _ in range(ticks):
        command = controls.step(values, state, frame, car.speed, car.gear, made.max_steer, made.wheelbase, made.peak_slip, made.tire_mu, surface_mu)
        if command.shift == SHIFT_TO_REVERSE:
            car.shift_to_reverse()
        elif command.shift == SHIFT_TO_FORWARD:
            car.shift_to_forward()
        car.step(command.steer, command.throttle, command.brake, surface_mu)
        rows.append((car.gear, car.vx, command.shift))
    return rows


def test_controls_with_the_car_brake_backs_up_and_throttle_stops_and_goes_forward_again():
    car, state = Car(spec()), ControlState()
    rows = drive(car, state, BRAKE, 240)
    gears = [gear for gear, _, _ in rows]
    assert gears[:HOLD_TICKS - 1] == [1] * (HOLD_TICKS - 1) and gears[HOLD_TICKS - 1:] == [REVERSE] * (240 - HOLD_TICKS + 1)  # 0.5秒で、後退へ入る
    assert [shift for _, _, shift in rows].count(SHIFT_TO_REVERSE) == 1  # 車が受けたので、指示は1度だけ
    assert car.vx < -3.0 and car.x < -3.0  # ブレーキの入力で、後ろへ進む
    # アクセルの入力で、止まる（制動として働く）。止まると、前進へ戻り、そのまま前へ進む。
    rows = drive(car, state, GAS, 300)
    gears = [gear for gear, _, _ in rows]
    switch = gears.index(1)
    assert gears[:switch] == [REVERSE] * switch and all(gear >= 1 for gear in gears[switch:]) and 10 < switch < 150
    assert min(vx for _, vx, _ in rows[:switch]) < -3.0 and all(vx < 0.5 for _, vx, _ in rows[:switch])  # 戻るまでは、前へ進まない
    assert [shift for _, _, shift in rows].count(SHIFT_TO_FORWARD) == 1
    assert car.gear >= 1 and car.vx > 3.0


def test_controls_with_the_car_a_trigger_that_rests_above_zero_still_backs_up_and_stays_in_reverse():
    # アクセルが0.02のまま（線より下。戻りが0にならないトリガー）。ブレーキ0.5秒で後退に入り、入ったままでいる。
    car, state = Car(spec()), ControlState()
    rows = drive(car, state, InputFrame(throttle_analog=0.02, brake_digital=1), 300)
    gears = [gear for gear, _, _ in rows]
    assert gears.index(REVERSE) == HOLD_TICKS - 1 and set(gears[HOLD_TICKS - 1:]) == {REVERSE}
    assert [shift for _, _, shift in rows].count(SHIFT_TO_FORWARD) == 0
    assert car.vx < -3.0


def test_controls_with_the_car_both_pedals_held_at_a_stop_do_not_flip_between_the_gears():
    # 両方のペダルを押したまま、止まっている。前進のギアでは、後退へ入らない。後退のギアからは、前進へ戻って、そのまま。
    car, state = Car(spec()), ControlState()
    rows = drive(car, state, BOTH, 600)
    assert {gear for gear, _, _ in rows} == {1} and {shift for _, _, shift in rows} == {SHIFT_NONE}
    assert car.speed < 0.5  # ブレーキが勝って、止まったまま
    car, state = Car(spec()), ControlState()
    drive(car, state, BRAKE, 60)
    assert car.gear == REVERSE
    drive(car, state, NEUTRAL, 120)
    rows = drive(car, state, BOTH, 600)
    gears = [gear for gear, _, _ in rows]
    switch = gears.index(1)
    assert gears == [REVERSE] * switch + [1] * (600 - switch)  # 1度だけ、前進へ戻る
    assert [shift for _, _, shift in rows].count(SHIFT_TO_FORWARD) == 1 and SHIFT_TO_REVERSE not in {shift for _, _, shift in rows}


def test_controls_with_the_car_reverse_waits_until_the_car_is_in_first_and_not_shifting():
    # 5速のまま、急に止められた車（壁に当たった形）。ATが1速へ下げ終わるまで（変速4回で、約0.9秒）、車は、後退へ入る指示を
    # 受けない。指示は、出続ける。
    car, state = Car(spec()), ControlState()
    car.reset(0.0, 0.0, 0.0, 50.0)
    assert car.gear == 5
    car.relocate(0.0, 0.0, 0.0, 0.0)
    rows = drive(car, state, BRAKE, 120)
    gears = [gear for gear, _, _ in rows]
    entered = gears.index(REVERSE)
    assert entered > HOLD_TICKS - 1 and gears[HOLD_TICKS - 1] != REVERSE and set(gears[entered:]) == {REVERSE}
    asked = [shift for _, _, shift in rows].count(SHIFT_TO_REVERSE)
    assert asked == entered - (HOLD_TICKS - 1) + 1  # 受けられるまで、毎tick出て、受けたら止まる
    assert car.vx < 0.0
