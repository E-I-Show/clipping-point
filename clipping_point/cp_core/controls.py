"""操作補正の最小版（純Python）。決まりは docs/design/overview.md の「入力と操作補正」。

入力フレームから、車両モデルへ渡す、舵角の指令（rad）、アクセル、ブレーキ（0〜1）と、変速の指示を作る。毎tick、入力を読んだ直後、
車両モデルの直前に、1回呼ぶ（step）。AI車は通らない。
入っているもの（段0 区切り9）：
  入力の合成    舵、アクセル、ブレーキのそれぞれで、デジタル値が0でなければデジタル値、そうでなければアナログ値を使う
  車速に応じた最大舵角（舵の上限）
                上限 = min(車の最大舵角, ka × L × a ÷ v² + km × αp)。L はホイールベース、v は車速、αp はタイヤが最大グリップを
                出す滑り角。a は、その路面で出せる横加速度（路面の摩擦係数（下限つき）× タイヤの摩擦係数 × 重力加速度）。
                車速が、決めた速さ未満なら、車の最大舵角。入力の全倒し（とキーの押しっぱなし）が、この上限に当たる
  切る速さ      舵角の指令を、目標へ、決めた速さで近づける。速さは「舵の上限に対する割合」で決める（上限いっぱいを動く時間）
  後退          ほぼ止まった状態で、ブレーキを押し続けると、後退へ入る指示を出す（アクセルを押している間は、数えない）。
                後退中は、ブレーキの入力を後退の駆動、アクセルの入力を制動として渡す。舵の向きは、変えない（左へ切れば、
                前輪は左を向く。後ろへ進むので、車体の向きは右へ回る）。後退中に、アクセルを押していて、ほぼ止まっていれば、
                前進へ戻る指示を出す。「押している」は、合成した後のペダルの値が、線（pedal_press_min）以上のこと
入れていないもの（段1の「入力と操作補正」の区切りで作り替える）：遊びの除去、応答カーブ、カウンターの緩和、デジタル操作の
押し始めの遅さと戻りの速さ、踏む速さ、アシスト、調整項目の段階、「どちらでもなければ、直前の扱いを保つ」。
状態（ControlState）は、舵角の指令（前のtickの値）と、ブレーキを押し続けているtick数だけ。世界が持つ。後退中かは、持たない
（車のギアから引く。世界が、車のギアを渡す）。後退へ入る指示を、車が受けなかったとき（1速でない、変速中）は、条件が続いていれば、
次のtickに、また出る。
値（ControlParams）は、定義データの表 assists の項目から作る（params_from_entry）。使う項目の id は DEFAULT_SET。
"""
from dataclasses import dataclass
from typing import NamedTuple

from cp_core.fixed_loop import TICK_HZ
from cp_core.input_frame import InputFrame
from cp_core.vehicle import GRAVITY, REVERSE

DT = 1.0 / TICK_HZ  # 1 tick（秒）
DEFAULT_SET = "default"  # 表 assists の、使う項目の id（いまは、仮の1組だけ。既定の組と段階は、段1）
# 変速の指示。世界が、車の変速の口（Car.shift_to_reverse()、Car.shift_to_forward()）へ渡す。
SHIFT_NONE, SHIFT_TO_REVERSE, SHIFT_TO_FORWARD = "none", "to_reverse", "to_forward"


@dataclass(frozen=True, slots=True)
class ControlParams:
    """操作補正の値。定義データの表 assists の項目から作る。書き換えられない。"""

    limit_mu_min: float  # 舵の上限の式で、路面の摩擦係数を、これ未満にしない
    limit_min_speed: float  # 車速が、これ未満（m/s）なら、舵の上限は、車の最大舵角
    analog_ka: float  # アナログ操作の、舵の上限の式の係数 ka
    analog_km: float  # 同じく、余裕の係数 km
    analog_full_time: float  # アナログ操作で、舵の上限いっぱいを動く時間（秒）
    digital_ka: float  # デジタル操作の ka
    digital_km: float  # デジタル操作の km
    digital_full_time: float  # デジタル操作で、舵の上限いっぱいを動く時間（秒）
    stop_speed: float  # 後退：「ほぼ止まった」と見る速さ（m/s）。これ未満
    brake_hold_ticks: int  # 後退：ブレーキを押し続けるtick数。これ以上で、後退へ入る指示を出す
    pedal_press_min: float  # 後退：ペダルを「押している」と見る線（0〜1）。これ以上


class Command(NamedTuple):
    """操作補正の1 tickの結果。"""

    steer: float  # 舵角の指令（rad。左が正）
    throttle: float  # アクセル（0〜1）。後退中は、後ろ向きの駆動
    brake: float  # ブレーキ（0〜1）
    shift: str  # 変速の指示（SHIFT_NONE、SHIFT_TO_REVERSE、SHIFT_TO_FORWARD）


class ControlState:
    """操作補正の状態。世界が、車1台に1つ持つ。"""

    __slots__ = ("steer", "brake_hold_ticks")

    def __init__(self) -> None:
        self.steer = 0.0  # 舵角の指令（前のtickの値。rad）
        self.brake_hold_ticks = 0  # ほぼ止まった状態で、ブレーキを押し続けているtick数


def params_from_entry(entry: dict) -> ControlParams:
    """定義データの表 assists の項目（読み込み検査を通ったもの。GameData.entry("assists", DEFAULT_SET)）から、操作補正の値を作る。"""
    steer, reverse = entry["steer"], entry["reverse"]
    return ControlParams(
        limit_mu_min=steer["limit_mu_min"],
        limit_min_speed=steer["limit_min_speed_m_s"],
        analog_ka=steer["analog"]["limit_ka"],
        analog_km=steer["analog"]["limit_km"],
        analog_full_time=steer["analog"]["full_time_s"],
        digital_ka=steer["digital"]["limit_ka"],
        digital_km=steer["digital"]["limit_km"],
        digital_full_time=steer["digital"]["full_time_s"],
        stop_speed=reverse["stop_speed_m_s"],
        brake_hold_ticks=int(round(reverse["brake_hold_s"] * TICK_HZ)),
        pedal_press_min=reverse["pedal_press_min"],
    )


def combine(frame: InputFrame) -> tuple:
    """入力の合成。返すのは (舵 −1〜1、アクセル 0〜1、ブレーキ 0〜1、舵がデジタル操作か)。デジタル値が0でなければ、デジタル値を使う。"""
    digital = frame.steer_digital != 0
    return (
        float(frame.steer_digital) if digital else frame.steer_analog,
        1.0 if frame.throttle_digital else frame.throttle_analog,
        1.0 if frame.brake_digital else frame.brake_analog,
        digital,
    )


def steer_limit(ka: float, km: float, params: ControlParams, speed: float, max_steer: float, wheelbase: float, peak_slip: float, tire_mu: float, surface_mu: float) -> float:
    """車速に応じた最大舵角（rad）。引数の意味は step() と同じ。ka、km は、舵の上限の式の係数。"""
    if speed < params.limit_min_speed:
        return max_steer
    mu = surface_mu if surface_mu > params.limit_mu_min else params.limit_mu_min
    limit = ka * wheelbase * (mu * tire_mu * GRAVITY) / (speed * speed) + km * peak_slip
    return limit if limit < max_steer else max_steer


def step(
    params: ControlParams, state: ControlState, frame: InputFrame, speed: float, gear: int,
    max_steer: float, wheelbase: float, peak_slip: float, tire_mu: float, surface_mu: float,
) -> Command:
    """操作補正を 1 tick 進める。state を書き換え、車両モデルへ渡す値を返す。

    speed は、車速（m/s。0以上。世界座標での速度の大きさ）。gear は、車のギア（後退は REVERSE）。
    max_steer は、車の最大舵角（rad）。wheelbase は、ホイールベース（m）。peak_slip は、タイヤが最大グリップを出す滑り角（rad）。
    tire_mu は、タイヤの摩擦係数。surface_mu は、路面の摩擦係数。車の4つは、車の値（CarSpec）の同じ名の値。
    """
    steer_in, throttle_in, brake_in, digital = combine(frame)
    # --- 舵。車速に応じた最大舵角を掛け、切る速さで近づける ---
    if digital:
        limit = steer_limit(params.digital_ka, params.digital_km, params, speed, max_steer, wheelbase, peak_slip, tire_mu, surface_mu)
        full_time = params.digital_full_time
    else:
        limit = steer_limit(params.analog_ka, params.analog_km, params, speed, max_steer, wheelbase, peak_slip, tire_mu, surface_mu)
        full_time = params.analog_full_time
    current = state.steer
    size = current if current >= 0.0 else -current
    span = limit if limit > size else size  # 切る速さは、舵の上限（いまの舵角のほうが大きければ、そちら）に対する割合
    step_max = span / full_time * DT
    change = steer_in * limit - current
    if change > step_max:
        change = step_max
    elif change < -step_max:
        change = -step_max
    steer = current + change
    state.steer = steer
    # --- ペダルと後退 ---
    press = params.pedal_press_min
    stopped = speed < params.stop_speed
    if gear == REVERSE:
        # 後退中。ブレーキの入力が後退の駆動、アクセルの入力が制動。アクセルを押していて、ほぼ止まっていれば、前進へ戻る。
        state.brake_hold_ticks = 0
        shift = SHIFT_TO_FORWARD if stopped and throttle_in >= press else SHIFT_NONE
        return Command(steer, brake_in, throttle_in, shift)
    # 前進。ほぼ止まった状態で、ブレーキだけを押しているtickを、続けて数える（アクセルを押している間は、数えない）。
    # 指示を出すのは、条件がそろっているtickだけ（押し続ける長さが0の値でも、条件の無いtickには出さない）。
    if stopped and brake_in >= press and throttle_in < press:
        state.brake_hold_ticks += 1
        shift = SHIFT_TO_REVERSE if state.brake_hold_ticks >= params.brake_hold_ticks else SHIFT_NONE
    else:
        state.brake_hold_ticks = 0
        shift = SHIFT_NONE
    return Command(steer, throttle_in, brake_in, shift)
