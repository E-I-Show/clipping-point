"""コース（cp_core.track）のテスト。コースの表、照会、位置を引く口、壁の押し戻し、形の検査。pyxel は読み込まない。

コースは、実物の定義データ（clipping_point/data/tracks/test_loop.json）を、アプリと同じ読み方で読んで作る。
仮の周回路は、直線2本（200 m）と、緩和区間つきの半円2つ（半径45 m、緩和区間25 m）の左回り。頭の制御点は、1本目の直線の始まり。
  s = 0〜200 が1本目の直線、200〜366.4 が1つ目の半円（円弧は 225〜341.4）、366.4〜566.4 が2本目の直線、その先が2つ目の半円。
"""
import functools
import math
import sys

import pytest

from conftest import ROOT
from cp_app import data_files
from cp_core import track
from cp_core.track import SURFACE_ASPHALT, SURFACE_GRASS, Track, TrackQuery

STRAIGHT_M, RADIUS_M, TRANSITION_M = 200.0, 45.0, 25.0  # 仮の周回路の寸法（定義データの _notes と同じ）
ARC_M = RADIUS_M * math.pi + TRANSITION_M  # 半円1つの長さ
LAP_M = 2.0 * (STRAIGHT_M + ARC_M)  # 全長（約732.7 m）
HALF_M, WALL_M = 6.0, 14.0  # 幅の半分と、中心線から壁まで
HALF_LENGTH_M, HALF_WIDTH_M = 2.1, 0.85  # 壁の当たりに使う、車体の半長と半幅（車の値と同じ）
FIELDS = TrackQuery.__slots__  # 照会の結果の、全部の項目


@functools.cache
def game_data():
    return data_files.load({}, None)


def loop_entry() -> dict:
    """実物のコースの項目。引くたびに、新しい複製（テストの中で、書き換えてよい）。"""
    return game_data().entry("tracks", "test_loop")


@functools.cache
def loop() -> Track:
    return track.build_track(loop_entry())


def values(query: TrackQuery) -> tuple:
    return tuple(getattr(query, name) for name in FIELDS)


def same_answer(a: TrackQuery, b: TrackQuery) -> bool:
    """取り直したか（requeried）のほかが、全部同じか。"""
    return all(getattr(a, name) == getattr(b, name) for name in FIELDS if name != "requeried")


def lap_gap(course: Track, a: float, b: float) -> float:
    """コースに沿った距離の差の大きさ（1周で折り返す）。"""
    return abs((a - b + 0.5 * course.length) % course.length - 0.5 * course.length)


# --- コースの表 ---
def test_track_table_of_the_test_loop_has_the_designed_length_and_closes_after_one_lap():
    course = loop()
    assert type(course) is Track and course.track_id == "test_loop"
    assert course.length == pytest.approx(LAP_M, abs=0.05)
    assert course.n == 366 and course.ds == pytest.approx(course.length / course.n) and course.ds == pytest.approx(2.0, abs=0.01)
    assert course.turning == pytest.approx(2.0 * math.pi, abs=1e-9)  # 左回りに、ちょうど1周
    # 頭の点は、1本目の直線の始まり。末尾の点の次は、頭の点（すき間が、ほかの刻みと同じ）。
    first, last = course.sample(0), course.sample(course.n - 1)
    assert (first[0], first[1]) == pytest.approx((0.0, 0.0), abs=1e-3)
    assert math.hypot(first[0] - last[0], first[1] - last[1]) == pytest.approx(course.ds, abs=1e-3)
    assert course.start_s == 60.0 and course.start_lateral == 0.0
    x, z, heading = course.start_pose()
    assert (x, z, heading) == pytest.approx((60.0, 0.0, 0.0), abs=1e-6)  # スタートは、1本目の直線の途中


def test_track_table_keeps_the_straights_straight_and_the_arcs_at_the_designed_radius():
    course = loop()
    for index in range(course.n):
        x, z, heading, curvature, half, wall_left, wall_right = course.sample(index)
        s = index * course.ds
        assert (half, wall_left, wall_right) == (HALF_M, WALL_M, WALL_M)
        assert curvature > -1e-3  # 左回り。右へは曲がらない
        on_first_straight = 15.0 <= s <= STRAIGHT_M - 15.0
        on_second_straight = STRAIGHT_M + ARC_M + 15.0 <= s <= 2.0 * STRAIGHT_M + ARC_M - 15.0
        if on_first_straight or on_second_straight:
            assert abs(curvature) < 1e-4, s  # 直線の曲率は、0に近い
            assert z == pytest.approx(0.0 if on_first_straight else 91.154, abs=0.01), s
        for arc_start in (STRAIGHT_M, 2.0 * STRAIGHT_M + ARC_M):
            if arc_start + TRANSITION_M + 10.0 <= s <= arc_start + ARC_M - TRANSITION_M - 10.0:
                assert 1.0 / curvature == pytest.approx(RADIUS_M, rel=0.01), s  # 半円の半径は、45 mに近い
    assert max(course.sample(index)[3] for index in range(course.n)) < 1.0 / (RADIUS_M * 0.99)


def test_track_table_cannot_be_changed_after_it_is_built():
    course = loop()
    for name, value in (("length", 1.0), ("n", 5), ("_x", ()), ("_half", (1.0,)), ("start_s", 0.0), ("extra", 1)):
        with pytest.raises(AttributeError):
            setattr(course, name, value)
    assert type(course._x) is tuple and type(course._k) is tuple and type(course._wall_l) is tuple
    # 路面の摩擦係数も、タプル（辞書だと、中身を書き換えられる。表は、覚えて、世界どうしで同じものを持つ）。
    assert type(course._mu) is tuple and len(course._mu) == len(track.SURFACES)
    with pytest.raises(TypeError):
        course._mu[1] = 1.0


def test_track_table_of_the_same_entry_is_built_once_and_handed_out_again():
    # 同じ中身の項目からは、前に作った表を、そのまま渡す（読み込み検査の形の検査と、世界で、2度作らない）。
    first = track.build_track(loop_entry())
    assert track.build_track(loop_entry()) is first  # 別の辞書でも、中身が同じなら、同じ表
    assert track.build_track(dict(reversed(loop_entry().items()))) is first  # 鍵の順は、関係ない
    # 中身が1か所でも違えば、別の表（id だけで覚えない）。
    wider = track.build_track(changed(width_m=14.0))
    assert wider is not first and wider.sample(0)[4] == 7.0 and first.sample(0)[4] == HALF_M
    moved = loop_entry()
    moved["control_points"][10]["z_m"] = 0.5
    assert track.build_track(moved) is not first and track.build_track(moved).sample(50)[1] != first.sample(50)[1]
    assert track.build_track(changed(start={"s_m": 10.0, "lateral_m": 0.0})).start_s == 10.0
    assert track.build_track(loop_entry()) is first


def test_track_remembered_tables_are_bounded_and_a_failed_build_is_not_remembered(monkeypatch):
    built = []

    class Counting(Track):
        def __init__(self, entry: dict) -> None:
            built.append(entry["width_m"])
            super().__init__(entry)

    monkeypatch.setattr(track, "Track", Counting)
    monkeypatch.setattr(track, "_built", {})
    widths = [10.0 + index for index in range(track.BUILT_MAX + 1)]
    for width in widths:
        track.build_track(changed(width_m=width))
    assert built == widths and len(track._built) == track.BUILT_MAX == 4
    track.build_track(changed(width_m=widths[-1]))  # 直近のものは、覚えている
    assert built == widths
    track.build_track(changed(width_m=widths[0]))  # いちばん古いものは、忘れている（作り直す）
    assert built == [*widths, widths[0]] and len(track._built) == track.BUILT_MAX
    # 使うと、新しい扱いになる（次に忘れるのは、使っていないもの）。
    track.build_track(changed(width_m=widths[2]))
    track.build_track(changed(width_m=99.0))
    track.build_track(changed(width_m=widths[2]))
    assert built == [*widths, widths[0], 99.0]
    # 作れなかった項目（計算の例外）は、覚えない。次も、同じ例外になる。
    broken = changed(control_points=[{"x_m": 0.0, "z_m": 0.0}] * 4)
    for _ in range(2):
        with pytest.raises(ZeroDivisionError):
            track.build_track(broken)
    assert len(track._built) == track.BUILT_MAX


def test_track_shape_check_and_the_later_build_share_one_table(monkeypatch):
    # 読み込み検査（形の検査）を通した項目から、表を作る。表を作る計算は、1度だけ。
    from cp_core import datadefs

    built = []

    class Counting(Track):
        def __init__(self, entry: dict) -> None:
            built.append(entry["id"])
            super().__init__(entry)

    monkeypatch.setattr(track, "Track", Counting)
    monkeypatch.setattr(track, "_built", {})
    data = datadefs.load_game_data(data_files.read_sources(data_files.DATA_DIR))
    assert built == ["test_loop"]
    course = track.build_track(data.entry("tracks", "test_loop"))
    assert built == ["test_loop"] and course.track_id == "test_loop"
    datadefs.load_game_data(data_files.read_sources(data_files.DATA_DIR))  # もう1度読んでも、作り直さない
    assert built == ["test_loop"]


def test_track_surface_friction_comes_from_the_entry():
    course = loop()
    assert track.SURFACES == (SURFACE_ASPHALT, SURFACE_GRASS) == ("asphalt", "grass")
    assert course.surface_mu(SURFACE_ASPHALT) == 1.0 and course.surface_mu(SURFACE_GRASS) == 0.55
    with pytest.raises(KeyError):
        course.surface_mu("gravel")
    assert (course.wall_restitution, course.wall_friction) == (0.15, 0.35)


# --- 位置を引く口 ---
def test_track_pose_at_walks_down_the_first_straight_and_wraps_after_one_lap():
    course = loop()
    for s in (0.0, 10.0, 99.5, 180.0):
        assert course.pose_at(s) == pytest.approx((s, 0.0, 0.0), abs=2e-3)
        assert course.pose_at(s, 3.0) == pytest.approx((s, 3.0, 0.0), abs=2e-3)  # 横のずれは、左（+z）が正
        assert course.pose_at(s, -3.0) == pytest.approx((s, -3.0, 0.0), abs=2e-3)
    # 2本目の直線は、逆向き（向きは π）。左は −z。
    x, z, heading = course.pose_at(STRAIGHT_M + ARC_M + 50.0, 2.0)
    assert (x, z) == pytest.approx((150.0, 91.154 - 2.0), abs=0.01) and abs(heading) == pytest.approx(math.pi, abs=1e-3)
    # 1周で折り返す。
    for s in (3.0, 250.0, 700.0):
        assert course.pose_at(s + course.length) == pytest.approx(course.pose_at(s), abs=1e-6)
        assert course.pose_at(s - course.length) == pytest.approx(course.pose_at(s), abs=1e-6)
    assert all(-math.pi < course.pose_at(index * 1.5)[2] <= math.pi for index in range(490))  # 向きは、−π〜π


# --- 照会 ---
@pytest.mark.parametrize("s", [0.0, 0.7, 60.0, 199.0, 212.0, 283.2, 360.0, 420.0, 566.0, 650.0, 732.0])
@pytest.mark.parametrize("lateral", [0.0, 3.0, -3.0, 5.99, -5.99, 6.01, -6.01, 13.9, -13.9])
def test_track_query_is_the_inverse_of_pose_at_inside_the_walls(s, lateral):
    course = loop()
    x, z, heading = course.pose_at(s, lateral)
    found = course.query(x, z)
    assert lap_gap(course, found.s, s) < 1e-6 and found.lateral == pytest.approx(lateral, abs=1e-6)
    assert 0.0 <= found.s < course.length  # コースに沿った距離は、0以上、全長未満
    assert math.cos(found.heading - heading) == pytest.approx(1.0, abs=1e-9)
    assert found.surface == (SURFACE_ASPHALT if abs(lateral) <= HALF_M else SURFACE_GRASS)  # 舗装の端の内は舗装、外は芝
    assert (found.half_left, found.half_right, found.wall_left, found.wall_right) == (HALF_M, HALF_M, WALL_M, WALL_M)
    assert found.to_wall_left == pytest.approx(WALL_M - lateral, abs=1e-6) and found.to_wall_right == pytest.approx(WALL_M + lateral, abs=1e-6)
    assert found.to_wall_left > 0.0 and found.to_wall_right > 0.0
    assert found.height == 0.0 and found.requeried is False
    assert 0 <= found.index < course.n and found.index * course.ds <= found.s + 1e-9 < (found.index + 1) * course.ds + 1e-9
    # 位置を引く口へ戻すと、元の位置。
    assert course.pose_at(found.s, found.lateral)[:2] == pytest.approx((x, z), abs=1e-6)


def test_track_query_gives_the_curvature_of_the_place():
    course = loop()
    assert abs(course.query(*course.pose_at(100.0)[:2]).curvature) < 1e-4
    assert 1.0 / course.query(*course.pose_at(STRAIGHT_M + ARC_M / 2.0, 2.0)[:2]).curvature == pytest.approx(RADIUS_M, rel=0.01)


@pytest.mark.parametrize("s", [100.0, 283.0, 500.0])
def test_track_query_beyond_a_wall_reports_a_negative_distance_to_that_wall(s):
    course = loop()
    for lateral, side in ((15.5, "left"), (-15.5, "right")):
        if lateral > 0.0 and 200.0 < s < 366.0:
            continue  # 半円の内側は、壁の外へ遠く出ると、曲率の中心に近づく。外側だけを見る
        found = course.query(*course.pose_at(s, lateral)[:2])
        assert found.lateral == pytest.approx(lateral, abs=1e-6) and found.surface == SURFACE_GRASS
        beyond, inside = (found.to_wall_left, found.to_wall_right) if side == "left" else (found.to_wall_right, found.to_wall_left)
        assert beyond == pytest.approx(-1.5, abs=1e-6) and inside == pytest.approx(2.0 * WALL_M + 1.5, abs=1e-6)


def drive_around(course: Track, step_m: float, laps: float = 1.2):
    """コースに沿って、step_m ずつ進む位置の列（横のずれは、左右に振る）。1周をまたぐ。"""
    count = int(course.length * laps / step_m)
    for index in range(count):
        s = index * step_m
        yield course.pose_at(s, 5.0 * math.sin(s * 0.05))[:2]


def test_track_query_with_the_previous_segment_gives_the_same_answer_and_never_requeries():
    course = loop()
    hint, indices = None, []
    for x, z in drive_around(course, 1.0):
        local = course.query(x, z, hint)
        assert local.requeried is False  # 正しい前回の区間なら、取り直さない（頭の1回は、前回の区間が無い）
        assert values(local) == values(course.query(x, z))  # 前回の区間つきと、無しで、同じ答え
        hint = local.index
        indices.append(hint)
    assert indices[0] == 0 and max(indices) == course.n - 1 and indices[-1] < course.n // 2  # 1周をまたいで、頭へ戻っている
    assert len(set(indices)) == course.n  # 全部の区間を通った


def test_track_query_walks_backwards_from_the_previous_segment_too():
    course = loop()
    hint = course.query(*course.pose_at(30.0)[:2]).index
    for s in (25.0, 12.0, 1.0, -8.0, -20.0):  # 後ろへ動いて、1周の境目を逆にまたぐ
        x, z, _ = course.pose_at(s)
        found = course.query(x, z, hint)
        assert found.requeried is False and found.s == pytest.approx(s % course.length, abs=1e-6)
        hint = found.index


@pytest.mark.parametrize("wrong", [100, 183, 300, -40, 366 + 120, 10 ** 6 + 7])
def test_track_query_with_a_far_segment_requeries_and_gives_the_same_answer(wrong):
    course = loop()
    x, z, _ = course.pose_at(60.0, 2.5)
    plain = course.query(x, z)
    far = course.query(x, z, wrong)
    assert far.requeried is True and plain.requeried is False
    assert same_answer(far, plain) and far.s == pytest.approx(60.0, abs=1e-6) and far.lateral == pytest.approx(2.5, abs=1e-6)


def test_track_query_stays_on_the_leg_of_the_previous_segment_when_that_leg_runs_alongside():
    # 向かい側の直線の、同じ x の区間を、前回の区間として渡す。位置を挟む区間が、その近くにあるので、そちらの道の上の答えになる
    # （隣の道へ飛ばないための決め。取り直さない）。車を置き直した後は、前回の区間を渡さない。
    course = loop()
    x, z, _ = course.pose_at(60.0, 2.5)
    opposite = course.query(*course.pose_at(STRAIGHT_M + ARC_M + 140.0)[:2])  # 2本目の直線の、x = 60 の所
    stuck = course.query(x, z, opposite.index)
    assert stuck.requeried is False and stuck.index == opposite.index
    assert stuck.lateral == pytest.approx(91.154 - 2.5, abs=0.01) and stuck.to_wall_left < 0.0  # 向かい側から見ると、壁のはるか外
    assert course.query(x, z, None).s == pytest.approx(60.0, abs=1e-6)


def test_track_query_reaches_as_far_as_the_walk_limit_from_the_previous_segment():
    course = loop()
    start = course.query(*course.pose_at(100.0)[:2])

    def at_segment(offset: int) -> TrackQuery:
        """前回の区間から、offset 区間だけ離れた区間の、真ん中の点を、前回の区間つきで引く。"""
        found = course.query(*course.pose_at((start.index + offset + 0.5) * course.ds)[:2], start.index)
        assert found.index == start.index + offset
        return found

    assert track.QUERY_MAX_WALK == 16
    assert [at_segment(offset).requeried for offset in (1, 8, 15, -1, -8, -16)] == [False] * 6  # 前へ15区間、後ろへ16区間までは、歩いて届く
    assert [at_segment(offset).requeried for offset in (16, 17, 40, -17, -18, -40)] == [True] * 6  # その先は、全部を探して取り直す


def test_track_query_without_a_previous_segment_finds_the_nearer_leg_from_anywhere():
    course = loop()
    for x, z, s_want, lateral_want in ((100.0, 30.0, 100.0, 30.0), (100.0, 60.0, STRAIGHT_M + ARC_M + 100.0, 31.154), (-80.0, 45.577, 649.57, -22.5)):
        found = course.query(x, z)
        assert found.requeried is False and found.surface == SURFACE_GRASS
        assert found.s == pytest.approx(s_want, abs=0.05) and found.lateral == pytest.approx(lateral_want, abs=0.05)
    assert course.nearest_index(0.0, 0.0) == 0 and course.nearest_index(60.2, -3.0) == 30


# --- 壁の押し戻し ---
def push(course: Track, s: float, lateral: float, heading: float, speed: float, travel=None) -> tuple:
    """コースの上の点に置いた車を、押し戻す。travel は、進む向き（無ければ、車の向き）。返すのは (押し戻しの結果, 照会)。"""
    x, z, _ = course.pose_at(s, lateral)
    travel = heading if travel is None else travel
    found = course.query(x, z)
    return course.push_out(found, x, z, speed * math.cos(travel), speed * math.sin(travel), heading, HALF_LENGTH_M, HALF_WIDTH_M), found


def test_track_wall_contact_uses_the_car_as_an_oriented_rectangle():
    course = loop()
    for lateral, heading, want in (
        (WALL_M - HALF_WIDTH_M - 0.01, 0.0, (0.0, 0)),  # 壁と平行。半幅ぶん、寄れる
        (WALL_M - HALF_WIDTH_M + 0.25, 0.0, (0.25, 1)),
        (WALL_M - HALF_LENGTH_M - 0.01, math.pi / 2.0, (0.0, 0)),  # 壁へ正面。半長ぶん
        (WALL_M - HALF_LENGTH_M + 0.5, math.pi / 2.0, (0.5, 1)),
        (-(WALL_M - HALF_WIDTH_M + 0.25), 0.0, (0.25, -1)),  # 右の壁
        (-(WALL_M - HALF_LENGTH_M + 0.5), -math.pi / 2.0, (0.5, -1)),
        (0.0, 0.7, (0.0, 0)),
    ):
        x, z, _ = course.pose_at(100.0, lateral)
        pen, side = course.wall_contact(course.query(x, z), heading, HALF_LENGTH_M, HALF_WIDTH_M)
        assert (pen, side) == pytest.approx(want, abs=1e-6), (lateral, heading)
    # 斜め。法線へ投影した長さは、|sin|×半長 ＋ |cos|×半幅。
    x, z, _ = course.pose_at(100.0, 12.5)
    pen, side = course.wall_contact(course.query(x, z), math.radians(30.0), HALF_LENGTH_M, HALF_WIDTH_M)
    assert side == 1 and pen == pytest.approx(12.5 + 0.5 * HALF_LENGTH_M + math.cos(math.radians(30.0)) * HALF_WIDTH_M - WALL_M, abs=1e-6)
    assert pen == pytest.approx(0.286, abs=1e-3)


@pytest.mark.parametrize("angle_deg, speed_after", [(5.0, 28.84), (15.0, 25.88), (30.0, 20.07), (60.0, 5.99), (90.0, 4.50)])
def test_track_wall_takes_speed_away_by_the_angle_of_the_hit(angle_deg, speed_after):
    # 毎秒30 mで、左の壁へ当たる。当たった後の速さは、設計の「コース」の表と、試作の実測の値。
    course = loop()
    angle = math.radians(angle_deg)
    (x, z, wvx, wvz, hit, impact), _ = push(course, 100.0, 13.5, angle, 30.0)
    assert hit is True and impact == pytest.approx(30.0 * math.sin(angle))
    assert math.hypot(wvx, wvz) == pytest.approx(speed_after, abs=0.01)
    assert wvz == pytest.approx(-0.15 * 30.0 * math.sin(angle))  # 壁へ向かう速度は、反発の割合で跳ね返る
    assert -1e-9 <= wvx < 30.0 * math.cos(angle) + 1e-9  # 壁に沿う速度は、摩擦で減る（向きは変わらない）
    # 押し戻した後は、めり込んでいない。壁に沿っては、動かさない。
    after = course.query(x, z)
    assert course.wall_contact(after, angle, HALF_LENGTH_M, HALF_WIDTH_M)[0] == pytest.approx(0.0, abs=1e-9)
    assert after.s == pytest.approx(100.0, abs=1e-6) and after.lateral < 13.5


def test_track_wall_pushes_a_car_at_rest_out_without_giving_it_speed():
    course = loop()
    (x, z, wvx, wvz, hit, impact), _ = push(course, 100.0, 13.6, 0.3, 0.0)
    assert hit is True and impact == 0.0 and (wvx, wvz) == (0.0, 0.0)
    assert course.wall_contact(course.query(x, z), 0.3, HALF_LENGTH_M, HALF_WIDTH_M)[0] == pytest.approx(0.0, abs=1e-9)


def test_track_wall_leaves_the_velocity_alone_when_the_car_is_already_moving_away():
    course = loop()
    # 車体は壁へ向いたまま、後ろ（壁から離れる向き）へ動いている。押し戻すが、速度は変えない。
    (x, z, wvx, wvz, hit, impact), _ = push(course, 100.0, 13.0, math.pi / 2.0, 3.0, travel=-math.pi / 2.0)
    assert hit is True and impact == 0.0 and (wvx, wvz) == pytest.approx((0.0, -3.0))
    assert course.query(x, z).lateral == pytest.approx(WALL_M - HALF_LENGTH_M, abs=1e-6)


def test_track_wall_does_nothing_when_the_car_does_not_touch_it():
    course = loop()
    x, z, _ = course.pose_at(100.0, 5.0)
    found = course.query(x, z)
    assert course.push_out(found, x, z, 20.0, 9.0, 0.4, HALF_LENGTH_M, HALF_WIDTH_M) == (x, z, 20.0, 9.0, False, 0.0)


def test_track_wall_on_the_right_and_in_the_arc_pushes_back_towards_the_centre_line():
    course = loop()
    # 右の壁（1本目の直線では −z の側）。
    (x, z, wvx, wvz, hit, impact), _ = push(course, 100.0, -13.5, -math.radians(30.0), 30.0)
    assert hit is True and impact == pytest.approx(15.0) and wvz == pytest.approx(0.15 * 15.0) and z > -13.5
    # 半円の外側（右の壁）へ、正面から。押し戻しは、コースの法線の向き（中心線へ寄る）。
    s = STRAIGHT_M + ARC_M / 2.0
    heading = course.pose_at(s)[2] - math.pi / 2.0
    (x, z, wvx, wvz, hit, impact), found = push(course, s, -12.5, heading, 20.0)
    after = course.query(x, z)
    assert hit is True and impact == pytest.approx(20.0, abs=1e-6) and math.hypot(wvx, wvz) == pytest.approx(3.0, abs=1e-6)
    assert after.lateral == pytest.approx(-(WALL_M - HALF_LENGTH_M), abs=1e-3) and after.s == pytest.approx(found.s, abs=1e-3)


# --- 形の検査 ---
def square(side_m: float, per_side: int) -> list:
    """1辺 side_m の正方形を、左回りに回る制御点（1辺を per_side 等分）。"""
    corners = ((0.0, 0.0), (side_m, 0.0), (side_m, side_m), (0.0, side_m))
    points = []
    for index, (x0, z0) in enumerate(corners):
        x1, z1 = corners[(index + 1) % 4]
        points += [{"x_m": x0 + (x1 - x0) * step / per_side, "z_m": z0 + (z1 - z0) * step / per_side} for step in range(per_side)]
    return points


def changed(**values) -> dict:
    entry = loop_entry()
    entry.update(values)
    return entry


def test_track_shape_problems_are_none_for_the_shipped_entry():
    assert track.shape_problems(loop_entry()) == []
    # 半径100 mの円（左回りと、右回り）も通る。
    circle = [{"x_m": 100.0 * math.cos(2.0 * math.pi * index / 40), "z_m": 100.0 * math.sin(2.0 * math.pi * index / 40)} for index in range(40)]
    assert track.shape_problems(changed(control_points=circle)) == []
    assert track.shape_problems(changed(control_points=circle[::-1])) == []
    assert track.build_track(changed(control_points=circle[::-1])).turning == pytest.approx(-2.0 * math.pi, abs=1e-9)


def test_track_shape_check_stops_at_a_degenerate_loop_before_it_builds_the_table():
    points = loop_entry()["control_points"]
    # 点が足りない。
    assert track.shape_problems(changed(control_points=points[:3])) == [(("control_points",), "3 control points (at least 4)")]
    assert track.shape_problems(changed(control_points=[])) == [(("control_points",), "0 control points (at least 4)")]
    # 制御点の間隔が0（同じ点が続く。頭の点を、末尾に繰り返した）。
    repeated = [*points, dict(points[0])]
    assert track.shape_problems(changed(control_points=repeated)) == [
        (("control_points", 72), "this point and the next are 0.000 m apart (at least 0.5; do not repeat the first point at the end)")
    ]
    # 全部が同じ点。どの間隔も、問題。表を作る計算（0で割る）には、進まない。
    same = [{"x_m": 5.0, "z_m": 5.0} for _ in range(6)]
    assert [path for path, _ in track.shape_problems(changed(control_points=same))] == [("control_points", index) for index in range(6)]
    # 短すぎる輪と、長すぎる輪。
    assert track.shape_problems(changed(control_points=square(1.0, 1))) == [(("control_points",), "the loop is 4.0 m long (must be 16.0..20000.0)")]
    assert track.shape_problems(changed(control_points=square(6000.0, 20))) == [(("control_points",), "the loop is 24000.0 m long (must be 16.0..20000.0)")]


def test_track_shape_check_finds_a_loop_that_is_not_closed():
    points = loop_entry()["control_points"]
    assert track.shape_problems(changed(control_points=points[:40])) == [
        (("control_points",), "not closed: the gap from the last point back to the first is 192.9 m (the longest other gap is 12.5 m)")
    ]


def test_track_shape_check_finds_a_figure_of_eight():
    # 8の字。1周の向きの変化が、0になる。
    points = [
        {"x_m": 60.0 * math.sin(2.0 * math.pi * index / 48), "z_m": 30.0 * math.sin(4.0 * math.pi * index / 48)}
        for index in range(48)
    ]
    problems = track.shape_problems(changed(control_points=points, grass_m=0.0, width_m=4.0))
    assert len(problems) == 1 and problems[0][0] == ("control_points",) and problems[0][1].startswith("not one closed loop: the heading turns ")


def test_track_shape_check_finds_a_radius_that_is_too_small_and_an_inner_wall_that_folds():
    # 小さな四角。角の半径が、最小半径（8 m）より小さい。内側の壁（14 m）も、曲率の中心を越える。
    problems = track.shape_problems(changed(control_points=square(30.0, 3)))
    assert [path for path, _ in problems] == [("control_points",), ("control_points",)]
    assert problems[0][1].startswith("radius ") and problems[0][1].endswith("(at least 8.0)")
    assert problems[1][1].startswith("the inner wall (14.0 m from the centre line) folds over at s=")
    # 実物の形のまま、芝を広げる。半径は足りているが、内側の壁（幅の半分6 m＋芝34 m）が、半径45 mに近すぎる。
    problems = track.shape_problems(changed(grass_m=34.0))
    assert len(problems) == 1 and problems[0][1].startswith("the inner wall (40.0 m from the centre line) folds over at s=")
    assert track.shape_problems(changed(grass_m=30.0)) == []  # 1 − 36/45 は、線（0.15）より大きい


def test_track_shape_check_finds_a_start_that_is_off_the_asphalt_or_beyond_the_lap():
    def start(s_m: float, lateral_m: float) -> list:
        return track.shape_problems(changed(start={"s_m": s_m, "lateral_m": lateral_m}))

    assert start(60.0, 5.0) == [] and start(700.0, -5.0) == []
    assert start(60.0, 5.5) == [(("start", "lateral_m"), "5.5 is not on the asphalt (half width 6.0 m, keep 1.0 m from the edge)")]
    assert start(60.0, -9.0) == [(("start", "lateral_m"), "-9.0 is not on the asphalt (half width 6.0 m, keep 1.0 m from the edge)")]
    assert start(800.0, 0.0) == [(("start", "s_m"), "800.0 is beyond the lap length 732.7 m")]


# --- 仮の周回路の制御点を、式から作る補助（tools/claude/make_test_loop.py） ---
def test_track_control_points_of_the_test_loop_are_the_ones_the_formula_gives():
    # 定義データの制御点は、手で書かない。寸法（直線、半径、緩和区間）から作った点と、同じ。試験用データのコースも、同じ点。
    sys.path.append(str(ROOT / "tools" / "claude"))
    import make_test_loop

    points, (gap_m, gap_rad), length = make_test_loop.control_points()
    assert points == loop_entry()["control_points"]
    assert points == data_files.load({data_files.PACK_ENV: "extreme"}, None).entry("tracks", "wide_test_loop")["control_points"]
    assert len(points) == 72 and gap_m < 1e-6 and abs(gap_rad) < 1e-9  # 1周して、頭の点へ戻る
    assert (make_test_loop.STRAIGHT_M, make_test_loop.RADIUS_M, make_test_loop.TRANSITION_M) == (STRAIGHT_M, RADIUS_M, TRANSITION_M)
    assert length == pytest.approx(LAP_M) and loop().length == pytest.approx(length, abs=0.05)
    assert all(type(point["x_m"]) is float and type(point["z_m"]) is float for point in points)
    assert not [point for point in points if str(point["x_m"]).startswith("-0.0") and point["x_m"] == 0.0]  # −0.0 を書かない
    lines = make_test_loop.lines_of(points)
    assert lines[0] == '    {"x_m": 0.0, "z_m": 0.0},' and lines[-1] == '    {"x_m": -12.494, "z_m": 0.289}' and len(lines) == 72
    # 緩和区間は、向きの変化が、円弧へなめらかにつながる（区切りの所で、同じ値）。
    for edge in (make_test_loop.TRANSITION_M, make_test_loop.arc_length() - make_test_loop.TRANSITION_M):
        assert make_test_loop.arc_heading(edge - 1e-9) == pytest.approx(make_test_loop.arc_heading(edge + 1e-9), abs=1e-9)
    assert make_test_loop.arc_heading(make_test_loop.arc_length()) == pytest.approx(math.pi)


def test_track_shape_problems_come_as_key_paths_and_texts():
    for entry in (changed(control_points=square(30.0, 3)), changed(start={"s_m": 800.0, "lateral_m": 9.0}), changed(control_points=[])):
        problems = track.shape_problems(entry)
        assert problems and all(type(path) is tuple and type(message) is str and message for path, message in problems)
