"""世界の状態と1 tickの進行（純Python）。

世界は、tick を数え、受け取った入力フレームを畳み込み、用途ごとの乱数の流れを持ち、車1台を、コースの上で走らせる（段0 区切り9。
ほかの3台、周回判定、ラップは、段1から）。
作るとき：種、読み込んだ定義（cp_core.datadefs の GameData）、車の id、コースの id を受ける（既定の値は、置かない。決めるのは、アプリと道具）。
  定義は、ここで1度だけ引く（車の項目、コースの項目、操作補正の項目）。毎tickは引かない。無い id は、分かる文の ValueError。
  車は、コースのスタート位置に、止まった状態で置く。
1 tickの順（step）：
  入力の要約値 → 操作補正（cp_core.controls）→ 車両モデル（cp_core.vehicle）→ 照会（cp_core.track）→ 壁の押し戻し → 進行距離と走行の数え
  車両モデルと操作補正へ渡す、路面の摩擦係数は、前のtickの照会の路面の種類から引く（車1台に1つ。始まりは、スタート位置の照会）。
  照会には、前回の区間の番号を渡す（世界が持つ）。壁に押し戻されたtickは、押し戻した後の位置で、もう1度、前回の区間つきで照会する
  （要約と、次のtickの路面は、押し戻した後の位置の値）。
走行の数え（どれも、要約に入る。走行が成り立っていることを、要約だけで判定するための値）：
  進行距離      コースに沿った距離の、前へ進んだ分を積み上げる（1周しても、戻さない。後ろへ動いた分は、引かない）。
                1 tickで ODOMETER_MAX_STEP_M を超えて変わった分は、足さない
  最高速        tickの終わりの速さの、いちばん大きい値
  変速の回数    tickの前後で、ギアが変わった回数（ATの上げ下げと、後退の出入り）
  壁に当たった回数  当たり始めを1回と数える（押し付けられている間は、増やさない）
  後退に入った回数  車が、後退へ入る指示を受けた回数
  照会を取り直した回数  照会が、前回の区間の近くで探し当てられず、全部を探した回数（ふつうに走っていれば0。増えるのは、退行）
世界の要約（summary）が、指紋。決まった筋書きで回した要約を、ふるまいの写し（tests/snapshots/fingerprint.json）と比べる
（tools/fingerprint.py と tests/test_fingerprint.py）。要約は、整数と文字列だけの、入れ子の無い辞書。車の状態は、量子化した整数
（round(値 × 倍率)。入力フレームの量子化と同じ形）で入れる。小数を、そのまま入れない。
要約の項目の名、倍率、デスクトップ版とブラウザ版の比べ方は、ここの表（SUMMARY_FIELDS）の1か所に持つ。道具とテストは、ここから引く。
"""
from math import pi

from cp_core import controls, track, vehicle
from cp_core.datadefs import GameData
from cp_core.input_frame import DIGEST_START, InputFrame, fold, quantize
from cp_core.rng import PURPOSES, RngSet

RNG_STATE_FORMAT = "016x"  # 乱数の流れの状態（64ビットの整数）を、要約に入れる形。16桁の16進の文字列
RNG_PREFIX = "rng_"  # 要約の、乱数の流れの状態の項目の名の頭（rng_<用途の名>）
# デスクトップ版とブラウザ版の突き合わせでの、項目の比べ方（デスクトップ版どうしは、全部の項目が完全一致）。
COMPARE_EXACT = "exact"  # 完全一致
COMPARE_NEAR = "near"  # 許容差つき（量子化の刻みで数えた差が、道具の値まで）
COMPARE_WRAP = "wrap"  # 1周で折り返した差が、許容差の内（向きと、コースに沿った距離。1周の長さは Sim.summary_periods()）
MM = 1000  # 長さ（m）と速度（m/s）の倍率。mm と mm/s の整数にする
E5 = 100000  # 角度（rad）と角速度（rad/s）の倍率
# 要約の項目（乱数の流れの状態を除く）。(名, 倍率, 比べ方)。倍率が0の項目は、量子化しない（元から、整数か文字列）。
# 足すときは、末尾に足し、summary() の値の表と、tests/test_sim.py に足して、指紋の写しを取り直す。
SUMMARY_FIELDS = (
    ("tick", 0, COMPARE_EXACT),
    ("input_digest", 0, COMPARE_EXACT),
    ("seed", 0, COMPARE_EXACT),
    ("car", 0, COMPARE_EXACT),  # 車の id
    ("track", 0, COMPARE_EXACT),  # コースの id
    ("x_mm", MM, COMPARE_NEAR),  # 位置
    ("z_mm", MM, COMPARE_NEAR),
    ("vx_mm_s", MM, COMPARE_NEAR),  # 世界座標の速度
    ("vz_mm_s", MM, COMPARE_NEAR),
    ("heading_e5", E5, COMPARE_WRAP),  # 向き（−π〜π に折り返した値）
    ("yaw_rate_e5", E5, COMPARE_NEAR),  # ヨーレート
    ("steer_e5", E5, COMPARE_NEAR),  # 実舵角
    ("rpm", 1, COMPARE_NEAR),  # 回転数
    ("gear", 0, COMPARE_EXACT),  # ギア（後退は −1。前進は1〜）
    ("surface", 0, COMPARE_EXACT),  # 路面の種類
    ("s_mm", MM, COMPARE_WRAP),  # コースに沿った距離
    ("lateral_mm", MM, COMPARE_NEAR),  # 横のずれ（左が正）
    ("odometer_mm", MM, COMPARE_NEAR),  # 進行距離
    ("top_speed_mm_s", MM, COMPARE_NEAR),  # 最高速
    ("shifts", 0, COMPARE_EXACT),  # 変速の回数
    ("wall_hits", 0, COMPARE_EXACT),  # 壁に当たった回数
    ("reverse_count", 0, COMPARE_EXACT),  # 後退に入った回数
    ("requery_count", 0, COMPARE_EXACT),  # 照会を取り直した回数
)
HEADING_TURN_E5 = round(2.0 * pi * E5)  # 要約の向き（heading_e5）の、1周の長さ
# 進行距離に足す、1 tickの変化の上限（m）。これを超える変化は、走った分ではない（1 tickに40 mは、毎秒2,400 m。置き直しや、
# 照会が別の道へ飛んだ分を、進行距離に入れないための守り。値を合わせる対象ではない）。
ODOMETER_MAX_STEP_M = 40.0


def summary_compare() -> dict:
    """要約の項目の名 → デスクトップ版とブラウザ版の比べ方。乱数の流れの状態（rng_<用途の名>）は、完全一致。"""
    kinds = {name: kind for name, _, kind in SUMMARY_FIELDS}
    kinds.update({f"{RNG_PREFIX}{name}": COMPARE_EXACT for name in PURPOSES})
    return kinds


def _entry(data: GameData, table: str, ident, what: str) -> dict:
    """読み込んだ定義から、項目を1つ引く。無い id は、分かる文の ValueError（起動時に、ここで止まる）。"""
    if type(ident) is not str:
        raise TypeError(f"Sim: the {what} id must be str, got {type(ident).__name__}")
    known = data.ids(table) if table in data.counts() else ()
    if ident not in known:
        raise ValueError(f"Sim: the loaded data has no {what} with id {ident!r} (table {table!r} has: {', '.join(known) or 'nothing'})")
    return data.entry(table, ident)


class Sim:
    """世界。step() の1回が1 tick（1/60秒）。fps、フレーム番号、実時間は読まない。"""

    def __init__(self, seed: int, data: GameData, car_id: str, track_id: str) -> None:
        """seed は、世界の種（bool でない整数）。用途ごとの乱数の流れの、始まりの状態を決める。

        data は、読み込んだ定義。car_id と track_id は、車とコースの id。どれも、既定の値は無い。
        """
        self.rng = RngSet(seed)  # 用途ごとの乱数の流れ。いまは、引く所が無い（AIを作る段3から）
        self.seed = self.rng.seed  # 世界の種
        if not isinstance(data, GameData):
            raise TypeError(f"Sim takes the loaded data (GameData), got {type(data).__name__}")
        # 定義は、ここで1度だけ引く（引くたびに、奥まで複製される。毎tick引かない）。
        self.spec = vehicle.spec_from_entry(_entry(data, "cars", car_id, "car"))  # 車の値
        self.track = track.build_track(_entry(data, "tracks", track_id, "track"))  # コースの表
        self.control_params = controls.params_from_entry(_entry(data, "assists", controls.DEFAULT_SET, "assist set"))  # 操作補正の値
        self.car_id = self.spec.car_id  # 車の id（要約の car）
        self.track_id = self.track.track_id  # コースの id（要約の track）
        self.car = vehicle.Car(self.spec)  # 車（状態を持つ）
        self.control = controls.ControlState()  # 操作補正の状態（舵角の指令、ブレーキを押し続けているtick数）
        self.tick = 0  # 始まってから進めたtickの数（整数）
        self.input_digest = DIGEST_START  # 入力の要約値。受け取った入力フレームを、毎tick量子化して畳み込んだ整数
        # --- 走行の数え ---
        self.odometer = 0.0  # 進行距離（m）
        self.top_speed = 0.0  # 最高速（m/s）
        self.shifts = 0  # 変速の回数
        self.wall_hits = 0  # 壁に当たった回数
        self.reverse_count = 0  # 後退に入った回数
        self.requery_count = 0  # 照会を取り直した回数
        # --- 直近の照会の値。_settle() が置く ---
        self.segment = 0  # 前回の区間の番号（次の照会へ渡す）
        self.s = 0.0  # コースに沿った距離（m）
        self.lateral = 0.0  # 横のずれ（m。左が正）
        self.surface = track.SURFACE_ASPHALT  # 路面の種類
        self.mu = 0.0  # 路面の摩擦係数。次のtickの、操作補正と車両モデルへ渡す
        self.on_wall = False  # 直近のtickで、壁に当たっていたか
        x, z, heading = self.track.start_pose()
        self._settle(x, z, heading, 0.0)

    def _settle(self, x: float, z: float, heading: float, speed: float) -> None:
        """車を置いて、その位置を、前回の区間なしで照会する（全部を探す。取り直しには数えない）。操作補正の状態は、始まりに戻す。"""
        self.car.reset(x, z, heading, speed)
        self.control = controls.ControlState()
        query = self.track.query(x, z)
        self.segment = query.index
        self.s = query.s
        self.lateral = query.lateral
        self.surface = query.surface
        self.mu = self.track.surface_mu(query.surface)
        self.on_wall = False

    def place_car(self, x: float, z: float, heading: float, speed: float = 0.0) -> None:
        """車を、決めた位置 (x, z)（m）と、向き heading（rad）と、速さ speed（m/s。負は後ろ向き）に置き直す。

        テストと道具が、世界を、決めた場面から回すための口（芝の上、壁の前、など）。出荷するコードの、ふつうの道では、使わない。
        前回の区間は、捨てる（離れた所へ置き直した後に、別の道の区間を渡さないため）。tick、入力の要約値、走行の数えは、変えない
        （置き直した分は、進行距離に入らない）。
        """
        self._settle(x, z, heading, speed)

    def step(self, frame: InputFrame) -> None:
        """世界を1 tick進める。frame は、このtickの入力フレーム（必須）。"""
        if not isinstance(frame, InputFrame):
            raise TypeError(f"Sim.step takes an InputFrame, got {type(frame).__name__}")
        # 入力の要約値は、指紋（世界の要約）の一部。入力フレームが、世界へ、順のまま、欠けずに届いたことを見る。
        self.input_digest = fold(self.input_digest, quantize(frame))
        car = self.car
        spec = self.spec
        course = self.track
        mu = self.mu  # 前のtickの照会の、路面の摩擦係数
        gear_before = car.gear
        # --- 操作補正。入力フレームから、舵角の指令、アクセル、ブレーキ、変速の指示を作る ---
        command = controls.step(
            self.control_params, self.control, frame, car.speed, gear_before, spec.max_steer, spec.wheelbase, spec.peak_slip, spec.tire_mu, mu,
        )
        if command.shift == controls.SHIFT_TO_REVERSE:
            if car.shift_to_reverse():  # 車が受けたときだけ、後退に入った（1速でない、変速中は、受けない。指示は、次のtickにも出る）
                self.reverse_count += 1
        elif command.shift == controls.SHIFT_TO_FORWARD:
            car.shift_to_forward()
        # --- 車両モデル ---
        car.step(command.steer, command.throttle, command.brake, mu)
        if car.gear != gear_before:
            self.shifts += 1
        # --- 照会と、壁の押し戻し ---
        query = course.query(car.x, car.z, self.segment)
        if query.requeried:
            self.requery_count += 1
        x, z, wvx, wvz, hit, _ = course.push_out(query, car.x, car.z, car.wvx, car.wvz, car.heading, spec.half_length, spec.half_width)
        if hit:
            car.relocate(x, z, wvx, wvz)
            # 押し戻した後の位置で、照会し直す（前回の区間つき。要約と、次のtickの路面は、押し戻した後の位置の値にする）。
            query = course.query(x, z, query.index)
            if query.requeried:
                self.requery_count += 1
            if not self.on_wall:
                self.wall_hits += 1  # 当たり始めだけを数える
        self.on_wall = hit
        self.segment = query.index
        # --- 進行距離と、走行の数え ---
        moved = query.s - self.s
        half = course.length * 0.5
        if moved > half:  # 1周をまたいだ
            moved -= course.length
        elif moved < -half:
            moved += course.length
        if 0.0 < moved <= ODOMETER_MAX_STEP_M:
            self.odometer += moved
        if car.speed > self.top_speed:
            self.top_speed = car.speed
        surface = query.surface
        self.s = query.s
        self.lateral = query.lateral
        self.surface = surface
        self.mu = course.surface_mu(surface)  # 次のtickの、操作補正と車両モデルへ渡す
        self.tick += 1

    def summary_periods(self) -> dict:
        """折り返して比べる項目（COMPARE_WRAP）の、1周の長さ（量子化した整数）。{項目の名: 長さ}。"""
        return {"heading_e5": HEADING_TURN_E5, "s_mm": round(self.track.length * MM)}

    def summary(self) -> dict:
        """世界の要約（指紋）を返す。値は整数と文字列だけの、入れ子の無い辞書にし、JSONにそのまま書ける形にする。

        量子化する項目（倍率が0でない項目）は、round(値 × 倍率)。項目の並びは、SUMMARY_FIELDS の順で、その後ろに、乱数の流れの状態。
        乱数の流れの状態は、用途ごとの「rng_<用途の名>」に、16桁の16進の文字列で入れる
        （64ビットの整数を、JavaScriptを通っても欠けない形にする）。
        """
        car = self.car
        values = {
            "tick": self.tick, "input_digest": self.input_digest, "seed": self.seed,
            "car": self.car_id, "track": self.track_id,
            "x_mm": car.x, "z_mm": car.z, "vx_mm_s": car.wvx, "vz_mm_s": car.wvz,
            "heading_e5": car.heading, "yaw_rate_e5": car.yaw_rate, "steer_e5": car.steer,
            "rpm": car.rpm, "gear": car.gear, "surface": self.surface,
            "s_mm": self.s, "lateral_mm": self.lateral,
            "odometer_mm": self.odometer, "top_speed_mm_s": self.top_speed,
            "shifts": self.shifts, "wall_hits": self.wall_hits, "reverse_count": self.reverse_count, "requery_count": self.requery_count,
        }
        summary = {}
        for name, scale, _ in SUMMARY_FIELDS:
            summary[name] = round(values[name] * scale) if scale else values[name]
        for name, state in self.rng.state().items():
            summary[f"{RNG_PREFIX}{name}"] = format(state, RNG_STATE_FORMAT)
        return summary
