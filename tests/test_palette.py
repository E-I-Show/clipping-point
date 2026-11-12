"""色の役割（cp_core.palette）と、実物のパレット（clipping_point/data/palettes.json）のテスト。pyxel は読み込まない。

番号の役割は、設計の「描画」の表のとおり（32個）。パレットは、実物の定義データを、アプリと同じ読み方で読んで作る。
色の取り違え（空の並びが逆、明るい色と暗い色が逆、灯火の番号が違う）を、明るさの順で拾う。
実物の色は、作業の補助（tools/claude/make_palette.py）が作った値と同じ（手で書き換えない）。
"""
import dataclasses
import functools
import sys

import pytest

from conftest import ROOT
from cp_app import data_files
from cp_core import palette
from cp_core.palette import Palette

# 設計の表の、番号と役割。
DESIGN = {
    0: "black", 1: "navy", 2: "asphalt_dark", 3: "asphalt_mid", 4: "asphalt_light", 5: "white",
    6: "grass_dark", 7: "grass_mid", 8: "grass_light", 9: "sand_dark", 10: "sand_light",
    11: "red_dark", 12: "red", 13: "orange", 14: "yellow", 15: "cream",
    16: "sky_0", 17: "sky_1", 18: "sky_2", 19: "sky_3", 20: "mountain_dark", 21: "mountain_light",
    22: "blue_dark", 23: "blue", 24: "blue_light", 25: "glass",
    26: "trunk", 27: "leaf_dark", 28: "silver", 29: "tire", 30: "brake_lamp", 31: "pink",
}


@functools.cache
def evening() -> Palette:
    return palette.palette_from_entry(data_files.load({}, None).entry("palettes", palette.EVENING))


def brightness(color: int) -> float:
    """色（0xRRGGBB）の、明るさ（輝度の近似）。"""
    return 0.299 * ((color >> 16) & 255) + 0.587 * ((color >> 8) & 255) + 0.114 * (color & 255)


def bright(role: str) -> float:
    return brightness(evening().colors[palette.number(role)])


# --- 役割の名 ---
def test_palette_has_32_roles_with_the_numbers_of_the_design_table():
    assert palette.COLOR_COUNT == 32 and len(palette.ROLES) == 32 and len(set(palette.ROLES)) == 32
    assert dict(enumerate(palette.ROLES)) == DESIGN
    assert all(type(name) is str and name == name.lower() and name.replace("_", "").isalnum() for name in palette.ROLES)


def test_palette_constants_are_the_numbers_0_to_31_once_each():
    numbers = {name: getattr(palette, name.upper()) for name in palette.ROLES}
    assert sorted(numbers.values()) == list(range(32)) and all(type(value) is int for value in numbers.values())
    assert all(palette.ROLES[value] == name for name, value in numbers.items())  # 定数の名と、役割の名が、同じ番号
    assert (palette.BLACK, palette.WHITE, palette.CREAM, palette.SKY_0, palette.TIRE, palette.BRAKE_LAMP, palette.PINK) == (0, 5, 15, 16, 29, 30, 31)


def test_palette_number_looks_a_role_up_by_its_name():
    assert [palette.number(name) for name in palette.ROLES] == list(range(32))
    assert palette.number("asphalt_mid") == palette.ASPHALT_MID == 3 and palette.number("grass_mid") == palette.GRASS_MID == 7
    for strange in ("gray", "ASPHALT_MID", "", "sky", None, 3, True):
        with pytest.raises(KeyError):  # 知らない名で、黙って、別の色にしない
            palette.number(strange)


def test_palette_groups_name_the_sky_the_mountains_and_the_far_ground():
    assert palette.SKY == (16, 17, 18, 19) and palette.MOUNTAINS == (21, 20)  # 空は、上から下へ。山は、遠い尾根、近い尾根
    assert palette.FAR_GROUND == palette.GRASS_DARK == 6
    assert palette.COLOR_MAX == 0xFFFFFF == 16777215 and palette.EVENING == "evening"


# --- 実物のパレット ---
def test_palette_evening_has_32_colours_in_range_and_all_different():
    colors = evening().colors
    assert type(evening()) is Palette and evening().palette_id == "evening"
    assert type(colors) is tuple and len(colors) == 32 and all(type(color) is int and 0 <= color <= 0xFFFFFF for color in colors)
    assert len(set(colors)) == 32  # 同じ色が2つあると、絵の上で、役割を見分けられない
    with pytest.raises(dataclasses.FrozenInstanceError):
        evening().colors = ()


def test_palette_evening_sky_gets_brighter_from_the_top_down_to_the_horizon():
    sky = [brightness(evening().colors[index]) for index in palette.SKY]
    assert sky == sorted(sky) and len(set(sky)) == 4  # 上（暗い紫）から、下（明るい橙）へ
    assert sky[-1] - sky[0] > 100.0
    far, near = (brightness(evening().colors[index]) for index in palette.MOUNTAINS)
    assert near < far < sky[1]  # 山は、近い尾根ほど暗い。どちらも、空の下のほうより暗い


def test_palette_evening_shades_run_from_dark_to_light():
    # 主要な色は、1段暗い兄弟色を持つ（陰影が、影の色に選ぶ）。名のとおりの、明るさの順。
    for names in (
        ("asphalt_dark", "asphalt_mid", "asphalt_light"), ("grass_dark", "grass_mid", "grass_light"), ("sand_dark", "sand_light"),
        ("red_dark", "red"), ("blue_dark", "blue", "blue_light"), ("mountain_dark", "mountain_light"), ("leaf_dark", "grass_mid"),
        ("tire", "asphalt_mid", "silver", "white"), ("black", "navy", "asphalt_dark"),
    ):
        values = [bright(name) for name in names]
        assert values == sorted(values) and len(set(values)) == len(values), names
    assert min(palette.ROLES, key=bright) == "black" and max(palette.ROLES, key=bright) == "white"


def test_palette_evening_hues_are_not_swapped():
    def channels(role: str) -> tuple:
        color = evening().colors[palette.number(role)]
        return (color >> 16) & 255, (color >> 8) & 255, color & 255

    for role in ("red_dark", "red", "orange", "brake_lamp", "pink"):
        r, g, b = channels(role)
        assert r > g and r > b, role  # 赤が、いちばん強い
    for role in ("grass_dark", "grass_mid", "grass_light", "leaf_dark"):
        r, g, b = channels(role)
        assert g > r and g > b, role  # 緑が、いちばん強い
    for role in ("blue_dark", "blue", "blue_light", "navy"):
        r, g, b = channels(role)
        assert b > r and b > g, role  # 青が、いちばん強い
    r, g, b = channels("yellow")
    assert r > g > b and g > 150
    assert evening().colors[palette.BRAKE_LAMP] == 0xFF4050  # ブレーキランプは、夕方の式を掛けない（そのままの色）


def test_palette_evening_does_not_shade_the_lamps():
    assert evening().unshaded == (palette.CREAM, palette.BRAKE_LAMP) == (15, 30)  # ヘッドライトと、ブレーキランプ
    assert all(type(index) is int and 0 <= index < 32 for index in evening().unshaded)


def test_palette_is_built_from_an_entry_as_tuples():
    made = palette.palette_from_entry({"id": "noon", "colors": list(range(32)), "unshaded": [30]})
    assert made == Palette("noon", tuple(range(32)), (30,)) and type(made.colors) is tuple and type(made.unshaded) is tuple


# --- 夕方の色を、試作の昼の32色から作る補助（tools/claude/make_palette.py） ---
def test_palette_evening_colours_are_the_ones_the_helper_makes():
    # 定義データの色は、手で書かない。昼の32色に、夕方の式を掛け、空と山を差し替えた色と、同じ。
    sys.path.append(str(ROOT / "tools" / "claude"))
    import make_palette

    colors = make_palette.evening_colors()
    assert tuple(colors) == evening().colors and tuple(make_palette.UNSHADED) == evening().unshaded
    assert len(make_palette.BASE_NOON) == 32 and make_palette.PALETTE_ID == palette.EVENING
    # 式：赤×0.98＋6、緑×0.87＋3、青×0.78＋10。昼の白（F0F0E8）は、夕方に、赤みの白（F1D4BF）になる。
    assert make_palette.tint(0xF0F0E8) == 0xF1D4BF == colors[palette.WHITE]
    assert make_palette.tint(0x000000) == 0x06030A and make_palette.tint(0xFFFFFF) == 0xFFE1D1  # 0〜255 に収める
    # 空の4色と、山の2色は、式を通さずに、差し替える。ブレーキランプは、昼の色のまま。
    assert [colors[index] for index in palette.SKY] == list(make_palette.SKY_EVENING) == [0x3A2A68, 0x8A3A78, 0xE06A48, 0xF8C060]
    assert (colors[palette.MOUNTAIN_DARK], colors[palette.MOUNTAIN_LIGHT]) == (0x2A2044, 0x503060)
    assert colors[palette.BRAKE_LAMP] == make_palette.BASE_NOON[palette.BRAKE_LAMP]
    changed = [index for index in range(32) if colors[index] != make_palette.BASE_NOON[index]]
    assert changed == [index for index in range(32) if index != palette.BRAKE_LAMP]  # ほかの色は、全部、昼と違う
    # 定義データに書く形。1行に8色、4行。
    lines = make_palette.lines_of(colors)
    assert len(lines) == 4 and lines[0] == "        1446173, 2170678, 4143169, 5853268, 8286319, 15848639, 3428651, 5206579,"
    assert lines[-1].endswith("14836871") and all(line.startswith("        ") for line in lines)
    text = (ROOT / make_palette.PALETTES_JSON).read_text(encoding="utf-8")
    assert all(line in text for line in lines)  # 実物のファイルも、この行の形
