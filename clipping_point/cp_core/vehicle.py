"""車両モデル（純Python）。決まりは docs/design/overview.md の「車両モデル」。元は、設計時の試作（spikes/vehicle/vehicle.py）。

車輪の回転を状態に持たない4輪モデル。1 tick（1/60秒）の中を SUBSTEPS 回に分けて、世界座標の速度を積分する。
  座標     平面 (x, z)。向きは +x が 0、+z が +π/2。値が増える向きが左旋回。左の向きの単位ベクトルは (−sin h, cos h)
  符号     舵角、車体座標の横の速度（vy）、ヨーレートは、左が正。単位は m、s、rad、kg、N
  駆動と制動 輪ごとの「要求した力」を、タイヤが出せる力（摩擦係数×荷重）で頭打ちにする。u = 要求した力 ÷ 出せる力 が、
           前後の力の使用率（1を超えると空転、−1を下回るとロック）
  横力     出せる力 × ky(u) × sin(C × atan(B × sy))。sy = 滑り角の tan ÷ 最大グリップの滑り角の tan（1で最大。超えると落ちる）
  止める力の頭打ち  各輪の横力と制動力を、その輪を1回の分割で止める力までにする（安定の決め手。外すと、極低速で静止しない）
  荷重移動 ならした車体加速度（axf、ayf）から、4輪の荷重を出す
車の値（CarSpec）は、定義データの車の項目（cars.json）から作る（spec_from_entry）。式の値も、全部、その項目から読む。
ここに置く数は、物理の定数、単位の換算、1 tickの分け方（SUBSTEPS）、0で割らないための守り（MIN_TIRE_FORCE_N）だけ。
試作から変えた所（設計の「車両モデル」の、段1での扱いの先取り。段0 区切り9）：
  (a) 舵の速さを制限しない。受け取った舵角の指令を、車の最大舵角で切るだけ（切る速さは、操作補正の1か所で決める）
  (b) エンジンブレーキは、駆動輪の制動の要求に足す（車輪の進む向きに逆らう力になり、止める力の頭打ちが一緒に掛かる）。
      試作の形（負の駆動力）では、前進ギアのまま後ろ向きに動くと、車が後ろ向きに加速した
  (c) step() は、刻みの長さを受けない（いつも 1 tick）
  (d) アクセルとブレーキが範囲の外なら ValueError（黙って丸めない）
入れていないもの（段1の「車両モデル」の区切り）：ターボ、セッティングの対応（標準の値だけを、車の値として持つ）、荒れた路面、
輪ごとの路面、勾配、後輪ブレーキの倍率、MTの画面からの操作（変速の口だけは、ここにある）。
出す量（操作補正とアシストが段1で使う）：輪ごとの前後の使用率（wheel_util）、輪ごとの横の使用率（wheel_sy）、
車体の滑り角（body_slip）、ヨーレートの差（yaw_err）。
車の値の矛盾の検査（spec_problems）は、読み込み検査（cp_core/datadefs.py）が呼ぶ。ここからは datadefs を読み込まない。
"""
from dataclasses import dataclass
from math import atan, atan2, cos, isfinite, pi, sin, sqrt, tan

from cp_core.fixed_loop import TICK_HZ

GRAVITY = 9.81  # 重力加速度（m/s²）
AIR_DENSITY = 1.2  # 空気の密度（kg/m³）
PS_TO_W = 735.5  # 馬力（ps）を W にする
RPM_PER_RAD_S = 30.0 / pi  # 角速度（rad/s）を回転数（rpm）にする
TWO_PI = 2.0 * pi
SECONDS_PER_MINUTE = 60.0
DT = 1.0 / TICK_HZ  # 1 tick（秒）
# 1 tickの中の分割数。設計の「車両モデル」の決め（分割数2で、16分割との位置の差は0.09 m以下。試作の実測）。
SUBSTEPS = 2
SUBSTEP_S = DT / SUBSTEPS  # 分割1回の長さ（秒）
MIN_TIRE_FORCE_N = 1.0  # 出せる力がこれ未満の輪は、力を出さない（浮いた輪。0で割らないための守り）
REVERSE = -1  # 後退のギアの番号。前進は 1〜（変速比の数）
WHEELS = ("front_left", "front_right", "rear_left", "rear_right")  # 輪ごとの量（wheel_load、wheel_util、wheel_sy）の並び


@dataclass(frozen=True, slots=True)
class CarSpec:
    """車の値。定義データの車の項目から作る（spec_from_entry）。書き換えられない。導いた値も、ここに持つ。"""

    car_id: str  # 車の id
    mass: float  # 質量（kg）
    wheelbase: float  # ホイールベース（m）
    track: float  # トレッド（m）
    cg_to_front: float  # 重心から前軸まで（m）
    cg_to_rear: float  # 重心から後軸まで（m）
    yaw_inertia: float  # ヨーの慣性モーメント（kg·m²）
    half_length: float  # 車体の半長（m）。壁の当たり用
    half_width: float  # 車体の半幅（m）。壁の当たり用
    max_steer: float  # 車の最大舵角（rad）
    static_front: float  # 前の1輪の、止まっているときの荷重（N）
    static_rear: float  # 後ろの1輪の、止まっているときの荷重（N）
    load_long: float  # 前後の荷重移動（1輪あたり。N ÷ (m/s²)）
    load_lat_front: float  # 左右の荷重移動のうち、前軸の分（N ÷ (m/s²)）
    load_lat_rear: float  # 同じく、後軸の分
    load_blend: float  # 分割1回で、ならした車体加速度を、いまの加速度へ寄せる割合（0〜1）
    stop_front: float  # 前の1輪を、分割1回で止める力（N ÷ (m/s)）。止める力の頭打ち
    stop_rear: float  # 後ろの1輪の分
    stop_body: float  # 車体を、分割1回で止める力（N ÷ (m/s)）。転がり抵抗の頭打ち
    rolling_force: float  # 転がり抵抗（N）
    drag_k: float  # 空気抵抗（N ÷ (m/s)²）
    lift_k: float  # ダウンフォース（N ÷ (m/s)²）
    aero_front: float  # ダウンフォースの、前軸の取り分（0〜1）
    tire_mu: float  # タイヤの摩擦係数
    grip_front: float  # 前輪のグリップの倍率
    grip_rear: float  # 後輪のグリップの倍率
    peak_slip: float  # タイヤが最大グリップを出す滑り角（rad）
    tan_peak_inv: float  # 1 ÷ tan(peak_slip)
    low_speed_reg: float  # 低速の正則化。滑り角の計算で、前後の速度をこれ未満にしない（m/s）
    curve_c: float  # 横力の式の形（C）
    curve_b: float  # 横力の式の B。sy = 1 で最大になるように、C から導く
    ellipse_k: float  # 摩擦楕円。ky = sqrt(1 − ellipse_k × u²)
    ellipse_edge: float  # |u| = 1 での ky
    spin_k: float  # |u| が1を超えた輪の、横力の落ち方
    slide_force: float  # 空転かロックした輪の、前後の力（出せる力に対する割合）
    slide_full_inv: float  # 要求が、出せる力をどれだけ超えたら、slide_force まで落ち切るかの逆数
    load_k: float  # 荷重が増えると、摩擦係数が下がる割合
    brake_force: float  # ブレーキを踏み切ったときの、制動の要求の合計（N）
    brake_front: float  # 制動の、前軸の取り分（0〜1）
    front_drive: float  # 駆動力の、前軸の取り分（0＝後輪駆動、1＝前輪駆動）
    gear_total: tuple  # 総減速比。[0] は使わない。[1]〜[n_gears] が前進、末尾（[REVERSE]）が後退（負の値）
    n_gears: int  # 前進のギアの数
    rpm_per_m_s: float  # 車速（m/s）×総減速比 を、回転数（rpm）にする係数
    wheel_radius: float  # タイヤの半径（m）
    efficiency: float  # 駆動系の効率（0〜1）
    idle_rpm: float  # アイドリングの回転数
    redline_rpm: float  # 回転数の上限。ここから上は、トルクが0
    launch_rpm: float  # 全開で発進するときの、クラッチが滑っている間の回転数
    shift_up_rpm: float  # ATが上げる回転数
    shift_down_rpm: float  # ATが下げる線。1つ下のギアでの回転数が、これ未満なら下げる
    shift_down_first_rpm: float  # 2速から1速へ下げる線（低い。1速に入りたがると、全開でスピンする。試作の実測）
    shift_time: float  # 変速にかかる時間（秒）。この間は、駆動力が0
    torque_table: tuple  # トルクの表（N·m）。torque_step ごと
    torque_step: float  # トルクの表の刻み（rpm）
    engine_brake: float  # エンジンブレーキ（N·m ÷ rpm）
    rpm_blend: float  # 1 tickで、回転数の表示の値を、いまの値へ寄せる割合（0〜1）
    lsd_lock: float  # LSDのロック率（0〜1）
    lsd_coupling: float  # 左右の車輪の速さの差に対する、力の移し方（N ÷ (m/s)）
    lsd_preload: float  # LSDのプリロード（N）
    lsd_ramp: float  # 駆動力が大きいほど、移せる力が増える割合
    rest_speed_sq: float  # 静止への吸い付き。速さの2乗が、これ未満で（m²/s²）
    rest_yaw_rate: float  # 同じく、ヨーレートの大きさが、これ未満なら（rad/s）、アクセルを離していれば、止める
    slip_min_speed: float  # 出す量：滑り角を出す、速さの下限（m/s）。これ以下は0
    slip_speed_floor: float  # 出す量：滑り角の計算で、前後の速度をこれ未満にしない（m/s）
    limit_min_speed: float  # 出す量：限界を超えたか（on_limit）を見る、速さの下限（m/s）
    yaw_ref_min_speed: float  # 出す量：ヨーレートの目標を、路面が支えられる値で切る、速さの下限（m/s）


def _curve(points: tuple, rpm: float) -> float:
    """トルクの曲線（(回転数, 割合) の並び。回転数は昇順）を、折れ線で引く。両端の外は、端の値。"""
    if rpm <= points[0][0]:
        return points[0][1]
    for index in range(1, len(points)):
        r1, t1 = points[index]
        if rpm <= r1:
            r0, t0 = points[index - 1]
            return t0 + (t1 - t0) * (rpm - r0) / (r1 - r0)
    return points[-1][1]


def spec_problems(entry: dict) -> list:
    """車の値の矛盾の検査。読み込み検査が、鍵ごとの規則を全部通った項目にだけ呼ぶ。返すのは [(鍵の道, 問題の文)]。

    - 変速比が、1速から大きい順に並んでいる（同じ値も受けない）
    - トルクの曲線の回転数が、昇順に並んでいる（同じ値も受けない。折れ線を引くときに、0で割る）
    """
    problems = []
    gears = entry["drivetrain"]["gears"]
    for index in range(1, len(gears)):
        if not gears[index] < gears[index - 1]:
            problems.append((("drivetrain", "gears", index), f"gear ratio {gears[index]} is not below the gear before it ({gears[index - 1]})"))
    curve = entry["engine"]["torque_curve"]
    for index in range(1, len(curve)):
        if not curve[index]["rpm"] > curve[index - 1]["rpm"]:
            problems.append((
                ("engine", "torque_curve", index, "rpm"),
                f"rpm {curve[index]['rpm']} is not above the point before it ({curve[index - 1]['rpm']})",
            ))
    return problems


def spec_from_entry(entry: dict) -> CarSpec:
    """定義データの車の項目（読み込み検査を通ったもの。GameData.entry("cars", id)）から、車の値を作る。"""
    body, engine, drivetrain, lsd = entry["body"], entry["engine"], entry["drivetrain"], entry["lsd"]
    tires, suspension, brakes, aero = entry["tires"], entry["suspension"], entry["brakes"], entry["aero"]
    rest, outputs = entry["rest"], entry["outputs"]
    mass, wheelbase, track, cg_height = body["mass_kg"], body["wheelbase_m"], body["track_m"], body["cg_height_m"]
    cg_to_front = wheelbase * (1.0 - body["front_weight"])
    cg_to_rear = wheelbase * body["front_weight"]
    # トルクの表。曲線（割合）を、刻みごとに引いて、最高出力が power_ps になる倍率を掛ける。
    step, redline = engine["torque_step_rpm"], engine["redline_rpm"]
    points = tuple((point["rpm"], point["ratio"]) for point in engine["torque_curve"])
    top = int(redline / step)  # 回転数の上限（未満）で引く、いちばん上の番号
    shape = [_curve(points, index * step) for index in range(top + 2)]
    power_max = max(shape[index] * index * step for index in range(top + 1))
    scale = engine["power_ps"] * PS_TO_W / (power_max * TWO_PI / SECONDS_PER_MINUTE)
    torque_table = tuple(scale * value for value in shape)
    final, radius = drivetrain["final_gear"], drivetrain["wheel_radius_m"]
    gear_total = (0.0, *(gear * final for gear in drivetrain["gears"]), -drivetrain["reverse_gear"] * final)
    load_transfer, rpm_smooth = suspension["load_transfer_s"], engine["rpm_smooth_s"]
    curve_c, ellipse_k, peak_slip = tires["curve_c"], tires["ellipse_k"], tires["peak_slip_rad"]
    return CarSpec(
        car_id=entry["id"],
        mass=mass,
        wheelbase=wheelbase,
        track=track,
        cg_to_front=cg_to_front,
        cg_to_rear=cg_to_rear,
        yaw_inertia=mass * cg_to_front * cg_to_rear * body["yaw_inertia_k"],
        half_length=body["half_length_m"],
        half_width=body["half_width_m"],
        max_steer=entry["steering"]["max_steer_rad"],
        static_front=mass * GRAVITY * cg_to_rear / wheelbase * 0.5,
        static_rear=mass * GRAVITY * cg_to_front / wheelbase * 0.5,
        load_long=mass * cg_height / wheelbase * 0.5,
        load_lat_front=mass * cg_height / track * suspension["roll_front"],
        load_lat_rear=mass * cg_height / track * (1.0 - suspension["roll_front"]),
        load_blend=SUBSTEP_S / load_transfer if SUBSTEP_S < load_transfer else 1.0,
        stop_front=mass * cg_to_rear / wheelbase * 0.5 / SUBSTEP_S,
        stop_rear=mass * cg_to_front / wheelbase * 0.5 / SUBSTEP_S,
        stop_body=mass / SUBSTEP_S,
        rolling_force=tires["rolling_resistance"] * mass * GRAVITY,
        drag_k=0.5 * AIR_DENSITY * aero["drag_area_m2"],
        lift_k=0.5 * AIR_DENSITY * aero["lift_area_m2"],
        aero_front=aero["front_share"],
        tire_mu=tires["mu"],
        grip_front=tires["grip_front"],
        grip_rear=tires["grip_rear"],
        peak_slip=peak_slip,
        tan_peak_inv=1.0 / tan(peak_slip),
        low_speed_reg=tires["low_speed_reg_m_s"],
        curve_c=curve_c,
        curve_b=tan(pi / (2.0 * curve_c)),
        ellipse_k=ellipse_k,
        ellipse_edge=sqrt(1.0 - ellipse_k),
        spin_k=tires["spin_k"],
        slide_force=tires["slide_force"],
        slide_full_inv=tires["slide_full_inv"],
        load_k=tires["load_k"],
        brake_force=brakes["force_g"] * mass * GRAVITY,
        brake_front=brakes["front_share"],
        front_drive=drivetrain["front_drive"],
        gear_total=gear_total,
        n_gears=len(drivetrain["gears"]),
        rpm_per_m_s=RPM_PER_RAD_S / radius,
        wheel_radius=radius,
        efficiency=drivetrain["efficiency"],
        idle_rpm=engine["idle_rpm"],
        redline_rpm=redline,
        launch_rpm=engine["launch_rpm"],
        shift_up_rpm=drivetrain["shift_up_rpm"],
        shift_down_rpm=drivetrain["shift_up_rpm"] * drivetrain["shift_down_k"],
        shift_down_first_rpm=drivetrain["shift_up_rpm"] * drivetrain["shift_down_first_k"],
        shift_time=drivetrain["shift_time_s"],
        torque_table=torque_table,
        torque_step=step,
        engine_brake=engine["engine_brake_k"] * max(torque_table) / redline,
        rpm_blend=DT / rpm_smooth if DT < rpm_smooth else 1.0,
        lsd_lock=lsd["lock"],
        lsd_coupling=lsd["coupling_n_s_per_m"],
        lsd_preload=lsd["preload_n"],
        lsd_ramp=lsd["ramp"],
        rest_speed_sq=rest["speed_m_s"] * rest["speed_m_s"],
        rest_yaw_rate=rest["yaw_rate_rad_s"],
        slip_min_speed=outputs["slip_min_speed_m_s"],
        slip_speed_floor=outputs["slip_speed_floor_m_s"],
        limit_min_speed=outputs["limit_min_speed_m_s"],
        yaw_ref_min_speed=outputs["yaw_ref_min_speed_m_s"],
    )


def _make_tire(spec: CarSpec):
    """車の値を抱えた、タイヤ1輪の式を作る。車（Car）が、作るときに1度だけ呼ぶ。"""
    ellipse_k, ellipse_edge, spin_k = spec.ellipse_k, spec.ellipse_edge, spec.spin_k
    slide_drop, slide_full_inv = 1.0 - spec.slide_force, spec.slide_full_inv
    curve_c, curve_b = spec.curve_c, spec.curve_b
    tan_peak_inv, low_speed_reg = spec.tan_peak_inv, spec.low_speed_reg

    def tire(vlong: float, vlat: float, fmax: float, fdrv: float, fbrk: float, stop: float) -> tuple:
        """タイヤ1輪。返すのは (前後の力, 横の力, 横の使用率 sy, 前後の使用率 u)。輪の向きの座標で。

        vlong、vlat は、接地点の速度の、輪の向きの成分と、横の成分（m/s）。fmax は、出せる力（摩擦係数×荷重。N）。
        fdrv は、駆動の要求（符号つき。N）。fbrk は、制動の要求（0以上。転がる向きに逆らう。N）。
        stop は、この輪を分割1回で止める力（N ÷ (m/s)）。制動力と横力は、これ×速度 を超えない。
        """
        if fmax < MIN_TIRE_FORCE_N:
            return 0.0, 0.0, 0.0, 0.0
        av = vlong if vlong >= 0.0 else -vlong
        if fbrk > 0.0:
            lim = stop * av  # 制動は、分割1回の中で、輪を逆向きに回さない
            if fbrk > lim:
                fbrk = lim
            fxc = fdrv - fbrk if vlong > 0.0 else fdrv + fbrk
        else:
            fxc = fdrv
        u = fxc / fmax
        au = u if u >= 0.0 else -u
        if au <= 1.0:
            fx = fxc
            ky = sqrt(1.0 - ellipse_k * au * au)
        else:
            over = au - 1.0
            drop = over * slide_full_inv
            if drop > 1.0:
                drop = 1.0
            fx = fmax * (1.0 - slide_drop * drop)
            if u < 0.0:
                fx = -fx
            ky = ellipse_edge / (1.0 + spin_k * over)
        sy = vlat / (av if av > low_speed_reg else low_speed_reg) * tan_peak_inv
        asy = sy if sy >= 0.0 else -sy
        fy = fmax * ky * sin(curve_c * atan(curve_b * asy))
        lim = stop * (vlat if vlat >= 0.0 else -vlat)  # 横力は、分割1回の中で、横滑りを逆向きにしない
        if fy > lim:
            fy = lim
        if vlat > 0.0:
            fy = -fy
        return fx, fy, sy, u

    return tire


class Car:
    """車1台。状態を持つ。step() の1回が 1 tick。

    状態（次のtickを決めるもの）：位置（x、z）、向き（heading）、世界座標での速度（wvx、wvz）、ヨーレート（yaw_rate）、
    実舵角（steer）、ならした車体加速度（axf、ayf）、ギア（gear）、回転数（rpm）、変速の残り時間（shift_t）。
    車体座標での速度（vx、vy）は、tickの終わりに、世界座標での速度と向きから置く。次のtickの駆動系が vx を読むので、
    外から位置や速度を書くときは、relocate() を使う（属性を直に書くと、vx が1 tick古いままになる）。
    ほかの属性は、直近のtickの結果（出す量）。
    """

    __slots__ = (
        "spec", "auto", "_tire",
        "x", "z", "heading", "wvx", "wvz", "yaw_rate", "steer", "axf", "ayf", "gear", "rpm", "shift_t",
        "vx", "vy", "speed", "ax", "ay", "drive_force", "engine_brake_force",
        "body_slip", "slip_front", "slip_rear", "wheel_load", "wheel_util", "wheel_sy",
        "on_limit", "drive_util", "drive_util_axle", "brake_util", "yaw_ref", "yaw_err",
    )

    def __init__(self, spec: CarSpec) -> None:
        if not isinstance(spec, CarSpec):
            raise TypeError(f"Car takes a CarSpec, got {type(spec).__name__}")
        self.spec = spec
        # ATか。False にすると、自分では変速しない（shift_up()、shift_down() で変える）。MTの操作は、段1で作る。
        self.auto = True
        self._tire = _make_tire(spec)
        self.reset(0.0, 0.0, 0.0)

    def reset(self, x: float, z: float, heading: float, speed: float = 0.0) -> None:
        """車を置き直す。向き heading（rad）へ、速さ speed（m/s。負なら後ろ向き）で進んでいる状態にする。ほかの状態は、始まりの値。

        ATなら、ギアは、速さに合うものを選ぶ。世界がスタート位置に置くときと、テストと道具が、決めた位置と速度に置くときに使う。
        """
        spec = self.spec
        self.x = float(x)
        self.z = float(z)
        self.heading = float(heading)
        self.wvx = speed * cos(heading)
        self.wvz = speed * sin(heading)
        self.vx = float(speed)
        self.vy = 0.0
        self.yaw_rate = 0.0
        self.speed = abs(float(speed))
        self.steer = 0.0
        self.axf = 0.0
        self.ayf = 0.0
        self.ax = 0.0
        self.ay = 0.0
        self.shift_t = 0.0
        gear = 1
        if self.auto and speed > 0.0:
            while gear < spec.n_gears and speed * spec.rpm_per_m_s * spec.gear_total[gear] > (
                spec.shift_down_rpm if gear > 1 else spec.shift_down_first_rpm
            ):
                gear += 1
        self.gear = gear
        self.rpm = max(spec.idle_rpm, abs(speed) * spec.rpm_per_m_s * spec.gear_total[gear])
        self.drive_force = 0.0  # 駆動力（N。符号つき）。エンジンブレーキの間は0
        self.engine_brake_force = 0.0  # エンジンブレーキとして、駆動輪の制動の要求に足した力（N。0以上）
        self.body_slip = 0.0  # 車体の滑り角（rad）
        self.slip_front = 0.0  # 前軸の滑り角（rad）。正は、接地点が、輪の向きの左へ動いている
        self.slip_rear = 0.0
        self.wheel_load = [spec.static_front, spec.static_front, spec.static_rear, spec.static_rear]  # 輪ごとの荷重（N）。並びは WHEELS
        self.wheel_util = [0.0, 0.0, 0.0, 0.0]  # 輪ごとの前後の使用率
        self.wheel_sy = [0.0, 0.0, 0.0, 0.0]  # 輪ごとの横の使用率
        self.on_limit = False  # どれかの輪が、前後か横の限界を超えているか
        self.drive_util = 0.0  # 駆動輪の前後の使用率の最大（0以上）
        self.drive_util_axle = 0.0  # 駆動軸ごとの、要求した駆動力 ÷ 出せる力 の最大
        self.brake_util = 0.0  # 全輪の、制動の使用率の最大（0以上）
        self.yaw_ref = 0.0  # ヨーレートの目標（舵角と速度から。rad/s）
        self.yaw_err = 0.0  # ヨーレートの差（実際 − 目標）

    def relocate(self, x: float, z: float, wvx: float, wvz: float) -> None:
        """位置と、世界座標での速度を、外から置き直す（壁の押し戻し用）。車体座標での速度と、速さも、一緒に置き直す。

        向き、ヨーレート、ギア、ならした車体加速度は、変えない。
        """
        self.x = x
        self.z = z
        self.wvx = wvx
        self.wvz = wvz
        c = cos(self.heading)
        s = sin(self.heading)
        self.vx = wvx * c + wvz * s
        self.vy = wvz * c - wvx * s
        self.speed = sqrt(wvx * wvx + wvz * wvz)

    # --- 変速の口。受けたら True。受けられなければ、何も変えずに False ---
    def shift_up(self) -> bool:
        """1つ上のギアへ。前進のギアで、いちばん上でなければ受ける（後退からは shift_to_forward()）。"""
        if not 1 <= self.gear < self.spec.n_gears:
            return False
        self.gear += 1
        self.shift_t = self.spec.shift_time
        return True

    def shift_down(self) -> bool:
        """1つ下のギアへ。2速より上なら受ける（1速から後退へは shift_to_reverse()）。"""
        if self.gear <= 1:
            return False
        self.gear -= 1
        self.shift_t = self.spec.shift_time
        return True

    def shift_to_reverse(self) -> bool:
        """後退へ入る。1速で、変速中でなければ受ける。止まっているかは、呼ぶ側（操作補正）が決める。"""
        if self.gear != 1 or self.shift_t > 0.0:
            return False
        self.gear = REVERSE
        self.shift_t = self.spec.shift_time
        return True

    def shift_to_forward(self) -> bool:
        """後退から、前進（1速）へ戻る。後退のギアで、変速中でなければ受ける。"""
        if self.gear != REVERSE or self.shift_t > 0.0:
            return False
        self.gear = 1
        self.shift_t = self.spec.shift_time
        return True

    def step(self, steer_cmd: float, throttle: float, brake: float, mu: float) -> None:
        """車を 1 tick 進める。

        steer_cmd は、舵角の指令（rad。左が正）。車の最大舵角で切る（速さは制限しない）。NaN は ValueError。
        throttle、brake は、アクセルとブレーキ（0〜1）。範囲の外と NaN は ValueError（黙って丸めない）。
        mu は、路面の摩擦係数（0以上。4輪で共通）。負、NaN、無限大は ValueError。
        後退のギアでは、throttle が後ろ向きの駆動になる（ペダルの読み替えは、操作補正がする）。
        """
        if not 0.0 <= throttle <= 1.0:
            raise ValueError(f"throttle={throttle!r} must be in 0..1")
        if not 0.0 <= brake <= 1.0:
            raise ValueError(f"brake={brake!r} must be in 0..1")
        if steer_cmd != steer_cmd:
            raise ValueError("steer_cmd must not be NaN")
        if not (mu >= 0.0 and isfinite(mu)):
            raise ValueError(f"mu={mu!r} must be a finite number >= 0")
        spec = self.spec
        tire = self._tire

        # --- 舵。車の最大舵角で切るだけ ---
        max_steer = spec.max_steer
        steer = max_steer if steer_cmd > max_steer else -max_steer if steer_cmd < -max_steer else steer_cmd
        self.steer = steer
        cd = cos(steer)
        sd = sin(steer)

        # --- 駆動系。1 tickに1度 ---
        gear = self.gear
        gear_total = spec.gear_total
        ratio = gear_total[gear]
        avx = self.vx if self.vx >= 0.0 else -self.vx
        rpm_wheel = avx * spec.rpm_per_m_s * (ratio if ratio >= 0.0 else -ratio)
        engaged = True
        if self.shift_t > 0.0:
            self.shift_t -= DT  # 変速中は、駆動力が0
            engaged = False
        elif self.auto and gear >= 1:
            if rpm_wheel > spec.shift_up_rpm and gear < spec.n_gears:
                gear += 1
                self.gear = gear
                self.shift_t = spec.shift_time
                engaged = False
            elif gear > 1 and rpm_wheel * gear_total[gear - 1] / ratio < (spec.shift_down_rpm if gear > 2 else spec.shift_down_first_rpm):
                gear -= 1
                self.gear = gear
                self.shift_t = spec.shift_time
                engaged = False
            if not engaged:
                ratio = gear_total[gear]
                rpm_wheel = avx * spec.rpm_per_m_s * ratio
        clutch_rpm = spec.idle_rpm + throttle * (spec.launch_rpm - spec.idle_rpm)
        if rpm_wheel < clutch_rpm:  # クラッチが滑っている（発進と、回転数が低すぎるとき）
            rpm_engine = clutch_rpm
            slipping = True
        else:
            rpm_engine = rpm_wheel
            slipping = False
        torque = spec.torque_table[int(rpm_engine / spec.torque_step)] if rpm_engine < spec.redline_rpm else 0.0
        torque *= throttle
        if not slipping:
            torque -= (1.0 - throttle) * spec.engine_brake * rpm_engine  # エンジンブレーキ
        drive = 0.0
        engine_brake = 0.0
        if engaged:
            force = torque * ratio * spec.efficiency / spec.wheel_radius
            if torque >= 0.0:
                drive = force  # 駆動（後退のギアでは、負＝後ろ向き）。デフと空転の判定へ渡す
            else:
                # 割り切り：駆動とエンジンブレーキを合わせた正味のトルクが負のときは、その大きさを、駆動輪の制動の要求に足す
                # （車輪の進む向きに逆らい、止める力の頭打ちが一緒に掛かる）。デフを通らないので、アクセルを離した減速の間は、
                # LSDの左右の移しが効かない（試作には有る）。見直すのは、段1の「車両モデル」の区切り。
                engine_brake = force if force >= 0.0 else -force
        self.drive_force = drive
        self.engine_brake_force = engine_brake
        self.rpm += (rpm_engine - self.rpm) * spec.rpm_blend

        # --- 分割の中で使う値 ---
        mass = spec.mass
        cg_to_front = spec.cg_to_front
        cg_to_rear = spec.cg_to_rear
        half_track = spec.track * 0.5
        yaw_inertia = spec.yaw_inertia
        static_front = spec.static_front
        static_rear = spec.static_rear
        load_blend = spec.load_blend
        mu_base = mu * spec.tire_mu
        mu_front = mu_base * spec.grip_front
        mu_rear = mu_base * spec.grip_rear
        front_drive = spec.front_drive
        brake_front = brake * spec.brake_force * spec.brake_front * 0.5 + engine_brake * front_drive * 0.5  # 1輪あたり
        brake_rear = brake * spec.brake_force * (1.0 - spec.brake_front) * 0.5 + engine_brake * (1.0 - front_drive) * 0.5
        drive_front = drive * front_drive  # 軸あたり
        drive_rear = drive - drive_front
        lock = spec.lsd_lock
        lock_excess = 2.0 * lock - 1.0
        coupling = spec.lsd_coupling
        preload = spec.lsd_preload
        ramp = spec.lsd_ramp
        stop_front = spec.stop_front
        stop_rear = spec.stop_rear
        stop_body = spec.stop_body
        drag_k = spec.drag_k
        lift_k = spec.lift_k
        aero_front = spec.aero_front
        load_long = spec.load_long
        load_lat_front = spec.load_lat_front
        load_lat_rear = spec.load_lat_rear
        rolling_force = spec.rolling_force
        load_k = spec.load_k
        load_k_front = load_k / static_front
        load_k_rear = load_k / static_rear
        h = SUBSTEP_S

        x = self.x
        z = self.z
        heading = self.heading
        wvx = self.wvx
        wvz = self.wvz
        r = self.yaw_rate
        axf = self.axf
        ayf = self.ayf

        for _ in range(SUBSTEPS):
            c = cos(heading)
            s = sin(heading)
            vx = wvx * c + wvz * s
            vy = wvz * c - wvx * s
            downforce = lift_k * (vx * vx + vy * vy)
            load_f = static_front + downforce * aero_front * 0.5
            load_r = static_rear + downforce * (1.0 - aero_front) * 0.5
            shift_long = load_long * axf
            shift_lat_f = load_lat_front * ayf
            shift_lat_r = load_lat_rear * ayf
            f0 = load_f - shift_long - shift_lat_f  # 前左
            f1 = load_f - shift_long + shift_lat_f  # 前右
            f2 = load_r + shift_long - shift_lat_r  # 後左
            f3 = load_r + shift_long + shift_lat_r  # 後右
            if f0 < 0.0:
                f0 = 0.0
            if f1 < 0.0:
                f1 = 0.0
            if f2 < 0.0:
                f2 = 0.0
            if f3 < 0.0:
                f3 = 0.0
            # 出せる力。荷重が増えると、摩擦係数が下がる。
            m0 = mu_front * (1.0 + load_k - load_k_front * f0) * f0
            m1 = mu_front * (1.0 + load_k - load_k_front * f1) * f1
            m2 = mu_rear * (1.0 + load_k - load_k_rear * f2) * f2
            m3 = mu_rear * (1.0 + load_k - load_k_rear * f3) * f3
            # 接地点の速度（車体座標）。
            vy_front = vy + r * cg_to_front
            vy_rear = vy - r * cg_to_rear
            vx_left = vx - r * half_track
            vx_right = vx + r * half_track
            wheel_dv = r * half_track * 2.0  # 右の車輪の速さ − 左の車輪の速さ
            # --- デフ。軸の駆動の要求を、左右に分ける ---
            if drive_front != 0.0:
                # (1) 速いほうの車輪が、遅いほうへ力を渡す
                move = lock * coupling * wheel_dv
                lim = lock * (preload + ramp * (drive_front if drive_front > 0.0 else -drive_front))
                if move > lim:
                    move = lim
                elif move < -lim:
                    move = -lim
                c0 = 0.5 * drive_front + move
                c1 = 0.5 * drive_front - move
                # (2) 出せる力を超えた輪は空転する。オープンデフなら、反対の輪も同じ力まで落ち、ロックなら、反対の輪が超えた分を受ける
                e0 = c0 - m0
                e1 = c1 - m1
                if e0 > 0.0 and e0 >= e1:
                    c0 = m0 + (1.0 - lock) * e0
                    c1 += lock_excess * e0
                elif e1 > 0.0:
                    c1 = m1 + (1.0 - lock) * e1
                    c0 += lock_excess * e1
            else:
                c0 = c1 = 0.0
            if drive_rear != 0.0:
                move = lock * coupling * wheel_dv
                lim = lock * (preload + ramp * (drive_rear if drive_rear > 0.0 else -drive_rear))
                if move > lim:
                    move = lim
                elif move < -lim:
                    move = -lim
                c2 = 0.5 * drive_rear + move
                c3 = 0.5 * drive_rear - move
                e0 = c2 - m2
                e1 = c3 - m3
                if e0 > 0.0 and e0 >= e1:
                    c2 = m2 + (1.0 - lock) * e0
                    c3 += lock_excess * e0
                elif e1 > 0.0:
                    c3 = m3 + (1.0 - lock) * e1
                    c2 += lock_excess * e1
            else:
                c2 = c3 = 0.0
            # --- タイヤ。前輪は、舵角の分だけ回した座標で ---
            fx0, fy0, sy0, u0 = tire(vx_left * cd + vy_front * sd, vy_front * cd - vx_left * sd, m0, c0, brake_front, stop_front)
            fx1, fy1, sy1, u1 = tire(vx_right * cd + vy_front * sd, vy_front * cd - vx_right * sd, m1, c1, brake_front, stop_front)
            fx2, fy2, sy2, u2 = tire(vx_left, vy_rear, m2, c2, brake_rear, stop_rear)
            fx3, fy3, sy3, u3 = tire(vx_right, vy_rear, m3, c3, brake_rear, stop_rear)
            bx0 = fx0 * cd - fy0 * sd
            by0 = fx0 * sd + fy0 * cd
            bx1 = fx1 * cd - fy1 * sd
            by1 = fx1 * sd + fy1 * cd
            force_x = bx0 + bx1 + fx2 + fx3
            force_y = by0 + by1 + fy2 + fy3
            moment = cg_to_front * (by0 + by1) - cg_to_rear * (fy2 + fy3) + half_track * (bx1 - bx0 + fx3 - fx2)
            # --- 車体の抵抗。空気抵抗と転がり抵抗（転がり抵抗は、車を逆向きに動かさない） ---
            avx = vx if vx >= 0.0 else -vx
            resist = rolling_force
            lim = stop_body * avx
            if resist > lim:
                resist = lim
            resist += drag_k * vx * vx
            if vx > 0.0:
                force_x -= resist
            else:
                force_x += resist
            ax = force_x / mass  # 車体座標の加速度
            ay = force_y / mass
            axf += (ax - axf) * load_blend
            ayf += (ay - ayf) * load_blend
            # --- 世界座標で積分する（速度を先に進め、その速度で位置を進める） ---
            wvx += (ax * c - ay * s) * h
            wvz += (ax * s + ay * c) * h
            r += moment / yaw_inertia * h
            heading += r * h
            x += wvx * h
            z += wvz * h

        # --- 静止への吸い付き。アクセルを離していて、ほぼ止まっていれば、ちょうど0にする ---
        rest_yaw_rate = spec.rest_yaw_rate
        if throttle == 0.0 and wvx * wvx + wvz * wvz < spec.rest_speed_sq and -rest_yaw_rate < r < rest_yaw_rate:
            wvx = 0.0
            wvz = 0.0
            r = 0.0
        if heading > pi:
            heading -= TWO_PI
        elif heading < -pi:
            heading += TWO_PI

        # --- 状態と、出す量を置く ---
        self.x = x
        self.z = z
        self.heading = heading
        self.wvx = wvx
        self.wvz = wvz
        self.yaw_rate = r
        self.axf = axf
        self.ayf = ayf
        self.ax = ax
        self.ay = ay
        c = cos(heading)
        s = sin(heading)
        vx = wvx * c + wvz * s
        vy = wvz * c - wvx * s
        self.vx = vx
        self.vy = vy
        speed = sqrt(wvx * wvx + wvz * wvz)
        self.speed = speed
        avx = vx if vx >= 0.0 else -vx
        floor = spec.slip_speed_floor
        den = avx if avx > floor else floor
        if speed > spec.slip_min_speed:
            self.body_slip = atan2(vy, den)
            front_long = vx * cd + (vy + r * cg_to_front) * sd
            if front_long < 0.0:
                front_long = -front_long
            self.slip_front = atan2((vy + r * cg_to_front) * cd - vx * sd, front_long if front_long > floor else floor)
            self.slip_rear = atan2(vy - r * cg_to_rear, den)
        else:
            self.body_slip = 0.0
            self.slip_front = 0.0
            self.slip_rear = 0.0
        loads = self.wheel_load
        loads[0] = f0
        loads[1] = f1
        loads[2] = f2
        loads[3] = f3
        utils = self.wheel_util
        utils[0] = u0
        utils[1] = u1
        utils[2] = u2
        utils[3] = u3
        slips = self.wheel_sy
        slips[0] = sy0
        slips[1] = sy1
        slips[2] = sy2
        slips[3] = sy3
        drive_util = 0.0
        if front_drive > 0.0:
            drive_util = u0 if u0 > u1 else u1
        if front_drive < 1.0:
            rear_util = u2 if u2 > u3 else u3
            if rear_util > drive_util:
                drive_util = rear_util
        self.drive_util = drive_util if drive_util > 0.0 else 0.0
        axle_util = 0.0
        if drive_front > 0.0 and m0 + m1 > MIN_TIRE_FORCE_N:
            axle_util = drive_front / (m0 + m1)
        if drive_rear > 0.0 and m2 + m3 > MIN_TIRE_FORCE_N:
            rear_util = drive_rear / (m2 + m3)
            if rear_util > axle_util:
                axle_util = rear_util
        self.drive_util_axle = axle_util
        brake_util = -min(u0, u1, u2, u3)
        self.brake_util = brake_util if brake_util > 0.0 else 0.0
        self.on_limit = speed > spec.limit_min_speed and (
            u0 > 1.0 or u0 < -1.0 or u1 > 1.0 or u1 < -1.0 or u2 > 1.0 or u2 < -1.0 or u3 > 1.0 or u3 < -1.0
            or sy0 > 1.0 or sy0 < -1.0 or sy1 > 1.0 or sy1 < -1.0 or sy2 > 1.0 or sy2 < -1.0 or sy3 > 1.0 or sy3 < -1.0
        )
        # ヨーレートの目標。舵角と速度から求め、路面が支えられる値で切る。
        yaw_ref = vx * steer / spec.wheelbase
        if speed > spec.yaw_ref_min_speed:
            lim = mu * spec.tire_mu * GRAVITY / speed
            if yaw_ref > lim:
                yaw_ref = lim
            elif yaw_ref < -lim:
                yaw_ref = -lim
        self.yaw_ref = yaw_ref
        self.yaw_err = r - yaw_ref

    def state(self) -> tuple:
        """次のtickを決める値の組（テストと、同じ入力で同じ結果になることの確かめに使う）。"""
        return (
            self.x, self.z, self.heading, self.wvx, self.wvz, self.yaw_rate, self.steer, self.axf, self.ayf,
            self.shift_t, self.gear, self.rpm, self.vx, self.vy,
        )
