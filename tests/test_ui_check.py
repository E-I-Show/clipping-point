"""はみ出しの検査（cp_ui.check）のテスト。Pyxelは使わない。

6種類（空の矩形、画面の外、囲みの外、出せない文字、文字どうしの重なり、開かれなかった囲み）が、1つずつ出ること。
端にちょうど接する矩形は、はみ出しにならないこと。囲みどうしの入れ子。
"""
import pytest

from cp_ui.canvas import Canvas
from cp_ui.check import KINDS, Violation, find_violations, is_drawable


def kinds(canvas: Canvas) -> list:
    return [violation.kind for violation in find_violations(canvas)]


def test_ui_check_counts_six_kinds():
    assert KINDS == ("empty", "off_screen", "out_of_box", "bad_char", "text_overlap", "box_not_entered")


def test_ui_check_clean_canvas_has_no_violations():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    with canvas.box("title", 0, 0, 320, 12):
        canvas.text(4, 3, "CLIPPING POINT", 7)
    canvas.line(0, 12, 319, 12, 5)
    canvas.rectb(2, 38, 316, 19, 5)
    assert find_violations(canvas) == []


def test_ui_check_empty_canvas_has_no_violations():
    assert find_violations(Canvas()) == []


# --- 1つずつ出ること ---
@pytest.mark.parametrize(
    "draw",
    [
        lambda c: c.rect(10, 10, 0, 5, 1),
        lambda c: c.rect(10, 10, 5, 0, 1),
        lambda c: c.rect(10, 10, -3, 5, 1),
        lambda c: c.rectb(10, 10, 5, -1, 1),
        lambda c: c.text(10, 10, "", 7),  # 空の文字列は、幅が −1
        lambda c: c.text(10, 10, "\n", 7),  # 改行だけ。どの行も0字
    ],
)
def test_ui_check_reports_an_empty_rectangle(draw):
    canvas = Canvas()
    draw(canvas)
    assert kinds(canvas) == ["empty"]


@pytest.mark.parametrize(
    "draw",
    [
        lambda c: c.text(300, 100, "TOO FAR RIGHT", 7),
        lambda c: c.text(-1, 100, "A", 7),
        lambda c: c.text(4, 236, "A", 7),  # 高さ5。下の端を1ピクセル出る
        lambda c: c.rect(0, -1, 10, 10, 1),
        lambda c: c.rectb(311, 0, 10, 10, 1),
        lambda c: c.line(0, 12, 320, 12, 5),  # 両端を含むので、x=320 は画面の外
        lambda c: c.rect(400, 300, 10, 10, 1),  # 丸ごと外
    ],
)
def test_ui_check_reports_a_command_that_leaves_the_screen(draw):
    canvas = Canvas()
    draw(canvas)
    assert kinds(canvas) == ["off_screen"]


def test_ui_check_reports_a_text_longer_than_its_box():
    canvas = Canvas()
    with canvas.box("status", 2, 18, 40, 10):
        canvas.text(4, 20, "RENDER 9999999", 7)  # 幅55。囲みは x=42 まで
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["out_of_box"]
    assert "RENDER 9999999" in found[0].text and "status" in found[0].text


@pytest.mark.parametrize(
    "draw",
    [
        lambda c: c.rect(49, 60, 10, 10, 1),  # 左へ1ピクセル
        lambda c: c.rectb(50, 59, 10, 10, 1),  # 上へ1ピクセル
        lambda c: c.line(50, 60, 150, 60, 5),  # 右へ1ピクセル（囲みは x=149 まで）
        lambda c: c.text(52, 96, "A", 7),  # 下へ1ピクセル（囲みは y=99 まで）
    ],
)
def test_ui_check_reports_every_kind_of_command_that_leaves_its_box(draw):
    canvas = Canvas()
    with canvas.box("panel", 50, 60, 100, 40):
        draw(canvas)
    assert kinds(canvas) == ["out_of_box"]


@pytest.mark.parametrize("text", ["ティック 120", "TICK\t120", "A\x7fB", "CAFÉ", "A\rB", "\x1f"])
def test_ui_check_reports_characters_the_font_does_not_draw(text):
    canvas = Canvas()
    canvas.text(4, 20, text, 7)
    assert kinds(canvas) == ["bad_char"]


def test_ui_check_reports_two_texts_that_overlap():
    canvas = Canvas()
    canvas.text(4, 20, "TICK 120", 7)
    canvas.text(30, 22, "RENDER 60", 7)
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["text_overlap"]
    assert "TICK 120" in found[0].text and "RENDER 60" in found[0].text


def test_ui_check_each_violation_has_a_kind_and_a_readable_text():
    canvas = Canvas()
    canvas.rect(0, 0, 10, 10, 1)
    canvas.text(300, 100, "TOO FAR RIGHT", 7)
    (violation,) = find_violations(canvas)
    assert isinstance(violation, Violation) and violation.kind in KINDS
    # どの命令か（番号、種類、文字）、位置と大きさ。
    assert "#1" in violation.text and "text" in violation.text and "'TOO FAR RIGHT'" in violation.text
    assert "(300,100)" in violation.text and "51x5" in violation.text and "320x240" in violation.text


# --- 端にちょうど接するのは、内 ---
def test_ui_check_rectangles_that_touch_the_screen_edge_are_inside():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 240, 1)  # 画面いっぱい
    canvas.rectb(0, 0, 320, 240, 5)
    canvas.line(0, 0, 319, 239, 5)  # 隅から隅
    canvas.text(313, 235, "AB", 7)  # 幅7、高さ5。右下の隅にちょうど接する
    canvas.text(0, 0, "AB", 7)
    assert find_violations(canvas) == []


def test_ui_check_one_pixel_past_the_edge_is_outside():
    canvas = Canvas()
    canvas.text(314, 100, "AB", 7)
    assert kinds(canvas) == ["off_screen"]
    canvas = Canvas()
    canvas.rect(0, 0, 321, 240, 1)
    assert kinds(canvas) == ["off_screen"]


def test_ui_check_a_command_that_fills_its_box_exactly_is_inside():
    canvas = Canvas()
    with canvas.box("panel", 50, 60, 100, 40):
        canvas.rect(50, 60, 100, 40, 1)
        canvas.rectb(50, 60, 100, 40, 5)
        canvas.line(50, 60, 149, 99, 5)
        canvas.text(143, 95, "AB", 7)  # 囲みの右下の隅にちょうど接する
    assert find_violations(canvas) == []


def test_ui_check_texts_side_by_side_do_not_overlap():
    canvas = Canvas()
    canvas.text(4, 20, "AB", 7)  # x=4〜10、y=20〜24
    canvas.text(11, 20, "CD", 7)  # すぐ右
    canvas.text(4, 25, "EF", 7)  # すぐ下
    assert find_violations(canvas) == []
    canvas = Canvas()
    canvas.text(4, 20, "AB", 7)
    canvas.text(10, 24, "G", 7)  # 1画素（10, 24）だけ、上の文字の矩形に掛かる
    assert kinds(canvas) == ["text_overlap"]


def test_ui_check_descender_row_counts_for_the_overlap():
    # g j p q y は6行目を使う。すぐ下の行（y+5）に文字を置くと、重なる。
    canvas = Canvas()
    canvas.text(4, 20, "gy", 7)
    canvas.text(4, 25, "AB", 7)
    assert kinds(canvas) == ["text_overlap"]


# --- 数えないもの ---
def test_ui_check_text_on_a_filled_rectangle_is_not_an_overlap():
    canvas = Canvas()
    canvas.rect(0, 0, 320, 12, 1)
    canvas.rect(0, 0, 100, 12, 2)  # 矩形どうし
    canvas.rectb(0, 0, 320, 12, 5)
    canvas.line(0, 5, 319, 5, 5)
    canvas.text(4, 3, "CLIPPING POINT", 7)  # 下地の上の文字
    assert find_violations(canvas) == []


def test_ui_check_printable_ascii_and_newline_are_drawable():
    every = "".join(chr(code) for code in range(32, 127))
    assert is_drawable(every) and is_drawable("AB\nCD") and is_drawable("")
    assert not is_drawable(chr(31)) and not is_drawable(chr(127)) and not is_drawable("\t")
    canvas = Canvas(w=400, h=20)
    canvas.text(0, 0, every, 7)  # 95字。幅379
    canvas.text(0, 7, "AB\nCD", 7)
    assert find_violations(canvas) == []


def test_ui_check_uses_the_size_of_the_canvas_it_was_given():
    canvas = Canvas(w=100, h=50)
    canvas.rect(0, 0, 100, 50, 1)
    assert find_violations(canvas) == []
    canvas.rect(0, 0, 101, 50, 1)
    (violation,) = find_violations(canvas)
    assert violation.kind == "off_screen" and "100x50" in violation.text


# --- 空の矩形は、ほかの判定をしない ---
def test_ui_check_an_empty_command_gets_no_other_judgement():
    canvas = Canvas()
    with canvas.box("panel", 50, 60, 100, 40):
        canvas.rect(-20, -20, 0, 5, 1)  # 画面の外で、囲みの外でもある
    canvas.text(4, 20, "TICK 120", 7)
    canvas.text(6, 22, "", 7)  # 上の文字の矩形の中にある、空の文字列
    assert kinds(canvas) == ["empty", "empty"]


# --- 2種類が同時に出る ---
def test_ui_check_reports_both_kinds_when_a_text_leaves_its_box_and_the_screen():
    canvas = Canvas()
    with canvas.box("title", 0, 0, 320, 12):
        canvas.text(300, 3, "CLIPPING POINT", 7)
    assert kinds(canvas) == ["off_screen", "out_of_box"]


def test_ui_check_reports_bad_characters_beside_the_placement():
    canvas = Canvas()
    canvas.text(310, 20, "ティック", 7)
    assert kinds(canvas) == ["off_screen", "bad_char"]


def test_ui_check_text_overlap_does_not_ask_about_boxes():
    canvas = Canvas()
    with canvas.box("left", 0, 20, 60, 10):
        canvas.text(4, 22, "TICK 120", 7)
    with canvas.box("right", 30, 20, 60, 10):  # 囲みどうしが重なるのは、数えない
        canvas.text(32, 22, "RENDER", 7)
    assert kinds(canvas) == ["text_overlap"]


# --- 囲みにも当てる。入れ子 ---
def test_ui_check_a_box_inside_its_parent_is_clean():
    canvas = Canvas()
    with canvas.box("panel", 10, 10, 200, 100):
        with canvas.box("row", 10, 10, 200, 20):  # 親の端にちょうど接する
            canvas.text(12, 12, "ROW", 7)
            with canvas.box("cell", 100, 12, 110, 18):  # 親（row）の右下の隅にちょうど接する
                canvas.text(102, 14, "CELL", 7)
    assert find_violations(canvas) == []


def test_ui_check_reports_a_box_that_leaves_its_parent():
    canvas = Canvas()
    with canvas.box("panel", 10, 10, 200, 100):
        with canvas.box("row", 12, 100, 190, 14):  # 下へ4ピクセル出る
            canvas.text(14, 102, "ROW", 7)
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["out_of_box"]
    # 出ているのは囲み。中の文字は、自分の囲み（row）の内に収まっている。
    assert "box #1 'row'" in found[0].text and "'panel'" in found[0].text


def test_ui_check_a_command_is_judged_against_its_own_box_not_the_grandparent():
    canvas = Canvas()
    with canvas.box("panel", 10, 10, 200, 100):
        with canvas.box("row", 12, 12, 100, 10):
            canvas.text(60, 14, "LONG TEXT IN A ROW", 7)  # row は出るが、panel の内
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["out_of_box"]
    assert "leaves box #1 'row'" in found[0].text


def test_ui_check_reports_a_box_that_leaves_the_screen_or_has_no_area():
    canvas = Canvas()
    with canvas.box("wide", 0, 0, 321, 10):
        pass
    with canvas.box("flat", 0, 20, 100, 0):
        pass
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["off_screen", "empty"]
    assert "'wide'" in found[0].text and "'flat'" in found[1].text


# --- 開かれなかった囲み ---
def test_ui_check_reports_a_box_that_was_declared_without_with():
    canvas = Canvas()
    canvas.box("status", 2, 18, 64, 18)  # `with` の付け忘れ
    canvas.text(4, 20, "TICK 120", 7)
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["box_not_entered"]
    assert "box #0 'status'" in found[0].text and "(2,18) 64x18" in found[0].text and "with" in found[0].text


def test_ui_check_a_forgotten_with_no_longer_hides_a_text_that_leaves_the_box():
    # 囲みより長い文字。`with` があれば、囲みの外（out_of_box）で数える。
    canvas = Canvas()
    with canvas.box("status", 2, 18, 64, 18):
        canvas.text(4, 20, "TICKS SINCE START 9999999", 7)
    assert kinds(canvas) == ["out_of_box"]
    # `with` を付け忘れると、文字は囲みに入らず、囲みの外へ出たことは数えられない。開かれなかった囲みとして数える（0件にしない）。
    canvas = Canvas()
    canvas.box("status", 2, 18, 64, 18)
    canvas.text(4, 20, "TICKS SINCE START 9999999", 7)
    assert kinds(canvas) == ["box_not_entered"]


def test_ui_check_a_box_entered_with_nothing_drawn_in_it_is_clean():
    # 中身が0行の一覧など。入ったが、何も描かなかった囲みは、数えない。
    canvas = Canvas()
    with canvas.box("list", 10, 10, 200, 100):
        for row in ():
            canvas.text(12, 12, row, 7)
    with canvas.box("panel", 10, 120, 200, 100):
        with canvas.box("inner", 12, 122, 100, 10):
            pass
    assert find_violations(canvas) == []


def test_ui_check_a_box_declared_first_and_entered_later_is_clean():
    canvas = Canvas()
    panel = canvas.box("panel", 10, 10, 200, 100)
    assert kinds(canvas) == ["box_not_entered"]  # まだ入っていない
    with panel:
        canvas.text(12, 12, "PANEL", 7)
    assert find_violations(canvas) == []


def test_ui_check_reports_a_nested_box_that_was_not_entered():
    canvas = Canvas()
    with canvas.box("panel", 10, 10, 200, 100):
        canvas.box("row", 12, 12, 100, 10)  # 入れ子の中の付け忘れ
        canvas.text(14, 14, "ROW", 7)
    found = find_violations(canvas)
    assert [violation.kind for violation in found] == ["box_not_entered"]
    assert "'row'" in found[0].text
    assert canvas.commands[0].box == 0  # 文字は、外側の囲み（panel）に入っている


def test_ui_check_a_box_that_was_not_entered_is_still_judged_for_its_placement():
    canvas = Canvas()
    canvas.box("wide", 0, 0, 321, 10)
    canvas.box("flat", 0, 20, 100, 0)
    assert kinds(canvas) == ["off_screen", "box_not_entered", "empty", "box_not_entered"]


def test_ui_check_boxes_come_before_commands_and_overlaps_last():
    canvas = Canvas()
    canvas.text(300, 20, "TOO FAR RIGHT", 7)
    canvas.text(302, 22, "X", 7)
    with canvas.box("wide", 0, 0, 321, 10):
        pass
    assert kinds(canvas) == ["off_screen", "off_screen", "text_overlap"]
    assert "box #0" in find_violations(canvas)[0].text
