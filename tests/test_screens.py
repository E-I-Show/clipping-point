"""画面の組み立て（cp_ui.screens）のテスト。Pyxelは使わない。"""
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, TITLE, build_placeholder

FONT_W, FONT_H = 4, 6  # 内蔵フォントの1文字の大きさ（設計の前提）


def placeholder(tick: int = 120, renders: int = 60) -> list:
    canvas = Canvas()
    build_placeholder(canvas, tick, renders)
    return canvas.commands


def test_screens_placeholder_shows_title_tick_and_render_count():
    texts = [command.text for command in placeholder(120, 60) if command.kind == "text"]
    assert texts == [TITLE, "TICK 120", "RENDER 60"]


def test_screens_placeholder_follows_the_given_numbers():
    texts = [command.text for command in placeholder(7, 3) if command.kind == "text"]
    assert texts[1:] == ["TICK 7", "RENDER 3"]


def test_screens_placeholder_text_is_ascii_only():
    for command in placeholder():
        if command.kind == "text":
            assert command.text.isascii()
            assert command.text == command.text.upper()


def test_screens_placeholder_stays_inside_the_screen():
    # 6桁のtick（約4.6時間ぶん）でも、画面の内に収まる。
    for command in placeholder(999999, 999999):
        assert 0 <= command.x < SCREEN_W and 0 <= command.y < SCREEN_H
        if command.kind == "rect":
            assert command.x + command.w <= SCREEN_W and command.y + command.h <= SCREEN_H
        else:
            assert command.x + FONT_W * len(command.text) <= SCREEN_W
            assert command.y + FONT_H <= SCREEN_H


def test_screens_placeholder_draws_something_other_than_the_background():
    assert any(command.col != COL_BACK for command in placeholder())
