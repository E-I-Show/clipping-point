"""カメラ（cp_core.camera）のテスト。後方追従、塊が見えるかの判定、背景をずらす量、判定用の柱。pyxel は読み込まない。

位置は、全部、ロジックの座標（平面が (x, z)。+z は、+x の左。向きは +x が 0、+z が +π/2 で、増えると左旋回）。
カメラの値は、実物の定義データ（clipping_point/data/cameras.json の chase）を、アプリと同じ読み方で読んで作る。
Pyxelの3Dへ渡すときの、z の反転は、cp_app/render.py が行う（ここでは、見ない）。
"""
import dataclasses
import functools
import math

import pytest

from cp_app import data_files
from cp_core import camera, palette
from cp_core.camera import CameraPose, CameraSpec, chase_pose, chunk_visible
from cp_core.mesh import MeshPart, face_normal

CAR_X, CAR_Z = 60.0, 5.0  # 車の位置の見本
BACK_M, HEIGHT_M, LOOK_AHEAD_M, LOOK_HEIGHT_M, FOV_DEG, NEAR_M, FAR_M = 6.2, 2.1, 6.0, 0.9, 58.0, 0.3, 300.0  # 設計の表の値
SCREEN_H = 240


@functools.cache
def chase() -> CameraSpec:
    return camera.spec_from_entry(data_files.load({}, None).entry("cameras", camera.CHASE))


def forward(heading: float) -> tuple:
    return math.cos(heading), math.sin(heading)


def left(heading: float) -> tuple:
    """左の向きの単位ベクトル。向き0で、左は +z。"""
    return -math.sin(heading), math.cos(heading)


def along(point: tuple, heading: float) -> tuple:
    """車から見た、点（ロジックの座標の (x, y, z)）の、(前方への距離, 左への距離)。"""
    dx, dz = point[0] - CAR_X, point[2] - CAR_Z
    fx, fz = forward(heading)
    lx, lz = left(heading)
    return dx * fx + dz * fz, dx * lx + dz * lz


# --- カメラの値 ---
def test_camera_chase_values_come_from_the_shipped_entry():
    spec = chase()
    assert type(spec) is CameraSpec and camera.CHASE == "chase"
    assert dataclasses.astuple(spec) == ("chase", BACK_M, HEIGHT_M, LOOK_AHEAD_M, LOOK_HEIGHT_M, FOV_DEG, NEAR_M, FAR_M)
    assert [field.name for field in dataclasses.fields(CameraSpec)] == ["camera_id", "back", "height", "look_ahead", "look_height", "fov_deg", "near", "far"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.back = 3.0


def test_camera_values_are_floats_even_when_the_entry_has_integers():
    spec = camera.spec_from_entry({"id": "wide", "back_m": 6, "height_m": 2, "look_ahead_m": 6, "look_height_m": 1, "fov_deg": 58, "near_m": 1, "far_m": 300})
    assert all(type(value) is float for value in dataclasses.astuple(spec)[1:]) and spec.camera_id == "wide"


# --- 後方追従 ---
@pytest.mark.parametrize("heading", [0.0, math.pi / 2.0, -math.pi / 2.0, math.pi - 1e-6, -math.pi + 1e-6, 0.7, 2.37, -2.0])
def test_camera_chase_puts_the_eye_behind_the_car_and_the_target_ahead(heading):
    pose = chase_pose(chase(), CAR_X, CAR_Z, heading)
    assert type(pose) is CameraPose
    # 目は、車の真後ろ 6.2 m、高さ 2.1 m。注視点は、真ん前 6.0 m、高さ 0.9 m。横へは、ずれない。
    assert along(pose.eye, heading) == pytest.approx((-BACK_M, 0.0), abs=1e-9) and pose.eye[1] == HEIGHT_M
    assert along(pose.target, heading) == pytest.approx((LOOK_AHEAD_M, 0.0), abs=1e-9) and pose.target[1] == LOOK_HEIGHT_M
    assert (pose.fov_deg, pose.near, pose.far) == (FOV_DEG, NEAR_M, FAR_M)
    # カメラの向きは、車の向き。少し、見下ろす。
    assert math.cos(pose.heading - heading) == pytest.approx(1.0) and -math.pi <= pose.heading <= math.pi
    assert pose.pitch == pytest.approx(math.atan2(LOOK_HEIGHT_M - HEIGHT_M, BACK_M + LOOK_AHEAD_M)) and pose.pitch < 0.0


def test_camera_chase_at_the_four_headings_in_plain_numbers():
    # 向き0（+x）：目は −x の側。向き +π/2（+z）：目は −z の側。向きの決まりを、数で固定する。
    assert chase_pose(chase(), CAR_X, CAR_Z, 0.0).eye == pytest.approx((CAR_X - BACK_M, HEIGHT_M, CAR_Z))
    assert chase_pose(chase(), CAR_X, CAR_Z, 0.0).target == pytest.approx((CAR_X + LOOK_AHEAD_M, LOOK_HEIGHT_M, CAR_Z))
    assert chase_pose(chase(), CAR_X, CAR_Z, math.pi / 2.0).eye == pytest.approx((CAR_X, HEIGHT_M, CAR_Z - BACK_M))
    assert chase_pose(chase(), CAR_X, CAR_Z, math.pi / 2.0).target == pytest.approx((CAR_X, LOOK_HEIGHT_M, CAR_Z + LOOK_AHEAD_M))
    assert chase_pose(chase(), CAR_X, CAR_Z, -math.pi / 2.0).eye == pytest.approx((CAR_X, HEIGHT_M, CAR_Z + BACK_M))
    assert chase_pose(chase(), CAR_X, CAR_Z, math.pi).eye == pytest.approx((CAR_X + BACK_M, HEIGHT_M, CAR_Z))


@pytest.mark.parametrize("heading", [0.0, 1.0, math.pi / 2.0, 2.5, -1.2, -3.0])
def test_camera_eye_swings_to_the_right_rear_when_the_heading_grows(heading):
    # 向きが増える＝左旋回。車の鼻先は左へ回り、後ろの目は、元の向きから見て、右へ回る。
    before, after = chase_pose(chase(), CAR_X, CAR_Z, heading), chase_pose(chase(), CAR_X, CAR_Z, heading + 0.1)
    assert along(after.eye, heading)[1] < along(before.eye, heading)[1] - 0.5  # 右（左への距離が、負）へ
    assert along(after.target, heading)[1] > along(before.target, heading)[1] + 0.5  # 注視点は、左へ
    assert along(after.eye, heading)[0] < 0.0  # 後ろのまま


def test_camera_follows_the_car_without_any_lag():
    # 車の位置と向きに、そのまま付いていく（前の呼び出しの値を、持たない）。
    first = chase_pose(chase(), 0.0, 0.0, 0.0)
    chase_pose(chase(), 500.0, -300.0, 2.0)
    assert chase_pose(chase(), 0.0, 0.0, 0.0) == first
    moved = chase_pose(chase(), 10.0, 20.0, 0.0)
    assert moved.eye == pytest.approx((first.eye[0] + 10.0, first.eye[1], first.eye[2] + 20.0))


# --- 塊が見えるかの判定 ---
def test_camera_chunk_behind_the_camera_is_not_visible():
    pose = chase_pose(chase(), 0.0, 0.0, 0.0)  # 目は (−6.2, 0)。+x を見ている
    assert chunk_visible(pose, -100.0, 0.0, 30.0) is False  # 真後ろ
    assert chunk_visible(pose, -60.0, 40.0, 30.0) is False  # 斜め後ろ
    assert chunk_visible(pose, 100.0, 0.0, 30.0) is True  # 真ん前
    assert chunk_visible(pose, -6.2, 80.0, 30.0) is True  # 真横（前方への射影が0）


def test_camera_chunk_that_straddles_the_camera_is_visible():
    pose = chase_pose(chase(), 0.0, 0.0, 0.0)
    assert chunk_visible(pose, -20.0, 0.0, 30.0) is True  # 中心は後ろだが、半径が、目をまたぐ
    assert chunk_visible(pose, -6.2 - 29.9, 0.0, 30.0) is True
    assert chunk_visible(pose, -6.2 - 30.1, 0.0, 30.0) is False  # 前方への射影が、−半径より小さい


def test_camera_chunk_beyond_the_far_plane_is_not_visible():
    pose = chase_pose(chase(), 0.0, 0.0, 0.0)
    assert chunk_visible(pose, 400.0, 0.0, 30.0) is False  # 奥（300 m）より遠い
    assert chunk_visible(pose, -6.2 + FAR_M + 29.9, 0.0, 30.0) is True  # 奥＋半径より近ければ、見える
    assert chunk_visible(pose, -6.2 + FAR_M + 30.1, 0.0, 30.0) is False
    assert chunk_visible(pose, 0.0, 340.0, 30.0) is False  # 横でも、遠ければ見えない


def test_camera_visibility_turns_with_the_camera():
    pose = chase_pose(chase(), 0.0, 0.0, math.pi / 2.0)  # +z を見ている
    assert chunk_visible(pose, 0.0, 100.0, 30.0) is True and chunk_visible(pose, 0.0, -100.0, 30.0) is False
    pose = chase_pose(chase(), 0.0, 0.0, math.pi)  # −x を見ている
    assert chunk_visible(pose, -100.0, 0.0, 30.0) is True and chunk_visible(pose, 100.0, 0.0, 30.0) is False


def test_camera_looking_straight_down_decides_by_the_distance_only():
    pose = CameraPose(eye=(0.0, 50.0, 0.0), target=(0.0, 0.0, 0.0), fov_deg=58.0, near=0.3, far=300.0)
    assert pose.heading == 0.0 and pose.pitch == pytest.approx(-math.pi / 2.0)
    assert chunk_visible(pose, -100.0, 0.0, 30.0) is True and chunk_visible(pose, 100.0, 0.0, 30.0) is True
    assert chunk_visible(pose, 400.0, 0.0, 30.0) is False


def test_camera_sees_the_chunks_ahead_on_the_test_loop_and_hides_the_ones_behind():
    # 実物のコースの塊で。スタート位置（1本目の直線。向き0）からは、後ろの塊が見えない。
    from cp_core import track

    course = track.build_track(data_files.load({}, None).entry("tracks", "test_loop"))
    chunks = course.mesh_chunks()
    x, z, heading = course.start_pose()
    pose = chase_pose(chase(), x, z, heading)
    seen = [chunk_visible(pose, chunk.center[0], chunk.center[1], chunk.radius) for chunk in chunks]
    assert seen[1] is True and seen[2] is True  # 車のいる塊と、その先
    assert 0 < seen.count(False) < len(chunks)  # 後ろの塊は、隠す
    # 反対を向けば、見える塊と見えない塊が、入れ替わる所がある。
    back = chase_pose(chase(), x, z, heading + math.pi)
    seen_back = [chunk_visible(back, chunk.center[0], chunk.center[1], chunk.radius) for chunk in chunks]
    assert seen_back != seen and any(a and not b for a, b in zip(seen, seen_back))


# --- 背景をずらす量 ---
def test_camera_focal_length_follows_the_vertical_field_of_view():
    assert camera.focal_px(90.0, SCREEN_H) == pytest.approx(120.0)  # 縦の画角90度なら、画面の高さの半分
    assert camera.focal_px(FOV_DEG, SCREEN_H) == pytest.approx(216.4857, abs=1e-3)
    assert camera.focal_px(FOV_DEG, 480) == pytest.approx(2.0 * camera.focal_px(FOV_DEG, SCREEN_H))
    assert camera.focal_px(30.0, SCREEN_H) > camera.focal_px(FOV_DEG, SCREEN_H)  # 望遠ほど、長い


def test_camera_backdrop_goes_round_once_when_the_heading_goes_round_once():
    period = camera.backdrop_period_px(FOV_DEG, SCREEN_H)
    assert period == 1360 and type(period) is int  # 2π×焦点距離（画素）
    assert camera.backdrop_shift_px(0.0, period) == 0
    assert camera.backdrop_shift_px(math.pi / 2.0, period) == period // 4
    assert camera.backdrop_shift_px(math.pi, period) == period // 2
    assert camera.backdrop_shift_px(-math.pi / 2.0, period) == 3 * period // 4  # 負の向きも、同じ輪の上
    for heading in (0.0, 0.3, 1.0, 2.5, -1.2, -3.1):
        assert camera.backdrop_shift_px(heading + 2.0 * math.pi, period) == pytest.approx(camera.backdrop_shift_px(heading, period), abs=1)
        assert camera.backdrop_shift_px(heading + 20.0 * math.pi, period) == pytest.approx(camera.backdrop_shift_px(heading, period), abs=1)


def test_camera_backdrop_flows_to_the_right_when_the_heading_grows():
    period = camera.backdrop_period_px(FOV_DEG, SCREEN_H)
    steps = [camera.backdrop_shift_px(2.0 * math.pi * index / 2000.0, period) for index in range(2000)]
    assert all(type(shift) is int and 0 <= shift < period for shift in steps)
    assert steps == sorted(steps) and steps[0] == 0 and steps[-1] == period - 1  # 1周の間、減らない。1周で、絵が1周ぶん
    # 画面の中央では、向きが 0.01 rad 増えると、絵は、焦点距離×0.01（約2.2画素）だけ右へ動く。
    assert camera.backdrop_shift_px(1.01, period) - camera.backdrop_shift_px(1.0, period) in (2, 3)
    assert camera.backdrop_shift_px(0.99, period) < camera.backdrop_shift_px(1.0, period)  # 右へ回れば、絵は左へ


def test_camera_horizon_rises_on_the_screen_when_the_camera_looks_down():
    pose = chase_pose(chase(), CAR_X, CAR_Z, 0.3)
    row = camera.horizon_row(pose, SCREEN_H)
    assert row == 99 and type(row) is int  # 画面の中央（120）より、上
    level = CameraPose(eye=(0.0, 2.0, 0.0), target=(10.0, 2.0, 0.0), fov_deg=FOV_DEG, near=NEAR_M, far=FAR_M)
    assert camera.horizon_row(level, SCREEN_H) == 120
    up = CameraPose(eye=(0.0, 2.0, 0.0), target=(10.0, 4.0, 0.0), fov_deg=FOV_DEG, near=NEAR_M, far=FAR_M)
    assert camera.horizon_row(up, SCREEN_H) > 120  # 見上げれば、下へ
    assert camera.horizon_row(pose, SCREEN_H) == camera.horizon_row(chase_pose(chase(), -300.0, 80.0, -2.0), SCREEN_H)  # 車の位置と向きには、よらない


# --- 判定用の柱 ---
def test_camera_left_pillar_is_on_the_left_in_logic_coordinates():
    # 向き0：前は +x、左は +z。左の柱の z は、車より大きい。
    (left_x, left_z), (right_x, right_z) = camera.pillar_positions(CAR_X, CAR_Z, 0.0)
    assert (left_x, left_z) == pytest.approx((CAR_X + 8.0, CAR_Z + 3.0)) and left_z > CAR_Z
    assert (right_x, right_z) == pytest.approx((CAR_X + 8.0, CAR_Z - 3.0)) and right_z < CAR_Z
    # 向き +π/2：前は +z、左は −x。左の柱の x は、車より小さい。
    (left_x, left_z), (right_x, right_z) = camera.pillar_positions(CAR_X, CAR_Z, math.pi / 2.0)
    assert (left_x, left_z) == pytest.approx((CAR_X - 3.0, CAR_Z + 8.0)) and left_x < CAR_X
    assert (right_x, right_z) == pytest.approx((CAR_X + 3.0, CAR_Z + 8.0)) and right_x > CAR_X
    assert (camera.PILLAR_AHEAD_M, camera.PILLAR_SIDE_M, camera.PILLAR_WIDTH_M, camera.PILLAR_HEIGHT_M) == (8.0, 3.0, 0.5, 2.0)


@pytest.mark.parametrize("heading", [0.0, 0.4, math.pi / 2.0, 2.37, math.pi, -1.0, -2.6])
def test_camera_pillars_are_mirror_images_about_the_line_ahead_of_the_car(heading):
    left_pillar, right_pillar = camera.pillar_positions(CAR_X, CAR_Z, heading)
    ahead_left, side_left = along((left_pillar[0], 0.0, left_pillar[1]), heading)
    ahead_right, side_right = along((right_pillar[0], 0.0, right_pillar[1]), heading)
    assert (ahead_left, side_left) == pytest.approx((8.0, 3.0)) and (ahead_right, side_right) == pytest.approx((8.0, -3.0))
    # 前方のベクトルと、柱へのベクトルの、外積（x×z の成分）。ロジックの座標では、左の点が、正。
    fx, fz = forward(heading)
    assert fx * (left_pillar[1] - CAR_Z) - fz * (left_pillar[0] - CAR_X) > 0.0
    assert fx * (right_pillar[1] - CAR_Z) - fz * (right_pillar[0] - CAR_X) < 0.0


@pytest.mark.parametrize("heading", [0.0, 0.4, math.pi / 2.0, 2.37, math.pi, -1.0, -2.6])
def test_camera_pillar_boards_stand_on_the_ground_and_face_the_camera(heading):
    parts = camera.pillar_parts(CAR_X, CAR_Z, heading)
    positions = camera.pillar_positions(CAR_X, CAR_Z, heading)
    eye = chase_pose(chase(), CAR_X, CAR_Z, heading).eye
    assert [part.name for part in parts] == ["pillar_left", "pillar_right"] == [camera.PILLAR_LEFT, camera.PILLAR_RIGHT]
    for part, (px, pz) in zip(parts, positions):
        assert type(part) is MeshPart and len(part.vertices) == 4 and part.triangle_count == 2
        assert sorted(vertex[1] for vertex in part.vertices) == [0.0, 0.0, 2.0, 2.0]  # 地面から、高さ2 m
        middle = [sum(vertex[axis] for vertex in part.vertices) / 4.0 for axis in range(3)]
        assert middle == pytest.approx([px, 1.0, pz])
        for triangle in part.triangles:
            nx, ny, nz = face_normal(part.vertices, triangle)
            # (b−a)×(c−a) は、車の後ろの向き (−cos h, 0, −sin h)。目の側を向く（片面の板の、表）。
            assert (nx, ny, nz) == pytest.approx((-math.cos(heading), 0.0, -math.sin(heading)), abs=1e-9)
            assert nx * (eye[0] - px) + nz * (eye[2] - pz) > 0.0
        bottom = [vertex for vertex in part.vertices if vertex[1] == 0.0]
        assert math.hypot(bottom[1][0] - bottom[0][0], bottom[1][2] - bottom[0][2]) == pytest.approx(0.5)  # 幅0.5 m


def test_camera_pillars_have_two_different_colour_roles():
    left_part, right_part = camera.pillar_parts(0.0, 0.0, 0.0)
    assert (left_part.role, right_part.role) == ("red", "blue") and left_part.role != right_part.role
    assert {left_part.role, right_part.role} <= set(palette.ROLES)
    assert camera.PILLAR_ROLES == {"pillar_left": "red", "pillar_right": "blue"}
