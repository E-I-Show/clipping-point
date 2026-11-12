"""色の役割（純Python）。パレットの32個の番号に決めた、使い道の名。決まりは docs/design/overview.md の「描画」の表。

2Dの画面（cp_ui）も、3D（cp_app/render.py）も、色の番号を、ここの名で引く（番号を、直に書かない）。
時間帯は「番号の役割は同じで、色だけが違う」パレット。色は、定義データの表 palettes の項目に持つ（palettes.json）。
  colors    32色。0xRRGGBB の整数（0〜16,777,215）。並びは、ここの ROLES の順
  unshaded  陰影で暗くしない色の番号の並び（灯火の色）。陰影の表を作り直した後に、この番号の行を、全部の段で元の色にする
パレットを当てる所（パレットの差し替え、陰影の表の作り直し、灯火の手直し）は cp_app/render.py の1つの関数。ここは、Pyxelに触れない。
実物の色（夕方）は、作業の補助（tools/claude/make_palette.py）が、試作の昼の32色から作った値。
"""
from dataclasses import dataclass

# 役割の名。並びが、色の番号（0〜31）。設計の表：0〜1 黒、紺／2〜4 アスファルト3階調／5 白／6〜8 芝3階調／9〜10 砂2階調／
# 11〜15 赤2階調、橙、黄、クリーム（ヘッドライト）／16〜21 空4階調、山2階調／22〜25 青3階調、ガラス／
# 26〜31 幹、濃緑、銀、タイヤ、ブレーキランプ、桃。
ROLES = (
    "black", "navy",
    "asphalt_dark", "asphalt_mid", "asphalt_light",
    "white",
    "grass_dark", "grass_mid", "grass_light",
    "sand_dark", "sand_light",
    "red_dark", "red", "orange", "yellow", "cream",
    "sky_0", "sky_1", "sky_2", "sky_3", "mountain_dark", "mountain_light",
    "blue_dark", "blue", "blue_light", "glass",
    "trunk", "leaf_dark", "silver", "tire", "brake_lamp", "pink",
)
COLOR_COUNT = 32  # パレットの色の数
COLOR_MAX = 0xFFFFFF  # 色の値の上限（0xRRGGBB）
(
    BLACK, NAVY,
    ASPHALT_DARK, ASPHALT_MID, ASPHALT_LIGHT,
    WHITE,
    GRASS_DARK, GRASS_MID, GRASS_LIGHT,
    SAND_DARK, SAND_LIGHT,
    RED_DARK, RED, ORANGE, YELLOW, CREAM,
    SKY_0, SKY_1, SKY_2, SKY_3, MOUNTAIN_DARK, MOUNTAIN_LIGHT,
    BLUE_DARK, BLUE, BLUE_LIGHT, GLASS,
    TRUNK, LEAF_DARK, SILVER, TIRE, BRAKE_LAMP, PINK,
) = range(COLOR_COUNT)
SKY = (SKY_0, SKY_1, SKY_2, SKY_3)  # 空の4色。上（天頂の側）から、下（地平線の側）へ
MOUNTAINS = (MOUNTAIN_LIGHT, MOUNTAIN_DARK)  # 山並みの2色。遠い尾根、近い尾根の順
FAR_GROUND = GRASS_DARK  # 遠い地面の色（背景の、地平線より下。コースの外の地面の板）
# 割り切り：パレットは、いつも、この id（夕方の1本だけ）。時間帯を選ぶ所が、まだ無い。
# 時間帯を足す段（コースの描画を作る段1より後）で、選んだ id を渡す形に見直す。
EVENING = "evening"  # 表 palettes の、使う項目の id


def number(role: str) -> int:
    """役割の名から、色の番号（0〜31）を引く。知らない名は KeyError（黙って、別の色にしない）。"""
    if type(role) is not str or role not in ROLES:
        raise KeyError(role)
    return ROLES.index(role)


@dataclass(frozen=True, slots=True)
class Palette:
    """パレット1本。定義データの表 palettes の項目から作る（palette_from_entry）。書き換えられない。"""

    palette_id: str  # パレットの id
    colors: tuple  # 32色。0xRRGGBB の整数。並びは ROLES の順
    unshaded: tuple  # 陰影で暗くしない色の番号（灯火の色）


def palette_from_entry(entry: dict) -> Palette:
    """定義データの表 palettes の項目（読み込み検査を通ったもの。GameData.entry("palettes", id)）から、パレットを作る。"""
    return Palette(entry["id"], tuple(entry["colors"]), tuple(entry["unshaded"]))
