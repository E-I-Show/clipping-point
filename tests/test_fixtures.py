"""見本データ（cp_ui.fixtures）のテストと、画面の一覧の突き合わせ。Pyxelは使わない。

突き合わせ：ロジックが持つ画面の名（cp_core.flow の SCREEN_NAMES）、画面の登録（cp_ui.screens の SCREENS）の鍵、
見本データが組み立てられる画面（全部の変種）が、同じ集まりであること。登録の無い画面があれば、ここで落ちる。
"""
import dataclasses

import pytest

from cp_core import storage, track
from cp_core.flow import SCREEN_NAMES, CarView, Flow, PerfView, PlaceholderView
from cp_core.input_frame import BUTTONS, quantize
from cp_core.vehicle import REVERSE
from cp_ui import fixtures, screens
from cp_ui.canvas import Canvas
from cp_ui.check import find_violations
from cp_ui.screens import SCREENS


def test_fixtures_has_a_typical_and_an_extreme_variant():
    assert fixtures.VARIANTS == ("typical", "extreme")


@pytest.mark.parametrize("variant", fixtures.VARIANTS)
def test_fixtures_placeholder_is_a_view_value_that_cannot_be_changed(variant):
    view = fixtures.build("placeholder", variant)
    assert isinstance(view, PlaceholderView)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.tick = 0


def test_fixtures_placeholder_extreme_holds_the_longest_values():
    view = fixtures.build("placeholder", "extreme")
    assert (view.tick, view.renders) == (9_999_999, 9_999_999)
    # 舵のアナログ値が −1（符号の分、1字長い）。アクセルとブレーキは最大。ボタンを10個とも押している。
    assert quantize(view.frame)[:6] == (-1000, -1, 1000, 1, 1000, 1)
    assert view.frame.held == frozenset(BUTTONS) and len(view.frame.held) == 10


def test_fixtures_placeholder_extreme_carries_the_longest_notice_of_the_storage_notices():
    # 知らせの文は、保存の口（cp_core/storage.py）の組から引く。文を足したり伸ばしたりすると、極端な値も一緒に変わる。
    notice = fixtures.build("placeholder", "extreme").notice
    assert notice == fixtures.longest_notice() and notice in storage.NOTICES
    assert all(len(notice) >= len(other) for other in storage.NOTICES)
    assert notice == "SAVE STORAGE UNAVAILABLE. PROGRESS WILL NOT BE KEPT" and len(notice) == 51


def test_fixtures_longest_notice_follows_the_notices_of_the_storage(monkeypatch):
    longer = "SAVE STORAGE UNAVAILABLE. A NOTICE THAT IS LONGER THAN ALL THE OTHERS"
    monkeypatch.setattr(fixtures, "NOTICES", (*storage.NOTICES, longer))
    assert fixtures.longest_notice() == longer
    assert fixtures.build("placeholder", "extreme").notice == longer


def test_fixtures_placeholder_extreme_carries_the_widest_car_values():
    # 車の値は、仮の表示の桁をいっぱいに使う。ギアは後退（R）。位置は、コースの座標の上限の、負の側（符号の分、1字長い）。
    car = fixtures.build("placeholder", "extreme").car
    assert car == CarView(speed_kmh=999, gear=REVERSE, rpm=99_999, x_dm=-200_000, z_dm=-200_000, surface="asphalt")
    assert fixtures.farthest_position_dm() == -round(track.MAX_LENGTH_M * 10) == -200_000
    # 路面の種類は、コース（cp_core/track.py）の組から引く。種類を足すと、極端な値も一緒に変わる。
    assert car.surface == fixtures.longest_surface() and car.surface in track.SURFACES
    assert all(len(car.surface) >= len(name) for name in track.SURFACES)


def test_fixtures_longest_surface_follows_the_surfaces_of_the_track(monkeypatch):
    monkeypatch.setattr(fixtures, "SURFACES", (*track.SURFACES, "wet_asphalt"))
    assert fixtures.longest_surface() == "wet_asphalt"


def test_fixtures_placeholder_extreme_carries_the_widest_measured_times():
    # 処理時間の値は、仮の表示の桁をいっぱいに使う（99.9 ms、毎秒999.9回、999.9秒）。桁を変えると、ここも付いて変わる。
    perf = fixtures.build("placeholder", "extreme").perf
    assert perf == PerfView(999, 999, 999, 999, 9999, 9999, 9999, 9999)
    assert fixtures.widest_measured(screens.MS_DIGITS) == 999 and fixtures.widest_measured(screens.RATE_DIGITS) == 9999
    assert fixtures.widest_measured(screens.SECONDS_DIGITS) == 9999
    # どの項目も、測れている（「-」より、長い字になる）。
    assert all(value is not None for value in dataclasses.astuple(perf))
    # ふつうの値は、デスクトップ版の形（PAGE は、測れていない）。ほかは、測れている。
    typical = fixtures.build("placeholder", "typical").perf
    assert typical == PerfView(3, 12, 24, 41, 600, 300, 12, None)
    assert all(a < b for a, b in zip(dataclasses.astuple(typical)[:-1], dataclasses.astuple(perf)[:-1]))


def test_fixtures_placeholder_typical_is_not_the_extreme():
    typical, extreme = fixtures.build("placeholder", "typical"), fixtures.build("placeholder", "extreme")
    assert typical != extreme
    assert typical.tick < extreme.tick and typical.renders < extreme.renders
    assert 0 < len(typical.frame.held) < len(extreme.frame.held)
    assert typical.notice == "" and extreme.notice  # ふつうの値は、知らせが無い
    # ふつうの値の車は、舗装の上を、前進のギアで走っている。
    assert typical.car == CarView(speed_kmh=87, gear=3, rpm=5200, x_dm=1234, z_dm=-56, surface="asphalt")
    assert typical.car.speed_kmh < extreme.car.speed_kmh and typical.car.rpm < extreme.car.rpm


def test_fixtures_build_gives_the_same_value_every_time():
    for variant in fixtures.VARIANTS:
        assert fixtures.build("placeholder", variant) == fixtures.build("placeholder", variant)


@pytest.mark.parametrize("screen, variant", [("no_such_screen", "typical"), ("placeholder", "no_such_variant"), ("", ""), ("placeholder", "")])
def test_fixtures_unknown_screen_or_variant_is_a_key_error(screen, variant):
    with pytest.raises(KeyError):
        fixtures.build(screen, variant)


def test_fixtures_extreme_text_is_longer_than_the_typical_text():
    def longest(variant: str) -> int:
        canvas = Canvas()
        SCREENS["placeholder"](canvas, fixtures.build("placeholder", variant))
        return sum(len(command.text) for command in canvas.commands if command.kind == "text")

    assert longest("extreme") > longest("typical")


# --- 突き合わせ ---
def test_fixtures_logic_screens_registry_and_fixtures_name_the_same_screens():
    logic, registered, with_fixtures = set(SCREEN_NAMES), set(SCREENS), set(fixtures.screen_names())
    assert logic == registered, f"ロジックだけ：{sorted(logic - registered)}、登録だけ：{sorted(registered - logic)}"
    assert registered == with_fixtures, f"登録だけ：{sorted(registered - with_fixtures)}、見本データだけ：{sorted(with_fixtures - registered)}"
    assert logic, "画面が1つも無い"
    # 同じ名が2度並んでいない。
    assert len(SCREEN_NAMES) == len(logic) and len(fixtures.screen_names()) == len(with_fixtures)


def test_fixtures_every_logic_screen_builds_in_every_variant():
    assert fixtures.VARIANTS, "変種が1つも無い"
    for screen in SCREEN_NAMES:
        for variant in fixtures.VARIANTS:
            canvas = Canvas()
            SCREENS[screen](canvas, fixtures.build(screen, variant))
            assert canvas.commands, f"{screen}/{variant}: 画面が、描画命令を1つも残さない"
            assert find_violations(canvas) == [], f"{screen}/{variant}"


def test_fixtures_the_current_screen_of_the_logic_is_registered():
    assert Flow().screen in SCREENS
