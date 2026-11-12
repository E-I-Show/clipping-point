"""画面の状態（cp_core.flow）のテスト。いまは最小の形：画面の名の一覧、いまの画面の名、表示用の値の型、世界から車の値を作る所、
測った値を、表示の桁に収める所。"""
import dataclasses
import functools

import pytest

import input_reference
from cp_core import flow
from cp_core.flow import PERF_FIELDS, PERF_NOT_MEASURED, SCREEN_NAMES, START_SCREEN, CarView, Flow, PerfView, PlaceholderView, car_view
from cp_core.input_frame import NEUTRAL, InputFrame
from cp_core.vehicle import REVERSE

CAR = CarView(speed_kmh=87, gear=3, rpm=5200, x_dm=1234, z_dm=-56, surface="asphalt")
# 処理時間の値。更新1回が平均0.3 ms、最大1.2 ms。実描画1回が平均2.4 ms、最大4.1 ms。毎秒60回と30回。起動に1.2秒。PAGE は、測れていない。
PERF = PerfView(3, 12, 24, 41, 600, 300, 12, None)


def test_flow_logic_holds_one_screen_for_now():
    assert SCREEN_NAMES == ("placeholder",)


def test_flow_screen_names_are_distinct_strings():
    assert all(type(name) is str and name for name in SCREEN_NAMES)
    assert len(set(SCREEN_NAMES)) == len(SCREEN_NAMES)


def test_flow_starts_on_a_known_screen():
    assert START_SCREEN in SCREEN_NAMES
    assert Flow().screen == START_SCREEN == "placeholder"


def test_flow_two_flows_do_not_share_their_screen():
    a, b = Flow(), Flow()
    a.screen = "somewhere_else"
    assert b.screen == START_SCREEN


def test_flow_placeholder_view_holds_tick_renders_the_input_frame_the_notice_the_car_and_the_measured_times():
    frame = InputFrame(steer_analog=0.5, held=frozenset({"up"}))
    view = PlaceholderView(120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS", CAR, PERF)
    assert (view.tick, view.renders, view.frame, view.notice, view.car) == (120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS", CAR)
    assert view.perf == PERF
    # 処理時間の値は、末尾（車の値の後ろ）。前の項目の並びは、変わらない。
    assert [field.name for field in dataclasses.fields(PlaceholderView)] == ["tick", "renders", "frame", "notice", "car", "perf"]
    assert PlaceholderView(0, 0, NEUTRAL, "", CAR, PERF).notice == ""  # 知らせが無ければ、空


def test_flow_placeholder_view_cannot_be_changed():
    view = PlaceholderView(0, 0, NEUTRAL, "", CAR, PERF)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.renders = 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.notice = "CHANGED"
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.car = CAR
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.car.gear = 4
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.perf = PERF
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.perf.boot_s_x10 = 5


def test_flow_placeholder_view_rejects_a_misspelt_field():
    # 素の辞書だと、項目の打ち間違いは、描く時まで分からない。型なら、作る時に落ちる。
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, render=2, frame=NEUTRAL, notice="", car=CAR, perf=PERF)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, notice="", car=CAR, perf=PERF)


def test_flow_placeholder_view_needs_the_notice_the_car_and_the_measured_times():
    # 知らせの1行と、車の値と、処理時間の値は、省けない。アプリが渡し忘れたら、作る時に落ちる（空の知らせや、止まった車や、
    # 測れていない値で、黙って描かない）。
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL, car=CAR, perf=PERF)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL, car=CAR, perf=PERF)
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL, "", perf=PERF)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL, notice="", perf=PERF)
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL, "", CAR)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL, notice="", car=CAR)


@pytest.mark.parametrize("notice", [None, 5, b"SAVE", ["SAVE"], True])
def test_flow_placeholder_view_rejects_a_notice_that_is_not_text(notice):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, notice, CAR, PERF)


@pytest.mark.parametrize("tick, renders", [(1.0, 2), (1, 2.5), (True, 2), (1, False), ("1", 2), (None, 2)])
def test_flow_placeholder_view_rejects_counts_that_are_not_integers(tick, renders):
    with pytest.raises(TypeError):
        PlaceholderView(tick, renders, NEUTRAL, "", CAR, PERF)


@pytest.mark.parametrize("tick, renders", [(-1, 0), (0, -1)])
def test_flow_placeholder_view_rejects_negative_counts(tick, renders):
    with pytest.raises(ValueError):
        PlaceholderView(tick, renders, NEUTRAL, "", CAR, PERF)


@pytest.mark.parametrize("frame", [None, (0, 0, 0), {"steer_analog": 0.0}, "NEUTRAL"])
def test_flow_placeholder_view_rejects_anything_but_an_input_frame(frame):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, frame, "", CAR, PERF)


@pytest.mark.parametrize("car", [None, (87, 3, 5200, 1234, -56, "asphalt"), dataclasses.asdict(CAR), "CAR"])
def test_flow_placeholder_view_rejects_anything_but_a_car_view(car):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, "", car, PERF)


@pytest.mark.parametrize("perf", [None, (3, 12, 24, 41, 600, 300, 12, None), dataclasses.asdict(PERF), "PERF"])
def test_flow_placeholder_view_rejects_anything_but_a_perf_view(perf):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, "", CAR, perf)


# --- 処理時間の値（表示用の値の一部） ---
def test_flow_perf_view_holds_whole_tenths_or_not_measured():
    assert [field.name for field in dataclasses.fields(PerfView)] == list(PERF_FIELDS) == [
        "update_mean_ms_x10", "update_max_ms_x10", "render_mean_ms_x10", "render_max_ms_x10",
        "updates_per_s_x10", "renders_per_s_x10", "boot_s_x10", "page_s_x10",
    ]
    assert dataclasses.astuple(PERF) == (3, 12, 24, 41, 600, 300, 12, None)
    assert all(value is None or type(value) is int for value in dataclasses.astuple(PERF))
    # どれも測れていない値（最初の数tick）も、作れる。
    assert dataclasses.astuple(PERF_NOT_MEASURED) == (None,) * 8
    assert PerfView(0, 0, 0, 0, 0, 0, 0, 0).boot_s_x10 == 0


@pytest.mark.parametrize("field", PERF_FIELDS)
@pytest.mark.parametrize("value", [1.5, True, "12", [12]])
def test_flow_perf_view_rejects_values_that_are_not_integers(field, value):
    # 小数を、そのまま渡さない（丸めるのは、測った値を表示の桁に収める所 capped_tenths の1か所）。
    with pytest.raises(TypeError):
        dataclasses.replace(PERF, **{field: value})


@pytest.mark.parametrize("field", PERF_FIELDS)
def test_flow_perf_view_rejects_negative_values(field):
    with pytest.raises(ValueError):
        dataclasses.replace(PERF, **{field: -1})


@pytest.mark.parametrize("field", PERF_FIELDS)
def test_flow_perf_view_does_not_raise_on_a_value_beyond_the_digits(field):
    # 上限では、例外にしない（ふつうの起動の、実描画の中で作る。例外になると、ブラウザ版は、エラー表示で止まる）。
    assert getattr(dataclasses.replace(PERF, **{field: 10 ** 9}), field) == 10 ** 9


# --- 車の値（表示用の値の一部） ---
def test_flow_car_view_holds_integers_and_the_surface_name_only():
    assert [field.name for field in dataclasses.fields(CarView)] == ["speed_kmh", "gear", "rpm", "x_dm", "z_dm", "surface"]
    assert dataclasses.astuple(CAR) == (87, 3, 5200, 1234, -56, "asphalt")
    assert all(type(value) in (int, str) for value in dataclasses.astuple(CAR))
    assert CarView(0, REVERSE, 0, 0, 0, "grass").gear == -1  # 後退のギアは −1。位置は、負も、0もある
    assert (flow.KMH_PER_M_S, flow.DM_PER_M) == (3.6, 10)


@pytest.mark.parametrize("change", [
    {"speed_kmh": 87.5}, {"speed_kmh": True}, {"gear": 3.0}, {"gear": "R"}, {"rpm": 5200.0}, {"rpm": None},
    {"x_dm": 123.4}, {"z_dm": "-5.6"}, {"x_dm": False},
])
def test_flow_car_view_rejects_values_that_are_not_integers(change):
    # 小数を、そのまま渡さない（丸めるのは、世界から作る所の1か所）。
    with pytest.raises(TypeError):
        dataclasses.replace(CAR, **change)


@pytest.mark.parametrize("change", [{"speed_kmh": -1}, {"rpm": -1}, {"gear": 0}, {"surface": "gravel"}, {"surface": "ASPHALT"}, {"surface": ""}, {"surface": None}])
def test_flow_car_view_rejects_values_out_of_range(change):
    with pytest.raises(ValueError):
        dataclasses.replace(CAR, **change)


def test_flow_car_view_of_the_world_at_the_start():
    sim = input_reference.make_sim()
    view = car_view(sim)
    assert view == CarView(speed_kmh=0, gear=1, rpm=850, x_dm=600, z_dm=0, surface="asphalt")
    assert sim.summary() == input_reference.make_sim().summary()  # 世界は、書き換えない


def test_flow_car_view_rounds_the_speed_to_whole_kmh_and_the_position_to_tenths_of_a_metre():
    sim = input_reference.make_sim()
    x, z, heading = sim.track.pose_at(123.44, -9.06)  # 1本目の直線の、右の芝
    sim.place_car(x, z, heading, 27.0)
    view = car_view(sim)
    assert (view.speed_kmh, view.x_dm, view.z_dm, view.surface) == (97, 1234, -91, "grass")  # 毎秒27 m は、時速97.2 km
    assert view.gear >= 2 and view.rpm == round(sim.car.rpm)


@functools.cache
def views_of(path, ticks: int) -> tuple:
    """台本を回した世界の、全tickの、車の値。"""
    sim, script = input_reference.make_sim(), input_reference.load_script(path)[1]
    views = []
    for tick in range(ticks):
        sim.step(script.frame_at(tick))
        views.append((car_view(sim), sim.on_wall))
    return tuple(views)


def test_flow_car_view_can_be_made_on_every_tick_of_the_drive_script():
    views = [view for view, _ in views_of(input_reference.DRIVE_SCRIPT, 900)]
    assert len(views) == 900
    assert max(view.speed_kmh for view in views) == 98 and {view.gear for view in views} == {1, 2, 3}
    assert max(view.rpm for view in views) > 6500 and {view.surface for view in views} == {"asphalt"}
    assert views[-1].x_dm > 2000 and views[-1].z_dm > 500  # 最初のコーナーの中


def test_flow_car_view_can_be_made_on_every_tick_of_the_wall_script_in_reverse_on_the_grass_and_at_the_wall():
    views = views_of(input_reference.WALL_SCRIPT, 780)
    assert len(views) == 780
    in_reverse = [view for view, _ in views if view.gear == REVERSE]
    on_grass = [view for view, _ in views if view.surface == "grass"]
    at_the_wall = [view for view, on_wall in views if on_wall]
    assert len(in_reverse) > 100 and len(on_grass) > 100 and at_the_wall  # 後退のギア、芝の上、壁に当たっている間も、作れる
    assert {view.gear for view, _ in views} == {REVERSE, 1, 2}
    assert max(view.speed_kmh for view in in_reverse) > 15  # 後ろへ進んでいる間も、速度は0以上
    assert all(view.speed_kmh >= 0 and view.rpm >= 0 for view, _ in views)


# --- 測った値を、表示の 0.1 刻みの整数にして、桁いっぱいで頭打ちにする ---
@pytest.mark.parametrize("value, digits, want", [
    (0.0, 2, 0), (0.04, 2, 0), (0.05, 2, 0), (0.06, 2, 1), (1.0, 2, 10), (12.34, 2, 123), (12.36, 2, 124), (3, 2, 30),
    (99.8, 2, 998), (99.9, 2, 999), (99.94, 2, 999),  # 桁の内は、そのまま
    (59.96, 3, 600), (999.9, 3, 9999), (123.45, 1, 99),
])
def test_flow_capped_tenths_rounds_a_measured_value_to_tenths(value, digits, want):
    got = flow.capped_tenths(value, digits)
    assert got == want and type(got) is int


@pytest.mark.parametrize("value, digits, want", [
    (99.95, 2, 999), (100.0, 2, 999), (12345.6, 2, 999), (1000.0, 3, 9999), (1e308, 3, 9999), (float("inf"), 2, 999), (10 ** 400, 2, 999),
])
def test_flow_capped_tenths_stops_at_the_widest_value_the_digits_can_show(value, digits, want):
    # 表示の桁を超えた値は、桁いっぱいの値にする。例外にしない（ふつうの起動の、更新か実描画の中で呼ぶ）。
    got = flow.capped_tenths(value, digits)
    assert got == want and type(got) is int


def test_flow_capped_tenths_keeps_not_measured_apart_from_zero():
    assert flow.capped_tenths(None, 2) is None  # 測れていない
    assert flow.capped_tenths(float("nan"), 2) is None  # 数にならなかった値も、測れていない扱い
    assert flow.capped_tenths(0.0, 2) == 0 and flow.capped_tenths(0, 3) == 0
    assert flow.capped_tenths(-0.5, 2) == 0 and flow.capped_tenths(float("-inf"), 2) == 0  # 負の値は、0


def test_flow_capped_tenths_rejects_what_is_not_a_number_and_a_width_below_one():
    for value in ("1.5", True, [1.5], b"1"):
        with pytest.raises(TypeError):
            flow.capped_tenths(value, 2)
    for digits in (0, -1, 2.0, True, None, "2"):
        with pytest.raises(ValueError):
            flow.capped_tenths(1.5, digits)
