"""車の仮の形（純Python）。車の定義データの寸法から、箱の頂点と三角形と色の役割を作る。決まりは docs/design/overview.md の「描画」。

ここで作る形は、全部、模型の座標（鼻先が +X、右が +Z、上が +Y、原点は接地中心。右手系）。ロジックの座標ではない。
Pyxelの3Dへは、そのまま渡す（z の反転も、頂点の順の入れ替えも、しない。車の根のノードの変換の下に置く）。
ロジックの座標と同じ扱いにすると、車だけが、鏡写しになる。面の向きの決まりは cp_core/mesh.py（(b−a)×(c−a) が外向き）。
  車体（body）   箱。前後は ±半長、左右は ±半幅、下は最低地上高、上は車体の箱の上面の高さ
  屋根（roof）   箱。車体の箱の上に載る。前後は roof_rear_m〜roof_front_m、左右は、半幅から roof_inset_m だけ絞る。上は全高
  車輪（wheel）  箱1つ（中心が原点。前後と上下は、タイヤの直径、左右は、タイヤの幅）と、4輪の中心の位置。
                 前軸は、重心から前へ（ホイールベース×(1−前軸の重量配分)）、後軸は、後ろへ。左右は ∓トレッド÷2。高さは、タイヤの半径
車輪は、車体の箱の子にしない（車の根の下に置く。ピッチとロールで、車輪が浮かないため）。
寸法は、車の項目の body（半長、半幅、ホイールベース、トレッド、前軸の重量配分）、drivetrain（タイヤの半径）、shape（仮の形の寸法）。
寸法の矛盾の検査（shape_problems）は、読み込み検査（cp_core/datadefs.py）が呼ぶ。ここからは datadefs を読み込まない。
判定用の印（mark_parts）は、検証の口があるときにだけ使う、左右と前後の向きの目印。模型の座標で、車の根の下に置く。
入れていないもの（段1の「走行画面」の区切り）：断面の表から作る車のモデル、面ごとの色の表、車の影、灯火。
"""
from dataclasses import dataclass

from cp_core import mesh
from cp_core.vehicle import WHEELS

BODY, ROOF, WHEEL = "body", "roof", "wheel"  # 部品の名
# 部品の、色の役割の名（cp_core/palette.py の ROLES）。車ごとの色の表は、段1。
PART_ROLES = {BODY: "red", ROOF: "glass", WHEEL: "tire"}
# 判定用の印（左右と前後の向きの目印）。調整する値ではなく、検証の決め（道具の判定の余裕 tools/budgets.json と、対で決める）。
MARK_RIGHT, MARK_NOSE = "mark_right", "mark_nose"  # 印の名（部品の名。結果の鍵にも使う）
MARK_CENTERS = {MARK_RIGHT: (0.0, 1.0, 1.5), MARK_NOSE: (3.0, 1.0, 0.0)}  # 印の中心（模型の座標。m）。右の印は +Z、鼻先の印は +X
MARK_ROLES = {MARK_RIGHT: "yellow", MARK_NOSE: "pink"}  # 印の、色の役割の名。柱（cp_core/camera.py の PILLAR_ROLES）とも、違う色
MARK_SIZE_M = 0.5  # 印の板の、幅と高さ（m）


@dataclass(frozen=True, slots=True)
class CarShape:
    """車の仮の形。模型の座標。書き換えられない。"""

    car_id: str  # 車の id
    body: tuple  # 車体の部品（車体の箱、屋根の箱）。cp_core.mesh の MeshPart。車体のノード（ピッチとロール）に置く
    wheel: mesh.MeshPart  # 車輪1つの形（中心が原点）。4輪で共有する
    wheel_centers: tuple  # 4輪の中心 ((x, y, z), …)。模型の座標。並びは cp_core.vehicle の WHEELS（前左、前右、後左、後右）

    @property
    def triangle_count(self) -> int:
        return sum(part.triangle_count for part in self.body) + len(self.wheel_centers) * self.wheel.triangle_count


def shape_problems(entry: dict) -> list:
    """車の仮の形の、寸法の矛盾の検査。読み込み検査が、鍵ごとの規則を全部通った項目にだけ呼ぶ。返すのは [(鍵の道, 問題の文)]。

    - 車体の箱の上面が、最低地上高より高い。全高が、車体の箱の上面より高い（箱が、裏返らない）
    - 屋根の箱の前の端が、後ろの端より前。どちらも、車体の半長の内
    - 屋根の横の絞りが、車体の半幅より小さい
    """
    body, shape = entry["body"], entry["shape"]
    half_length, half_width = body["half_length_m"], body["half_width_m"]
    problems = []
    if not shape["body_top_m"] > shape["ground_clearance_m"]:
        problems.append((("shape", "body_top_m"), f"{shape['body_top_m']} is not above the ground clearance ({shape['ground_clearance_m']})"))
    if not shape["height_m"] > shape["body_top_m"]:
        problems.append((("shape", "height_m"), f"{shape['height_m']} is not above the top of the body box ({shape['body_top_m']})"))
    if not shape["roof_front_m"] > shape["roof_rear_m"]:
        problems.append((("shape", "roof_front_m"), f"{shape['roof_front_m']} is not ahead of the rear end of the roof ({shape['roof_rear_m']})"))
    if shape["roof_front_m"] > half_length:
        problems.append((("shape", "roof_front_m"), f"{shape['roof_front_m']} is ahead of the nose (half length {half_length})"))
    if shape["roof_rear_m"] < -half_length:
        problems.append((("shape", "roof_rear_m"), f"{shape['roof_rear_m']} is behind the tail (half length {half_length})"))
    if not shape["roof_inset_m"] < half_width:
        problems.append((("shape", "roof_inset_m"), f"{shape['roof_inset_m']} leaves no roof (half width {half_width})"))
    return problems


def _box_part(name: str, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> mesh.MeshPart:
    vertices, triangles = mesh.box(x0, x1, y0, y1, z0, z1)
    return mesh.MeshPart(name, PART_ROLES[name], vertices, triangles)


def build_car_shape(entry: dict) -> CarShape:
    """定義データの車の項目（読み込み検査を通ったもの。GameData.entry("cars", id)）から、車の仮の形を作る。模型の座標。"""
    body, shape = entry["body"], entry["shape"]
    half_length, half_width = float(body["half_length_m"]), float(body["half_width_m"])
    clearance, body_top, height = float(shape["ground_clearance_m"]), float(shape["body_top_m"]), float(shape["height_m"])
    roof_half = half_width - float(shape["roof_inset_m"])
    radius, tire_half = float(entry["drivetrain"]["wheel_radius_m"]), 0.5 * float(shape["tire_width_m"])
    # 車の位置は、重心（車両モデルの決め）。前軸は、重心から前へ、後軸は、後ろへ。
    front_x = float(body["wheelbase_m"]) * (1.0 - float(body["front_weight"]))
    rear_x = front_x - float(body["wheelbase_m"])
    half_track = 0.5 * float(body["track_m"])
    centers = {
        "front_left": (front_x, radius, -half_track), "front_right": (front_x, radius, half_track),
        "rear_left": (rear_x, radius, -half_track), "rear_right": (rear_x, radius, half_track),
    }
    return CarShape(
        car_id=entry["id"],
        body=(
            _box_part(BODY, -half_length, half_length, clearance, body_top, -half_width, half_width),
            _box_part(ROOF, float(shape["roof_rear_m"]), float(shape["roof_front_m"]), body_top, height, -roof_half, roof_half),
        ),
        wheel=_box_part(WHEEL, -radius, radius, -radius, radius, -tire_half, tire_half),
        wheel_centers=tuple(centers[name] for name in WHEELS),
    )


def mark_parts() -> tuple:
    """判定用の印の形。返すのは (右の印, 鼻先の印)。どちらも、片面の板（cp_core.mesh の MeshPart）。模型の座標。

    板の表は、車の後ろの側（カメラの側）を向く：(b−a)×(c−a) が (−1, 0, 0)。模型の座標の形なので、Pyxelの3Dへは、そのまま渡し、
    車の根のノードの変換の下に置く（反転も、頂点の順の入れ替えも、しない）。
    """
    parts = []
    for name in (MARK_RIGHT, MARK_NOSE):
        vertices, triangles = mesh.board(MARK_CENTERS[name], (-1.0, 0.0), MARK_SIZE_M, MARK_SIZE_M)
        parts.append(mesh.MeshPart(name, MARK_ROLES[name], vertices, triangles))
    return tuple(parts)
