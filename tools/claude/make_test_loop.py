"""仮の周回路（clipping_point/data/tracks/test_loop.json）の制御点を、式から作る。作業用のスクリプト。

  python3 tools/claude/make_test_loop.py           制御点を、定義データに書く形（1行に1点）で出す
  python3 tools/claude/make_test_loop.py --check   定義データの制御点と照らす。0＝同じ、1＝違う、2＝定義データが読めない

形は、直線2本と、緩和区間つきの半円2つ（左回り）。寸法は、下の定数（定義データの _notes にも、同じ値を書く）。
  直線 → 半円（入口の緩和区間、円弧、出口の緩和区間）→ 直線 → 半円。緩和区間は、曲率を、0から 1/半径 まで、距離に比例して変える。
  半円1つの長さは、半径×π＋緩和区間（緩和区間の中で向きが変わる分だけ、円弧が短くなる）。
制御点は、約10 m刻み。直線は等間隔、緩和区間は2つに割り、円弧は等間隔に割る。座標は、mm に丸める。
頭の点は、1本目の直線の始まり（原点。向きは +x）。末尾の点は、頭の点を繰り返さない。
定義データへは、出した行を、手で写す（このスクリプトは、ファイルを書かない）。寸法を変えたら、--check が1になる。
出荷するコードと、検証の道具は、このスクリプトを読まない。テスト（tests/test_track.py）が、定義データの制御点と照らす。
元は、設計時の試作（spikes/track/design_akane.py の、緩和区間つきの円弧）。
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import FAIL, INCOMPLETE, OK, ROOT, finish  # noqa: E402

LOOP_JSON = "clipping_point/data/tracks/test_loop.json"
STRAIGHT_M = 200.0  # 直線の長さ
RADIUS_M = 45.0  # 半円の半径
TRANSITION_M = 25.0  # 緩和区間の長さ（入口と出口のそれぞれ）
SPACING_M = 10.0  # 制御点の刻みの目安
INTEGRATE_STEP_M = 0.02  # 円弧の位置を積み上げる刻み
TURN_RAD = math.pi  # 半円1つで変わる向き（左回り）


def arc_length() -> float:
    """半円1つ（緩和区間つき）の長さ。"""
    return RADIUS_M * TURN_RAD + TRANSITION_M


def arc_heading(u: float) -> float:
    """半円の始まりから u（m）進んだ所の、向きの変化（rad）。"""
    length = arc_length()
    if u < TRANSITION_M:
        return u * u / (2.0 * TRANSITION_M * RADIUS_M)
    if u > length - TRANSITION_M:
        return TURN_RAD - (length - u) ** 2 / (2.0 * TRANSITION_M * RADIUS_M)
    return TRANSITION_M / (2.0 * RADIUS_M) + (u - TRANSITION_M) / RADIUS_M


def arc_offset(heading: float, u_end: float) -> tuple:
    """向き heading で始まる半円を、u_end（m）進んだ所までの、位置の変化 (dx, dz)。中点で積み上げる。"""
    count = max(1, int(math.ceil(u_end / INTEGRATE_STEP_M)))
    du = u_end / count
    x = z = 0.0
    for index in range(count):
        h = heading + arc_heading((index + 0.5) * du)
        x += du * math.cos(h)
        z += du * math.sin(h)
    return x, z


def straight_offsets() -> list:
    """直線の中の、制御点の位置（始まりからの距離）。終わりの点は、次の半円の頭なので、入れない。"""
    count = int(round(STRAIGHT_M / SPACING_M))
    return [STRAIGHT_M * index / count for index in range(count)]


def arc_offsets() -> list:
    """半円の中の、制御点の位置。緩和区間は2つに割り、円弧は等間隔に割る。終わりの点は、次の直線の頭なので、入れない。"""
    length = arc_length()
    circle = length - 2.0 * TRANSITION_M
    count = max(1, int(round(circle / SPACING_M)))
    return [0.0, 0.5 * TRANSITION_M, *(TRANSITION_M + circle * index / count for index in range(count + 1)), length - 0.5 * TRANSITION_M]


def control_points() -> tuple:
    """制御点 [{"x_m", "z_m"}] と、1周して戻った所のずれ（m と rad）、全長（m）。"""
    points = []
    x = z = heading = 0.0
    for _ in range(2):
        for offset in straight_offsets():
            points.append((x + offset * math.cos(heading), z + offset * math.sin(heading)))
        x += STRAIGHT_M * math.cos(heading)
        z += STRAIGHT_M * math.sin(heading)
        for offset in arc_offsets():
            dx, dz = arc_offset(heading, offset) if offset > 0.0 else (0.0, 0.0)
            points.append((x + dx, z + dz))
        dx, dz = arc_offset(heading, arc_length())
        x += dx
        z += dz
        heading += TURN_RAD
    rounded = [{"x_m": round(px, 3) + 0.0, "z_m": round(pz, 3) + 0.0} for px, pz in points]  # + 0.0 は、−0.0 を 0.0 にする
    return rounded, (math.hypot(x, z), heading - 2.0 * TURN_RAD), 2.0 * (STRAIGHT_M + arc_length())


def lines_of(points: list) -> list:
    """定義データに書く形。1行に1点。"""
    return [f'    {{"x_m": {point["x_m"]}, "z_m": {point["z_m"]}}}' + ("," if index < len(points) - 1 else "") for index, point in enumerate(points)]


def main() -> int:
    ap = argparse.ArgumentParser(description="仮の周回路の制御点を、式から作る")
    ap.add_argument("--check", action="store_true", help="定義データの制御点と照らす")
    args = ap.parse_args()
    points, (gap_m, gap_rad), length = control_points()
    detail = f"points={len(points)} length_m={length:.2f} closing_gap_m={gap_m:.4f} closing_turn_rad={gap_rad:.6f}"
    if not args.check:
        print('  "control_points": [')
        print("\n".join(lines_of(points)))
        print("  ]")
        return finish("make_test_loop", OK, detail)
    try:
        recorded = json.loads((ROOT / LOOP_JSON).read_text(encoding="utf-8"))["control_points"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return finish("make_test_loop", INCOMPLETE, f"{detail} reason=cannot_read ({type(exc).__name__})")
    different = recorded != points
    if different:
        print(f"  make_test_loop: {LOOP_JSON} の制御点が、式から作った制御点と違う（{len(recorded)} 点と {len(points)} 点）")
    return finish("make_test_loop", FAIL if different else OK, f"{detail} same={'no' if different else 'yes'}")


if __name__ == "__main__":
    sys.exit(main())
