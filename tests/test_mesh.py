"""メッシュ用の数値の型と、面の向きの決まり（cp_core.mesh）のテスト。pyxel は読み込まない。

面の向きの決まりは、どちらの座標（ロジックの座標、模型の座標）でも同じ：頂点の3つ組を、そのままベクトルとして、
(b−a)×(c−a) が外向き。コースの面の向きは tests/test_track.py、車は tests/test_car_shape.py、柱は tests/test_camera.py。
"""
import dataclasses

import pytest

from cp_core import mesh
from cp_core.mesh import MeshPart, board, box, face_normal, quad


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def centroid(vertices, triangle) -> tuple:
    return tuple(sum(vertices[index][axis] for index in triangle) / 3.0 for axis in range(3))


def test_mesh_face_normal_is_the_plain_cross_product_of_the_two_edges():
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    assert face_normal(vertices, (0, 1, 2)) == (0.0, 0.0, 1.0)  # x × y = z
    assert face_normal(vertices, (0, 2, 3)) == (1.0, 0.0, 0.0)  # y × z = x
    assert face_normal(vertices, (0, 3, 1)) == (0.0, 1.0, 0.0)  # z × x = y
    assert face_normal(vertices, (0, 2, 1)) == (0.0, 0.0, -1.0)  # 順を入れ替えると、逆を向く
    # 長さは、面積の2倍（そろえない）。
    assert face_normal(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0)), (0, 1, 2)) == (0.0, 0.0, 6.0)


def test_mesh_quad_keeps_the_facing_of_its_first_three_corners():
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0))
    first, second = quad(0, 1, 2, 3)
    assert (first, second) == ((0, 1, 2), (0, 2, 3))
    assert face_normal(vertices, first) == face_normal(vertices, second) == (0.0, 0.0, 1.0)


def test_mesh_box_has_eight_corners_and_twelve_triangles_that_all_face_outwards():
    vertices, triangles = box(-2.0, 3.0, 0.5, 1.5, -1.0, 4.0)
    assert len(vertices) == 8 and len(set(vertices)) == 8 and len(triangles) == 12
    assert {vertex[0] for vertex in vertices} == {-2.0, 3.0} and {vertex[1] for vertex in vertices} == {0.5, 1.5}
    assert {vertex[2] for vertex in vertices} == {-1.0, 4.0}
    middle = (0.5, 1.0, 1.5)
    seen = []
    for triangle in triangles:
        normal = face_normal(vertices, triangle)
        outward = tuple(c - m for c, m in zip(centroid(vertices, triangle), middle))
        assert dot(normal, outward) > 0.0, triangle  # 箱の外を向く
        assert sorted(abs(value) for value in normal)[:2] == [0.0, 0.0]  # 軸に沿った面
        seen.append(tuple(0 if value == 0.0 else (1 if value > 0.0 else -1) for value in normal))
    # 6つの面に、三角形が2つずつ。並びは、+x、−x、+y、−y、+z、−z。
    assert seen == [face for face in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)) for _ in range(2)]


@pytest.mark.parametrize("corners", [(1.0, 1.0, 0.0, 1.0, 0.0, 1.0), (0.0, 1.0, 2.0, 1.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0, 1.0, -1.0)])
def test_mesh_box_that_is_flat_or_inside_out_is_rejected(corners):
    # 裏返った箱は、面が全部、内を向く（裏の面を捨てる設定で、何も描かれない）。黙って作らない。
    with pytest.raises(ValueError):
        box(*corners)


@pytest.mark.parametrize("facing", [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0), (0.6, 0.8), (-0.8, 0.6)])
def test_mesh_board_stands_upright_and_faces_the_given_way(facing):
    vertices, triangles = board((10.0, 1.0, -5.0), facing, 0.5, 2.0)
    assert len(vertices) == 4 and len(triangles) == 2
    assert sorted(vertex[1] for vertex in vertices) == [0.0, 0.0, 2.0, 2.0]  # 中心の高さ1 m、高さ2 m
    middle = tuple(sum(vertex[axis] for vertex in vertices) / 4.0 for axis in range(3))
    assert middle == pytest.approx((10.0, 1.0, -5.0))
    for triangle in triangles:
        normal = face_normal(vertices, triangle)
        # (b−a)×(c−a) は、facing の向き（長さは、板の面積）。
        assert normal == pytest.approx((facing[0] * 0.5 * 2.0, 0.0, facing[1] * 0.5 * 2.0))
    # 板の幅は、facing に直角な向きに 0.5 m。
    bottom = [vertex for vertex in vertices if vertex[1] == 0.0]
    across = (bottom[1][0] - bottom[0][0], bottom[1][2] - bottom[0][2])
    assert (across[0] ** 2 + across[1] ** 2) ** 0.5 == pytest.approx(0.5)
    assert across[0] * facing[0] + across[1] * facing[1] == pytest.approx(0.0)


def test_mesh_board_needs_a_positive_size():
    for width, height in ((0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)):
        with pytest.raises(ValueError):
            board((0.0, 0.0, 0.0), (1.0, 0.0), width, height)


def test_mesh_part_cannot_be_changed_and_counts_its_triangles():
    vertices, triangles = box(0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
    part = MeshPart("body", "red", vertices, triangles)
    assert part.triangle_count == 12 and (part.name, part.role) == ("body", "red")
    with pytest.raises(dataclasses.FrozenInstanceError):
        part.role = "blue"
    assert len(mesh.BOX_FACES) == 6 and sorted(index for face in mesh.BOX_FACES for index in face) == sorted(list(range(8)) * 3)  # どの角も、3つの面に入る
