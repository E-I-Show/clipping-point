"""画面の状態（cp_core.flow）のテスト。いまは最小の形：画面の名の一覧、いまの画面の名、表示用の値の型、世界から車の値を作る所。"""
import dataclasses
import functools

import pytest

import input_reference
from cp_core import flow
from cp_core.flow import SCREEN_NAMES, START_SCREEN, CarView, Flow, PlaceholderView, car_view
from cp_core.input_frame import NEUTRAL, InputFrame
from cp_core.vehicle import REVERSE

CAR = CarView(speed_kmh=87, gear=3, rpm=5200, x_dm=1234, z_dm=-56, surface="asphalt")


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


def test_flow_placeholder_view_holds_tick_renders_the_input_frame_the_notice_and_the_car():
    frame = InputFrame(steer_analog=0.5, held=frozenset({"up"}))
    view = PlaceholderView(120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS", CAR)
    assert (view.tick, view.renders, view.frame, view.notice, view.car) == (120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS", CAR)
    assert [field.name for field in dataclasses.fields(PlaceholderView)] == ["tick", "renders", "frame", "notice", "car"]
    assert PlaceholderView(0, 0, NEUTRAL, "", CAR).notice == ""  # 知らせが無ければ、空


def test_flow_placeholder_view_cannot_be_changed():
    view = PlaceholderView(0, 0, NEUTRAL, "", CAR)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.renders = 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.notice = "CHANGED"
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.car = CAR
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.car.gear = 4


def test_flow_placeholder_view_rejects_a_misspelt_field():
    # 素の辞書だと、項目の打ち間違いは、描く時まで分からない。型なら、作る時に落ちる。
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, render=2, frame=NEUTRAL, notice="", car=CAR)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, notice="", car=CAR)


def test_flow_placeholder_view_needs_the_notice_and_the_car():
    # 知らせの1行と、車の値は、省けない。アプリが渡し忘れたら、作る時に落ちる（空の知らせや、止まった車で、黙って描かない）。
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL, car=CAR)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL, car=CAR)
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL, "")
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL, notice="")


@pytest.mark.parametrize("notice", [None, 5, b"SAVE", ["SAVE"], True])
def test_flow_placeholder_view_rejects_a_notice_that_is_not_text(notice):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, notice, CAR)


@pytest.mark.parametrize("tick, renders", [(1.0, 2), (1, 2.5), (True, 2), (1, False), ("1", 2), (None, 2)])
def test_flow_placeholder_view_rejects_counts_that_are_not_integers(tick, renders):
    with pytest.raises(TypeError):
        PlaceholderView(tick, renders, NEUTRAL, "", CAR)


@pytest.mark.parametrize("tick, renders", [(-1, 0), (0, -1)])
def test_flow_placeholder_view_rejects_negative_counts(tick, renders):
    with pytest.raises(ValueError):
        PlaceholderView(tick, renders, NEUTRAL, "", CAR)


@pytest.mark.parametrize("frame", [None, (0, 0, 0), {"steer_analog": 0.0}, "NEUTRAL"])
def test_flow_placeholder_view_rejects_anything_but_an_input_frame(frame):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, frame, "", CAR)


@pytest.mark.parametrize("car", [None, (87, 3, 5200, 1234, -56, "asphalt"), dataclasses.asdict(CAR), "CAR"])
def test_flow_placeholder_view_rejects_anything_but_a_car_view(car):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, "", car)


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
