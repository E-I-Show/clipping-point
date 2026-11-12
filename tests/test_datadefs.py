"""定義データの読み込み検査と、試験用データの重ね方（cp_core.datadefs）のテスト。pyxel は読み込まない。

読み込み検査は、ファイルに触れない（受けるのは「相対の名 → 文」の辞書）。ファイルを読むのは、実物の定義データを
辞書にする所（real_sources）だけ。実物の表の定義は、並びと、入れ子の項目を持つ（車の値、コースの形、操作補正の値）。参照と、
省ける項目は、まだ持たない。それらは、作り物の表の定義（FAKE_TABLES）で確かめる。
項目の見本（ENTRY、PACK_CARS など）は、実物の項目を読んで作る（鍵が増えても、見本が、足りない鍵の問題を出さない）。
壊した場合は、どれも DataError になること（ほかの例外にならない）と、問題の行が、狙ったファイルと場所を指すことを見る。
表を足す、項目を足すときは、ここの BROKEN に、その表とその鍵の、壊した場合を足す（足さないと、末尾の節の見張りのテストが落ちる）。
見張りは、入れ子の項目、並びの中の項目、省ける項目の中まで開いて、鍵の道（engine.idle_rpm など）の全部に、壊した場合を求める。
壊した場合の札（どの鍵を壊したか）は、並ぶはずの行の場所と照らす（書いた人の申告のままにしない）。
数、入れ子の項目、並びの鍵の、壊した場合は、鍵の道から作る（GENERATED）。並ぶはずの行は、鍵の道と、決まった文から組み立てる
（読み込み検査の出力からは、作らない）。
項目をまたぐ検査（車の値の矛盾、コースの形の誤り）は、読み込み検査を通して、問題の行の形と、呼ばれる条件を見る。検査の中身は
tests/test_vehicle.py と tests/test_track.py。
ファイルを読む所は tests/test_data_files.py、道具 check の data の節は tests/test_check_tool.py。
"""
import json
import math
import re

import pytest

from conftest import ROOT
from cp_core import camera, car_shape, datadefs, palette, profile, storage, track, vehicle
from cp_core.datadefs import (
    ONE_ENTRY,
    ONE_TABLE,
    TABLES,
    Bool,
    DataError,
    Enum,
    GameData,
    Ident,
    Int,
    Label,
    ListOf,
    Num,
    Obj,
    Opt,
    Ref,
    TableDef,
    load_game_data,
)

DATA = ROOT / "clipping_point" / "data"
CARS, LOOP, ASSISTS = "cars.json", "tracks/test_loop.json", "assists.json"  # 実物の定義データのファイル
CAMERAS, PALETTES = "cameras.json", "palettes.json"  # 同じく、カメラとパレット（段0 区切り10）


def real_sources() -> dict:
    """実物の定義データ。「相対の名 → 文」の辞書。"""
    return {path.relative_to(DATA).as_posix(): path.read_text(encoding="utf-8") for path in sorted(DATA.rglob("*")) if path.is_file()}


def real_car() -> dict:
    """実物の車の項目（kazane）。引くたびに、新しい辞書。"""
    return json.loads(real_sources()[CARS])["cars"][0]


def real_loop() -> dict:
    """実物のコースの項目（test_loop）。ファイルの頭の注は、落とす。引くたびに、新しい辞書。"""
    return without(json.loads(real_sources()[LOOP]), "_notes")


def real_assist() -> dict:
    """実物の操作補正の項目（default）。引くたびに、新しい辞書。"""
    return json.loads(real_sources()[ASSISTS])["assists"][0]


def real_camera() -> dict:
    """実物のカメラの項目（chase）。引くたびに、新しい辞書。"""
    return json.loads(real_sources()[CAMERAS])["cameras"][0]


def real_palette() -> dict:
    """実物のパレットの項目（evening）。引くたびに、新しい辞書。"""
    return json.loads(real_sources()[PALETTES])["palettes"][0]


def without(entry: dict, *keys) -> dict:
    """項目から、鍵を落としたもの。元の辞書は変えない。"""
    return {key: value for key, value in entry.items() if key not in keys}


def edited(name: str, change, sources=None) -> dict:
    """定義データのファイル1つを、JSONとして読んで、change で書き換えたもの。元の辞書は変えない。"""
    sources = dict(real_sources() if sources is None else sources)
    doc = json.loads(sources[name])
    change(doc)
    sources[name] = json.dumps(doc)
    return sources


def with_text(name: str, text, sources=None) -> dict:
    """定義データのファイル1つを、文のまま置き換えたもの（足すこともできる）。"""
    return {**(real_sources() if sources is None else sources), name: text}


def problems_of(sources: dict, pack=None, tables=TABLES) -> list:
    """読み込み検査が並べた問題の行。DataError のほかの例外は、そのまま外へ出る（テストが落ちる）。"""
    with pytest.raises(DataError) as info:
        load_game_data(sources, pack, tables)
    return list(info.value.problems)


# --- 実物の定義データ ---
def test_datadefs_shipped_data_loads_with_no_warnings():
    data = load_game_data(real_sources())
    assert type(data) is GameData
    assert data.warnings == ()  # 出荷するデータは、警告0件
    assert data.counts() == {"cars": 1, "tracks": 1, "assists": 1, "cameras": 1, "palettes": 1}
    assert data.ids("cars") == ("kazane",) and data.ids("tracks") == ("test_loop",) and data.ids("assists") == ("default",)
    assert data.ids("cameras") == ("chase",) and data.ids("palettes") == ("evening",)
    car, loop, assist = data.entry("cars", "kazane"), data.entry("tracks", "test_loop"), data.entry("assists", "default")
    chase, evening = data.entry("cameras", "chase"), data.entry("palettes", "evening")
    assert (car["id"], car["name"], car["data_version"]) == ("kazane", "KAZANE", 1)
    assert (loop["id"], loop["name"], loop["data_version"]) == ("test_loop", "TEST LOOP", 1)
    # 読み込んだ項目は、ファイルの項目と同じ（注の鍵のほかは、何も落とさず、何も足さない）。
    assert car == real_car() and loop == real_loop() and assist == real_assist() and chase == real_camera() and evening == real_palette()
    assert list(car) == list(TABLES["cars"].fields) and list(loop) == list(TABLES["tracks"].fields) and list(assist) == list(TABLES["assists"].fields)
    assert list(chase) == list(TABLES["cameras"].fields) and list(evening) == list(TABLES["palettes"].fields)
    # 走りの値、コースの形、操作補正の値の、頭の所を、数字でも固定する。
    assert car["body"]["mass_kg"] == 960.0 and car["drivetrain"]["gears"] == [3.136, 1.888, 1.33, 1.0, 0.86] and len(car["engine"]["torque_curve"]) == 6
    assert len(loop["control_points"]) == 72 and loop["control_points"][0] == {"x_m": 0.0, "z_m": 0.0} and loop["width_m"] == 12.0
    assert assist["reverse"] == {"stop_speed_m_s": 0.5, "brake_hold_s": 0.5, "pedal_press_min": 0.1}
    # 描画の値（車の仮の形、メッシュの寸法、カメラ、パレット）も、数字で固定する。
    assert car["shape"] == {
        "height_m": 1.24, "body_top_m": 0.78, "roof_front_m": 0.42, "roof_rear_m": -1.0, "roof_inset_m": 0.29, "ground_clearance_m": 0.17, "tire_width_m": 0.22,
    }
    assert loop["mesh"] == {"step_m": 4.0, "road_strips": 4, "line_m": 0.2, "wall_height_m": 0.9, "chunk_m": 60.0}
    assert chase == {"id": "chase", "back_m": 6.2, "height_m": 2.1, "look_ahead_m": 6.0, "look_height_m": 0.9, "fov_deg": 58.0, "near_m": 0.3, "far_m": 300.0}
    assert len(evening["colors"]) == 32 and evening["colors"][0] == 0x16111D and evening["colors"][31] == 0xE26487 and evening["unshaded"] == [15, 30]
    assert data.pack is None and data.save_namespace == "main" == storage.DEFAULT_NAMESPACE


def test_datadefs_shipped_entries_build_the_car_the_track_and_the_controls():
    # 読み込んだ項目から、車の値、コースの表、操作補正の値が作れる（使う側が読む鍵が、表の定義と食い違っていない）。
    from cp_core import controls

    data = load_game_data(real_sources())
    assert vehicle.spec_from_entry(data.entry("cars", "kazane")).car_id == "kazane"
    assert track.build_track(data.entry("tracks", "test_loop")).track_id == "test_loop"
    assert controls.params_from_entry(data.entry("assists", controls.DEFAULT_SET)).brake_hold_ticks == 30
    assert sorted(data.entry("tracks", "test_loop")["surface_mu"]) == sorted(track.SURFACES)  # 路面の種類ごとに、摩擦係数がある
    # 描画の側（車の仮の形、メッシュ用の数値、カメラの値、パレット）も、読み込んだ項目から作れる。使う項目の id は、使う側の定数。
    assert car_shape.build_car_shape(data.entry("cars", "kazane")).triangle_count == 72
    assert len(track.build_track(data.entry("tracks", "test_loop")).mesh_chunks()) == 12
    assert camera.spec_from_entry(data.entry("cameras", camera.CHASE)).camera_id == "chase"
    assert len(palette.palette_from_entry(data.entry("palettes", palette.EVENING)).colors) == palette.COLOR_COUNT == 32


def test_datadefs_shipped_files_carry_their_notes_and_the_notes_are_not_handed_out():
    # 根拠の薄い値は、同じファイルの頭の _notes に「仮の値：<根拠>。<合わせる時>」と書く。注は、使う側へ渡らない。
    for name, text in real_sources().items():
        notes = json.loads(text)["_notes"]
        assert notes and all(note.startswith("仮の値：") for note in notes.values()), name
    data = load_game_data(real_sources())
    for table in TABLES:
        for ident in data.ids(table):
            assert not [key for key in data.entry(table, ident) if key.startswith("_")]


def test_datadefs_real_table_definitions_are_cars_tracks_assists_cameras_and_palettes():
    assert list(TABLES) == ["cars", "tracks", "assists", "cameras", "palettes"]
    assert TABLES["cars"].layout == ONE_TABLE and TABLES["tracks"].layout == ONE_ENTRY and TABLES["assists"].layout == ONE_TABLE
    assert TABLES["cameras"].layout == ONE_TABLE and TABLES["palettes"].layout == ONE_TABLE
    for name in ("cars", "tracks"):
        table = TABLES[name]
        assert list(table.fields)[:3] == ["id", "name", "data_version"]
        assert type(table.fields["id"]) is Ident and type(table.fields["name"]) is Label
        assert table.fields["name"].max_len == datadefs.NAME_MAX == 14  # 車名もコース名も、14字まで
        assert type(table.fields["data_version"]) is Int
        assert (table.fields["data_version"].low, table.fields["data_version"].high) == (1, None)  # データの版は、1以上の整数
    assert list(TABLES["cars"].fields)[3:] == ["body", "steering", "engine", "drivetrain", "lsd", "tires", "suspension", "brakes", "aero", "rest", "outputs", "shape"]
    assert list(TABLES["tracks"].fields)[3:] == ["table", "width_m", "grass_m", "surface_mu", "wall", "start", "mesh", "control_points"]
    assert list(TABLES["assists"].fields) == ["id", "steer", "reverse"] and type(TABLES["assists"].fields["id"]) is Ident
    assert list(TABLES["cameras"].fields) == ["id", "back_m", "height_m", "look_ahead_m", "look_height_m", "fov_deg", "near_m", "far_m"]
    assert list(TABLES["palettes"].fields) == ["id", "colors", "unshaded"]
    assert type(TABLES["cameras"].fields["id"]) is Ident and type(TABLES["palettes"].fields["id"]) is Ident
    assert list(TABLES["cars"].fields["shape"].fields) == ["height_m", "body_top_m", "roof_front_m", "roof_rear_m", "roof_inset_m", "ground_clearance_m", "tire_width_m"]
    assert list(TABLES["tracks"].fields["mesh"].fields) == ["step_m", "road_strips", "line_m", "wall_height_m", "chunk_m"]
    # パレットの色は、ちょうど32個（0〜16,777,215 の整数）。陰影で暗くしない色の番号は、0〜31 が、1個以上。
    colors, unshaded = TABLES["palettes"].fields["colors"], TABLES["palettes"].fields["unshaded"]
    assert type(colors) is ListOf and (colors.min_len, colors.max_len) == (32, 32) and type(colors.item) is Int and (colors.item.low, colors.item.high) == (0, 16777215)
    assert type(unshaded) is ListOf and (unshaded.min_len, unshaded.max_len) == (1, 32) and type(unshaded.item) is Int and (unshaded.item.low, unshaded.item.high) == (0, 31)
    # 項目をまたぐ検査は、車とコースが持つ。検査の関数は、使う側のモジュールに置く（datadefs が読み込む向き）。
    # 車は、車の値の矛盾（vehicle）と、仮の形の寸法の矛盾（car_shape）を、続けて並べる。
    assert TABLES["cars"].check is datadefs.car_problems and TABLES["tracks"].check is track.shape_problems
    assert TABLES["assists"].check is None and TABLES["cameras"].check is None and TABLES["palettes"].check is None
    entry = real_car()
    entry["drivetrain"]["gears"] = [1.0, 2.0]
    entry["shape"]["roof_inset_m"] = 1.0
    assert datadefs.car_problems(entry) == vehicle.spec_problems(entry) + car_shape.shape_problems(entry)
    assert [path for path, _ in datadefs.car_problems(entry)] == [("drivetrain", "gears", 1), ("shape", "roof_inset_m")]
    assert datadefs.car_problems(real_car()) == []
    assert TableDef(ONE_TABLE, {"id": Ident()}).check is None  # 省けば、無い


def zero_is_outside(rule) -> bool:
    return type(rule) is Num and rule.check(0) is not None and rule.check(0.0) is not None


def test_datadefs_values_that_would_divide_by_zero_cannot_be_zero():
    # 0で割ることになる値は、鍵の規則の範囲で、0を外す（車の値を作る計算と、1 tickの計算が、止まらない）。
    car = TABLES["cars"].fields
    for group, keys in (
        ("body", ("mass_kg", "wheelbase_m", "track_m", "front_weight", "yaw_inertia_k")),
        ("engine", ("power_ps", "redline_rpm", "torque_step_rpm", "rpm_smooth_s")),
        ("drivetrain", ("reverse_gear", "final_gear", "wheel_radius_m")),
        ("tires", ("mu", "peak_slip_rad", "curve_c", "low_speed_reg_m_s")),
        ("suspension", ("load_transfer_s",)),
        ("outputs", ("slip_speed_floor_m_s",)),
    ):
        for key in keys:
            assert zero_is_outside(car[group].fields[key]), (group, key)
    assert car["body"].fields["front_weight"].high < 1.0  # 1でも、後軸の荷重が0になる
    assert zero_is_outside(car["drivetrain"].fields["gears"].item) and zero_is_outside(car["engine"].fields["torque_curve"].item.fields["ratio"])
    loop = TABLES["tracks"].fields
    assert all(zero_is_outside(loop["table"].fields[key]) for key in ("sample_step_m", "dense_step_m")) and zero_is_outside(loop["width_m"])
    assert all(zero_is_outside(rule) for rule in loop["surface_mu"].fields.values())  # 摩擦係数が0の路面では、進めない
    assist = TABLES["assists"].fields
    assert zero_is_outside(assist["steer"].fields["limit_min_speed_m_s"]) and zero_is_outside(assist["reverse"].fields["pedal_press_min"])
    assert all(zero_is_outside(assist["steer"].fields[kind].fields["full_time_s"]) for kind in ("analog", "digital"))
    # 描画の値。メッシュの区切りと塊の長さ、路面を割る数、タイヤの幅、画角（焦点距離は、tan(画角÷2) で割る）。
    mesh = loop["mesh"].fields
    assert zero_is_outside(mesh["step_m"]) and zero_is_outside(mesh["chunk_m"]) and zero_is_outside(mesh["line_m"]) and mesh["road_strips"].low == 1
    assert 2.0 * mesh["line_m"].high < loop["width_m"].low  # 白線2本は、舗装の幅の下限に収まる（路面の幅が、0にならない）
    assert zero_is_outside(car["shape"].fields["tire_width_m"]) and zero_is_outside(car["shape"].fields["height_m"])
    lens = TABLES["cameras"].fields
    assert zero_is_outside(lens["fov_deg"]) and lens["fov_deg"].high < 180.0 and zero_is_outside(lens["back_m"]) and zero_is_outside(lens["near_m"])
    assert lens["near_m"].high <= 1.0 < lens["far_m"].low  # 手前は 1.0 を超えない（足元が欠ける）。奥は、いつも、手前より遠い


# --- 実物の定義データを、1か所ずつ壊す。{名前: (表, 札, 壊したファイルの辞書, 並ぶはずの問題の行)} ---
# 札は、壊した鍵の道（頭の階の鍵は name、入れ子の中の鍵は engine.idle_rpm、並びの中の項目の鍵は engine.curve.rpm）。
# どの鍵でもない所を壊した件（知らない鍵、空の表）は None。札は、並ぶはずの行の場所と照らされる（下の見張り）。
def car(**values):
    return edited(CARS, lambda doc: doc["cars"][0].update(values))


def loop(**values):
    return edited(LOOP, lambda doc: doc.update(values))


def assist(**values):
    return edited(ASSISTS, lambda doc: doc["assists"][0].update(values))


def car_group(group: str, **values):
    """実物の車の、入れ子の項目（body、engine など）の中の値を、書き換えたもの。"""
    return edited(CARS, lambda doc: doc["cars"][0][group].update(values))


def loop_mesh(**values):
    """実物のコースの、メッシュの寸法（mesh）の中の値を、書き換えたもの。"""
    return edited(LOOP, lambda doc: doc["mesh"].update(values))


def chase_camera(**values):
    return edited(CAMERAS, lambda doc: doc["cameras"][0].update(values))


def evening_palette(**values):
    return edited(PALETTES, lambda doc: doc["palettes"][0].update(values))


def evening_colors(change):
    """実物のパレットの、色の並びを、change で書き換えたもの。"""
    return edited(PALETTES, lambda doc: change(doc["palettes"][0]["colors"]))


def key_paths(fields: dict, prefix: str = "") -> list:
    """鍵ごとの規則の、鍵の道の全部（定義の順）。入れ子の項目、並びの中の項目、省ける項目の中も開く。

    {"engine": Obj({"idle_rpm": …, "curve": ListOf(Obj({"rpm": …}), …)})} なら、engine、engine.idle_rpm、engine.curve、engine.curve.rpm。
    """
    found = []
    for key, rule in fields.items():
        path = f"{prefix}{key}"
        found.append(path)
        while isinstance(rule, (Opt, ListOf)):  # 省ける項目と並びは、中の規則まで開く
            rule = rule.inner if isinstance(rule, Opt) else rule.item
        if isinstance(rule, Obj):
            found += key_paths(rule.fields, f"{path}.")
    return found


BROKEN = {
    "cars unknown key": ("cars", None, car(nmae="KAZANE"), ["cars.json:cars[0].nmae: unknown key"]),
    "cars missing key": ("cars", "name", edited(CARS, lambda doc: doc["cars"][0].pop("name")), ["cars.json:cars[0].name: missing"]),
    "cars bool where int": ("cars", "data_version", car(data_version=True), ["cars.json:cars[0].data_version: expected an integer, got bool"]),
    "cars string where int": ("cars", "data_version", car(data_version="1"), ["cars.json:cars[0].data_version: expected an integer, got str"]),
    "cars float where int": ("cars", "data_version", car(data_version=1.0), ["cars.json:cars[0].data_version: expected an integer, got float"]),
    "cars out of range": ("cars", "data_version", car(data_version=0), ["cars.json:cars[0].data_version: 0 is outside 1.."]),
    "cars non-ascii label": ("cars", "name", car(name="カザネ"), ["cars.json:cars[0].name: 'カザネ' has characters outside printable ASCII"]),
    "cars label too long": ("cars", "name", car(name="K" * 15), [f"cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)"]),
    "cars empty label": ("cars", "name", car(name=""), ["cars.json:cars[0].name: expected a non-empty text, got ''"]),
    "cars bad id": ("cars", "id", car(id="Kazane RS"), ["cars.json:cars[0].id: 'Kazane RS' is not an id (lowercase ASCII, digits, _)"]),
    "cars duplicate id": (
        "cars", "id", edited(CARS, lambda doc: doc["cars"].append(dict(doc["cars"][0]))), ["cars.json:cars[1].id: duplicate id 'kazane'"],
    ),
    "cars empty table": ("cars", None, edited(CARS, lambda doc: doc["cars"].clear()), ["cars.json:cars: no entries"]),
    "tracks unknown key": ("tracks", None, loop(lenght_m=1800), ["tracks/test_loop.json:lenght_m: unknown key"]),
    "tracks missing key": (
        "tracks", "data_version", edited(LOOP, lambda doc: doc.pop("data_version")), ["tracks/test_loop.json:data_version: missing"],
    ),
    "tracks bool where int": ("tracks", "data_version", loop(data_version=False), ["tracks/test_loop.json:data_version: expected an integer, got bool"]),
    "tracks out of range": ("tracks", "data_version", loop(data_version=-3), ["tracks/test_loop.json:data_version: -3 is outside 1.."]),
    "tracks non-ascii label": ("tracks", "name", loop(name="テスト"), ["tracks/test_loop.json:name: 'テスト' has characters outside printable ASCII"]),
    "tracks label too long": ("tracks", "name", loop(name="TEST LOOP LONG!"), ["tracks/test_loop.json:name: 'TEST LOOP LONG!' is 15 characters (at most 14)"]),
    "tracks file name differs from id": (
        "tracks", "id", loop(id="other_loop"), ["tracks/test_loop.json:id: 'other_loop' does not match the file name 'test_loop'"],
    ),
    "tracks bad id": (
        "tracks", "id", {**without(real_sources(), LOOP), "tracks/Test Loop.json": json.dumps({**real_loop(), "id": "Test Loop"})},
        ["tracks/Test Loop.json:id: 'Test Loop' is not an id (lowercase ASCII, digits, _)"],
    ),
    "assists unknown key": ("assists", None, assist(steeer={}), ["assists.json:assists[0].steeer: unknown key"]),
    "assists bad id": ("assists", "id", assist(id="Default Set"), ["assists.json:assists[0].id: 'Default Set' is not an id (lowercase ASCII, digits, _)"]),
    "assists empty table": ("assists", None, edited(ASSISTS, lambda doc: doc["assists"].clear()), ["assists.json:assists: no entries"]),
    # 入れ子の項目の中の、知らない鍵（鍵の名の打ち間違い）。
    "cars unknown key in a group": ("cars", None, car_group("body", mass=960.0), ["cars.json:cars[0].body.mass: unknown key"]),
    "tracks unknown key in a point": (
        "tracks", None, edited(LOOP, lambda doc: doc["control_points"][3].update(y_m=0.0)), ["tracks/test_loop.json:control_points[3].y_m: unknown key"],
    ),
    # 並びの中の値。3番目の変速比が、数でない。
    "cars gear that is not a number": (
        "cars", "drivetrain.gears", car_group("drivetrain", gears=[3.136, 1.888, "1.33", 1.0, 0.86]),
        ["cars.json:cars[0].drivetrain.gears[2]: expected a number, got str"],
    ),
    # 項目をまたぐ検査（車の値の矛盾、コースの形の誤り）。問題の行は、ほかの問題と同じ形（ファイルと、鍵の道）。
    "cars gear ratios that do not fall": (
        "cars", "drivetrain.gears", car_group("drivetrain", gears=[3.136, 1.888, 1.888, 1.0, 0.86]),
        ["cars.json:cars[0].drivetrain.gears[2]: gear ratio 1.888 is not below the gear before it (1.888)"],
    ),
    "cars torque points that do not rise": (
        "cars", "engine.torque_curve.rpm", edited(CARS, lambda doc: doc["cars"][0]["engine"]["torque_curve"][3].update(rpm=4500.0)),
        ["cars.json:cars[0].engine.torque_curve[3].rpm: rpm 4500.0 is not above the point before it (4500.0)"],
    ),
    "tracks loop that is not closed": (
        "tracks", "control_points", edited(LOOP, lambda doc: doc.update(control_points=doc["control_points"][:40])),
        ["tracks/test_loop.json:control_points: not closed: the gap from the last point back to the first is 192.9 m (the longest other gap is 12.5 m)"],
    ),
    "tracks first point repeated at the end": (
        "tracks", "control_points", edited(LOOP, lambda doc: doc["control_points"].append(dict(doc["control_points"][0]))),
        ["tracks/test_loop.json:control_points[72]: this point and the next are 0.000 m apart (at least 0.5; do not repeat the first point at the end)"],
    ),
    "tracks inner wall that folds over": (
        "tracks", "control_points", loop(grass_m=34.0),
        ["tracks/test_loop.json:control_points: the inner wall (40.0 m from the centre line) folds over at s=679 m (radius 44.8 m)"],
    ),
    "tracks start off the asphalt": (
        "tracks", "start.lateral_m", loop(start={"s_m": 60.0, "lateral_m": 5.5}),
        ["tracks/test_loop.json:start.lateral_m: 5.5 is not on the asphalt (half width 6.0 m, keep 1.0 m from the edge)"],
    ),
    "tracks start beyond the lap": (
        "tracks", "start.s_m", loop(start={"s_m": 800.0, "lateral_m": 0.0}),
        ["tracks/test_loop.json:start.s_m: 800.0 is beyond the lap length 732.7 m"],
    ),
    # 描画の値（段0 区切り10）。メッシュの寸法の、整数の鍵（数の鍵の、型と範囲は、下で、鍵の道から作る）。
    "tracks unknown key in the mesh": ("tracks", None, loop_mesh(lod_m=30.0), ["tracks/test_loop.json:mesh.lod_m: unknown key"]),
    "tracks mesh strips that are not an integer": (
        "tracks", "mesh.road_strips", loop_mesh(road_strips=4.0), ["tracks/test_loop.json:mesh.road_strips: expected an integer, got float"],
    ),
    "tracks mesh with no strips": ("tracks", "mesh.road_strips", loop_mesh(road_strips=0), ["tracks/test_loop.json:mesh.road_strips: 0 is outside 1..16"]),
    # 車の仮の形の、寸法の矛盾（項目をまたぐ検査。cp_core/car_shape.py）。
    "cars shape body box below the ground clearance": (
        "cars", "shape.body_top_m", car_group("shape", ground_clearance_m=0.9),
        ["cars.json:cars[0].shape.body_top_m: 0.78 is not above the ground clearance (0.9)"],
    ),
    "cars shape height below the body box": (
        "cars", "shape.height_m", car_group("shape", height_m=0.7), ["cars.json:cars[0].shape.height_m: 0.7 is not above the top of the body box (0.78)"],
    ),
    "cars shape roof ahead of the nose": (
        "cars", "shape.roof_front_m", car_group("shape", roof_front_m=2.5), ["cars.json:cars[0].shape.roof_front_m: 2.5 is ahead of the nose (half length 2.1)"],
    ),
    "cars shape roof behind the tail": (
        "cars", "shape.roof_rear_m", car_group("shape", roof_rear_m=-2.5), ["cars.json:cars[0].shape.roof_rear_m: -2.5 is behind the tail (half length 2.1)"],
    ),
    "cars shape roof squeezed to nothing": (
        "cars", "shape.roof_inset_m", car_group("shape", roof_inset_m=0.9), ["cars.json:cars[0].shape.roof_inset_m: 0.9 leaves no roof (half width 0.85)"],
    ),
    # カメラ。
    "cameras unknown key": ("cameras", None, chase_camera(distance_m=6.2), ["cameras.json:cameras[0].distance_m: unknown key"]),
    "cameras bad id": ("cameras", "id", chase_camera(id="Chase Cam"), ["cameras.json:cameras[0].id: 'Chase Cam' is not an id (lowercase ASCII, digits, _)"]),
    "cameras empty table": ("cameras", None, edited(CAMERAS, lambda doc: doc["cameras"].clear()), ["cameras.json:cameras: no entries"]),
    "cameras near plane beyond one metre": ("cameras", "near_m", chase_camera(near_m=3.0), ["cameras.json:cameras[0].near_m: 3.0 is outside 0.01..1.0"]),
    "cameras field of view of a half turn": ("cameras", "fov_deg", chase_camera(fov_deg=180.0), ["cameras.json:cameras[0].fov_deg: 180.0 is outside 10.0..120.0"]),
    # パレット。色は、ちょうど32個の、0〜16,777,215 の整数。
    "palettes unknown key": ("palettes", None, evening_palette(colours=[]), ["palettes.json:palettes[0].colours: unknown key"]),
    "palettes bad id": ("palettes", "id", evening_palette(id="Evening"), ["palettes.json:palettes[0].id: 'Evening' is not an id (lowercase ASCII, digits, _)"]),
    "palettes empty table": ("palettes", None, edited(PALETTES, lambda doc: doc["palettes"].clear()), ["palettes.json:palettes: no entries"]),
    "palettes 31 colours": (
        "palettes", "colors", evening_colors(lambda colors: colors.pop()), ["palettes.json:palettes[0].colors: expected a list of 32..32 items, got 31"],
    ),
    "palettes 33 colours": (
        "palettes", "colors", evening_colors(lambda colors: colors.append(0)), ["palettes.json:palettes[0].colors: expected a list of 32..32 items, got 33"],
    ),
    "palettes colour beyond 24 bits": (
        "palettes", "colors", evening_colors(lambda colors: colors.__setitem__(3, 0x1000000)),
        ["palettes.json:palettes[0].colors[3]: 16777216 is outside 0..16777215"],
    ),
    "palettes negative colour": (
        "palettes", "colors", evening_colors(lambda colors: colors.__setitem__(31, -1)), ["palettes.json:palettes[0].colors[31]: -1 is outside 0..16777215"],
    ),
    "palettes colour written as a hex text": (
        "palettes", "colors", evening_colors(lambda colors: colors.__setitem__(0, "16111D")), ["palettes.json:palettes[0].colors[0]: expected an integer, got str"],
    ),
    "palettes colour that is a float": (
        "palettes", "colors", evening_colors(lambda colors: colors.__setitem__(5, 15848639.0)), ["palettes.json:palettes[0].colors[5]: expected an integer, got float"],
    ),
    "palettes unshaded number beyond 31": (
        "palettes", "unshaded", evening_palette(unshaded=[15, 32]), ["palettes.json:palettes[0].unshaded[1]: 32 is outside 0..31"],
    ),
}

# --- 数、入れ子の項目、並びの鍵の、壊した場合を、鍵の道から作る ---
# 表ごとの、(実物のファイル, 問題の行の、項目までの頭, ファイルの中身から項目を取る関数)。
HEADS = {
    "cars": (CARS, "cars.json:cars[0].", lambda doc: doc["cars"][0]),
    "tracks": (LOOP, "tracks/test_loop.json:", lambda doc: doc),
    "assists": (ASSISTS, "assists.json:assists[0].", lambda doc: doc["assists"][0]),
    "cameras": (CAMERAS, "cameras.json:cameras[0].", lambda doc: doc["cameras"][0]),
    "palettes": (PALETTES, "palettes.json:palettes[0].", lambda doc: doc["palettes"][0]),
}
MISSING = object()  # 鍵を消す、の印


def rules_along(fields: dict, path: str) -> list:
    """鍵の道（engine.torque_curve.rpm）を、[(鍵, その鍵の規則)] にする。省ける項目は、中の規則にする。"""
    steps = []
    for key in path.split("."):
        rule = fields[key]
        if isinstance(rule, Opt):
            rule = rule.inner
        steps.append((key, rule))
        inner = rule.item if isinstance(rule, ListOf) else rule
        fields = inner.fields if isinstance(inner, Obj) else {}
    return steps


def set_at(entry: dict, steps: list, value) -> str:
    """項目の、鍵の道の所へ、値を置く（MISSING なら、鍵を消す）。並びの中は、頭の項目。返すのは、問題の行に出る場所（engine.torque_curve[0].rpm）。"""
    holder, where = entry, []
    for key, rule in steps[:-1]:
        holder = holder[key]
        where.append(key)
        if isinstance(rule, ListOf):
            holder = holder[0]
            where[-1] += "[0]"
    key = steps[-1][0]
    if value is MISSING:
        del holder[key]
    else:
        holder[key] = value
    return ".".join([*where, key])


def generated_cases() -> dict:
    """実物の表の定義の、鍵の道の全部について、壊した場合を作る。{名前: (表, 札, 壊したファイルの辞書, 並ぶはずの問題の行)}。

    どの鍵も、鍵を消す（missing）。数は、型の違い（文字列）と、範囲の外（上限＋1）。入れ子の項目は、型の違い（整数）。
    並びは、型の違い（文字列）と、長さ（空）。並ぶはずの行は、鍵の道と、決まった文から組み立てる（読み込み検査の出力からは、作らない）。
    """
    cases = {}
    for table, (name, head, entry_of) in HEADS.items():
        for path in key_paths(TABLES[table].fields):
            steps = rules_along(TABLES[table].fields, path)
            rule = steps[-1][1]
            changes = [("missing", MISSING, "missing")]
            if type(rule) is Num:
                too_big = rule.high + 1
                changes += [("wrong type", "x", "expected a number, got str"), ("out of range", too_big, f"{too_big} is outside {rule.low}..{rule.high}")]
            elif type(rule) is Obj:
                changes += [("wrong type", 5, "expected an object, got int")]
            elif type(rule) is ListOf:
                changes += [
                    ("wrong type", "x", "expected a list, got str"),
                    ("empty", [], f"expected a list of {rule.min_len}..{rule.max_len} items, got 0"),
                ]
            for label, value, message in changes:
                places = []
                sources = edited(name, lambda doc: places.append(set_at(entry_of(doc), steps, value)))  # noqa: B023 - その場で呼ばれる
                cases[f"{table} {path} {label}"] = (table, path, sources, [f"{head}{places[0]}: {message}"])
    return cases


GENERATED = generated_cases()
assert not set(GENERATED) & set(BROKEN)
BROKEN.update(GENERATED)


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_datadefs_broken_shipped_data_is_rejected_with_the_file_and_the_place(case):
    _, _, sources, want = BROKEN[case]
    assert problems_of(sources) == want


def test_datadefs_the_longest_name_and_the_first_data_version_pass():
    data = load_game_data(car(name="K" * 14, data_version=1))
    assert data.entry("cars", "kazane")["name"] == "K" * 14
    assert load_game_data(car(name="A b-1!", data_version=10 ** 12)).entry("cars", "kazane")["data_version"] == 10 ** 12


def test_datadefs_three_planted_problems_are_all_listed():
    # 最初の1件で止めず、全部を並べる。ファイルをまたいでも、同じ。
    sources = edited(CARS, lambda doc: doc["cars"][0].update(nmae="X", name="K" * 15))
    sources = edited(LOOP, lambda doc: doc.update(data_version=0), sources)
    assert problems_of(sources) == [
        "cars.json:cars[0].nmae: unknown key",
        f"cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)",
        "tracks/test_loop.json:data_version: 0 is outside 1..",
    ]


def test_datadefs_error_text_has_the_count_and_every_line():
    with pytest.raises(DataError) as info:
        load_game_data(edited(CARS, lambda doc: doc["cars"][0].update(nmae="X", data_version=0)))
    assert isinstance(info.value, ValueError) and type(info.value.problems) is tuple
    assert str(info.value) == "2 data problem(s):\n  cars.json:cars[0].nmae: unknown key\n  cars.json:cars[0].data_version: 0 is outside 1.."


# --- JSONの読み。重複した鍵、NaN、Infinity、読めない文、読めなかったファイル ---
@pytest.mark.parametrize(
    "name, text, want",
    [
        (CARS, '{"cars": [{"id": "kazane", "name": "A", "name": "KAZANE", "data_version": 1}]}', "cars.json: duplicate key 'name'"),
        (CARS, '{"cars": [], "cars": [{"id": "kazane", "name": "KAZANE", "data_version": 1}]}', "cars.json: duplicate key 'cars'"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "data_version": NaN}', "tracks/test_loop.json: NaN is not accepted (not a JSON number)"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "data_version": Infinity}', "tracks/test_loop.json: Infinity is not accepted (not a JSON number)"),
        (LOOP, '{"id": "test_loop", "name": "TEST LOOP", "_note": -Infinity, "data_version": 1}', "tracks/test_loop.json: -Infinity is not accepted (not a JSON number)"),
    ],
)
def test_datadefs_duplicate_keys_and_nan_are_problems_of_the_file(name, text, want):
    # 標準の読み方は、重複した鍵を後勝ちで黙って通し、NaN も通す。注の中の NaN も、JSONの文としては受けない。
    assert problems_of(with_text(name, text)) == [want]


ENTRY = real_car()  # 実物の車の項目。読み込み検査を通る、項目の見本
# 2つ目の車。実物の項目から作る。知らない鍵、足りない鍵（表示名）、範囲の外（データの版）。
SECOND_CAR_BROKEN = json.dumps({**without(ENTRY, "name"), "id": "second", "nmae": "X", "data_version": 0})
SECOND_CAR_LINES = ["cars.json:cars[1].nmae: unknown key", "cars.json:cars[1].name: missing", "cars.json:cars[1].data_version: 0 is outside 1.."]


@pytest.mark.parametrize(
    "first, want",
    [
        pytest.param('{"id": "kazane", "name": "A", "name": "KAZANE", "data_version": 1}', "cars.json: duplicate key 'name'", id="duplicate_key"),
        pytest.param(
            '{"id": "kazane", "name": "KAZANE", "_trial": NaN, "data_version": 1}', "cars.json: NaN is not accepted (not a JSON number)",
            id="nan_in_a_note",
        ),
        pytest.param(
            '{"id": "kazane", "name": "KAZANE", "data_version": Infinity}', "cars.json: Infinity is not accepted (not a JSON number)",
            id="infinity",
        ),
    ],
)
def test_datadefs_file_with_a_duplicate_key_or_nan_is_handled_like_a_file_that_is_not_json(first, want):
    # 決め：重複した鍵か、NaN・無限大のあるファイルは、JSONが読めないファイルと同じ扱い。そのファイルの項目は、検査へ渡さない。
    # 1つ目の項目に重複した鍵（か NaN）、2つ目の項目に、ほかの問題。並ぶのは、JSONの文を読む所の行だけ。
    # 後勝ちの値で検査を続ける形にはしない（誤った値を検査して、原因と違う行が並ぶ）。
    text = f'{{"cars": [{first}, {SECOND_CAR_BROKEN}]}}'
    assert problems_of(with_text(CARS, text)) == [want]
    # 対：1つ目の項目が読める文なら、2つ目の項目の問題は、全部並ぶ（2つ目の項目の問題が、見本に実際にあること）。
    plain = f'{{"cars": [{json.dumps(ENTRY)}, {SECOND_CAR_BROKEN}]}}'
    assert problems_of(with_text(CARS, plain)) == SECOND_CAR_LINES
    # JSONでないファイルも、同じ形（そのファイルの行が1つだけ）。
    cut = problems_of(with_text(CARS, plain[:-1]))
    assert len(cut) == 1 and cut[0].startswith("cars.json: cannot read: not JSON")
    # ほかのファイルの問題は、一緒に並ぶ。
    both = edited(LOOP, lambda doc: doc.update(data_version=0), with_text(CARS, text))
    assert problems_of(both) == [want, "tracks/test_loop.json:data_version: 0 is outside 1.."]
    # 試験用データの側でも、同じ。
    assert problems_of(real_sources(), ("p", {CARS: text})) == [f"testpacks/p/{want}"]


def test_datadefs_references_to_a_file_that_handed_no_entry_are_listed_as_missing():
    # 参照される側の表のファイルが、項目を検査へ渡さなかった（重複した鍵、JSONでない）。その表への参照は、どれも
    # 「無い id への参照」として並ぶ。どちらの場合も、同じ形（重複した鍵のファイルを、読めないファイルと同じに扱う）。
    refs = ["cars.json:cars[0].sound: no sounds with id 'eng_na'"]
    sources = fake_sources()
    sources["sounds.json"] = '{"sounds": [{"id": "eng_na", "kind": "engine", "kind": "engine"}]}'
    assert problems_of(sources, tables=FAKE_TABLES) == ["sounds.json: duplicate key 'kind'", *refs]
    sources["sounds.json"] = '{"sounds": [{"id": "eng_na", "kind": "engine"}'
    got = problems_of(sources, tables=FAKE_TABLES)
    assert len(got) == 2 and got[0].startswith("sounds.json: cannot read: not JSON") and got[1:] == refs


@pytest.mark.parametrize(
    "text",
    [
        "", "{", '{"cars": [}', "{'cars': []}", '{"cars": [1,]}',
        # BOMつきの文。見えない字（U+FEFF）は、ソースに直に置かず、名前のエスケープで書く（書き直しや整形で消えると、"{}" になって、
        # 狙いと違う理由で落ちる）。
        pytest.param("\N{BYTE ORDER MARK}{}", id="bom"),
        pytest.param("[" * 100000 + "]" * 100000, id="nested_too_deep"),
    ],
)
def test_datadefs_text_that_is_not_json_is_a_problem_of_the_file(text):
    # JSONでない文と、入れ子が深すぎる文。どちらも、そのファイルの問題（ほかの例外にしない）。
    got = problems_of(with_text(CARS, text))
    assert len(got) == 1 and got[0].startswith("cars.json: cannot read: ")


@pytest.mark.parametrize("value", [None, b'{"cars": []}', 5, ["x"]])
def test_datadefs_file_that_could_not_be_read_is_a_problem_of_the_file(value):
    # 読めなかったファイルは、読む所（cp_app/data_files.py）が、値を None にして渡す。文字列でなければ、どれも問題。
    assert problems_of(with_text(CARS, value)) == ["cars.json: cannot read the file"]
    assert problems_of(with_text(LOOP, value)) == ["tracks/test_loop.json: cannot read the file"]


def test_datadefs_number_too_big_for_a_float_is_not_a_number():
    # 1e999 は、標準の読み方で無限大になる（NaN と違い、JSONの文を読む所では止まらない）。数の規則が受けない。
    tables = {"cars": TableDef(ONE_TABLE, {"id": Ident(), "mass": Num(500, 2500)})}
    assert problems_of({"cars.json": '{"cars": [{"id": "a", "mass": 1e999}]}'}, tables=tables) == ["cars.json:cars[0].mass: inf is not a finite number"]


# --- 知らないファイル、2つの形に当たらない名、無いファイル ---
@pytest.mark.parametrize(
    "name",
    [
        "notes.txt",  # .json でない
        "sounds.json",  # 表の定義に無い名
        "tracks.json",  # 1ファイル1項目の表を、1ファイル1表の形で置いた
        "cars/kazane.json",  # 1ファイル1表の表を、1ファイル1項目の形で置いた
        "tracks/deep/test_loop.json",  # 深い階
        "tracks/readme.md",
        "tracks/.json",
        "sounds/engine.json",  # 知らないディレクトリ
        "CARS.JSON",
    ],
)
def test_datadefs_file_that_no_table_reads_is_a_problem(name):
    # 拾わない名を、黙って無視しない。中身は読まない（JSONでなくても、読めなくても、問題は1つ）。
    for text in ("{}", "not json", None):
        assert problems_of(with_text(name, text)) == [f"{name}: unknown file (no table reads this name)"]


def test_datadefs_missing_table_files_are_problems():
    sources = real_sources()
    assert problems_of(without(sources, CARS)) == ["cars.json: missing file"]
    assert problems_of(without(sources, LOOP)) == ["tracks/: no entry files"]
    assert problems_of(without(sources, ASSISTS)) == ["assists.json: missing file"]
    assert problems_of(without(sources, CAMERAS)) == ["cameras.json: missing file"]
    assert problems_of(without(sources, PALETTES)) == ["palettes.json: missing file"]
    assert problems_of({CARS: sources[CARS]}) == ["tracks/: no entry files", "assists.json: missing file", "cameras.json: missing file", "palettes.json: missing file"]
    assert problems_of({}) == [
        "cars.json: missing file", "tracks/: no entry files", "assists.json: missing file", "cameras.json: missing file", "palettes.json: missing file",
    ]


# --- ファイルの頭の形の誤り。2つの形のそれぞれで ---
LOOP_ENTRY = real_loop()  # 実物のコースの項目。読み込み検査を通る、項目の見本
# コースの項目の、id のほかの鍵が、全部足りないときに並ぶ行（表の定義の順）。
LOOP_KEYS_MISSING = [
    f"tracks/test_loop.json:{key}: missing"
    for key in ("name", "data_version", "table", "width_m", "grass_m", "surface_mu", "wall", "start", "mesh", "control_points")
]


@pytest.mark.parametrize(
    "doc, want",
    [
        ([ENTRY], ['cars.json: the file must be {"cars": [...]}, got list']),
        ("cars", ['cars.json: the file must be {"cars": [...]}, got str']),
        (None, ['cars.json: the file must be {"cars": [...]}, got NoneType']),
        ({}, ['cars.json:cars: missing (the file must be {"cars": [...]})']),
        ({"car": [ENTRY]}, ["cars.json:car: unknown key at the top level (only 'cars' and notes)", 'cars.json:cars: missing (the file must be {"cars": [...]})']),
        ({"cars": [ENTRY], "extra": 1, "more": 2}, ["cars.json:extra: unknown key at the top level (only 'cars' and notes)", "cars.json:more: unknown key at the top level (only 'cars' and notes)"]),
        ({"cars": {"kazane": ENTRY}}, ["cars.json:cars: expected a list of entries, got dict"]),
        ({"cars": None}, ["cars.json:cars: expected a list of entries, got NoneType"]),
        ({"cars": [ENTRY, 5, "x", [ENTRY]]}, [
            "cars.json:cars[1]: expected an entry (an object), got int",
            "cars.json:cars[2]: expected an entry (an object), got str",
            "cars.json:cars[3]: expected an entry (an object), got list",
        ]),
        ({"cars": [without(ENTRY, "id")]}, ["cars.json:cars[0].id: missing"]),
        ({"cars": [{**ENTRY, "id": 7}]}, ["cars.json:cars[0].id: expected a string id, got int"]),
        ({"cars": [{**ENTRY, "id": None}]}, ["cars.json:cars[0].id: expected a string id, got NoneType"]),
        # id が無い項目も、ほかの鍵は照らす（全部を並べる）。
        ({"cars": [{**without(ENTRY, "id", "data_version"), "name": "", "nmae": 1}]}, ["cars.json:cars[0].id: missing", "cars.json:cars[0].nmae: unknown key", "cars.json:cars[0].name: expected a non-empty text, got ''", "cars.json:cars[0].data_version: missing"]),
        # 3つの鍵だけの項目（走りの値が無い）。足りない鍵が、全部並ぶ。
        ({"cars": [{"id": "kazane", "name": "KAZANE", "data_version": 1}]}, [f"cars.json:cars[0].{key}: missing" for key in list(TABLES["cars"].fields)[3:]]),
    ],
)
def test_datadefs_one_table_file_with_a_wrong_head_is_a_problem_of_the_file(doc, want):
    assert problems_of(with_text(CARS, json.dumps(doc))) == want


@pytest.mark.parametrize(
    "doc, want",
    [
        ([LOOP_ENTRY], ["tracks/test_loop.json: the file must be one entry (an object), got list"]),
        ("test_loop", ["tracks/test_loop.json: the file must be one entry (an object), got str"]),
        (3, ["tracks/test_loop.json: the file must be one entry (an object), got int"]),
        (without(LOOP_ENTRY, "id"), ["tracks/test_loop.json:id: missing"]),
        ({**LOOP_ENTRY, "id": ["test_loop"]}, ["tracks/test_loop.json:id: expected a string id, got list"]),
        ({}, ["tracks/test_loop.json:id: missing", *LOOP_KEYS_MISSING]),
        # 1ファイル1表の形（{"tracks": […]}）で置いた。
        ({"tracks": [LOOP_ENTRY]}, ["tracks/test_loop.json:id: missing", "tracks/test_loop.json:tracks: unknown key", *LOOP_KEYS_MISSING]),
    ],
)
def test_datadefs_one_entry_file_with_a_wrong_head_is_a_problem_of_the_file(doc, want):
    assert problems_of(with_text(LOOP, json.dumps(doc))) == want


WEIRD = [None, True, False, 0, 1, -1, 1.5, "", "x", [], [None], [[]], {}, {"id": None}, {"id": []}, {"id": {}}, {"cars": 1}, {"_": 1}]


def test_datadefs_strange_values_anywhere_never_raise_anything_but_data_error():
    # 変な値を、ファイルの頭、表の値、項目、id、ほかの鍵に置く。DataError のほかの例外（KeyError、TypeError）にならない。
    for value in WEIRD:
        for sources in (
            with_text(CARS, json.dumps(value)),
            with_text(CARS, json.dumps({"cars": value})),
            with_text(CARS, json.dumps({"cars": [value]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "id": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "name": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "extra": value}]})),
            with_text(LOOP, json.dumps(value)),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "id": value})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "data_version": value})),
            # 入れ子の項目、並び、並びの中の項目に置く。項目をまたぐ検査が読む鍵でも、同じ。
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "body": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "drivetrain": {**ENTRY["drivetrain"], "gears": value}}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "drivetrain": {**ENTRY["drivetrain"], "gears": [value, value]}}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "engine": {**ENTRY["engine"], "torque_curve": value}}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "engine": {**ENTRY["engine"], "torque_curve": [value, value]}}]})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "control_points": value})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "control_points": [value] * 4})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "control_points": [{"x_m": value, "z_m": 0.0}] * 4})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "start": value})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "table": value})),
            with_text(ASSISTS, json.dumps({"assists": [{**real_assist(), "steer": value}]})),
            with_text(ASSISTS, json.dumps({"assists": [{**real_assist(), "reverse": {"stop_speed_m_s": value}}]})),
            # 描画の値。車の仮の形と、メッシュの寸法（項目をまたぐ検査と、表を作る計算が読む鍵）、カメラ、パレット。
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "shape": value}]})),
            with_text(CARS, json.dumps({"cars": [{**ENTRY, "shape": {**ENTRY["shape"], "roof_front_m": value}}]})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "mesh": value})),
            with_text(LOOP, json.dumps({**LOOP_ENTRY, "mesh": {**LOOP_ENTRY["mesh"], "road_strips": value}})),
            with_text(CAMERAS, json.dumps(value)),
            with_text(CAMERAS, json.dumps({"cameras": [value]})),
            with_text(CAMERAS, json.dumps({"cameras": [{**real_camera(), "fov_deg": value}]})),
            with_text(PALETTES, json.dumps({"palettes": value})),
            with_text(PALETTES, json.dumps({"palettes": [{**real_palette(), "colors": value}]})),
            with_text(PALETTES, json.dumps({"palettes": [{**real_palette(), "colors": [value] * 32}]})),
            with_text(PALETTES, json.dumps({"palettes": [{**real_palette(), "unshaded": [value]}]})),
        ):
            try:
                load_game_data(sources)
            except DataError as exc:
                assert exc.problems
            # 試験用データの側に置いても、同じ。
            try:
                load_game_data(real_sources(), ("p", sources))
            except DataError as exc:
                heads = ("testpacks/p/", "cars.json", "tracks/", "assists.json", "cameras.json", "palettes.json")
                assert exc.problems and all(line.startswith(heads) for line in exc.problems)


def P(x: float, z: float) -> dict:  # noqa: N802 - 制御点1つ。下の表を、短く書くための名
    return {"x_m": float(x), "z_m": float(z)}


# 鍵ごとの規則は通るが、形が退化したコース。項目をまたぐ検査が、表を作る計算で止まらずに、問題の行にする。
DEGENERATE_LOOPS = {
    "every point is the same point": [P(5, 5)] * 6,
    "two points": [P(0, 0), P(5, 5)],
    "three points": [P(0, 0), P(50, 0), P(0, 50)],
    "the same two points twice": [P(0, 0), P(50, 0), P(0, 0), P(50, 0)],
    "a line there and back": [P(0, 0), P(20, 0), P(40, 0), P(60, 0), P(40, 0), P(20, 0)],
    "four points on a line": [P(0, 0), P(10, 0), P(20, 0), P(30, 0)],
    "two tight pairs far apart": [P(0, 0), P(0.6, 0), P(100, 0), P(100.6, 0)],
    "a sliver": [P(0, 0), P(100, 0), P(100, 0.5), P(0, 0.5)],
    "a zigzag that does not close": [P(index * 5, index % 2 * 5) for index in range(20)],
    "points at the far corners": [P(-20000, -20000), P(20000, -20000), P(20000, 20000), P(-20000, 20000)],
    "a figure of eight": [P(60.0 * math.sin(2.0 * math.pi * index / 48), 30.0 * math.sin(4.0 * math.pi * index / 48)) for index in range(48)],
}


@pytest.mark.parametrize("case", sorted(DEGENERATE_LOOPS))
def test_datadefs_degenerate_loops_are_data_errors_and_never_anything_else(case):
    points = DEGENERATE_LOOPS[case]
    for table in ({"sample_step_m": 2.0, "dense_step_m": 0.25}, {"sample_step_m": 8.0, "dense_step_m": 1.0}, {"sample_step_m": 0.5, "dense_step_m": 0.05}):
        got = problems_of(loop(control_points=points, table=table))  # DataError のほかの例外は、ここで外へ出る
        assert got and all(line.startswith("tracks/test_loop.json:control_points") for line in got), got
    # 試験用データの側に置いても、同じ。
    got = problems_of(real_sources(), ("p", {LOOP: json.dumps({**LOOP_ENTRY, "control_points": points})}))
    assert got and all(line.startswith("testpacks/p/tracks/test_loop.json:control_points") for line in got)


def test_datadefs_degenerate_car_values_are_data_errors_and_never_anything_else():
    # 鍵ごとの規則は通るが、車の値を作る計算が、0で割ることになる値（同じ回転数の点、同じ変速比）。
    flat = [{"rpm": 3000.0, "ratio": 1.0}] * 4
    for sources in (
        car_group("engine", torque_curve=flat),
        car_group("drivetrain", gears=[1.0] * 5),
        car_group("drivetrain", gears=[0.2, 10.0]),
        edited(CARS, lambda doc: (doc["cars"][0]["engine"].update(torque_curve=flat), doc["cars"][0]["drivetrain"].update(gears=[1.0, 1.0]))),
    ):
        got = problems_of(sources)
        assert got and all(line.startswith(("cars.json:cars[0].engine.torque_curve[", "cars.json:cars[0].drivetrain.gears[")) for line in got), got


# --- 規則の部品。1つずつ ---
@pytest.mark.parametrize(
    "rule, good, bad",
    [
        (Int(1, 5), [1, 3, 5], [0, 6, True, False, 1.0, "1", None, [1]]),
        (Int(0), [0, 10 ** 30], [-1, True, 0.0, "0"]),
        (Num(0.5, 2.5), [1, 2, 0.5, 2.5, 1.25], [0, 3, 0.49, True, "1.5", None, float("nan"), float("inf"), float("-inf"), 10 ** 400]),
        (Bool(), [True, False], [0, 1, "true", None]),
        (Enum("FF", "FR"), ["FF", "FR"], ["RR", "ff", "", 1, None, ["FF"]]),
        (Ident(), ["kazane", "a", "test_loop", "x_1", "9lives"], ["", "Kazane", "a b", "a-b", "a.b", "é", 5, None, ["a"]]),
        (Label(14), ["KAZANE", "A", "K" * 14, "A b-1!~"], ["", "K" * 15, "カザネ", "A\tB", "A\nB", "é", "\x7f", 5, None, ["A"]]),
        (Ref("cars"), ["kazane", ""], [5, None, ["kazane"], True]),
        (ListOf(Int(0), 1, 3), [[1], [1, 2, 3], ["not checked here"]], [[], [1, 2, 3, 4], "abc", (1,), None, {"0": 1}]),
        (Obj({"a": Int(0)}), [{}, {"a": "not checked here"}], [[], "x", None, 5]),
    ],
)
def test_datadefs_rule_part_accepts_and_rejects(rule, good, bad):
    # 規則の部品は、値を受けて、問題の文（無ければ None）を返す。並びと入れ子の項目は、自分の階だけを見る（中は、読み込み検査が照らす）。
    for value in good:
        assert rule.check(value) is None, value
    for value in bad:
        message = rule.check(value)
        assert type(message) is str and message, value


# --- 作り物の表の定義。参照、並び、入れ子の項目、省ける項目、列挙、数、真偽 ---
FAKE_TABLES = {
    "sounds": TableDef(ONE_TABLE, {"id": Ident(), "kind": Enum("engine", "sfx"), "base_hz": Opt(Num(20, 2000))}),
    "cars": TableDef(ONE_TABLE, {
        "id": Ident(),
        "name": Label(14),
        "turbo": Bool(),
        "sound": Ref("sounds"),
        "gears": ListOf(Num(0.5, 5.0), 2, 4),
        "engine": Obj({"idle_rpm": Int(500, 2000), "curve": ListOf(Obj({"rpm": Int(0, 9000), "torque": Num(0, 500)}), 1, 4)}),
        "extras": Opt(ListOf(Ref("sounds"), 0, 3)),
    }),
    "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "name": Label(14), "cars": ListOf(Ref("cars"), 1, 3)}),
}
FAKE_CAR = {
    "id": "kazane", "name": "KAZANE", "turbo": False, "sound": "eng_na", "gears": [3.2, 1.9, 1.0],
    "engine": {"idle_rpm": 900, "curve": [{"rpm": 1000, "torque": 120.5}, {"rpm": 6000, "torque": 160}]},
}
FAKE_SOUNDS = [{"id": "eng_na", "kind": "engine", "base_hz": 110}]
FAKE_TRACK = {"id": "test_loop", "name": "TEST LOOP", "cars": ["kazane"]}


def fake_sources(car=None, sounds=None, track=None, cars=None) -> dict:
    """作り物の表の定義に合う、定義データ。car は、車の項目に重ねる値。"""
    rows = [{**FAKE_CAR, **(car or {})}] if cars is None else cars
    return {
        "sounds.json": json.dumps({"sounds": FAKE_SOUNDS if sounds is None else sounds}),
        "cars.json": json.dumps({"cars": rows}),
        "tracks/test_loop.json": json.dumps({**FAKE_TRACK, **(track or {})}),
    }


def test_datadefs_fake_tables_load_and_keep_the_nested_values():
    data = load_game_data(fake_sources(), tables=FAKE_TABLES)
    assert data.warnings == () and data.counts() == {"sounds": 1, "cars": 1, "tracks": 1}
    assert data.entry("cars", "kazane") == FAKE_CAR
    assert data.entry("tracks", "test_loop") == FAKE_TRACK


@pytest.mark.parametrize(
    "car, want",
    [
        ({"turbo": 1}, ["cars.json:cars[0].turbo: expected true or false, got int"]),
        ({"sound": "eng_v8"}, ["cars.json:cars[0].sound: no sounds with id 'eng_v8'"]),  # 無い参照
        ({"sound": 5}, ["cars.json:cars[0].sound: expected an id of sounds, got int"]),
        ({"extras": ["eng_na", "nobody", "also_nobody"]}, [  # 並びの中の、無い参照。2つとも並ぶ
            "cars.json:cars[0].extras[1]: no sounds with id 'nobody'", "cars.json:cars[0].extras[2]: no sounds with id 'also_nobody'",
        ]),
        ({"extras": None}, ["cars.json:cars[0].extras: expected a list, got NoneType"]),  # 省ける項目でも、null は受けない
        ({"gears": [3.2]}, ["cars.json:cars[0].gears: expected a list of 2..4 items, got 1"]),  # 並びの長さ
        ({"gears": [3.2, 1.9, 1.4, 1.0, 0.8]}, ["cars.json:cars[0].gears: expected a list of 2..4 items, got 5"]),
        ({"gears": [3.2, "1.9", 9.0, True]}, [  # 並びの中は、最初の1件で止めない
            "cars.json:cars[0].gears[1]: expected a number, got str",
            "cars.json:cars[0].gears[2]: 9.0 is outside 0.5..5.0",
            "cars.json:cars[0].gears[3]: expected a number, got bool",
        ]),
        ({"gears": "3.2 1.9"}, ["cars.json:cars[0].gears: expected a list, got str"]),
        # 入れ子の中の誤り。鍵の道が付く。
        ({"engine": {"idle_rpm": 100, "curve": [{"rpm": 1000, "torque": 120.5}]}}, ["cars.json:cars[0].engine.idle_rpm: 100 is outside 500..2000"]),
        ({"engine": {"idle_rpm": 900, "curve": [{"rpm": 1000, "torque": 120.5}, {"rpm": -1, "torque": "x", "trq": 1}]}}, [
            "cars.json:cars[0].engine.curve[1].trq: unknown key",
            "cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000",
            "cars.json:cars[0].engine.curve[1].torque: expected a number, got str",
        ]),
        ({"engine": {"idle_rpm": 900}}, ["cars.json:cars[0].engine.curve: missing"]),
        ({"engine": {"idle_rpm": 900, "curve": [5]}}, ["cars.json:cars[0].engine.curve[0]: expected an object, got int"]),
        ({"engine": [900]}, ["cars.json:cars[0].engine: expected an object, got list"]),
    ],
)
def test_datadefs_fake_broken_values_are_rejected_with_the_key_path(car, want):
    assert problems_of(fake_sources(car), tables=FAKE_TABLES) == want


def test_datadefs_value_outside_the_enumeration_and_optional_keys():
    assert problems_of(fake_sources(sounds=[{"id": "eng_na", "kind": "bgm"}]), tables=FAKE_TABLES) == [
        "sounds.json:sounds[0].kind: 'bgm' is not one of ['engine', 'sfx']"
    ]
    # 省ける項目は、無くてもよい。あれば、規則で照らす。
    assert load_game_data(fake_sources(sounds=[{"id": "eng_na", "kind": "engine"}]), tables=FAKE_TABLES).entry("sounds", "eng_na") == {"id": "eng_na", "kind": "engine"}
    assert problems_of(fake_sources(sounds=[{"id": "eng_na", "kind": "engine", "base_hz": 5}]), tables=FAKE_TABLES) == [
        "sounds.json:sounds[0].base_hz: 5 is outside 20..2000"
    ]


def test_datadefs_references_are_checked_after_every_table_is_read():
    # 参照の先の表（sounds）が、参照する側の表（cars）より後ろに定義されていても、同じに読める（表を読む順に頼らない）。
    backwards = {name: FAKE_TABLES[name] for name in ("tracks", "cars", "sounds")}
    data = load_game_data(fake_sources(), tables=backwards)
    assert data.counts() == {"tracks": 1, "cars": 1, "sounds": 1} and data.warnings == ()
    # 1ファイル1項目の表からの、並びの中の参照。
    assert problems_of(fake_sources(track={"cars": ["kazane", "nobody"]}), tables=backwards) == ["tracks/test_loop.json:cars[1]: no cars with id 'nobody'"]


def test_datadefs_unreferenced_definition_is_a_warning_not_a_problem():
    # 参照される側の表（sounds と cars）で、どこからも参照されていない定義は、警告。読み込みは通る。
    sounds = [*FAKE_SOUNDS, {"id": "sfx_unused", "kind": "sfx"}, {"id": "sfx_other", "kind": "sfx"}]
    cars = [FAKE_CAR, {**FAKE_CAR, "id": "spare", "extras": ["sfx_other"]}]
    data = load_game_data(fake_sources(sounds=sounds, cars=cars), tables=FAKE_TABLES)
    assert data.warnings == ("sounds.sfx_unused: defined but never referenced", "cars.spare: defined but never referenced")
    assert data.counts() == {"sounds": 3, "cars": 2, "tracks": 1}
    # 参照されない側の表（tracks）の定義は、警告にならない。実物の表の定義には、参照が無いので、警告は出ない。
    assert load_game_data(fake_sources(), tables=FAKE_TABLES).warnings == ()


def test_datadefs_note_keys_pass_at_every_level_and_are_not_handed_out():
    car = {
        **FAKE_CAR, "_note": "placeholder", "_checked": {"by": "nobody", "_deep": [1, 2]},
        "engine": {
            "idle_rpm": 900, "_note": "idle",
            "curve": [{"rpm": 1000, "torque": 120.5, "_source": ["bench", {"_x": 1}]}, {"rpm": 6000, "torque": 160}],
        },
    }
    sources = {
        "sounds.json": json.dumps({"_notes": {"sounds": "仮の値：…"}, "_more": [1], "sounds": FAKE_SOUNDS}),
        "cars.json": json.dumps({"_notes": "text", "cars": [car]}),
        "tracks/test_loop.json": json.dumps({**FAKE_TRACK, "_notes": {"test_loop": "仮の値：…"}}),
    }
    data = load_game_data(sources, tables=FAKE_TABLES)

    def keys_of(value) -> list:
        if type(value) is dict:
            return [*value, *(key for item in value.values() for key in keys_of(item))]
        return [key for item in value for key in keys_of(item)] if type(value) is list else []

    for table in FAKE_TABLES:
        for ident in data.ids(table):
            assert not [key for key in keys_of(data.entry(table, ident)) if key.startswith("_")], (table, ident)
    assert data.entry("cars", "kazane") == FAKE_CAR and data.entry("tracks", "test_loop") == FAKE_TRACK


def test_datadefs_wrong_table_definitions_are_value_errors_not_data_errors():
    # 表の定義そのものの誤りは、データの問題ではない。
    for tables in (
        {"cars": TableDef("one_per_line", {"id": Ident()})},
        {"cars": TableDef(ONE_TABLE, {"name": Label(14)})},
        {"cars": TableDef(ONE_TABLE, {"id": Label(14)})},
        {"cars": TableDef(ONE_TABLE, {"id": Ident(), "sound": Ref("sounds")})},
        {"cars": TableDef(ONE_TABLE, {"id": Ident(), "engine": Obj({"sounds": ListOf(Ref("sounds"), 0, 2)})})},
    ):
        with pytest.raises(ValueError) as info:
            load_game_data({}, tables=tables)
        assert not isinstance(info.value, DataError)


# --- 読み込んだ定義 ---
def test_datadefs_ids_come_in_file_order_and_missing_names_are_key_errors():
    cars = [{**FAKE_CAR, "id": "zeta"}, {**FAKE_CAR, "id": "alpha"}, {**FAKE_CAR, "id": "kazane"}]
    data = load_game_data(fake_sources(cars=cars), tables=FAKE_TABLES)
    assert data.ids("cars") == ("zeta", "alpha", "kazane") and type(data.ids("cars")) is tuple  # 整列しない。ファイルの順
    for table, ident in (("cars", "nobody"), ("nothing", "kazane"), ("cars", None)):
        with pytest.raises(KeyError):
            data.entry(table, ident)
    with pytest.raises(KeyError):
        data.ids("nothing")


def test_datadefs_entry_is_a_fresh_copy_down_to_the_nested_lists():
    # 引いた値の、奥の並びと辞書を書き換えても、次に引いた値が変わらない（浅い複製では、奥が同じ物になる）。
    data = load_game_data(fake_sources(), tables=FAKE_TABLES)
    first = data.entry("cars", "kazane")
    first["name"] = "CHANGED"
    first["gears"].append(0.1)
    first["engine"]["idle_rpm"] = 0
    first["engine"]["curve"][0]["rpm"] = -5
    first["engine"]["curve"].clear()
    second = data.entry("cars", "kazane")
    assert second == FAKE_CAR
    third = data.entry("cars", "kazane")
    assert second is not third and second["gears"] is not third["gears"]
    assert second["engine"] is not third["engine"] and second["engine"]["curve"][0] is not third["engine"]["curve"][0]
    counts = data.counts()
    counts["cars"] = 99
    assert data.counts()["cars"] == 1


def test_datadefs_loading_does_not_change_the_sources():
    sources, pack_files = real_sources(), {CARS: json.dumps({"cars": [{**ENTRY, "name": "OTHER", "data_version": 2}]})}
    before, pack_before = dict(sources), dict(pack_files)
    assert load_game_data(sources, ("p", pack_files)).entry("cars", "kazane")["name"] == "OTHER"
    assert sources == before and pack_files == pack_before


# --- 問題の行の順 ---
def test_datadefs_problem_lines_come_in_the_same_order_every_time():
    # 辞書へ入れた順と、JSONの中の鍵の順を変えても、問題の行は、同じ順で並ぶ（集合を回した順に頼らない）。
    # ほかの鍵（走りの値、コースの形）は、実物の値のまま（問題にならない）。操作補正、カメラ、パレットのファイルも、実物のまま。
    car = {"zz": 1, "id": "kazane", "aa": 2, "data_version": 0, "name": "", "mm": 3, **without(ENTRY, "id", "name", "data_version")}
    loop_entry = {"data_version": "1", "zz": 1, "name": "カ", "aa": 2, "id": "test_loop", **without(LOOP_ENTRY, "id", "name", "data_version")}
    names = ["notes.txt", CARS, "zz.json", LOOP, "aa.json", ASSISTS, PALETTES, CAMERAS]
    texts = {
        CARS: {"cars": [car, dict(reversed(car.items()))]}, LOOP: loop_entry, "notes.txt": {}, "zz.json": {}, "aa.json": {},
        ASSISTS: json.loads(real_sources()[ASSISTS]), CAMERAS: json.loads(real_sources()[CAMERAS]), PALETTES: json.loads(real_sources()[PALETTES]),
    }
    want = [
        "aa.json: unknown file (no table reads this name)",
        "notes.txt: unknown file (no table reads this name)",
        "zz.json: unknown file (no table reads this name)",
        "cars.json:cars[1].id: duplicate id 'kazane'",
        "cars.json:cars[0].aa: unknown key",
        "cars.json:cars[0].mm: unknown key",
        "cars.json:cars[0].zz: unknown key",
        "cars.json:cars[0].name: expected a non-empty text, got ''",
        "cars.json:cars[0].data_version: 0 is outside 1..",
        "tracks/test_loop.json:aa: unknown key",
        "tracks/test_loop.json:zz: unknown key",
        "tracks/test_loop.json:name: 'カ' has characters outside printable ASCII",
        "tracks/test_loop.json:data_version: expected an integer, got str",
        "cars.json:cars[1].aa: unknown key",
        "cars.json:cars[1].mm: unknown key",
        "cars.json:cars[1].zz: unknown key",
        "cars.json:cars[1].name: expected a non-empty text, got ''",
        "cars.json:cars[1].data_version: 0 is outside 1..",
    ]
    for order in (names, list(reversed(names)), sorted(names), names[2:] + names[:2]):
        sources = {name: json.dumps(texts[name]) for name in order}
        assert problems_of(sources) == want
    assert problems_of({name: json.dumps(texts[name], sort_keys=True) for name in names}) == want


# --- 試験用データの重ね方 ---
# 試験用データの車の表。実物の項目から作る（項目ごと差し替える重ね方なので、全部の鍵を持つ）。1台目は、同じ id で、表示名と
# データの版と質量を変える。2台目は、新しい id。
PACK_CARS = {"cars": [
    {**ENTRY, "name": "KAZANE RS TEST", "data_version": 3, "body": {**ENTRY["body"], "mass_kg": 1234.5}},
    {**ENTRY, "id": "wide_test_car", "name": "W" * 14},
]}


def test_datadefs_pack_replaces_the_same_id_and_appends_a_new_id():
    sources = real_sources()
    data = load_game_data(sources, ("extreme", {CARS: json.dumps(PACK_CARS)}))
    assert data.pack == "extreme" and data.warnings == ()
    assert data.ids("cars") == ("kazane", "wide_test_car")  # 同じ id は、元の位置で差し替え。新しい id は、末尾
    replaced = data.entry("cars", "kazane")
    assert replaced == PACK_CARS["cars"][0] and (replaced["name"], replaced["data_version"]) == ("KAZANE RS TEST", 3)
    assert replaced["body"]["mass_kg"] == 1234.5  # 項目ごと差し替える（入れ子の中の値も、試験用データの値）
    assert data.entry("cars", "wide_test_car")["name"] == "W" * 14
    assert data.counts() == {"cars": 2, "tracks": 1, "assists": 1, "cameras": 1, "palettes": 1}  # 重ねなかった表は、そのまま
    # 元のデータは変わらない。
    plain = load_game_data(sources)
    assert plain.pack is None and plain.ids("cars") == ("kazane",) and plain.entry("cars", "kazane")["name"] == "KAZANE"
    assert plain.entry("cars", "kazane")["body"]["mass_kg"] == 960.0


def test_datadefs_pack_entry_that_leaves_keys_out_is_not_merged_with_the_shipped_entry():
    # 重ね方は、項目ごとの差し替え。試験用データの項目が、鍵を持たなければ、足りない鍵の問題になる（出荷するデータの値で、埋めない）。
    partial = {"cars": [{"id": "kazane", "name": "KAZANE RS TEST", "data_version": 1}]}
    assert problems_of(real_sources(), ("p", {CARS: json.dumps(partial)})) == [
        f"testpacks/p/cars.json:cars[0].{key}: missing" for key in list(TABLES["cars"].fields)[3:]
    ]


def test_datadefs_pack_keeps_the_position_of_a_replaced_entry():
    cars = [{**FAKE_CAR, "id": "first"}, {**FAKE_CAR, "id": "kazane"}, {**FAKE_CAR, "id": "last"}]
    pack = {"cars.json": json.dumps({"cars": [{**FAKE_CAR, "id": "new_one"}, {**FAKE_CAR, "id": "kazane", "name": "REPLACED"}]})}
    data = load_game_data(fake_sources(cars=cars), ("p", pack), FAKE_TABLES)
    assert data.ids("cars") == ("first", "kazane", "last", "new_one")
    assert data.entry("cars", "kazane")["name"] == "REPLACED" and data.entry("cars", "first")["name"] == "KAZANE"


def test_datadefs_pack_of_one_entry_files_replaces_the_same_name_and_adds_a_new_name():
    replaced = {**LOOP_ENTRY, "name": "REPLACED LOOP", "data_version": 9, "width_m": 10.0}
    pack = {
        LOOP: json.dumps(replaced),
        "tracks/wide_test_loop.json": json.dumps({**LOOP_ENTRY, "id": "wide_test_loop", "name": "M" * 14}),
        "tracks/another_loop.json": json.dumps({**LOOP_ENTRY, "id": "another_loop", "name": "ANOTHER"}),
    }
    data = load_game_data(real_sources(), ("extreme", pack))
    assert data.ids("tracks") == ("test_loop", "another_loop", "wide_test_loop")  # 元の順のあとに、新しい名（名を整列した順）
    assert data.entry("tracks", "test_loop") == replaced and data.entry("tracks", "test_loop")["width_m"] == 10.0
    assert data.counts() == {"cars": 1, "tracks": 3, "assists": 1, "cameras": 1, "palettes": 1}
    assert load_game_data(real_sources()).entry("tracks", "test_loop")["name"] == "TEST LOOP"


def test_datadefs_the_overlaid_result_goes_through_the_same_checks():
    # 重ねた結果を、同じ読み込み検査に通す。試験用データの中の問題は、頭に testpacks/<名>/ が付く。
    bad = {"cars": [{**ENTRY, "name": "K" * 15}, {**without(ENTRY, "name"), "id": "new_car", "nmae": "X", "data_version": True}]}
    assert problems_of(real_sources(), ("extreme", {CARS: json.dumps(bad)})) == [
        f"testpacks/extreme/cars.json:cars[0].name: '{'K' * 15}' is 15 characters (at most 14)",
        "testpacks/extreme/cars.json:cars[1].nmae: unknown key",
        "testpacks/extreme/cars.json:cars[1].name: missing",
        "testpacks/extreme/cars.json:cars[1].data_version: expected an integer, got bool",
    ]
    assert problems_of(real_sources(), ("extreme", {LOOP: json.dumps({**LOOP_ENTRY, "id": "other", "name": "X"})})) == [
        "testpacks/extreme/tracks/test_loop.json:id: 'other' does not match the file name 'test_loop'"
    ]
    # 項目をまたぐ検査も、重ねた結果に掛かる。足した項目（新しい id）と、差し替えた項目の、どちらにも。
    slow = {**ENTRY, "id": "new_car", "drivetrain": {**ENTRY["drivetrain"], "gears": [1.0, 2.0]}}
    open_loop = {**LOOP_ENTRY, "control_points": LOOP_ENTRY["control_points"][:40]}
    assert problems_of(real_sources(), ("extreme", {CARS: json.dumps({"cars": [slow]}), LOOP: json.dumps(open_loop)})) == [
        "testpacks/extreme/cars.json:cars[0].drivetrain.gears[1]: gear ratio 2.0 is not below the gear before it (1.0)",
        "testpacks/extreme/tracks/test_loop.json:control_points: not closed: the gap from the last point back to the first is 192.9 m (the longest other gap is 12.5 m)",
    ]
    # 参照も、重ねた結果で照らす。試験用データが足した定義への参照は通り、無い定義への参照は落ちる。
    more_sounds = {"sounds.json": json.dumps({"sounds": [{"id": "eng_turbo", "kind": "engine"}]})}
    turbo = {"cars.json": json.dumps({"cars": [{**FAKE_CAR, "sound": "eng_turbo", "extras": ["eng_na"]}]})}
    assert load_game_data(fake_sources(), ("p", {**more_sounds, **turbo}), FAKE_TABLES).entry("cars", "kazane")["sound"] == "eng_turbo"
    assert problems_of(fake_sources(), ("p", turbo), FAKE_TABLES) == ["testpacks/p/cars.json:cars[0].sound: no sounds with id 'eng_turbo'"]
    # 出荷するデータの、差し替えられた項目の問題は、重ねた結果には無い。差し替えられなかった項目の問題は、残る。
    broken = edited(CARS, lambda doc: doc["cars"][0].update(nmae="X"))
    assert load_game_data(broken, ("extreme", {CARS: json.dumps(PACK_CARS)})).ids("cars") == ("kazane", "wide_test_car")
    only_new = {CARS: json.dumps({"cars": [PACK_CARS["cars"][1]]})}
    assert problems_of(broken, ("extreme", only_new)) == ["cars.json:cars[0].nmae: unknown key"]


@pytest.mark.parametrize(
    "files, want",
    [
        # ファイルの頭の形が合わないファイルは、重ねない。問題は、そのファイルの1行だけ（突き合わせの途中で、別の例外にならない）。
        ({CARS: json.dumps([PACK_CARS["cars"][0]])}, ['testpacks/p/cars.json: the file must be {"cars": [...]}, got list']),
        ({CARS: json.dumps({"cars": {"kazane": {}}})}, ["testpacks/p/cars.json:cars: expected a list of entries, got dict"]),
        ({CARS: json.dumps({"cars": []})}, ["testpacks/p/cars.json:cars: no entries"]),
        ({CARS: json.dumps({"cars": [PACK_CARS["cars"][0], 5]})}, ["testpacks/p/cars.json:cars[1]: expected an entry (an object), got int"]),
        ({CARS: json.dumps({"cars": [{**without(ENTRY, "id"), "name": "X"}]})}, ["testpacks/p/cars.json:cars[0].id: missing"]),
        ({CARS: json.dumps({"cars": [{**ENTRY, "id": 5, "name": ""}]})}, [
            "testpacks/p/cars.json:cars[0].id: expected a string id, got int", "testpacks/p/cars.json:cars[0].name: expected a non-empty text, got ''",
        ]),
        ({LOOP: json.dumps(["test_loop"])}, ["testpacks/p/tracks/test_loop.json: the file must be one entry (an object), got list"]),
        ({LOOP: json.dumps({**without(LOOP_ENTRY, "id"), "name": "X"})}, ["testpacks/p/tracks/test_loop.json:id: missing"]),
        ({CARS: "{"}, None),
        ({CARS: None}, ["testpacks/p/cars.json: cannot read the file"]),
        ({CARS: '{"cars": [], "cars": []}'}, ["testpacks/p/cars.json: duplicate key 'cars'"]),
        # 同じファイルの中の、id の重複。
        ({CARS: json.dumps({"cars": [PACK_CARS["cars"][1], PACK_CARS["cars"][1]]})}, ["testpacks/p/cars.json:cars[1].id: duplicate id 'wide_test_car'"]),
        # 2つの形に当たらない名。「重ねたつもりで、重なっていない」まま通さない。
        ({"notes.txt": "x"}, ["testpacks/p/notes.txt: unknown file (no table reads this name)", "testpacks/p/: no table files (nothing would be overlaid)"]),
        ({"tracks.json": "{}", CARS: json.dumps(PACK_CARS)}, ["testpacks/p/tracks.json: unknown file (no table reads this name)"]),
        ({"cars/kazane.json": "{}", "tracks/deep/x.json": "{}", CARS: json.dumps(PACK_CARS)}, [
            "testpacks/p/cars/kazane.json: unknown file (no table reads this name)", "testpacks/p/tracks/deep/x.json: unknown file (no table reads this name)",
        ]),
        # 表のファイルが1つも無い。
        ({}, ["testpacks/p/: no table files (nothing would be overlaid)"]),
    ],
)
def test_datadefs_pack_file_with_a_wrong_shape_is_not_overlaid_and_is_a_problem(files, want):
    got = problems_of(real_sources(), ("p", files))
    if want is None:
        assert len(got) == 1 and got[0].startswith("testpacks/p/cars.json: cannot read: ")
    else:
        assert got == want


@pytest.mark.parametrize("name", ["", "Extreme", "extreme pack", "a-b", "a.b", "a/b", "..", "é", "a" * 44, None, 5, ["extreme"]])
def test_datadefs_bad_pack_name_is_a_value_error(name):
    with pytest.raises(ValueError) as info:
        load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
    assert not isinstance(info.value, DataError)
    with pytest.raises(ValueError):
        datadefs.check_pack_name(name)


# --- 保存の名前空間 ---
def test_datadefs_save_namespace_is_main_or_pack_and_the_name():
    assert load_game_data(real_sources()).save_namespace == "main"
    for name in ("extreme", "x_1", "9", "a" * 43):
        data = load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
        assert data.pack == name == datadefs.check_pack_name(name)
        assert data.save_namespace == f"pack_{name}"
        # 保存の口が、名前空間として受ける（48字まで。「.」を含まない）。
        assert storage.SaveStore(storage.MemoryBackend(), data.save_namespace).namespace == f"pack_{name}"
    assert datadefs.PACK_NAME_MAX == 43 and len(datadefs.PACK_NAMESPACE_PREFIX) + datadefs.PACK_NAME_MAX == storage.KEY_MAX
    assert datadefs.PACK_NAMESPACE_PREFIX == "pack_" and datadefs.PACKS_DIR == "testpacks"


def test_datadefs_pack_named_like_a_namespace_in_use_does_not_share_that_namespace():
    # 名が、ふつうの保存の名前空間（main）や、保存の往復の名前空間（selfcheck）と同じ試験用データを、実際に重ねる。
    # 保存の名前空間は、どちらとも重ならない（頭の pack_ が無いと、名 main の試験用データが、ふだんの保存に触れる）。
    in_use = {storage.DEFAULT_NAMESPACE, profile.SELFCHECK_NAMESPACE}
    assert in_use == {"main", "selfcheck"}
    for name in sorted(in_use):
        data = load_game_data(real_sources(), (name, {CARS: json.dumps(PACK_CARS)}))
        assert data.pack == name
        assert data.save_namespace not in in_use, name
        # 保存の口が受ける名前空間でも、重ならない。
        assert storage.SaveStore(storage.MemoryBackend(), data.save_namespace).namespace not in in_use, name


# --- 表を足す、項目を足すときの手順の見張り（鍵の道を集める key_paths は、BROKEN の前に置いてある） ---
def key_path_of(line: str, table: str, tables: dict) -> str:
    """問題の行の場所を、項目の中の鍵の道にする。並びの中の番号と、1ファイル1表の頭（表の名と、項目の番号）は落とす。

    「cars.json:cars[0].engine.curve[1].rpm: …」は engine.curve.rpm、「tracks/test_loop.json:name: …」は name。
    項目の中を指さない行（ファイルの問題、表の問題）は、空の文字列。
    """
    where = line.split(": ", 1)[0].partition(":")[2]
    if tables[table].layout == ONE_TABLE:
        head = re.match(rf"{re.escape(table)}\[\d+\](\.|$)", where)
        if head is None:
            return ""
        where = where[head.end():]
    return re.sub(r"\[\d+\]", "", where)


def broken_case_problems(tables: dict, broken: dict) -> list:
    """壊した場合の表（{名前: (表, 札, 壊したファイルの辞書, 並ぶはずの問題の行)}）を、表の定義と照らす。返すのは、足りない所と、札の食い違い。

    - 表ごとに、どの鍵でもない所を壊した件（札が None。知らない鍵か、空の表）が、1つ以上ある。
    - 表の、鍵の道の全部（key_paths。入れ子の奥まで）に、その鍵の道を札にした件が、1つ以上ある。
    - 札は、書いた人の申告のままにしない。並ぶはずの行は1つ以上あり、その場所（key_path_of）は、どれも、札と同じ鍵の道。
      札が None の件の行は、表のどの鍵の道も指さない。
    """
    problems = []
    for name, table in tables.items():
        paths = key_paths(table.fields)
        cases = {case: (tag, want) for case, (case_table, tag, _, want) in broken.items() if case_table == name}
        tags = {tag for tag, _ in cases.values()}
        if None not in tags:
            problems.append(f"{name}: 知らない鍵か、空の表の、壊した場合が無い")
        problems += [f"{name}: 壊した場合の無い鍵：{path}" for path in paths if path not in tags]
        for case in sorted(cases):
            tag, want = cases[case]
            places = [key_path_of(line, name, tables) for line in want]
            if not places:
                problems.append(f"{case}: 並ぶはずの行が無い")
            if tag is None:
                problems += [f"{case}: 札は None、行の場所は、鍵 {place}" for place in places if place in paths]
                continue
            if tag not in paths:
                problems.append(f"{case}: 札 {tag} は、表 {name} の鍵の道に無い")
            problems += [f"{case}: 札は {tag}、行の場所は {place or '項目の外'}" for place in places if place != tag]
    problems += [f"{case}: 表の定義に無い表：{value[0]}" for case, value in sorted(broken.items()) if value[0] not in tables]
    return problems


def test_datadefs_every_real_table_has_its_files_and_every_key_has_a_broken_case():
    sources = real_sources()
    for name, table in TABLES.items():
        if table.layout == ONE_TABLE:
            assert f"{name}.json" in sources, name
        else:
            assert [source for source in sources if source.startswith(f"{name}/")], name
    # 鍵は、入れ子の奥まで見る（鍵の道ごとに、壊した場合が要る）。札は、並ぶはずの行の場所と照らす。
    assert broken_case_problems(TABLES, BROKEN) == []
    assert {case_table for case_table, _, _, _ in BROKEN.values()} == set(TABLES)
    assert all(datadefs._classify(name, TABLES) is not None for name in sources)  # 実物の置き場に、知らないファイルが無い


def test_datadefs_generated_broken_cases_are_built_from_the_key_paths_and_fixed_texts():
    # 鍵の道から作った、壊した場合。並ぶはずの行を、いくつか、手で書いた行と照らす（作り方が、狙った場所と文になっていること）。
    assert GENERATED["cars body.mass_kg missing"][1:] == ("body.mass_kg", GENERATED["cars body.mass_kg missing"][2], ["cars.json:cars[0].body.mass_kg: missing"])
    assert GENERATED["cars body.mass_kg wrong type"][3] == ["cars.json:cars[0].body.mass_kg: expected a number, got str"]
    assert GENERATED["cars body.mass_kg out of range"][3] == ["cars.json:cars[0].body.mass_kg: 5001.0 is outside 100.0..5000.0"]
    assert GENERATED["cars engine.torque_curve.rpm out of range"][3] == ["cars.json:cars[0].engine.torque_curve[0].rpm: 20001.0 is outside 0.0..20000.0"]
    assert GENERATED["cars engine.torque_curve empty"][3] == ["cars.json:cars[0].engine.torque_curve: expected a list of 2..32 items, got 0"]
    assert GENERATED["cars drivetrain wrong type"][3] == ["cars.json:cars[0].drivetrain: expected an object, got int"]
    assert GENERATED["tracks control_points.x_m wrong type"][3] == ["tracks/test_loop.json:control_points[0].x_m: expected a number, got str"]
    assert GENERATED["tracks control_points wrong type"][3] == ["tracks/test_loop.json:control_points: expected a list, got str"]
    assert GENERATED["tracks start.s_m out of range"][3] == ["tracks/test_loop.json:start.s_m: 20001.0 is outside 0.0..20000.0"]
    assert GENERATED["assists steer.digital.full_time_s missing"][3] == ["assists.json:assists[0].steer.digital.full_time_s: missing"]
    assert GENERATED["assists reverse.pedal_press_min out of range"][3] == ["assists.json:assists[0].reverse.pedal_press_min: 2.0 is outside 0.001..1.0"]
    # 描画の値（車の仮の形、メッシュの寸法、カメラ、パレット）。
    assert GENERATED["cars shape.roof_front_m out of range"][3] == ["cars.json:cars[0].shape.roof_front_m: 6.0 is outside -5.0..5.0"]
    assert GENERATED["cars shape wrong type"][3] == ["cars.json:cars[0].shape: expected an object, got int"]
    assert GENERATED["tracks mesh.step_m out of range"][3] == ["tracks/test_loop.json:mesh.step_m: 21.0 is outside 1.0..20.0"]
    assert GENERATED["tracks mesh.road_strips missing"][3] == ["tracks/test_loop.json:mesh.road_strips: missing"]
    assert GENERATED["tracks mesh missing"][3] == ["tracks/test_loop.json:mesh: missing"]
    assert GENERATED["cameras fov_deg out of range"][3] == ["cameras.json:cameras[0].fov_deg: 121.0 is outside 10.0..120.0"]
    assert GENERATED["cameras far_m wrong type"][3] == ["cameras.json:cameras[0].far_m: expected a number, got str"]
    assert GENERATED["palettes colors empty"][3] == ["palettes.json:palettes[0].colors: expected a list of 32..32 items, got 0"]
    assert GENERATED["palettes unshaded empty"][3] == ["palettes.json:palettes[0].unshaded: expected a list of 1..32 items, got 0"]
    assert GENERATED["palettes colors wrong type"][3] == ["palettes.json:palettes[0].colors: expected a list, got str"]
    # 壊したファイルは、狙った1か所だけが、実物と違う。
    doc = json.loads(GENERATED["cars body.mass_kg wrong type"][2][CARS])["cars"][0]
    assert doc["body"]["mass_kg"] == "x" and {**doc, "body": {**doc["body"], "mass_kg": 960.0}} == real_car()
    assert "mass_kg" not in json.loads(GENERATED["cars body.mass_kg missing"][2][CARS])["cars"][0]["body"]
    # どの鍵にも、鍵を消した場合。数の鍵には、型の違いと、範囲の外の、2通り。入れ子の項目と並びには、型の違い。
    for table, definition in TABLES.items():
        for path in key_paths(definition.fields):
            rule = rules_along(definition.fields, path)[-1][1]
            want = {"missing"} | ({"wrong type", "out of range"} if type(rule) is Num else set())
            want |= {"wrong type"} if type(rule) is Obj else {"wrong type", "empty"} if type(rule) is ListOf else set()
            assert {name.rsplit(f" {path} ", 1)[1] for name in GENERATED if name.startswith(f"{table} {path} ")} == want, (table, path)
    # 実物の表の定義の、数の鍵の数（足したら、ここも変える。鍵が、規則ごと消えていないこと）。
    numbers = [path for table in TABLES.values() for path in key_paths(table.fields) if type(rules_along(table.fields, path)[-1][1]) is Num]
    assert len(numbers) == 79 + 7 + 4 + 7  # 段0 区切り9までの79に、車の仮の形の7、メッシュの寸法の4（路面を割る数は、整数）、カメラの7


# --- 項目をまたぐ検査の口（TableDef.check）。作り物の表の定義で、呼ばれる条件と、問題の行の形を見る ---
def checked_tables(check) -> dict:
    return {
        "cars": TableDef(ONE_TABLE, {"id": Ident(), "low": Num(0, 10), "high": Num(0, 10), "points": Opt(ListOf(Obj({"x": Num(0, 9)}), 0, 4))}, check),
        "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "length": Num(0, 100)}, check),
    }


def checked_sources(cars, track=None) -> dict:
    return {"cars.json": json.dumps({"cars": cars}), "tracks/test_loop.json": json.dumps({"id": "test_loop", "length": 5} if track is None else track)}


def low_above_high(entry: dict) -> list:
    """作り物の検査。low が high より大きければ、問題（鍵の道は low）。並びの点は、x が昇順でなければ、その点の問題。"""
    problems = [(("low",), f"{entry['low']} is above high ({entry['high']})")] if "low" in entry and entry["low"] > entry["high"] else []
    points = entry.get("points", [])
    problems += [(("points", index, "x"), "x does not rise") for index in range(1, len(points)) if points[index]["x"] <= points[index - 1]["x"]]
    if entry.get("length") == 13:
        problems += [((), "an unlucky length"), (("length",), "13 is not accepted")]
    return problems


def test_datadefs_cross_check_lines_have_the_file_and_the_key_path_like_any_other_problem():
    tables = checked_tables(low_above_high)
    cars = [{"id": "a", "low": 1, "high": 2}, {"id": "b", "low": 5, "high": 2, "points": [{"x": 1}, {"x": 1}, {"x": 0}]}, {"id": "c", "low": 9, "high": 0}]
    assert load_game_data(checked_sources(cars[:1]), tables=tables).ids("cars") == ("a",)
    assert problems_of(checked_sources(cars, {"id": "test_loop", "length": 13}), tables=tables) == [
        "cars.json:cars[1].low: 5 is above high (2)",
        "cars.json:cars[1].points[1].x: x does not rise",
        "cars.json:cars[1].points[2].x: x does not rise",
        "cars.json:cars[2].low: 9 is above high (0)",
        "tracks/test_loop.json: an unlucky length",  # 鍵の道が空なら、項目そのものの問題
        "tracks/test_loop.json:length: 13 is not accepted",
    ]
    # 試験用データの中の項目も、同じ。頭に testpacks/<名>/ が付く。
    pack = {"cars.json": json.dumps({"cars": [{"id": "a", "low": 3, "high": 2}]})}
    assert problems_of(checked_sources(cars[:1]), ("p", pack), tables) == ["testpacks/p/cars.json:cars[0].low: 3 is above high (2)"]


def test_datadefs_cross_check_is_called_only_for_entries_that_pass_every_key_rule():
    seen = []

    def remember(entry: dict) -> list:
        seen.append(entry)
        return [(("low",), "checked")]

    tables = checked_tables(remember)
    cars = [
        {"id": "ok", "low": 1, "high": 2, "_note": "x", "points": [{"x": 1, "_why": "y"}]},
        {"id": "range", "low": 11, "high": 2},  # 範囲の外
        {"id": "unknown", "low": 1, "high": 2, "hgih": 3},  # 知らない鍵
        {"id": "missing", "low": 1},  # 足りない鍵
        {"id": "Bad Id", "low": 1, "high": 2},  # id の規則
        {"low": 1, "high": 2},  # id が無い
        {"id": "nested", "low": 1, "high": 2, "points": [{"x": 99}]},  # 並びの中の値
    ]
    got = problems_of(checked_sources(cars), tables=tables)
    assert [line for line in got if line.endswith(": checked")] == ["cars.json:cars[0].low: checked", "tracks/test_loop.json:low: checked"]
    assert len(got) == 2 + 6  # ほかの6つの項目は、鍵ごとの規則の問題が1件ずつ。検査の関数は、呼ばれない
    # 検査の関数へは、注の鍵を落とした、複製が渡る（書き換えても、読み込んだ定義に響かない）。
    assert seen == [{"id": "ok", "low": 1, "high": 2, "points": [{"x": 1}]}, {"id": "test_loop", "length": 5}]

    def scribble(entry: dict) -> list:
        entry["low"] = 99
        entry.setdefault("points", []).append({"x": 5})
        return []

    data = load_game_data(checked_sources(cars[:1]), tables=checked_tables(scribble))
    assert data.entry("cars", "ok") == {"id": "ok", "low": 1, "high": 2, "points": [{"x": 1}]}


@pytest.mark.parametrize(
    "error, text",
    [
        (ZeroDivisionError("float division by zero"), "ZeroDivisionError: float division by zero"),
        (ValueError("math domain error"), "ValueError: math domain error"),
        (IndexError("tuple index out of range"), "IndexError: tuple index out of range"),
        (OverflowError("cannot convert float infinity to integer"), "OverflowError: cannot convert float infinity to integer"),
        (KeyError("gears"), "KeyError: 'gears'"),
        (TypeError("unsupported operand"), "TypeError: unsupported operand"),
    ],
)
def test_datadefs_cross_check_that_raises_becomes_a_problem_line_of_the_entry(error, text):
    # 検査の関数が、計算の例外を出しても、DataError のほかの例外は、外へ出ない。その項目の問題の行になり、ほかの問題も並ぶ。
    def explode(entry: dict) -> list:
        if entry["id"] in ("b", "test_loop"):
            raise error
        return []

    tables = checked_tables(explode)
    cars = [{"id": "a", "low": 1, "high": 2}, {"id": "b", "low": 1, "high": 2}, {"id": "c", "low": 1, "high": 99}]
    assert problems_of(checked_sources(cars), tables=tables) == [
        f"cars.json:cars[1]: cannot check the entry ({text})",
        "cars.json:cars[2].high: 99 is outside 0..10",
        f"tracks/test_loop.json: cannot check the entry ({text})",
    ]


def test_datadefs_real_cross_checks_run_only_when_the_key_rules_pass_and_list_everything():
    # 実物の表の定義で。変速比の順と、足りない鍵を、同じ車に仕込む。並ぶのは、足りない鍵だけ（規則を通らない値で、検査を始めない）。
    both = edited(CARS, lambda doc: (doc["cars"][0]["drivetrain"].update(gears=[1.0, 2.0]), doc["cars"][0]["body"].pop("mass_kg")))
    assert problems_of(both) == ["cars.json:cars[0].body.mass_kg: missing"]
    # 車の矛盾2つ、車の仮の形の矛盾2つ、コースの形の誤り2つ。6つとも並ぶ（車は、車の値の矛盾が先、仮の形の寸法が後）。
    sources = edited(CARS, lambda doc: (
        doc["cars"][0]["drivetrain"].update(gears=[3.0, 3.5, 1.0]), doc["cars"][0]["engine"]["torque_curve"][1].update(rpm=900.0),
        doc["cars"][0]["shape"].update(height_m=0.5, roof_rear_m=-3.0),
    ))
    sources = edited(LOOP, lambda doc: doc.update(grass_m=34.0, start={"s_m": 900.0, "lateral_m": 0.0}), sources)
    assert problems_of(sources) == [
        "cars.json:cars[0].drivetrain.gears[1]: gear ratio 3.5 is not below the gear before it (3.0)",
        "cars.json:cars[0].engine.torque_curve[1].rpm: rpm 900.0 is not above the point before it (1000.0)",
        "cars.json:cars[0].shape.height_m: 0.5 is not above the top of the body box (0.78)",
        "cars.json:cars[0].shape.roof_rear_m: -3.0 is behind the tail (half length 2.1)",
        "tracks/test_loop.json:control_points: the inner wall (40.0 m from the centre line) folds over at s=679 m (radius 44.8 m)",
        "tracks/test_loop.json:start.s_m: 900.0 is beyond the lap length 732.7 m",
    ]
    # 仮の形の寸法の矛盾と、足りない鍵を、同じ車に仕込む。並ぶのは、足りない鍵だけ。
    both = edited(CARS, lambda doc: (doc["cars"][0]["shape"].update(height_m=0.5), doc["cars"][0]["shape"].pop("tire_width_m")))
    assert problems_of(both) == ["cars.json:cars[0].shape.tire_width_m: missing"]


# 見張りそのものの確かめ。実物の表の定義は、省ける項目を持たないので、作り物の表の定義（入れ子の項目、並びの中の項目、
# 省ける項目の中の項目。2つのファイルの形）で、見張りが、奥の鍵と、札の食い違いを拾うことを見る。
GUARD_TABLES = {
    "cars": TableDef(ONE_TABLE, {
        "id": Ident(),
        "engine": Obj({"idle_rpm": Int(500, 2000), "curve": ListOf(Obj({"rpm": Int(0, 9000)}), 1, 4)}),
        "tune": Opt(Obj({"boost": Num(0, 2)})),
    }),
    "tracks": TableDef(ONE_ENTRY, {"id": Ident(), "gates": Opt(ListOf(Obj({"x": Num(-100, 100)}), 1, 3))}),
}
GUARD_CAR = {"id": "kazane", "engine": {"idle_rpm": 900, "curve": [{"rpm": 1000}]}, "tune": {"boost": 1}}
GUARD_TRACK = {"id": "test_loop", "gates": [{"x": 0}, {"x": 5}]}


def guard_case(table: str, tag, car=None, track=None) -> tuple:
    """作り物の表の定義の、壊した場合1つ。並ぶはずの行は、実際に読み込み検査を通して作る（行の形を、手で書かない）。"""
    sources = {
        "cars.json": json.dumps({"cars": [{**GUARD_CAR, **(car or {})}]}),
        "tracks/test_loop.json": json.dumps({**GUARD_TRACK, **(track or {})}),
    }
    return table, tag, sources, problems_of(sources, tables=GUARD_TABLES)


def guard_cases() -> dict:
    """作り物の表の定義の、鍵の道の全部に1件ずつと、表ごとに、知らない鍵の件。"""
    engine = GUARD_CAR["engine"]
    return {
        "cars unknown key": guard_case("cars", None, car={"nmae": 1}),
        "cars id": guard_case("cars", "id", car={"id": "Bad Id"}),
        "cars engine": guard_case("cars", "engine", car={"engine": [900]}),
        "cars idle": guard_case("cars", "engine.idle_rpm", car={"engine": {**engine, "idle_rpm": 100}}),
        "cars curve": guard_case("cars", "engine.curve", car={"engine": {**engine, "curve": []}}),
        "cars rpm": guard_case("cars", "engine.curve.rpm", car={"engine": {**engine, "curve": [{"rpm": 1000}, {"rpm": -1}]}}),
        "cars tune": guard_case("cars", "tune", car={"tune": 5}),
        "cars boost": guard_case("cars", "tune.boost", car={"tune": {"boost": 9}}),
        "tracks unknown key": guard_case("tracks", None, track={"lenght_m": 1}),
        "tracks id": guard_case("tracks", "id", track={"id": "other"}),
        "tracks gates": guard_case("tracks", "gates", track={"gates": "x"}),
        "tracks gate x": guard_case("tracks", "gates.x", track={"gates": [{"x": 0}, {"x": 999}]}),
    }


def test_datadefs_broken_case_guard_collects_the_key_paths_down_to_the_nested_keys():
    assert key_paths(GUARD_TABLES["cars"].fields) == ["id", "engine", "engine.idle_rpm", "engine.curve", "engine.curve.rpm", "tune", "tune.boost"]
    assert key_paths(GUARD_TABLES["tracks"].fields) == ["id", "gates", "gates.x"]
    assert key_paths(FAKE_TABLES["cars"].fields) == [
        "id", "name", "turbo", "sound", "gears", "engine", "engine.idle_rpm", "engine.curve", "engine.curve.rpm", "engine.curve.torque", "extras",
    ]
    # 実物。入れ子の項目と、並びの中の項目の鍵まで、開く。
    assert key_paths(TABLES["tracks"].fields) == [
        "id", "name", "data_version", "table", "table.sample_step_m", "table.dense_step_m", "width_m", "grass_m",
        "surface_mu", "surface_mu.asphalt", "surface_mu.grass", "wall", "wall.restitution", "wall.friction",
        "start", "start.s_m", "start.lateral_m",
        "mesh", "mesh.step_m", "mesh.road_strips", "mesh.line_m", "mesh.wall_height_m", "mesh.chunk_m",
        "control_points", "control_points.x_m", "control_points.z_m",
    ]
    assert key_paths(TABLES["cameras"].fields) == ["id", "back_m", "height_m", "look_ahead_m", "look_height_m", "fov_deg", "near_m", "far_m"]
    assert key_paths(TABLES["palettes"].fields) == ["id", "colors", "unshaded"]  # 並びの中が、数だけなら、鍵の道は、並びまで
    assert key_paths(TABLES["assists"].fields) == [
        "id", "steer", "steer.limit_mu_min", "steer.limit_min_speed_m_s",
        "steer.analog", "steer.analog.limit_ka", "steer.analog.limit_km", "steer.analog.full_time_s",
        "steer.digital", "steer.digital.limit_ka", "steer.digital.limit_km", "steer.digital.full_time_s",
        "reverse", "reverse.stop_speed_m_s", "reverse.brake_hold_s", "reverse.pedal_press_min",
    ]
    car_paths = key_paths(TABLES["cars"].fields)
    assert car_paths[:5] == ["id", "name", "data_version", "body", "body.mass_kg"] and len(car_paths) == 72 + 8  # 仮の形（shape）と、その7つの寸法
    assert {"engine.torque_curve", "engine.torque_curve.rpm", "engine.torque_curve.ratio", "drivetrain.gears", "outputs.yaw_ref_min_speed_m_s"} <= set(car_paths)
    assert car_paths[-8:] == [
        "shape", "shape.height_m", "shape.body_top_m", "shape.roof_front_m", "shape.roof_rear_m", "shape.roof_inset_m",
        "shape.ground_clearance_m", "shape.tire_width_m",
    ]
    # 問題の行の場所を、鍵の道にする。
    assert key_path_of("cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000", "cars", GUARD_TABLES) == "engine.curve.rpm"
    assert key_path_of("testpacks/p/cars.json:cars[12].id: duplicate id 'kazane'", "cars", GUARD_TABLES) == "id"
    assert key_path_of("tracks/test_loop.json:gates[1].x: 999 is outside -100..100", "tracks", GUARD_TABLES) == "gates.x"
    assert key_path_of("tracks/Test Loop.json:id: 'Test Loop' is not an id (lowercase ASCII, digits, _)", "tracks", GUARD_TABLES) == "id"
    for line in ("cars.json: duplicate key 'name'", "cars.json:cars: no entries", "cars.json:car: unknown key at the top level (only 'cars' and notes)"):
        assert key_path_of(line, "cars", GUARD_TABLES) == "", line


def test_datadefs_broken_case_guard_wants_a_case_for_every_key_path():
    full = guard_cases()
    # 並ぶはずの行は、1件ずつ、狙った鍵の道を指している（見本が、空振りでないこと）。
    assert full["cars rpm"][3] == ["cars.json:cars[0].engine.curve[1].rpm: -1 is outside 0..9000"]
    assert full["tracks gate x"][3] == ["tracks/test_loop.json:gates[1].x: 999 is outside -100..100"]
    assert all(len(want) == 1 for _, _, _, want in full.values())
    assert broken_case_problems(GUARD_TABLES, full) == []
    # 件を1つ抜くと、その鍵の道が挙がる。入れ子の中の鍵も、並びの中の項目の鍵も、省ける項目の中の鍵も、同じ
    # （頭の階の鍵 engine の件が残っていても、engine.idle_rpm の件が無ければ、通さない）。
    for case, (table, tag, _, _) in full.items():
        rest = {name: value for name, value in full.items() if name != case}
        missing = f"{table}: 知らない鍵か、空の表の、壊した場合が無い" if tag is None else f"{table}: 壊した場合の無い鍵：{tag}"
        assert broken_case_problems(GUARD_TABLES, rest) == [missing], case
    # 壊した場合の表が、表の定義に無い表を指す。
    stray = {**full, "sounds unknown key": ("sounds", None, {}, ["sounds.json:sounds[0].nmae: unknown key"])}
    assert broken_case_problems(GUARD_TABLES, stray) == ["sounds unknown key: 表の定義に無い表：sounds"]


def test_datadefs_broken_case_guard_checks_the_tag_against_the_place_of_the_lines():
    full = guard_cases()
    unknown_key, idle = full["cars unknown key"][3], full["cars idle"][3]

    def with_case(tag, want, name="cars idle") -> list:
        return broken_case_problems(GUARD_TABLES, {**full, name: ("cars", tag, {}, want)})

    # 札の申告が、行の場所と違う。知らない鍵を壊した件に、鍵の札を付けても、通らない。
    assert with_case("engine.idle_rpm", unknown_key) == ["cars idle: 札は engine.idle_rpm、行の場所は nmae"]
    # 頭の階の鍵の札で、入れ子の中の鍵の件を兼ねられない（逆も）。
    assert with_case("engine", idle, "cars engine") == ["cars engine: 札は engine、行の場所は engine.idle_rpm"]
    assert with_case("engine.idle_rpm", full["cars engine"][3]) == ["cars idle: 札は engine.idle_rpm、行の場所は engine"]
    # 行が2つあれば、どちらも、札の鍵の道を指す。
    assert with_case("engine.idle_rpm", [*idle, *unknown_key]) == ["cars idle: 札は engine.idle_rpm、行の場所は nmae"]
    # 項目の中を指さない行（ファイルの問題）。
    assert with_case("engine.idle_rpm", ["cars.json: duplicate key 'idle_rpm'"]) == ["cars idle: 札は engine.idle_rpm、行の場所は 項目の外"]
    # 並ぶはずの行が無い件は、札を確かめられない。
    assert with_case("engine.idle_rpm", []) == ["cars idle: 並ぶはずの行が無い"]
    # 札が None の件の行が、表の鍵を指している（鍵を壊した件を、知らない鍵の件として数えない）。
    assert with_case(None, idle, "cars unknown key") == ["cars unknown key: 札は None、行の場所は、鍵 engine.idle_rpm"]
    # 表に無い鍵の札。
    assert with_case("mass", ["cars.json:cars[0].mass: unknown key"], "cars mass") == ["cars mass: 札 mass は、表 cars の鍵の道に無い"]
    # レビューの見本：mass を壊していないのに、札だけ mass。
    assert with_case("mass", unknown_key, "cars mass") == ["cars mass: 札 mass は、表 cars の鍵の道に無い", "cars mass: 札は mass、行の場所は nmae"]
