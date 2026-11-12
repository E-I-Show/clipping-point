"""車の仮の形（cp_core.car_shape）のテスト。箱の頂点と三角形、寸法、面の向き、寸法の矛盾の検査、判定用の印。pyxel は読み込まない。

形は、全部、模型の座標（鼻先が +X、右が +Z、上が +Y、原点は接地中心）。ロジックの座標（+z が左）ではない。
車の項目は、実物の定義データ（clipping_point/data/cars.json の kazane）を、アプリと同じ読み方で読む。
面の向きの決まり（(b−a)×(c−a) が外向き）は cp_core/mesh.py。
"""
import dataclasses
import functools

import pytest

from cp_app import data_files
from cp_core import car_shape, palette
from cp_core.camera import PILLAR_ROLES
from cp_core.car_shape import CarShape, build_car_shape, mark_parts, shape_problems
from cp_core.mesh import MeshPart, face_normal
from cp_core.vehicle import WHEELS

HALF_LENGTH_M, HALF_WIDTH_M, WHEELBASE_M, TRACK_M, FRONT_WEIGHT, WHEEL_RADIUS_M = 2.1, 0.85, 2.27, 1.42, 0.51, 0.29  # 車の値（body と drivetrain）
HEIGHT_M, BODY_TOP_M, ROOF_FRONT_M, ROOF_REAR_M, ROOF_INSET_M, CLEARANCE_M, TIRE_WIDTH_M = 1.24, 0.78, 0.42, -1.0, 0.29, 0.17, 0.22  # 仮の形の寸法（shape）


def car_entry() -> dict:
    """実物の車の項目。引くたびに、新しい複製（テストの中で、書き換えてよい）。"""
    return data_files.load({}, None).entry("cars", "kazane")


@functools.cache
def shape() -> CarShape:
    return build_car_shape(car_entry())


def extent(vertices, axis: int) -> tuple:
    values = [vertex[axis] for vertex in vertices]
    return min(values), max(values)


def faces_outwards(vertices, triangles) -> bool:
    """どの三角形も、(b−a)×(c−a) が、形の真ん中から見て、外を向くか。"""
    middle = [sum(extent(vertices, axis)) / 2.0 for axis in range(3)]
    for triangle in triangles:
        normal = face_normal(vertices, triangle)
        centre = [sum(vertices[index][axis] for index in triangle) / 3.0 for axis in range(3)]
        if sum(normal[axis] * (centre[axis] - middle[axis]) for axis in range(3)) <= 0.0:
            return False
    return True


# --- 形 ---
def test_car_shape_of_the_shipped_car_has_a_body_a_roof_and_one_wheel_for_four_places():
    made = shape()
    assert type(made) is CarShape and made.car_id == "kazane"
    assert [part.name for part in made.body] == ["body", "roof"] and made.wheel.name == "wheel"
    assert all(type(part) is MeshPart for part in (*made.body, made.wheel))
    assert [part.role for part in made.body] == ["red", "glass"] and made.wheel.role == "tire"
    assert car_shape.PART_ROLES == {"body": "red", "roof": "glass", "wheel": "tire"}
    assert {part.role for part in (*made.body, made.wheel)} <= set(palette.ROLES)
    # 箱1つは、頂点8つ、三角形12。車体、屋根、車輪4つで、72三角形。
    assert all(len(part.vertices) == 8 and part.triangle_count == 12 for part in (*made.body, made.wheel))
    assert len(made.wheel_centers) == 4 and made.triangle_count == 12 + 12 + 4 * 12 == 72
    with pytest.raises(dataclasses.FrozenInstanceError):
        made.body = ()


def test_car_shape_every_box_faces_outwards():
    made = shape()
    for part in (*made.body, made.wheel):
        assert faces_outwards(part.vertices, part.triangles), part.name


def test_car_shape_body_box_has_the_nose_at_plus_x_and_the_sizes_of_the_car():
    body, roof = shape().body
    # 車体：前後は ±半長（鼻先が +X の端）、左右は ±半幅（右が +Z）、下は最低地上高、上は車体の箱の上面。
    assert extent(body.vertices, 0) == (-HALF_LENGTH_M, HALF_LENGTH_M)
    assert extent(body.vertices, 1) == (CLEARANCE_M, BODY_TOP_M)
    assert extent(body.vertices, 2) == (-HALF_WIDTH_M, HALF_WIDTH_M)
    # 屋根：車体の上に載る。上は全高。前後は、屋根の端。左右は、半幅から絞る。車体の箱から、はみ出さない。
    assert extent(roof.vertices, 0) == (ROOF_REAR_M, ROOF_FRONT_M)
    assert extent(roof.vertices, 1) == (BODY_TOP_M, HEIGHT_M)
    assert extent(roof.vertices, 2) == pytest.approx((-(HALF_WIDTH_M - ROOF_INSET_M), HALF_WIDTH_M - ROOF_INSET_M))
    assert -HALF_LENGTH_M < ROOF_REAR_M < ROOF_FRONT_M < HALF_LENGTH_M
    # 屋根は、車の真ん中より、後ろ寄り（鼻先の側が、長い）。前後を取り違えると、ここで分かる。
    assert HALF_LENGTH_M - ROOF_FRONT_M > ROOF_REAR_M + HALF_LENGTH_M


def test_car_shape_wheels_sit_at_the_wheelbase_and_the_track():
    made = shape()
    centers = dict(zip(WHEELS, made.wheel_centers))
    assert list(centers) == ["front_left", "front_right", "rear_left", "rear_right"]
    # 前軸と後軸の間は、ホイールベース。原点（車の位置＝重心）から、前軸までは、ホイールベース×(1−前軸の重量配分)。
    assert centers["front_left"][0] - centers["rear_left"][0] == pytest.approx(WHEELBASE_M)
    assert centers["front_left"][0] == pytest.approx(WHEELBASE_M * (1.0 - FRONT_WEIGHT)) and centers["front_left"][0] > 0.0 > centers["rear_left"][0]
    # 左右の間は、トレッド。右が +Z、左が −Z。高さは、タイヤの半径（地面に付く）。
    assert centers["front_right"][2] - centers["front_left"][2] == pytest.approx(TRACK_M)
    assert centers["front_left"][2] == pytest.approx(-TRACK_M / 2.0) and centers["rear_right"][2] == pytest.approx(TRACK_M / 2.0)
    assert all(center[1] == WHEEL_RADIUS_M for center in made.wheel_centers)
    # 車輪の形は、中心が原点の箱。前後と上下は、タイヤの直径、左右は、タイヤの幅。
    assert extent(made.wheel.vertices, 0) == (-WHEEL_RADIUS_M, WHEEL_RADIUS_M) and extent(made.wheel.vertices, 1) == (-WHEEL_RADIUS_M, WHEEL_RADIUS_M)
    assert extent(made.wheel.vertices, 2) == pytest.approx((-TIRE_WIDTH_M / 2.0, TIRE_WIDTH_M / 2.0))
    # 置いた車輪は、地面（y=0）に付き、車体の幅と長さの内。
    for x, y, z in made.wheel_centers:
        assert y - WHEEL_RADIUS_M == 0.0 and abs(z) + TIRE_WIDTH_M / 2.0 <= HALF_WIDTH_M and abs(x) + WHEEL_RADIUS_M <= HALF_LENGTH_M


def test_car_shape_is_the_same_on_the_left_and_on_the_right():
    made = shape()
    for part in (*made.body, made.wheel):
        mirrored = sorted((x, y, -z) for x, y, z in part.vertices)
        assert mirrored == sorted(part.vertices), part.name  # 左右を入れ替えても、同じ頂点
    front_left, front_right, rear_left, rear_right = made.wheel_centers
    assert (front_left[0], front_left[1], -front_left[2]) == front_right and (rear_left[0], rear_left[1], -rear_left[2]) == rear_right


def test_car_shape_is_the_same_for_the_same_entry_and_follows_the_sizes():
    assert build_car_shape(car_entry()) == shape()
    entry = car_entry()
    entry["shape"].update(height_m=1.5, roof_inset_m=0.1)
    entry["body"].update(half_length_m=2.3)
    entry["drivetrain"].update(wheel_radius_m=0.33)
    other = build_car_shape(entry)
    assert extent(other.body[0].vertices, 0) == (-2.3, 2.3) and extent(other.body[1].vertices, 1) == (BODY_TOP_M, 1.5)
    assert extent(other.body[1].vertices, 2) == pytest.approx((-0.75, 0.75))
    assert all(center[1] == 0.33 for center in other.wheel_centers) and extent(other.wheel.vertices, 1) == (-0.33, 0.33)


# --- 寸法の矛盾の検査 ---
def problems_with(**sizes) -> list:
    entry = car_entry()
    entry["shape"].update(sizes)
    return shape_problems(entry)


def test_car_shape_problems_are_none_for_the_shipped_entry():
    assert shape_problems(car_entry()) == []


def test_car_shape_check_finds_boxes_that_would_be_inside_out():
    assert problems_with(body_top_m=0.17) == [(("shape", "body_top_m"), "0.17 is not above the ground clearance (0.17)")]
    assert problems_with(ground_clearance_m=0.9) == [(("shape", "body_top_m"), "0.78 is not above the ground clearance (0.9)")]
    assert problems_with(height_m=0.78) == [(("shape", "height_m"), "0.78 is not above the top of the body box (0.78)")]
    assert problems_with(height_m=0.5) == [(("shape", "height_m"), "0.5 is not above the top of the body box (0.78)")]
    assert problems_with(roof_front_m=-1.0) == [(("shape", "roof_front_m"), "-1.0 is not ahead of the rear end of the roof (-1.0)")]
    assert problems_with(roof_inset_m=0.85) == [(("shape", "roof_inset_m"), "0.85 leaves no roof (half width 0.85)")]
    # 検査を通らない寸法は、箱を作る所でも、例外になる（黙って、裏返った箱を作らない）。
    entry = car_entry()
    entry["shape"].update(height_m=0.5)
    with pytest.raises(ValueError):
        build_car_shape(entry)


def test_car_shape_check_finds_a_roof_that_sticks_out_of_the_body():
    assert problems_with(roof_front_m=2.2) == [(("shape", "roof_front_m"), "2.2 is ahead of the nose (half length 2.1)")]
    assert problems_with(roof_rear_m=-2.2) == [(("shape", "roof_rear_m"), "-2.2 is behind the tail (half length 2.1)")]
    assert problems_with(roof_front_m=2.1, roof_rear_m=-2.1) == []  # 端ちょうどまでは、よい
    # 全部を並べる（最初の1件で止めない）。
    assert [path for path, _ in problems_with(body_top_m=0.1, height_m=0.05, roof_front_m=3.0, roof_rear_m=4.0, roof_inset_m=1.0)] == [
        ("shape", "body_top_m"), ("shape", "height_m"), ("shape", "roof_front_m"), ("shape", "roof_front_m"), ("shape", "roof_inset_m"),
    ]


def test_car_shape_problems_come_as_key_paths_and_texts():
    problems = problems_with(body_top_m=0.1, roof_inset_m=1.0)
    assert problems and all(type(path) is tuple and path[0] == "shape" and type(message) is str and message for path, message in problems)


# --- 判定用の印（模型の座標） ---
def test_car_shape_marks_sit_on_the_right_and_ahead_of_the_nose_in_model_coordinates():
    right, nose = mark_parts()
    assert [part.name for part in (right, nose)] == ["mark_right", "mark_nose"] == [car_shape.MARK_RIGHT, car_shape.MARK_NOSE]
    assert all(type(part) is MeshPart and len(part.vertices) == 4 and part.triangle_count == 2 for part in (right, nose))
    middle_right = [sum(vertex[axis] for vertex in right.vertices) / 4.0 for axis in range(3)]
    middle_nose = [sum(vertex[axis] for vertex in nose.vertices) / 4.0 for axis in range(3)]
    # 右の印は、+Z へ 1.5 m（模型の座標では、右が +Z）。鼻先の印は、+X へ 3 m。高さは、どちらも 1 m。
    assert middle_right == pytest.approx([0.0, 1.0, 1.5]) and middle_nose == pytest.approx([3.0, 1.0, 0.0])
    assert middle_right[2] > HALF_WIDTH_M and middle_nose[0] > HALF_LENGTH_M  # 車体の箱の外
    assert car_shape.MARK_CENTERS == {"mark_right": (0.0, 1.0, 1.5), "mark_nose": (3.0, 1.0, 0.0)} and car_shape.MARK_SIZE_M == 0.5
    for part in (right, nose):
        assert extent(part.vertices, 1) == (0.75, 1.25)  # 0.5 m 角
        assert extent(part.vertices, 2)[1] - extent(part.vertices, 2)[0] == pytest.approx(0.5)
        assert extent(part.vertices, 0)[0] == extent(part.vertices, 0)[1]  # 前後の向きに、厚みは無い（X に直角な板）


def test_car_shape_marks_face_the_rear_of_the_car_where_the_camera_is():
    # 模型の座標は、右手系。(b−a)×(c−a) が (−1, 0, 0)＝車の後ろ。Pyxelの3Dへは、反転も、頂点の順の入れ替えも、せずに渡す。
    for part in mark_parts():
        for triangle in part.triangles:
            assert face_normal(part.vertices, triangle) == pytest.approx((-0.25, 0.0, 0.0))


def test_car_shape_marks_and_pillars_have_four_different_colour_roles():
    roles = [part.role for part in mark_parts()] + list(PILLAR_ROLES.values())
    assert [part.role for part in mark_parts()] == ["yellow", "pink"]
    assert len(set(roles)) == 4 and set(roles) <= set(palette.ROLES)
    assert "black" not in roles  # 何も描かれていない所の色とは、違う色
