"""夕方のパレット（clipping_point/data/palettes.json の evening）の32色を、試作の昼の32色から作る。作業用のスクリプト。

  python3 tools/claude/make_palette.py           役割の名、番号、色の表と、定義データに書く形（colors と unshaded の行）を出す
  python3 tools/claude/make_palette.py --check   定義データのパレットと照らす。0＝同じ、1＝違う、2＝定義データが読めない

作り方は、描画の試作（spikes/render/common.py の make_palette）と同じ。
  昼の32色（BASE_NOON）に、夕方の式を掛ける：赤×0.98＋6、緑×0.87＋3、青×0.78＋10（0〜255 に丸める）。
  灯火の色のうち、ブレーキランプ（KEEP）は、式を掛けない（そのままの色）。
  空の4色（SKY_EVENING。上から下へ）と、山の2色（MOUNTAINS_EVENING。暗いほう、明るいほう）は、夕方の色に差し替える。
陰影で暗くしない色（UNSHADED）は、クリーム（ヘッドライト）と、ブレーキランプ（試作の fix_shading）。
番号の役割は、出荷するコード（clipping_point/cp_core/palette.py の ROLES）から読む（番号を、ここに書き写さない）。
定義データへは、出した行を、手で写す（このスクリプトは、ファイルを書かない）。式か、元の色を変えたら、--check が1になる。
出荷するコードと、検証の道具は、このスクリプトを読まない。テスト（tests/test_palette.py）が、定義データの色と照らす。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import APP, FAIL, INCOMPLETE, OK, ROOT, finish  # noqa: E402

if str(APP) not in sys.path:
    sys.path.append(str(APP))  # cp_core を読む。後ろに足す（標準ライブラリの名前を隠さないように）

from cp_core import palette  # noqa: E402 - pyxel を読み込まないモジュール

PALETTES_JSON = "clipping_point/data/palettes.json"
PALETTE_ID = palette.EVENING
# 試作の、昼の32色（0xRRGGBB）。並びは、色の役割の番号の順（cp_core/palette.py の ROLES）。
BASE_NOON = (
    0x101018, 0x1C2038, 0x3A3D46, 0x55585F, 0x7A7D82, 0xF0F0E8, 0x2F5A2A, 0x4A8034,
    0x74A848, 0x9A7A4A, 0xC8A870, 0x7A1C24, 0xD03030, 0xE87830, 0xF0C830, 0xF8ECA0,
    0x2A6AD0, 0x4A90E0, 0x80B8F0, 0xC0E0F8, 0x3C4868, 0x62709A, 0x1C3478, 0x3060C8,
    0x60B0E0, 0x24404C, 0x5A3C28, 0x1E4028, 0xB4B8C0, 0x26282E, 0xFF4050, 0xE070A0,
)
EVENING_SCALE = (0.98, 0.87, 0.78)  # 夕方の式。赤、緑、青に掛ける
EVENING_ADD = (6.0, 3.0, 10.0)  # 同じく、足す
SKY_EVENING = (0x3A2A68, 0x8A3A78, 0xE06A48, 0xF8C060)  # 空の4色。上（天頂の側）から、下（地平線の側）へ
MOUNTAINS_EVENING = {palette.MOUNTAIN_DARK: 0x2A2044, palette.MOUNTAIN_LIGHT: 0x503060}  # 山の2色
KEEP = (palette.BRAKE_LAMP,)  # 式を掛けない色（灯火）
UNSHADED = (palette.CREAM, palette.BRAKE_LAMP)  # 陰影で暗くしない色の番号
PER_LINE = 8  # 定義データに書くときの、1行の色の数


def tint(color: int) -> int:
    """昼の色1つに、夕方の式を掛ける。"""
    out = 0
    for shift, scale, add in zip((16, 8, 0), EVENING_SCALE, EVENING_ADD):
        channel = int(round(((color >> shift) & 255) * scale + add))
        out |= max(0, min(255, channel)) << shift
    return out


def evening_colors() -> list:
    """夕方の32色（0xRRGGBB の整数）。並びは、色の役割の番号の順。"""
    colors = [color if index in KEEP else tint(color) for index, color in enumerate(BASE_NOON)]
    for index, color in zip(palette.SKY, SKY_EVENING):
        colors[index] = color
    for index, color in MOUNTAINS_EVENING.items():
        colors[index] = color
    return colors


def lines_of(colors: list) -> list:
    """定義データに書く形。colors の中の行（1行に PER_LINE 色）。"""
    rows = [colors[start:start + PER_LINE] for start in range(0, len(colors), PER_LINE)]
    return ["        " + ", ".join(str(color) for color in row) + ("," if index < len(rows) - 1 else "") for index, row in enumerate(rows)]


def main() -> int:
    ap = argparse.ArgumentParser(description="夕方のパレットの32色を、試作の昼の32色から作る")
    ap.add_argument("--check", action="store_true", help="定義データのパレットと照らす")
    args = ap.parse_args()
    colors, unshaded = evening_colors(), list(UNSHADED)
    detail = f"palette={PALETTE_ID} colors={len(colors)} unshaded={len(unshaded)}"
    if len(colors) != palette.COLOR_COUNT or len(BASE_NOON) != len(palette.ROLES):
        return finish("make_palette", INCOMPLETE, f"{detail} reason=wrong_count")
    if not args.check:
        for index, (role, color) in enumerate(zip(palette.ROLES, colors)):
            print(f"  {index:2d} {role:15s} {color:06X}")
        print('      "colors": [')
        print("\n".join(lines_of(colors)))
        print("      ],")
        print(f'      "unshaded": {json.dumps(unshaded)}')
        return finish("make_palette", OK, detail)
    try:
        entries = json.loads((ROOT / PALETTES_JSON).read_text(encoding="utf-8"))["palettes"]
        recorded = next(entry for entry in entries if entry["id"] == PALETTE_ID)
        recorded_colors, recorded_unshaded = recorded["colors"], recorded["unshaded"]
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        return finish("make_palette", INCOMPLETE, f"{detail} reason=cannot_read ({type(exc).__name__})")
    different = recorded_colors != colors or recorded_unshaded != unshaded
    if recorded_colors != colors:
        where = [index for index in range(max(len(colors), len(recorded_colors))) if colors[index:index + 1] != recorded_colors[index:index + 1]]
        print(f"  make_palette: {PALETTES_JSON} の {PALETTE_ID} の色が、式から作った色と違う（番号 {where}）")
    if recorded_unshaded != unshaded:
        print(f"  make_palette: {PALETTES_JSON} の {PALETTE_ID} の unshaded が {recorded_unshaded}（{unshaded} のはず）")
    return finish("make_palette", FAIL if different else OK, f"{detail} same={'no' if different else 'yes'}")


if __name__ == "__main__":
    sys.exit(main())
