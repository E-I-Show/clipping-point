"""車両モデル（cp_core.vehicle）のテスト。pyxel は読み込まない。

車の値は、実物の定義データ（clipping_point/data/cars.json の kazane）を、アプリと同じ読み方で読んで作る。
測り方（0-100 km/h、最高速、制動距離、最大横加速度）は、設計時の試作（spikes/vehicle/common.py）の測り方を、そのまま写した。
試作のファイルは、読み込まない（spikes/ は、テストの外）。試作を、同じ値と同じ入力で回した値は、数字で写してある（STRAIGHT）。
設計の表の値からの幅は、道具の値（tools/budgets.json の vehicle_ で始まる値）。
"""
import functools
import math

import pytest

from _common import load_budgets
from cp_app import data_files
from cp_core import vehicle
from cp_core.vehicle import DT, GRAVITY, REVERSE, Car, CarSpec

KMH = 3.6  # m/s を km/h にする
# 設計の「車両モデル」の表の、カザネ RS の値。
DESIGN_ACCEL_0_100_S, DESIGN_TOP_SPEED_KMH, DESIGN_BRAKE_100_0_M, DESIGN_LATERAL_G = 6.6, 213.0, 42.0, 0.91
NEAR = {"rel": 1e-9, "abs": 1e-9}  # 参照値との比べ方（数学関数の、最下位の桁の違いは通す。式の違いは通さない）


@functools.cache
def game_data():
    return data_files.load({}, None)


def car_entry() -> dict:
    """実物の車の項目。引くたびに、新しい複製（テストの中で、書き換えてよい）。"""
    return game_data().entry("cars", "kazane")


@functools.cache
def spec() -> CarSpec:
    return vehicle.spec_from_entry(car_entry())


def new_car(speed: float = 0.0, heading: float = 0.0) -> Car:
    car = Car(spec())
    car.reset(0.0, 0.0, heading, speed)
    return car


def energy(car: Car) -> float:
    """運動エネルギー（並進と、ヨーの回転。J）。"""
    return 0.5 * car.spec.mass * car.speed ** 2 + 0.5 * car.spec.yaw_inertia * car.yaw_rate ** 2


def lcg(seed: int):
    """整数の線形合同法。同じ種から、同じ列。"""
    value = seed
    while True:
        value = (value * 1103515245 + 12345) % 2147483648
        yield value


# --- 車の値 ---
def test_vehicle_spec_is_built_from_the_shipped_entry_and_cannot_be_changed():
    made = spec()
    assert type(made) is CarSpec and made.car_id == "kazane"
    assert made.mass == 960.0 and made.wheelbase == 2.27 and made.max_steer == 0.55
    assert made.cg_to_front + made.cg_to_rear == pytest.approx(made.wheelbase)
    assert 2.0 * (made.static_front + made.static_rear) == pytest.approx(made.mass * GRAVITY)  # 4輪の荷重の合計は、車の重さ
    assert made.n_gears == 5 and len(made.gear_total) == 7
    assert made.gear_total[1] == pytest.approx(3.136 * 4.3) and made.gear_total[REVERSE] == pytest.approx(-3.0 * 4.3)
    assert made.peak_slip == pytest.approx(math.radians(7.5)) and made.tan_peak_inv == pytest.approx(1.0 / math.tan(math.radians(7.5)))
    assert made.half_length == 2.1 and made.half_width == 0.85
    # トルクの表は、最高出力が power_ps になる倍率を掛けてある。
    power = max(torque * index * made.torque_step * 2.0 * math.pi / 60.0 for index, torque in enumerate(made.torque_table))
    assert power / vehicle.PS_TO_W == pytest.approx(145.0)
    with pytest.raises(AttributeError):
        made.mass = 1.0
    with pytest.raises(TypeError):
        Car(car_entry())  # 項目そのものは受けない（車の値にしてから渡す）


def test_vehicle_two_cars_from_the_same_spec_do_not_share_state():
    a, b = new_car(), new_car()
    for _ in range(60):
        a.step(0.1, 1.0, 0.0, 1.0)
    assert b.state() == new_car().state() and a.state() != b.state()
    assert a.wheel_load is not b.wheel_load


# --- 設計の表の値の近くにあること（試作の測り方） ---
class IdealThrottle:
    """駆動輪の前後の使用率が、目標を超えないように、アクセルを戻す運転（試作の TCS）。"""

    def __init__(self, target: float = 0.97) -> None:
        self.cap, self.target = 1.0, target

    def __call__(self, car: Car, want: float = 1.0) -> float:
        self.cap = max(0.05, self.cap * self.target / car.drive_util) if car.drive_util > self.target else min(1.0, self.cap + 0.04)
        return min(want, self.cap)


class IdealBrake:
    """制動の使用率が、目標を超えないように、ブレーキを戻す運転（試作の ABS）。"""

    def __init__(self, target: float = 0.97) -> None:
        self.cap, self.target = 1.0, target

    def __call__(self, car: Car, want: float = 1.0) -> float:
        self.cap = max(0.05, self.cap * self.target / car.brake_util) if car.brake_util > self.target else min(1.0, self.cap + 0.04)
        return min(want, self.cap)


def accel_run(seconds: float = 60.0) -> tuple:
    """止まった状態から、舵0で全開（駆動輪が空転しない運転）。返すのは (0-100 km/hの秒数, 最後の速さ km/h, 最後のギア)。"""
    car, driver = new_car(), IdealThrottle()
    throttle, reached = 1.0, None
    for tick in range(int(seconds / DT)):
        car.step(0.0, throttle, 0.0, 1.0)
        throttle = driver(car)
        if reached is None and car.speed * KMH >= 100.0:
            reached = (tick + 1) * DT
    return reached, car.speed * KMH, car.gear


def brake_run(from_kmh: float = 100.0) -> float:
    """決めた速さから、舵0で、ロックしない全制動。返すのは、止まるまでの距離（m）。"""
    car, driver = new_car(from_kmh / KMH), IdealBrake()
    for _ in range(30):
        car.step(0.0, 0.3, 0.0, 1.0)  # 荷重を落ち着かせる
    car.relocate(car.x, car.z, from_kmh / KMH, 0.0)
    start, brake, ticks = car.x, 1.0, 0
    while car.speed > 0.01 and ticks < 3000:
        car.step(0.0, 0.0, brake, 1.0)
        brake = driver(car)
        ticks += 1
    assert ticks < 3000, "止まらない"
    return car.x - start


def circle_ramp(radius: float, v0: float, v1: float, rate: float = 0.25) -> tuple:
    """中心 (0, radius) の左回りの円に沿って走らせ、速さを少しずつ上げる。返すのは (保てた横加速度の最大 g, 外れた時の速さ m/s)。"""
    car = new_car(v0)
    wheelbase = car.spec.wheelbase
    target, best, steer_trim, throttle_trim, window, limiter, lost = v0, 0.0, 0.0, 0.0, [], IdealThrottle(), None
    for tick in range(int((v1 - v0) / rate / DT) + 600):
        dx, dz = car.x, car.z - radius
        rho = math.hypot(dx, dz)
        error = rho - radius
        error_rate = (car.wvx * dx + car.wvz * dz) / rho
        v = max(car.speed, 5.0)
        kp, kd = 4.0 * wheelbase / (v * v), 3.6 * wheelbase / (v * v)
        steer_trim = max(-0.3, min(0.3, steer_trim + 0.8 * kp * error * DT))
        throttle_trim = max(-0.5, min(1.0, throttle_trim + (target - car.speed) * 0.3 * DT))
        throttle = limiter(car, max(0.0, min(1.0, 0.6 * (target - car.speed) + throttle_trim)))
        car.step(wheelbase / radius + kp * error + kd * error_rate + steer_trim, throttle, 0.0, 1.0)
        if tick > 240:
            target = min(v1, target + rate * DT)
        window.append(car.speed ** 2 / math.hypot(car.x, car.z - radius) / GRAVITY)
        if len(window) > 30:
            window.pop(0)
        if abs(error) < 1.0 and len(window) == 30:
            best = max(best, sum(window) / 30.0)
        if abs(error) > 2.5 or abs(car.body_slip) > 0.6:
            lost = car.speed
            break
    return best, lost


def test_vehicle_acceleration_and_top_speed_are_near_the_design_table():
    budgets = load_budgets()
    reached, top_kmh, gear = accel_run()
    assert reached is not None and abs(reached - DESIGN_ACCEL_0_100_S) <= budgets["vehicle_accel_0_100_tolerance_s"], reached
    assert abs(top_kmh - DESIGN_TOP_SPEED_KMH) <= budgets["vehicle_top_speed_tolerance_kmh"], top_kmh
    assert gear == 5  # 最高速は、いちばん上のギアで出る


def test_vehicle_braking_distance_is_near_the_design_table():
    distance = brake_run()
    assert abs(distance - DESIGN_BRAKE_100_0_M) <= load_budgets()["vehicle_brake_100_0_tolerance_m"], distance


def test_vehicle_maximum_lateral_acceleration_is_near_the_design_table():
    best, lost = circle_ramp(30.0, 8.0, 22.0)
    assert abs(best - DESIGN_LATERAL_G) <= load_budgets()["vehicle_lateral_g_tolerance"], best
    assert lost is not None and lost < 22.0  # 限界を超えた所で、円から外れる（限界が無いまま、最後まで回らない）


# --- 数字で固定した参照値 ---
# 舵0・アクセル全開の直進。試作（spikes/vehicle/vehicle.py）を、同じ値（カザネ RS の標準）と同じ入力で回した値
# （段0 区切り9。3,600 tickまで、状態の全部の値の差が0.0だった）。{tick: (x, 世界座標の速度のx成分, ギア, 回転数)}
STRAIGHT = {
    60: (2.430524031351723, 4.93419159383034, 1, 4499.999987906731),
    300: (59.78122771728876, 22.657800149063462, 2, 5993.383986067143),
    600: (207.88414594993245, 35.725718165755744, 3, 6703.375557127502),
    900: (405.9870966474634, 43.35776697198185, 4, 6127.358210762815),
}
# 舵とペダルを変える走り。この実装を回した値（試作から変えた所が効く入力なので、試作とは比べない）。
# 始まりは、向き0、毎秒25 m。(x, z, 向き, 速さ, ヨーレート, ギア, 回転数)
MIXED = (
    ((0.03, 0.5, 0.0, 1.0), 120, (49.82685779193432, 11.351174038341627, 0.5025555253744877, 26.5441555970166, 0.26126841112666954, 3, 4989.044347950786)),
    ((0.05, 0.0, 0.6, 1.0), 60, (69.03094861153504, 23.242890395934467, 0.7620125874105538, 18.656710457089307, 0.3832031402522817, 2, 4929.951108245466)),
    ((-0.02, 0.0, 0.0, 0.55), 60, (81.54965389000658, 35.95354341781685, 1.3431887806407914, 16.87064233869821, 0.7153698043839741, 2, 4205.829854783366)),
)


def test_vehicle_straight_line_at_full_throttle_matches_the_spike():
    car = new_car()
    for tick in range(1, 901):
        car.step(0.0, 1.0, 0.0, 1.0)
        if tick in STRAIGHT:
            x, wvx, gear, rpm = STRAIGHT[tick]
            assert car.x == pytest.approx(x, **NEAR) and car.wvx == pytest.approx(wvx, **NEAR), tick
            assert car.gear == gear and car.rpm == pytest.approx(rpm, **NEAR), tick


def test_vehicle_mixed_inputs_match_the_recorded_values():
    car = new_car(25.0)
    assert car.gear == 3  # ATは、置いた速さに合うギアを選ぶ
    for inputs, ticks, want in MIXED:
        for _ in range(ticks):
            car.step(*inputs)
        got = (car.x, car.z, car.heading, car.speed, car.yaw_rate, car.gear, car.rpm)
        assert got == pytest.approx(want, **NEAR), inputs


# 出す量（段1の操作補正とアシストが使う）。MIXED の各区間の終わりの値。この実装を回した値（式は、試作と読み比べて同じ。段0 区切り9）。
# (車体の滑り角, 前軸の滑り, 後軸の滑り, ヨーレートの目標, ヨーレートの差, 限界か, 駆動の使用率（軸）, 制動の使用率,
#  輪ごとの荷重, 輪ごとの前後の使用率, 輪ごとの横の使用率)。輪の並びは WHEELS（左前、右前、左後、右後）。
MIXED_OUTPUTS = (
    (
        -0.027668332128876892, -0.046721514532906495, -0.03905488094295756, 0.3506695504469758, -0.08940113932030624, False,
        0.28508143579073636, 0.0,
        (1219.2813381672097, 3466.4681973423585, 1432.9168648261254, 3425.7052116418226),
        (0.0, 0.0, 0.609091458726957, 0.13061858675659854),
        (-0.3558676452739465, -0.3540902098382885, -0.2987479710215624, -0.2945991793915783),
    ),
    (
        -0.10183276854263627, -0.1290558521337279, -0.125426964254344, 0.40881188969560944, -0.02560874944332775, True,
        0.0, 1.113801318799236,
        (2309.8113142035263, 3989.8358820391695, 845.6074141071986, 2335.4405214331464),
        (-1.113801318799236, -0.7199221543894755, -1.0196928954525843, -0.40503157345297464),
        (-0.9860351402821879, -0.9685102784792965, -0.9622334991557644, -0.9345107639742101),
    ),
    (
        -0.418080248286996, -0.35416420861834164, -0.462037329336102, -0.13583766396775307, 0.8512074683517272, True,
        0.0, 0.25610939839753044,
        (1667.8877281417508, 3289.506821222699, 1536.762910542845, 2974.8024836523646),
        (0.0, 0.0, -0.25610939839753044, -0.14523434155970724),
        (-2.874128401395914, -2.683549311429759, -3.8718194381943185, -3.6261415915213284),
    ),
)


def test_vehicle_output_quantities_match_the_recorded_values():
    # 出す量は、世界の要約にも、状態の比べ（state()）にも入らない。式を取り違えても、ほかの確かめは通るので、ここで値を固定する。
    car = new_car(25.0)
    assert len(MIXED_OUTPUTS) == len(MIXED)
    for (inputs, ticks, _), want in zip(MIXED, MIXED_OUTPUTS):
        for _ in range(ticks):
            car.step(*inputs)
        body_slip, slip_front, slip_rear, yaw_ref, yaw_err, on_limit, drive_axle, brake_util, loads, utils, sides = want
        got = (car.body_slip, car.slip_front, car.slip_rear, car.yaw_ref, car.yaw_err, car.drive_util_axle, car.brake_util)
        assert got == pytest.approx((body_slip, slip_front, slip_rear, yaw_ref, yaw_err, drive_axle, brake_util), **NEAR), inputs
        assert car.on_limit is on_limit, inputs
        assert tuple(car.wheel_load) == pytest.approx(loads, **NEAR), inputs
        assert tuple(car.wheel_util) == pytest.approx(utils, **NEAR), inputs
        assert tuple(car.wheel_sy) == pytest.approx(sides, **NEAR), inputs


def test_vehicle_output_quantities_have_the_signs_of_the_turn():
    # 左へ切った定常旋回（限界の内）。ヨーレートと、その目標は正（左回り）。荷重は、外側（右）の輪が大きい。
    # 横の使用率と、前後の軸の滑りは、4輪とも負で、大きさは1（限界）の内。ヨーレートの差は、実際 − 目標。
    left, right = new_car(20.0), new_car(20.0)
    for _ in range(180):
        left.step(0.04, 0.3, 0.0, 1.0)
        right.step(-0.04, 0.3, 0.0, 1.0)
    assert left.yaw_rate > 0.2 and left.yaw_ref > 0.2 and not left.on_limit
    front_left, front_right, rear_left, rear_right = left.wheel_load
    assert front_right > front_left + 1000.0 and rear_right > rear_left + 1000.0
    assert all(-1.0 < value < -0.1 for value in left.wheel_sy)
    assert left.slip_front < 0.0 and left.slip_rear < 0.0 and left.body_slip < 0.0
    assert left.yaw_err == pytest.approx(left.yaw_rate - left.yaw_ref, abs=1e-12) and left.yaw_err < 0.0  # 目標より回らない（アンダーステア）
    # 右へ切ると、符号が全部逆で、左右の輪が入れ替わる。
    assert (right.yaw_rate, right.yaw_ref, right.yaw_err) == pytest.approx((-left.yaw_rate, -left.yaw_ref, -left.yaw_err), **NEAR)
    assert (right.slip_front, right.slip_rear, right.body_slip) == pytest.approx((-left.slip_front, -left.slip_rear, -left.body_slip), **NEAR)
    assert tuple(right.wheel_load) == pytest.approx((front_right, front_left, rear_right, rear_left), **NEAR)
    left_sides = left.wheel_sy
    assert tuple(right.wheel_sy) == pytest.approx((-left_sides[1], -left_sides[0], -left_sides[3], -left_sides[2]), **NEAR)


def test_vehicle_same_inputs_give_the_same_state():
    a, b = new_car(20.0, 0.4), new_car(20.0, 0.4)
    numbers = lcg(7)
    for _ in range(600):
        steer, throttle, brake = (next(numbers) % 1101 - 550) / 1000.0, next(numbers) % 3 / 2.0, next(numbers) % 2 * 0.5
        a.step(steer, throttle, brake, 1.0)
        b.step(steer, throttle, brake, 1.0)
        assert a.state() == b.state()
    assert a.wheel_util == b.wheel_util and a.wheel_sy == b.wheel_sy and a.yaw_err == b.yaw_err


# --- 止まること ---
def test_vehicle_stays_exactly_at_rest_while_the_wheel_is_turned_and_the_brake_is_pumped():
    car = Car(spec())
    car.reset(3.0, -2.0, 0.7)
    for tick in range(300):
        car.step(0.5 * math.sin(tick * 0.2), 0.0, 1.0 if tick // 30 % 2 else 0.0, 1.0)
        assert (car.x, car.z, car.heading, car.speed, car.yaw_rate) == (3.0, -2.0, 0.7, 0.0, 0.0), tick


def test_vehicle_full_braking_stops_without_rolling_back():
    car = new_car(60.0 / KMH)
    stopped_at, lowest = None, 0.0
    for tick in range(1, 601):
        car.step(0.2, 0.0, 1.0, 1.0)
        lowest = min(lowest, car.vx)
        if stopped_at is None and car.speed == 0.0 and car.yaw_rate == 0.0:
            stopped_at = tick
    assert stopped_at is not None and stopped_at * DT < 2.5  # 試作では1.8〜1.9秒
    assert lowest > -1e-3  # 行き過ぎて、後ろへ動かない
    assert car.speed == 0.0 and car.yaw_rate == 0.0 and car.vx == 0.0  # 止まった後は、ちょうど0のまま


def yaw_flip_ratio(rates: list) -> float:
    """ヨーレートの、増える・減るが、tickごとに入れ替わる割合（0〜1）。1に近いほど、毎tick反転している。"""
    steps = [b - a for a, b in zip(rates, rates[1:]) if abs(b - a) > 1e-9]
    if len(steps) < 3:
        return 0.0
    return sum(1 for a, b in zip(steps, steps[1:]) if a * b < 0.0) / (len(steps) - 1)


def test_vehicle_coasting_with_full_lock_comes_to_rest_without_the_yaw_rate_flipping():
    # 止める力の頭打ちの確かめ。外すと、極低速で、ヨーレートが毎tick反転して、静止しない（試作の実測）。
    car = new_car(5.0)
    rates, rest_tick = [], None
    for tick in range(1, 60 * 30 + 1):
        car.step(0.5, 0.0, 0.0, 1.0)
        if 0.05 < car.speed < 3.0:
            rates.append(car.yaw_rate)
        if car.speed == 0.0 and car.yaw_rate == 0.0:
            rest_tick = tick
            break
    assert rest_tick is not None and rest_tick * DT < 20.0  # 試作では9〜12秒
    assert len(rates) > 100 and yaw_flip_ratio(rates) < 0.05


def test_vehicle_spinning_with_full_throttle_then_letting_go_never_gains_energy_and_stops():
    car = new_car()
    for _ in range(300):
        car.step(0.5, 1.0, 0.0, 1.0)  # 舵いっぱいで全開を5秒
    assert car.speed > 3.0 and abs(car.yaw_rate) > 0.5
    before, rest_tick = energy(car), None
    for tick in range(1, 60 * 40 + 1):
        car.step(0.0, 0.0, 0.0, 1.0)
        now = energy(car)
        assert now <= before + 1e-6, tick
        before = now
        if car.speed == 0.0 and car.yaw_rate == 0.0:
            rest_tick = tick
            break
    assert rest_tick is not None
    assert math.isfinite(car.x + car.z + car.heading)


# --- アクセルを離している間、平地で、運動エネルギーが増えない ---
def place(start: str) -> Car:
    """前向き、後ろ向き、横向きに動いている車（どれも、前進のギア）。"""
    car = Car(spec())
    if start == "forward":
        car.reset(0.0, 0.0, 0.3, 30.0)
    elif start == "backward":
        car.reset(0.0, 0.0, 0.3, -15.0)
    else:
        car.reset(0.0, 0.0, 0.0)
        car.relocate(0.0, 0.0, 0.0, 20.0)  # 向きは +x、動きは +z（真横）
    return car


@pytest.mark.parametrize("start", ["forward", "backward", "sideways"])
@pytest.mark.parametrize("with_brake", [False, True])
@pytest.mark.parametrize("seed, hold", [(1, 1), (2, 7), (3, 20)])
def test_vehicle_energy_never_rises_while_the_throttle_is_released(start, with_brake, seed, hold):
    # 舵（とブレーキ）を、整数の線形合同法で作って、hold tickごとに変える。ブレーキを踏まない組は、エンジンブレーキと抵抗だけで減る。
    car, numbers = place(start), lcg(seed)
    assert car.gear >= 1
    began = before = energy(car)
    steer = brake = 0.0
    for tick in range(1200):
        if tick % hold == 0:
            steer = (next(numbers) % 1101 - 550) / 1000.0
            brake = next(numbers) % 3 * 0.5 if with_brake else 0.0
        car.step(steer, 0.0, brake, 1.0)
        now = energy(car)
        assert now <= before + 1e-6, (tick, steer, brake)
        before = now
    assert before < 0.5 * began  # 20秒で、半分より減っている（何も起きていない走りで、通らない）


def test_vehicle_rolling_backwards_in_a_forward_gear_slows_down():
    # 試作の形（エンジンブレーキが、負の駆動力）では、前進のギアのまま後ろ向きに動くと、車が後ろ向きに加速した
    # （毎秒8 mから、16秒で毎秒17〜20 m）。エンジンブレーキは、車輪の進む向きに逆らう。
    car = new_car(-8.0)
    assert car.gear == 1 and car.vx == -8.0
    fastest = car.speed
    for _ in range(16 * 60):
        car.step(0.0, 0.0, 0.0, 1.0)
        assert car.speed <= fastest + 1e-9
        fastest = car.speed
    assert car.speed < 4.0 and car.vx <= 0.0


def test_vehicle_engine_braking_goes_to_the_driven_wheels_as_a_braking_demand():
    car = new_car(100.0 / KMH)
    car.step(0.0, 0.0, 0.0, 1.0)
    # 後輪駆動。アクセルを離すと、駆動力は0で、エンジンブレーキが、後輪の制動の使用率（負）に出る。前輪には出ない。
    assert car.drive_force == 0.0 and car.engine_brake_force > 100.0
    assert car.wheel_util[0] == car.wheel_util[1] == 0.0 and car.wheel_util[2] < -0.01 and car.wheel_util[3] < -0.01
    assert car.ax < 0.0
    coasting = car.ax
    car.step(0.0, 1.0, 0.0, 1.0)
    assert car.drive_force > 0.0 and car.engine_brake_force == 0.0 and car.ax > coasting


# --- 舵。最大舵角で切るだけで、速さを制限しない ---
def test_vehicle_steer_command_is_only_clamped_to_the_lock_and_never_rate_limited():
    car = new_car(10.0)
    lock = car.spec.max_steer
    for command, want in ((0.5, 0.5), (-0.5, -0.5), (lock, lock), (0.9, lock), (-9.0, -lock), (float("inf"), lock), (0.0, 0.0), (0.001, 0.001)):
        car.step(command, 0.0, 0.0, 1.0)
        assert car.steer == want, command  # 1 tickで、指令のとおりになる


# --- AT ---
def test_vehicle_automatic_shifts_up_through_every_gear_and_cuts_the_drive_while_shifting():
    car = new_car()
    gears, shifting_ticks = [1], 0
    for _ in range(60 * 40):
        before = car.gear
        car.step(0.0, 1.0, 0.0, 1.0)
        if car.gear != before:
            gears.append(car.gear)
        if car.shift_t > 0.0:
            shifting_ticks += 1
            assert car.drive_force == 0.0  # 変速中は、駆動力が0
    assert gears == [1, 2, 3, 4, 5]
    # 変速1回が、約0.2秒。残り時間を小数で減らすので、12 tickちょうどにはならず、13 tick（試作と同じ。0.2 − 12/60 が、0より少し大きい）。
    assert shifting_ticks == 4 * (round(car.spec.shift_time / DT) + 1)
    assert car.rpm < car.spec.redline_rpm


def test_vehicle_automatic_shifts_down_while_braking_and_ends_in_first():
    car = new_car(150.0 / KMH)
    assert car.gear == 5
    gears = [5]
    for _ in range(60 * 12):
        before = car.gear
        car.step(0.0, 0.0, 0.5, 1.0)
        if car.gear != before:
            gears.append(car.gear)
    assert gears == [5, 4, 3, 2, 1] and car.speed == 0.0


def test_vehicle_with_the_automatic_off_only_shifts_when_asked():
    car = new_car()
    car.auto = False
    for _ in range(600):
        car.step(0.0, 1.0, 0.0, 1.0)
    assert car.gear == 1 and car.rpm > car.spec.shift_up_rpm  # 自分では上げない
    assert car.shift_down() is False and car.gear == 1
    assert car.shift_up() is True and car.gear == 2 and car.shift_t == car.spec.shift_time
    assert car.shift_up() is True and car.shift_up() is True and car.shift_up() is True and car.gear == 5
    assert car.shift_up() is False and car.gear == 5  # いちばん上
    assert car.shift_down() is True and car.gear == 4


# --- 後退 ---
def test_vehicle_reverse_gear_is_taken_only_from_first_and_not_while_shifting():
    car = new_car()
    assert car.shift_to_forward() is False and car.gear == 1  # 後退でなければ、受けない
    assert car.shift_to_reverse() is True and car.gear == REVERSE == -1 and car.shift_t == car.spec.shift_time
    before = car.state()
    assert car.shift_to_reverse() is False and car.shift_to_forward() is False  # 変速中は、どちらも受けない
    assert car.shift_up() is False and car.shift_down() is False  # 後退からは、上げ下げできない
    assert car.state() == before
    for _ in range(round(car.spec.shift_time / DT) + 1):
        car.step(0.0, 0.0, 0.0, 1.0)
    assert car.shift_t <= 0.0 and car.shift_to_forward() is True and car.gear == 1
    # 2速からは、後退へ入れない。
    second = new_car()
    second.auto = False
    second.shift_up()
    for _ in range(20):
        second.step(0.0, 0.0, 0.0, 1.0)
    before = second.state()
    assert second.gear == 2 and second.shift_t <= 0.0 and second.shift_to_reverse() is False and second.state() == before


def test_vehicle_in_reverse_the_throttle_drives_backwards_and_left_lock_turns_the_heading_right():
    car = new_car()
    assert car.shift_to_reverse()
    for _ in range(180):
        car.step(0.2, 0.5, 0.0, 1.0)
    assert car.gear == REVERSE  # 後退のギアでは、ATは変速しない
    assert car.vx < -3.0 and car.x < -5.0  # 後ろへ進む
    assert car.yaw_rate < 0.0 and car.heading < -0.3  # 左へ切って後ろへ進むと、車体の向きは右へ回る
    assert car.z > 0.0  # 車体の後ろは、左（+z）へ出る
    # 後退中のブレーキで、止まる。
    for _ in range(300):
        car.step(0.0, 0.0, 1.0, 1.0)
    assert car.speed == 0.0 and car.gear == REVERSE


# --- 置き直す口 ---
def test_vehicle_relocate_also_resets_the_body_frame_velocity():
    car = new_car(20.0, 0.5)
    for _ in range(30):
        car.step(0.0, 0.3, 0.0, 1.0)
    heading, yaw_rate, gear = car.heading, car.yaw_rate, car.gear
    car.relocate(7.0, -3.0, 0.0, 4.0)
    assert (car.x, car.z, car.wvx, car.wvz) == (7.0, -3.0, 0.0, 4.0) and car.speed == 4.0
    assert car.vx == pytest.approx(4.0 * math.sin(heading)) and car.vy == pytest.approx(4.0 * math.cos(heading))
    assert (car.heading, car.yaw_rate, car.gear) == (heading, yaw_rate, gear)  # 向き、ヨーレート、ギアは、変えない
    # 次のtickの駆動系は、置き直した速度を読む（1 tick古い値を使わない）。速さを0に置けば、回転数は、アイドリングへ向かう。
    car.relocate(7.0, -3.0, 0.0, 0.0)
    assert car.vx == 0.0 and car.vy == 0.0
    before = car.rpm
    car.step(0.0, 0.0, 0.0, 1.0)
    assert car.rpm < before


# --- 範囲の外の入力 ---
@pytest.mark.parametrize(
    "inputs",
    [
        (0.0, -0.01, 0.0, 1.0), (0.0, 1.01, 0.0, 1.0), (0.0, float("nan"), 0.0, 1.0), (0.0, 0.0, -0.5, 1.0), (0.0, 0.0, 2.0, 1.0),
        (0.0, 0.0, float("nan"), 1.0), (float("nan"), 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, -0.1), (0.0, 0.0, 0.0, float("nan")),
        (0.0, 0.0, 0.0, float("inf")), (0.0, float("inf"), 0.0, 1.0),
    ],
)
def test_vehicle_inputs_outside_the_range_are_value_errors_and_change_nothing(inputs):
    car = new_car(10.0)
    before = car.state()
    with pytest.raises(ValueError):
        car.step(*inputs)
    assert car.state() == before


def test_vehicle_edges_of_the_ranges_are_accepted():
    car = new_car(10.0)
    for inputs in ((0.0, 0.0, 0.0, 0.0), (0.0, 1.0, 1.0, 1.0), (0, 1, 0, 1), (-0.55, 0.0, 1.0, 0.55)):
        car.step(*inputs)
    assert math.isfinite(car.x + car.z + car.heading + car.speed)


def test_vehicle_grass_gives_less_grip_than_asphalt():
    on_asphalt, on_grass = new_car(100.0 / KMH), new_car(100.0 / KMH)
    for _ in range(60):
        on_asphalt.step(0.0, 0.0, 1.0, 1.0)
        on_grass.step(0.0, 0.0, 1.0, 0.55)
    assert on_grass.speed > on_asphalt.speed + 3.0  # 摩擦係数が小さいと、減速が弱い


# --- 車の値の矛盾の検査 ---
def test_vehicle_spec_problems_are_none_for_the_shipped_entry():
    assert vehicle.spec_problems(car_entry()) == []


def test_vehicle_spec_problems_list_gear_ratios_that_do_not_fall():
    entry = car_entry()
    entry["drivetrain"]["gears"] = [3.1, 1.9, 1.9, 1.0, 1.2]  # 3速が2速と同じ、5速が4速より大きい
    assert vehicle.spec_problems(entry) == [
        (("drivetrain", "gears", 2), "gear ratio 1.9 is not below the gear before it (1.9)"),
        (("drivetrain", "gears", 4), "gear ratio 1.2 is not below the gear before it (1.0)"),
    ]


def test_vehicle_spec_problems_list_torque_points_that_do_not_rise():
    entry = car_entry()
    curve = entry["engine"]["torque_curve"]
    curve[2]["rpm"] = curve[1]["rpm"]  # 同じ回転数が2つ（折れ線を引くと、0で割る）
    curve[5]["rpm"] = 100.0
    assert vehicle.spec_problems(entry) == [
        (("engine", "torque_curve", 2, "rpm"), "rpm 2500.0 is not above the point before it (2500.0)"),
        (("engine", "torque_curve", 5, "rpm"), "rpm 100.0 is not above the point before it (6500.0)"),
    ]
