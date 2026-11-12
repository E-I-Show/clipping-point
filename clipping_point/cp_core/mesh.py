"""メッシュ用の数値の型と、面の向きの決まり（純Python）。決まりは docs/design/overview.md の「描画」。

3Dの形は、純Pythonの層で、数値（頂点、三角形、色の役割の名）として作る。Pyxelの3Dの物にするのは cp_app/render.py。
座標は、2つある。取り違えない（形を作る所の注に、どちらの座標かを書く）。
  ロジックの座標  コース（cp_core/track.py）、地面、カメラの目と注視点、車の位置、判定用の柱（cp_core/camera.py）。
                  平面が (x, z)、高さが y（上が正）。+z は、+x の左。向きが増えると、左旋回
  模型の座標      車の模型と、模型に付ける印（cp_core/car_shape.py）。鼻先が +X、右が +Z、上が +Y、原点は接地中心
面の向きの決まりは、どちらの座標でも同じ：頂点の3つ組 (x, y, z) を、そのままベクトルとして、(b−a)×(c−a) が外向き
（face_normal。外向きも、同じ座標の成分で言う。路面は (0, +, 0)、ロジックの座標で +z の側にある左の壁は (0, 0, −)）。
Pyxelの3Dへ渡すとき、ロジックの座標の形は、z の符号を反転し、頂点の順も入れ替える。模型の座標の形は、そのまま渡す
（反転も、入れ替えも、しない）。どちらも、書くのは cp_app/render.py の1つの関数。
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MeshPart:
    """形の部品1つ。書き換えられない。どちらの座標かは、作った所が決める（コースと柱はロジックの座標、車と印は模型の座標）。"""

    name: str  # 部品の名（road、body、pillar_left など）
    role: str  # 色の役割の名（cp_core/palette.py の ROLES のどれか）。部品の中は、1色
    vertices: tuple  # 頂点 ((x, y, z), …)。単位は m
    triangles: tuple  # 三角形 ((a, b, c), …)。頂点の番号の3つ組。(b−a)×(c−a) が外向き

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)


def face_normal(vertices, triangle) -> tuple:
    """三角形（頂点の番号の3つ組）の、(b−a)×(c−a)。頂点の3つ組を、そのままベクトルとして掛ける。長さは、そろえない（面積の2倍）。"""
    a, b, c = vertices[triangle[0]], vertices[triangle[1]], vertices[triangle[2]]
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx


def quad(a: int, b: int, c: int, d: int) -> tuple:
    """四角形（頂点の番号を、輪の順に4つ）を、三角形2つにする。面の向きは、(a, b, c) の向き。"""
    return (a, b, c), (a, c, d)


# 箱の面。頂点の番号（下の box() の並び）を、輪の順に4つ。どの面も、(b−a)×(c−a) が、箱の外を向く。並びは、+x、−x、+y、−y、+z、−z。
BOX_FACES = ((1, 2, 6, 5), (0, 4, 7, 3), (3, 7, 6, 2), (0, 1, 5, 4), (4, 5, 6, 7), (0, 3, 2, 1))


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> tuple:
    """軸に沿った箱。返すのは (頂点8つ, 三角形12)。どの三角形も、(b−a)×(c−a) が、箱の外を向く。

    x0 < x1、y0 < y1、z0 < z1 でなければ ValueError（裏返った箱は、面が全部、内を向く）。
    """
    if not (x0 < x1 and y0 < y1 and z0 < z1):
        raise ValueError(f"box needs x0 < x1, y0 < y1, z0 < z1 (got {x0}..{x1}, {y0}..{y1}, {z0}..{z1})")
    vertices = (
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    )
    triangles = tuple(triangle for face in BOX_FACES for triangle in quad(*face))
    return vertices, triangles


def board(center: tuple, facing: tuple, width: float, height: float) -> tuple:
    """立てた板（片面）。返すのは (頂点4つ, 三角形2つ)。(b−a)×(c−a) は、facing の向き。

    center は、板の中心 (x, y, z)。facing は、板の表が向く、水平な向き (fx, fz)（長さ1。center と同じ座標の成分で言う）。
    width は横の幅、height は高さ（m）。どちらの座標でも、同じ式で作れる（面の向きの決まりが、同じため）。
    """
    if not (width > 0.0 and height > 0.0):
        raise ValueError(f"board needs a positive width and height (got {width}, {height})")
    fx, fz = facing
    # 板の横の向き r は、r × (0, 1, 0) が facing になる向き：r = (fz, 0, −fx)。
    rx, rz = fz * 0.5 * width, -fx * 0.5 * width
    cx, cy, cz = center
    low, high = cy - 0.5 * height, cy + 0.5 * height
    vertices = ((cx - rx, low, cz - rz), (cx + rx, low, cz + rz), (cx + rx, high, cz + rz), (cx - rx, high, cz - rz))
    return vertices, quad(0, 1, 2, 3)
