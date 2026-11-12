"""世界（Sim）のテスト。車1台が、仮の周回路を走る。pyxel は読み込まない。

世界は、実物の定義データ（clipping_point/data/）を、アプリと同じ読み方で読んで作る（車は kazane、コースは test_loop）。
見るのは、1回の step() で1 tick、入力の要約値、種と乱数の流れ、要約の項目（名、倍率、比べ方、整数と文字列だけ）、
1 tickの順（路面の摩擦係数は、前のtickの照会から）、進行距離と走行の数え、壁、置き直す口、無い id。
走る台本と壁の台本（tools/input_script_drive.json、input_script_wall.json）を回した世界も、ここで見る。
"""
import functools
import json
import math

import pytest

import input_reference
from cp_app import data_files
from cp_core import controls, sim as world, track, vehicle
from cp_core.input_frame import DIGEST_START, NEUTRAL, InputFrame, fold, quantize
from cp_core.rng import PURPOSES, RngSet
from cp_core.sim import Sim

LEFT = InputFrame(steer_analog=0.5, held=frozenset({"left"}), pressed=frozenset({"left"}))
GAS = InputFrame(throttle_digital=1)
BRAKE = InputFrame(brake_digital=1)
RNG_AI_OF_SEED_0 = "0ad0a11cea5bd376"  # 種0の世界の、用途 ai の流れの、始まりの状態（16桁の16進）
CAR_ID, TRACK_ID = "kazane", "test_loop"
# 始まりの要約。車は、スタート位置（1本目の直線の、頭から60 m。中心線の上）に、+x を向いて、止まっている。
START = {
    "tick": 0, "input_digest": DIGEST_START, "seed": 0, "car": CAR_ID, "track": TRACK_ID,
    "x_mm": 60000, "z_mm": 0, "vx_mm_s": 0, "vz_mm_s": 0, "heading_e5": 0, "yaw_rate_e5": 0, "steer_e5": 0,
    "rpm": 850, "gear": 1, "surface": "asphalt", "s_mm": 60000, "lateral_mm": 0, "odometer_mm": 0, "top_speed_mm_s": 0,
    "shifts": 0, "wall_hits": 0, "reverse_count": 0, "requery_count": 0, "rng_ai": RNG_AI_OF_SEED_0,
}
# 要約の項目の名（乱数の流れの状態を除く）と、倍率と、デスクトップ版とブラウザ版の比べ方。頼みの文の「要約の項目」の表を、ここに固定する。
FIELDS = (
    ("tick", 0, "exact"), ("input_digest", 0, "exact"), ("seed", 0, "exact"), ("car", 0, "exact"), ("track", 0, "exact"),
    ("x_mm", 1000, "near"), ("z_mm", 1000, "near"), ("vx_mm_s", 1000, "near"), ("vz_mm_s", 1000, "near"),
    ("heading_e5", 100000, "wrap"), ("yaw_rate_e5", 100000, "near"), ("steer_e5", 100000, "near"),
    ("rpm", 1, "near"), ("gear", 0, "exact"), ("surface", 0, "exact"),
    ("s_mm", 1000, "wrap"), ("lateral_mm", 1000, "near"), ("odometer_mm", 1000, "near"), ("top_speed_mm_s", 1000, "near"),
    ("shifts", 0, "exact"), ("wall_hits", 0, "exact"), ("reverse_count", 0, "exact"), ("requery_count", 0, "exact"),
)
GRASS_MU, ASPHALT_MU = 0.55, 1.0  # 実物のコースの、路面の摩擦係数
WALL_M = 14.0  # 中心線から壁まで（幅の半分6 m＋芝8 m）


@functools.cache
def game_data():
    return data_files.load({}, None)


def make(seed: int = 0) -> Sim:
    return Sim(seed, game_data(), CAR_ID, TRACK_ID)


def run(sim: Sim, frame: InputFrame, ticks: int) -> Sim:
    for _ in range(ticks):
        sim.step(frame)
    return sim


def place(sim: Sim, s: float, lateral: float, turn: float = 0.0, speed: float = 0.0) -> None:
    """車を、コースに沿った距離 s、横のずれ lateral の所に、コースの向きから turn（rad。左が正）だけ回して置く。"""
    x, z, heading = sim.track.pose_at(s, lateral)
    sim.place_car(x, z, heading + turn, speed)


@functools.cache
def script_of(path):
    return input_reference.load_script(path)[1]


def played(path, ticks: int) -> Sim:
    """台本を、世界に流す。"""
    sim, script = make(), script_of(path)
    for tick in range(ticks):
        sim.step(script.frame_at(tick))
    return sim


# --- 作り方と、始まりの状態 ---
def test_sim_starts_at_tick_zero():
    assert make().tick == 0
    assert make().summary() == START
    assert DIGEST_START == 2166136261  # 要約の値を、数字でも固定する


def test_sim_takes_the_seed_the_loaded_data_and_the_two_ids_without_defaults():
    with pytest.raises(TypeError):
        Sim()  # 既定の値は、置かない（車とコースを決めるのは、アプリと道具）
    with pytest.raises(TypeError):
        Sim(0)
    with pytest.raises(TypeError):
        Sim(0, game_data(), CAR_ID)
    sim = Sim(0, game_data(), CAR_ID, TRACK_ID)
    assert (sim.car_id, sim.track_id) == (CAR_ID, TRACK_ID)
    assert type(sim.spec) is vehicle.CarSpec and type(sim.car) is vehicle.Car and type(sim.track) is track.Track
    assert type(sim.control_params) is controls.ControlParams and type(sim.control) is controls.ControlState


def test_sim_puts_the_car_on_the_start_position_at_rest():
    sim = make()
    x, z, heading = sim.track.start_pose()
    car = sim.car
    assert (car.x, car.z, car.heading, car.speed, car.gear) == (x, z, heading, 0.0, 1)
    assert (sim.s, sim.lateral, sim.surface, sim.mu) == (pytest.approx(60.0), pytest.approx(0.0, abs=1e-9), "asphalt", ASPHALT_MU)
    assert (sim.odometer, sim.top_speed, sim.shifts, sim.wall_hits, sim.reverse_count, sim.requery_count, sim.on_wall) == (0.0, 0.0, 0, 0, 0, 0, False)


@pytest.mark.parametrize("car_id, track_id, words", [
    ("no_such_car", TRACK_ID, ("no car", "'no_such_car'", "'cars'", "kazane")),
    (CAR_ID, "no_such_track", ("no track", "'no_such_track'", "'tracks'", "test_loop")),
    ("test_loop", "kazane", ("no car", "'test_loop'")),  # 車とコースの id を、取り違えた
])
def test_sim_an_id_that_is_not_in_the_data_stops_with_a_message_that_names_it(car_id, track_id, words):
    # 起動時に、分かる文で止まる（KeyError の、id だけの文にしない）。文は、無い id、表の名、表にある id を挙げる。
    with pytest.raises(ValueError) as caught:
        Sim(0, game_data(), car_id, track_id)
    assert not isinstance(caught.value, KeyError)
    for word in words:
        assert word in str(caught.value), str(caught.value)


def test_sim_empty_data_stops_with_a_message_too():
    from cp_core.datadefs import TABLES, GameData

    empty = GameData({name: {} for name in TABLES}, (), None)
    with pytest.raises(ValueError, match="no car with id 'kazane'.*nothing"):
        Sim(0, empty, CAR_ID, TRACK_ID)
    with pytest.raises(ValueError, match="no car"):
        Sim(0, GameData({}, (), None), CAR_ID, TRACK_ID)  # 表そのものが無い


@pytest.mark.parametrize("data", [None, {}, {"cars": {}}, "data"])
def test_sim_data_must_be_the_loaded_data(data):
    with pytest.raises(TypeError):
        Sim(0, data, CAR_ID, TRACK_ID)


@pytest.mark.parametrize("car_id, track_id", [(None, TRACK_ID), (CAR_ID, None), (1, TRACK_ID), (CAR_ID, ["test_loop"])])
def test_sim_ids_must_be_strings(car_id, track_id):
    with pytest.raises(TypeError):
        Sim(0, game_data(), car_id, track_id)


def test_sim_reads_the_data_once_when_it_is_made_and_never_in_a_step(monkeypatch):
    # 読み込んだ定義は、引くたびに、奥まで複製される。世界は、作るときに1度だけ引く。
    data = data_files.load({}, None)
    asked = []
    entry = data.entry
    monkeypatch.setattr(data, "entry", lambda table, ident: asked.append((table, ident)) or entry(table, ident))
    sim = Sim(0, data, CAR_ID, TRACK_ID)
    assert asked == [("cars", CAR_ID), ("tracks", TRACK_ID), ("assists", controls.DEFAULT_SET)]
    run(sim, GAS, 120)
    sim.summary()
    assert len(asked) == 3


def test_sim_two_worlds_share_the_track_table_but_not_the_car():
    a, b = make(), make()
    assert a.track is b.track  # コースの表は、書き換えられない。同じ中身の項目からは、同じ表
    assert a.car is not b.car and a.control is not b.control
    run(a, GAS, 60)
    assert b.summary() == START


# --- 1 tick ---
def test_sim_step_advances_exactly_one_tick():
    sim = make()
    for expected in range(1, 121):
        sim.step(NEUTRAL)
        assert sim.tick == expected
    assert sim.summary()["tick"] == 120


def test_sim_car_stays_put_without_any_input():
    sim = run(make(), NEUTRAL, 120)
    assert sim.summary() == {**START, "tick": 120, "input_digest": sim.input_digest}


def test_sim_summary_is_plain_json_data():
    sim = run(make(), GAS, 200)
    sim.step(LEFT)
    summary = sim.summary()
    assert json.loads(json.dumps(summary)) == summary
    assert all(type(value) in (int, str) for value in summary.values())


def test_sim_summary_is_a_copy_not_the_state():
    sim = make()
    summary = sim.summary()
    for name in summary:
        summary[name] = 999
    assert sim.tick == 0
    assert sim.summary() == START


def test_sim_two_worlds_with_the_same_steps_agree():
    a, b = make(), make()
    for index in range(600):
        frame = LEFT if index % 7 == 0 else GAS if index % 3 else NEUTRAL
        a.step(frame)
        b.step(frame)
    assert a.summary() == b.summary()
    assert a.car.state() == b.car.state()  # 同じ環境の中では、小数も、最後の1ビットまで同じ
    assert a.summary()["odometer_mm"] > 50_000  # 走っている（止まったままの世界どうしを、比べていない）


# --- 入力フレームを受ける ---
def test_sim_step_needs_an_input_frame():
    sim = make()
    with pytest.raises(TypeError):
        sim.step()  # 引数は必須
    for bad in (None, {"steer_analog": 0.0}, (0, 0, 0, 0, 0, 0, 0, 0), "neutral", 0):
        with pytest.raises(TypeError):
            sim.step(bad)
    assert sim.summary() == START  # 受けなかった入力では、進まない


def test_sim_input_digest_folds_the_quantized_frame_of_every_tick():
    sim = make()
    digest = DIGEST_START
    for frame in (NEUTRAL, LEFT, LEFT, GAS, NEUTRAL):
        sim.step(frame)
        digest = fold(digest, quantize(frame))
        assert sim.input_digest == digest
    assert (sim.summary()["tick"], sim.summary()["input_digest"]) == (5, digest)
    assert digest == 3821819394  # 5 tick分を畳み込んだ値を、数字でも固定する


def test_sim_input_digest_changes_even_when_nothing_is_pressed():
    # 何も押していないtickも畳み込む。入力フレームが1 tick欠けたことを、拾えるように。
    a, b = make(), make()
    a.step(NEUTRAL)
    assert a.input_digest != DIGEST_START
    b.step(NEUTRAL)
    b.step(NEUTRAL)
    assert a.input_digest != b.input_digest


def test_sim_input_digest_depends_on_the_order_of_the_frames():
    a, b = make(), make()
    for frame in (LEFT, GAS, NEUTRAL):
        a.step(frame)
    for frame in (GAS, LEFT, NEUTRAL):
        b.step(frame)
    assert a.tick == b.tick and a.input_digest != b.input_digest


def test_sim_input_digest_sees_a_frame_that_arrives_one_tick_late():
    frames = [NEUTRAL, LEFT, GAS, NEUTRAL, NEUTRAL]
    on_time, late = make(), make()
    for frame in frames:
        on_time.step(frame)
    for frame in [NEUTRAL, *frames[:-1]]:
        late.step(frame)
    assert on_time.input_digest != late.input_digest


def test_sim_input_digest_is_a_32_bit_integer():
    sim = make()
    for _ in range(200):
        sim.step(LEFT)
        assert type(sim.input_digest) is int and 0 <= sim.input_digest < 2**32


# --- 種と、用途ごとの乱数の流れ ---
def test_sim_takes_a_seed_and_puts_it_and_the_stream_states_into_the_summary():
    assert make().seed == 0 and make(seed=7).seed == 7
    assert make(1).summary() == {**START, "seed": 1, "rng_ai": "3c07e3cc992538ed"}
    assert make(20261111).summary() == {**START, "seed": 20261111, "rng_ai": "3581644b167e57b5"}


def test_sim_summary_has_one_stream_state_per_registered_purpose():
    summary = make(3).summary()
    assert list(summary) == [*(name for name, _, _ in FIELDS), *(f"rng_{name}" for name in PURPOSES)]
    for name in PURPOSES:
        text = summary[f"rng_{name}"]
        # 16桁の16進の文字列（小文字）。64ビットの整数を、JavaScriptを通っても欠けない形にする。
        assert type(text) is str and len(text) == 16 and text == text.lower()
        assert int(text, 16) == RngSet(3).state()[name]


def test_sim_summary_stays_flat_integers_and_strings():
    # 要約は、整数と文字列だけの、入れ子の無い辞書（JSONにそのまま書ける）。走った後も、小数を入れない。
    for sim in (make(), make(2**63 + 12345), run(make(), GAS, 300), played(input_reference.WALL_SCRIPT, 500)):
        summary = sim.summary()
        assert all(type(key) is str for key in summary)
        assert all(type(value) in (int, str) for value in summary.values())
        assert json.loads(json.dumps(summary)) == summary


def test_sim_stream_state_in_the_summary_follows_the_stream():
    sim = make(7)
    assert sim.summary()["rng_ai"] == "7da0ebdcb37404f3"
    sim.rng.stream("ai").next_u64()  # 流れを1回引くと、要約が変わる
    assert sim.summary()["rng_ai"] == "1bd8659632be8108"


def test_sim_steps_do_not_draw_from_the_streams_yet():
    # いまは、乱数を引く所が無い（AIを作る段3から）。入力を流しても、流れの状態は動かない。
    sim = make(7)
    for frame in (NEUTRAL, LEFT, GAS) * 40:
        sim.step(frame)
    assert sim.summary()["rng_ai"] == make(7).summary()["rng_ai"]


def test_sim_worlds_with_different_seeds_differ_only_in_the_seed_and_the_streams():
    a, b = make(1), make(2)
    for frame in (LEFT, GAS, NEUTRAL) * 30:
        a.step(frame)
        b.step(frame)
    assert a.summary() != b.summary()
    assert {key for key in a.summary() if a.summary()[key] != b.summary()[key]} == {"seed", "rng_ai"}


@pytest.mark.parametrize("seed", [1.0, True, "1", None])
def test_sim_seed_must_be_an_integer(seed):
    with pytest.raises(TypeError):
        Sim(seed, game_data(), CAR_ID, TRACK_ID)


# --- 要約の項目（名、倍率、比べ方） ---
def test_sim_summary_field_table_is_the_one_the_request_fixed():
    assert world.SUMMARY_FIELDS == FIELDS
    assert (world.COMPARE_EXACT, world.COMPARE_NEAR, world.COMPARE_WRAP) == ("exact", "near", "wrap")
    assert (world.MM, world.E5) == (1000, 100000)
    names = [name for name, _, _ in FIELDS]
    assert len(set(names)) == len(names) == 23


def test_sim_summary_compare_names_every_field_of_the_summary_and_the_streams_are_exact():
    rules = world.summary_compare()
    assert set(rules) == set(make().summary())  # 比べ方の表と、要約の項目が、同じ集まり
    assert {name: kind for name, _, kind in FIELDS}.items() <= rules.items()
    assert all(rules[f"rng_{name}"] == "exact" for name in PURPOSES)
    # 回数と、名と、ギアと、路面は、完全一致（許容差つきにすると、変速の回数が1違っても通る）。
    exact = {name for name, kind in rules.items() if kind == "exact"}
    assert {"tick", "input_digest", "seed", "car", "track", "gear", "surface", "shifts", "wall_hits", "reverse_count", "requery_count"} <= exact
    assert {name for name, kind in rules.items() if kind == "wrap"} == {"heading_e5", "s_mm"}


def test_sim_summary_periods_are_one_turn_and_one_lap():
    sim = make()
    assert sim.summary_periods() == {"heading_e5": 628319, "s_mm": round(sim.track.length * 1000)}
    assert world.HEADING_TURN_E5 == round(2.0 * math.pi * 100000) == 628319
    assert set(sim.summary_periods()) == {name for name, kind in world.summary_compare().items() if kind == "wrap"}


def test_sim_summary_quantizes_the_car_state_by_rounding_value_times_scale():
    sim = played(input_reference.DRIVE_SCRIPT, 700)  # コーナーの中。舵、ヨーレート、横の速度が、0でない
    car, summary = sim.car, sim.summary()
    raw = {
        "x_mm": car.x, "z_mm": car.z, "vx_mm_s": car.wvx, "vz_mm_s": car.wvz, "heading_e5": car.heading, "yaw_rate_e5": car.yaw_rate,
        "steer_e5": car.steer, "rpm": car.rpm, "s_mm": sim.s, "lateral_mm": sim.lateral, "odometer_mm": sim.odometer, "top_speed_mm_s": sim.top_speed,
    }
    scales = {name: scale for name, scale, _ in FIELDS if scale}
    assert set(raw) == set(scales)
    for name, value in raw.items():
        assert summary[name] == round(value * scales[name]) and type(summary[name]) is int, name
        assert value != 0.0 and value * scales[name] != summary[name], name  # 元は、端数のある小数（丸めていることを、見ている）
    assert (summary["gear"], summary["surface"], summary["car"], summary["track"]) == (car.gear, sim.surface, CAR_ID, TRACK_ID)
    assert -314160 <= summary["heading_e5"] <= 314160  # 向きは、−π〜π に折り返した値


# --- 走る ---
def test_sim_full_throttle_moves_the_car_down_the_straight_and_the_distance_grows():
    sim = make()
    seen = []
    for _ in range(240):
        sim.step(GAS)
        seen.append((sim.odometer, sim.s, sim.car.x))
    assert all(later[0] >= earlier[0] for earlier, later in zip(seen, seen[1:]))  # 進行距離は、減らない
    assert seen[-1][0] == pytest.approx(seen[-1][1] - 60.0, abs=1e-6) == pytest.approx(seen[-1][2] - 60.0, abs=0.05)  # 直線では、進んだ分
    assert seen[-1][0] > 30.0 and sim.top_speed > 15.0 and sim.shifts >= 1 and sim.car.gear >= 2
    assert sim.top_speed == max(sim.top_speed, sim.car.speed) and (sim.wall_hits, sim.reverse_count, sim.requery_count) == (0, 0, 0)


def test_sim_drive_script_accelerates_shifts_brakes_and_turns_into_the_first_corner():
    sim = played(input_reference.DRIVE_SCRIPT, 900)
    summary = sim.summary()
    assert summary["odometer_mm"] > 250_000 and summary["top_speed_mm_s"] > 27_000  # 約259 m、時速約98 km
    assert summary["shifts"] == 3 and summary["gear"] == 2  # 1速 → 2速 → 3速 と上げて、コーナーの手前で2速へ下げた
    assert (summary["surface"], summary["wall_hits"], summary["reverse_count"], summary["requery_count"]) == ("asphalt", 0, 0, 0)
    assert abs(summary["lateral_mm"]) < 1000  # 中心線の近くを、回っている（スピンしていない）
    assert summary["heading_e5"] > 200_000  # 半円の中で、向きが、115度より大きく変わっている
    assert summary["s_mm"] == pytest.approx(60_000 + summary["odometer_mm"], abs=2)


def test_sim_wall_script_hits_the_wall_backs_up_and_returns_to_the_track():
    sim, script = make(), script_of(input_reference.WALL_SCRIPT)
    gears, surfaces, on_wall = set(), set(), 0
    for tick in range(780):
        sim.step(script.frame_at(tick))
        gears.add(sim.car.gear)
        surfaces.add(sim.surface)
        on_wall += sim.on_wall
    summary = sim.summary()
    assert (summary["wall_hits"], summary["reverse_count"]) == (1, 1)
    assert vehicle.REVERSE in gears and surfaces == {"asphalt", "grass"} and on_wall >= 1
    assert summary["gear"] >= 1 and summary["vx_mm_s"] > 10_000  # 最後は、前進のギアで、前へ進んでいる
    assert summary["shifts"] == 3  # 後退へ入る、前進へ戻る、2速へ上げる
    assert summary["surface"] == "asphalt" and abs(summary["lateral_mm"]) < 3000 and abs(summary["heading_e5"]) < 10_000
    assert summary["odometer_mm"] > 30_000 and summary["requery_count"] == 0


# --- 路面の摩擦係数は、前のtickの照会から ---
def test_sim_surface_grip_follows_the_surface_one_tick_later(monkeypatch):
    # 舗装の上から、左の芝へ出て行く。車両モデルと操作補正へ渡す摩擦係数は、前のtickの照会の、路面の種類の値。
    given = []
    car_step = vehicle.Car.step

    def recording_step(car, steer, throttle, brake, mu):
        given.append(mu)
        car_step(car, steer, throttle, brake, mu)

    monkeypatch.setattr(vehicle.Car, "step", recording_step)
    sim = make()
    place(sim, 100.0, 4.0, turn=math.pi / 2.0, speed=8.0)  # 中心線の左4 m。左（芝のほう）を向いて、毎秒8 m
    assert (sim.surface, sim.mu) == ("asphalt", ASPHALT_MU)
    surfaces = []
    for _ in range(40):
        sim.step(NEUTRAL)
        surfaces.append(sim.surface)
    first_grass = surfaces.index("grass")
    assert 5 < first_grass < 30 and set(surfaces[first_grass:]) == {"grass"}
    assert given[0] == ASPHALT_MU  # 始まりは、置いた所の照会
    # tick n の車両モデルは、tick n−1 の終わりの路面の値を受ける（芝へ入ったtickは、まだ舗装の値）。
    assert given[1:] == [GRASS_MU if surface == "grass" else ASPHALT_MU for surface in surfaces[:-1]]
    assert given[first_grass] == ASPHALT_MU and given[first_grass + 1] == GRASS_MU
    assert sim.mu == GRASS_MU == sim.track.surface_mu("grass")


def test_sim_car_stops_later_on_the_grass_than_on_the_asphalt():
    def stopping_distance(lateral: float) -> float:
        sim = make()
        place(sim, 20.0, lateral, speed=15.0)
        start = sim.car.x
        for _ in range(240):
            sim.step(BRAKE)
            if sim.car.speed == 0.0:  # 止まった所まで（押し続けると、0.5秒後に、後退へ入る）
                break
        assert sim.car.speed == 0.0 and sim.car.gear == 1
        return sim.car.x - start

    on_asphalt, on_grass = stopping_distance(0.0), stopping_distance(10.0)
    assert on_grass > 1.5 * on_asphalt > 10.0


def test_sim_controls_get_the_surface_grip_too(monkeypatch):
    seen = []
    step = controls.step

    def recording(params, state, frame, speed, gear, max_steer, wheelbase, peak_slip, tire_mu, surface_mu):
        seen.append((speed, gear, max_steer, wheelbase, peak_slip, tire_mu, surface_mu))
        return step(params, state, frame, speed, gear, max_steer, wheelbase, peak_slip, tire_mu, surface_mu)

    monkeypatch.setattr(controls, "step", recording)
    sim = make()
    place(sim, 20.0, 10.0, speed=12.0)  # 芝の上
    spec = sim.spec
    sim.step(GAS)
    assert seen == [(12.0, sim.car.gear, spec.max_steer, spec.wheelbase, spec.peak_slip, spec.tire_mu, GRASS_MU)]


# --- 壁 ---
def test_sim_wall_stops_the_car_and_counts_the_hit_once():
    sim = make()
    place(sim, 100.0, 6.0, turn=math.pi / 2.0, speed=10.0)  # 左の壁へ、正面から、毎秒10 m
    half_length = sim.spec.half_length
    hits = []
    for _ in range(120):
        sim.step(NEUTRAL)
        hits.append(sim.wall_hits)
        assert sim.lateral + half_length <= WALL_M + 1e-6  # 壁の外へ、出ない
    assert hits[0] == 0 and hits[-1] == 1  # 当たり始めを、1回
    # 壁へ向かう速さは、無くなった（弱く跳ね返って、ゆっくり離れていく）。壁を、突き抜けていない。
    assert sim.car.wvz <= 0.0 and sim.car.speed < 2.0 and WALL_M - half_length - 4.0 < sim.lateral < WALL_M - half_length
    assert sim.summary()["surface"] == "grass"


def test_sim_car_pressed_against_the_wall_does_not_count_a_hit_on_every_tick():
    sim = make()
    place(sim, 100.0, 9.0, turn=math.pi / 2.0, speed=5.0)
    contact = 0
    for _ in range(400):
        sim.step(GAS)  # アクセルを踏んだまま、壁に押し付ける
        contact += sim.on_wall
    assert contact > 200  # 大半のtickで、壁に当たっている
    assert 1 <= sim.wall_hits <= 8  # 数えるのは、当たり始めだけ（跳ね返って離れた後の、当たり直しを含む）
    settled = sim.wall_hits
    run(sim, GAS, 200)
    assert sim.wall_hits == settled and sim.on_wall  # 押し付けられている間は、増えない
    assert sim.lateral + sim.spec.half_length <= WALL_M + 1e-6


def test_sim_summary_position_is_the_one_after_the_wall_pushed_the_car_back():
    sim = make()
    place(sim, 100.0, 9.0, turn=math.pi / 2.0, speed=20.0)
    for _ in range(120):  # 上限つきで回す（壁の押し戻しが当たりを返さない崩れで、終わらないテストにしない）
        if sim.on_wall:
            break
        sim.step(NEUTRAL)
    assert sim.on_wall
    # 壁に当たったtick。要約の横のずれと、コースに沿った距離は、押し戻した後の位置の値（車の位置を、照会し直した値と同じ）。
    again = sim.track.query(sim.car.x, sim.car.z)
    assert (sim.s, sim.lateral) == (pytest.approx(again.s, abs=1e-9), pytest.approx(again.lateral, abs=1e-9))
    assert sim.lateral + sim.spec.half_length == pytest.approx(WALL_M, abs=1e-6) and sim.requery_count == 0


# --- 進行距離 ---
def test_sim_distance_does_not_shrink_when_the_car_backs_up():
    sim = make()
    run(sim, GAS, 120)
    run(sim, BRAKE, 200)  # 止まって、後退へ入り、後ろへ進む
    assert sim.car.gear == vehicle.REVERSE and sim.reverse_count == 1
    before, s_before = sim.odometer, sim.s
    run(sim, BRAKE, 120)
    assert sim.s < s_before - 3.0  # 後ろへ動いた
    assert sim.odometer == before  # 後ろへ動いた分は、引かない（足しもしない）


def test_sim_distance_keeps_growing_across_the_lap_boundary():
    sim = make()
    length = sim.track.length
    place(sim, length - 6.0, 0.0, speed=20.0)
    run(sim, GAS, 60)
    assert 10.0 < sim.s < 30.0  # コースに沿った距離は、1周で0へ戻る
    assert sim.odometer == pytest.approx(sim.s + 6.0, abs=1e-6)  # 進行距離は、戻らない


def test_sim_distance_ignores_a_jump_no_car_can_make():
    assert world.ODOMETER_MAX_STEP_M == 40.0
    sim = make()
    run(sim, GAS, 60)
    before = sim.odometer
    x, z, heading = sim.track.pose_at(sim.s + 45.0)
    sim.car.reset(x, z, heading, 10.0)  # 置き直す口を通さずに、車を、45 m先へ動かす
    sim.step(NEUTRAL)
    assert sim.odometer == before and sim.requery_count == 1  # 進行距離には足さない。照会は、取り直した


# --- 置き直す口（テストと道具用） ---
def test_sim_place_car_moves_the_car_and_looks_the_position_up_afresh():
    sim = make()
    run(sim, GAS, 100)
    tick, digest, odometer, top_speed, shifts = sim.tick, sim.input_digest, sim.odometer, sim.top_speed, sim.shifts
    x, z, heading = sim.track.pose_at(400.0, -9.0)  # 向かい側の直線の、右の芝
    sim.place_car(x, z, heading, 12.0)
    assert (sim.car.x, sim.car.z, sim.car.heading, sim.car.speed) == (x, z, heading, 12.0)
    assert (sim.s, sim.lateral, sim.surface, sim.mu) == (pytest.approx(400.0), pytest.approx(-9.0), "grass", GRASS_MU)
    assert (sim.control.steer, sim.control.brake_hold_ticks, sim.on_wall) == (0.0, 0, False)
    # tick、入力の要約値、走行の数えは、変えない。置き直した分は、進行距離に入らず、取り直しにも数えない。
    assert (sim.tick, sim.input_digest, sim.odometer, sim.top_speed, sim.shifts, sim.requery_count) == (tick, digest, odometer, top_speed, shifts, 0)
    sim.step(NEUTRAL)
    assert sim.requery_count == 0 and 0.0 < sim.odometer - odometer < 1.0  # 次のtickは、置いた所から、ふつうに進む


def test_sim_ordinary_driving_never_looks_the_whole_track_up_again():
    for path, ticks in ((input_reference.DRIVE_SCRIPT, 900), (input_reference.WALL_SCRIPT, 780), (input_reference.SMOKE_SCRIPT, 120)):
        assert played(path, ticks).requery_count == 0, path
