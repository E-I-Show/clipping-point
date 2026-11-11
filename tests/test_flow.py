"""画面の状態（cp_core.flow）のテスト。いまは最小の形：画面の名の一覧、いまの画面の名、表示用の値の型。"""
import dataclasses

import pytest

from cp_core.flow import SCREEN_NAMES, START_SCREEN, Flow, PlaceholderView
from cp_core.input_frame import NEUTRAL, InputFrame


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


def test_flow_placeholder_view_holds_tick_renders_the_input_frame_and_the_notice():
    frame = InputFrame(steer_analog=0.5, held=frozenset({"up"}))
    view = PlaceholderView(120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS")
    assert (view.tick, view.renders, view.frame, view.notice) == (120, 60, frame, "SAVE DATA UNREADABLE. USING DEFAULTS")
    assert [field.name for field in dataclasses.fields(PlaceholderView)] == ["tick", "renders", "frame", "notice"]
    assert PlaceholderView(0, 0, NEUTRAL, "").notice == ""  # 知らせが無ければ、空


def test_flow_placeholder_view_cannot_be_changed():
    view = PlaceholderView(0, 0, NEUTRAL, "")
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.renders = 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.notice = "CHANGED"


def test_flow_placeholder_view_rejects_a_misspelt_field():
    # 素の辞書だと、項目の打ち間違いは、描く時まで分からない。型なら、作る時に落ちる。
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, render=2, frame=NEUTRAL, notice="")
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, notice="")


def test_flow_placeholder_view_needs_the_notice():
    # 知らせの1行は、省けない。アプリが渡し忘れたら、作る時に落ちる（空の知らせで、黙って描かない）。
    with pytest.raises(TypeError):
        PlaceholderView(1, 2, NEUTRAL)
    with pytest.raises(TypeError):
        PlaceholderView(tick=1, renders=2, frame=NEUTRAL)


@pytest.mark.parametrize("notice", [None, 5, b"SAVE", ["SAVE"], True])
def test_flow_placeholder_view_rejects_a_notice_that_is_not_text(notice):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, NEUTRAL, notice)


@pytest.mark.parametrize("tick, renders", [(1.0, 2), (1, 2.5), (True, 2), (1, False), ("1", 2), (None, 2)])
def test_flow_placeholder_view_rejects_counts_that_are_not_integers(tick, renders):
    with pytest.raises(TypeError):
        PlaceholderView(tick, renders, NEUTRAL, "")


@pytest.mark.parametrize("tick, renders", [(-1, 0), (0, -1)])
def test_flow_placeholder_view_rejects_negative_counts(tick, renders):
    with pytest.raises(ValueError):
        PlaceholderView(tick, renders, NEUTRAL, "")


@pytest.mark.parametrize("frame", [None, (0, 0, 0), {"steer_analog": 0.0}, "NEUTRAL"])
def test_flow_placeholder_view_rejects_anything_but_an_input_frame(frame):
    with pytest.raises(TypeError):
        PlaceholderView(0, 0, frame, "")
