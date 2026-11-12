"""3Dの絵の参照（tools/scene_reference.py）のテスト。判定用の実描画の結果（結果の scene）の確かめと、パレットを自分で読む所。

Pyxelは使わない。道具 run、tour、web-smoke が、この関数を使う（アプリを別プロセスで回して、絵を壊したら落ちることは、道具 selftest-break が見る）。
ここでは、確かめが、合っている場合に通り、合わない場合に、その名で落ちることを見る。
  backdrop（空の画素）、scene3d（コースの画素と車の画素）、mirror（柱と印の重心）、palette（読み戻した32色）、
  scene_same（2Dの描画命令の矩形の外の、違う画素）、back_ink（矩形の内の、違う画素）
"""
import json

import pytest

import scene_reference
from conftest import ROOT
from cp_app import data_files
from cp_core import camera, car_shape, palette
from cp_ui.canvas import SCREEN_W

BUDGETS = {"scene_sky_min_px": 5000, "scene_track_min_px": 8000, "scene_car_min_px": 300, "scene_mirror_margin_px": 15}  # 判定の値の見本
PALETTE = list(data_files.load({}, None).entry("palettes", palette.EVENING)["colors"])  # アプリと同じ読み方で読んだ32色
# 正しく写った絵の、柱と印。左の柱は、中央（159.5）の左、右の柱と、模型の右の印は、右、鼻先の印は、中央。
PROBES = {
    "pillar_left": {"pixels": 180, "x10": 1138}, "pillar_right": {"pixels": 180, "x10": 2052},
    "mark_right": {"pixels": 300, "x10": 2119}, "mark_nose": {"pixels": 130, "x10": 1595},
}
SCENE = {"sky": 21000, "track": 30000, "car": 2400, "ink_inside": 3500, "ink_outside": 0, "probes": PROBES, "palette": PALETTE, "digest": 123456789}


def scene(**values) -> dict:
    """結果（scene だけを持つ）。values で、scene の値を置き換える。"""
    return {"scene": {**SCENE, **values}}


def probes(**values) -> dict:
    """柱と印を、values（名 = (画素の数, 重心の x)）で置き換えた結果。"""
    return scene(probes={**PROBES, **{name: {"pixels": pixels, "x10": x10} for name, (pixels, x10) in values.items()}})


def failed(result, names=scene_reference.SCENE_CHECKS, want_palette=PALETTE) -> list:
    return [name for name, ok, _ in scene_reference.scene_checks(result, BUDGETS, want_palette, "", names) if not ok]


# --- 合っている場合 ---
def test_scene_reference_good_scene_passes_every_check():
    checks = scene_reference.scene_checks({"scene": SCENE, "ticks": 120}, BUDGETS, PALETTE)
    assert [name for name, _, _ in checks] == list(scene_reference.SCENE_CHECKS) == ["backdrop", "scene3d", "mirror", "palette", "scene_same", "back_ink"]
    assert [name for name, ok, _ in checks if not ok] == []
    assert all(type(message) is str and message for _, _, message in checks)


def test_scene_reference_names_of_the_probes_come_from_the_shipped_code():
    # 柱と印の名は、出荷するコードの、部品の名。アプリが、結果の鍵に使う名と、道具が見る名が、同じ。
    assert scene_reference.PROBES == ("pillar_left", "pillar_right", "mark_right", "mark_nose")
    assert [part.name for part in camera.pillar_parts(0.0, 0.0, 0.0)] + [part.name for part in car_shape.mark_parts()] == list(scene_reference.PROBES)
    assert scene_reference.PROBE_SIDES == {"pillar_left": "left", "pillar_right": "right", "mark_right": "right", "mark_nose": "center"}
    assert scene_reference.CENTER_X10 == (SCREEN_W - 1) * 5 == 1595 and scene_reference.MAX_X10 == 3190


def test_scene_reference_a_subset_of_the_checks_can_be_asked_for():
    # 2Dの描画命令を重ねない絵（巡回の3Dの絵）では、scene_same と back_ink を外す。
    names = ("backdrop", "scene3d", "mirror", "palette")
    plain = scene(ink_inside=0, ink_outside=999)
    assert [name for name, _, _ in scene_reference.scene_checks(plain, BUDGETS, PALETTE, "", names)] == list(names)
    assert failed(plain, names) == [] and failed(plain) == ["scene_same", "back_ink"]
    with pytest.raises(ValueError):
        scene_reference.scene_checks(plain, BUDGETS, PALETTE, "", ("backdrop", "mirorr"))


# --- 合わない場合。確かめごとに、その名で落ちる ---
@pytest.mark.parametrize(
    "result, names",
    [
        # 背景を写していない（空の色の画素が、無いか、少ない）。
        (scene(sky=0), ["backdrop"]),
        (scene(sky=4999), ["backdrop"]),
        (scene(sky=None), ["backdrop"]),
        (scene(sky=True), ["backdrop"]),  # 真偽の値は、数えた値でない
        (scene(sky=21000.0), ["backdrop"]),
        (scene(sky="21000"), ["backdrop"]),
        # コースを描いていない（車だけが描かれた絵）、車を描いていない、どちらも描いていない。
        (scene(track=0), ["scene3d"]),
        (scene(track=7999), ["scene3d"]),
        (scene(car=0), ["scene3d"]),
        (scene(car=299), ["scene3d"]),
        (scene(track=0, car=0), ["scene3d"]),
        (scene(track=None), ["scene3d"]),
        (scene(car=-5), ["scene3d"]),
        # パレットを当てていない（Pyxelの既定の色のまま）、1色だけ違う、数が違う。
        (scene(palette=[0x000000, 0x2B335F, 0x7E2072, 0x19959C] + PALETTE[4:]), ["palette"]),
        (scene(palette=PALETTE[:5] + [PALETTE[5] ^ 1] + PALETTE[6:]), ["palette"]),
        (scene(palette=PALETTE[:31]), ["palette"]),
        (scene(palette=PALETTE + [0]), ["palette"]),
        (scene(palette=list(reversed(PALETTE))), ["palette"]),
        (scene(palette=None), ["palette"]),
        (scene(palette=tuple(PALETTE)), ["palette"]),  # JSONから読んだ並びは、list
        (scene(palette=[float(color) for color in PALETTE]), ["palette"]),
        # ふだんの実描画が、判定と同じ3Dを描いていない（矩形の外に、違う画素がある）。
        (scene(ink_outside=1), ["scene_same"]),
        (scene(ink_outside=40000), ["scene_same"]),
        (scene(ink_outside=None), ["scene_same"]),
        (scene(ink_outside=False), ["scene_same"]),  # 真偽の値は、0 でない
        # 2Dの描画命令が、裏画面に描かれていない。
        (scene(ink_inside=0), ["back_ink"]),
        (scene(ink_inside=None), ["back_ink"]),
        (scene(ink_inside=True), ["back_ink"]),
        # 合否に使わない値は、何でもよい。
        (scene(digest=0), []),
        (scene(digest=None), []),
    ],
)
def test_scene_reference_each_deviation_fails_under_its_own_name(result, names):
    assert failed(result) == names


@pytest.mark.parametrize(
    "result",
    [
        # 鏡写しの絵（z の反転を外した）。左の柱が右に、右の柱が左に写る。模型の右の印も、左に写る。
        probes(pillar_left=(180, 2052), pillar_right=(180, 1138), mark_right=(300, 1071)),
        # 車だけが鏡写し（模型にも、反転を掛けた）。柱は正しいが、模型の右の印が、左に写る。
        probes(mark_right=(300, 1071)),
        # 柱だけが鏡写し（柱の位置の計算に、右旋回が正の決まりが混ざった）。
        probes(pillar_left=(180, 2052), pillar_right=(180, 1138)),
        # 車の向きの符号が逆。模型の右の印が、中央へ寄り、鼻先の印が、横へ出る。
        probes(mark_right=(300, 1650), mark_nose=(130, 2300)),
        probes(mark_nose=(130, 1800)),  # 鼻先の印だけが、横へ出る
        probes(mark_nose=(130, 1390)),
        # 余裕（15画素）の内は、左右を決めたことにしない。
        probes(pillar_left=(180, 1500)),
        probes(pillar_left=(180, 1445)),  # 中央から、ちょうど15画素
        probes(pillar_right=(180, 1745)),
        probes(mark_right=(300, 1700)),
        # どれかの色が、写っていない（模型にも、頂点の順の入れ替えを掛けて、片面の板が裏を向いた。柱を作っていない）。
        probes(mark_right=(0, 0), mark_nose=(0, 0)),
        probes(pillar_left=(0, 0)),
        probes(pillar_right=(0, 2052)),
        probes(mark_nose=(0, 1595)),
        # 値の形が違う。
        probes(pillar_left=(True, 1138)),
        probes(pillar_left=(180, None)),
        probes(pillar_left=(180, 113.8)),
        probes(pillar_left=(180, -1)),
        probes(pillar_right=(180, 3191)),  # 画面の外
        scene(probes=None),
        scene(probes={}),
        scene(probes=[PROBES]),
        scene(probes={name: value for name, value in PROBES.items() if name != "mark_nose"}),
        scene(probes={**PROBES, "pillar_left": [180, 1138]}),
        scene(probes={**PROBES, "mark_left": {"pixels": 5, "x10": 100}}),  # 知らない名
    ],
)
def test_scene_reference_mirrored_or_missing_probes_fail_the_mirror_check(result):
    assert failed(result) == ["mirror"]


def test_scene_reference_probes_just_beyond_the_margin_pass():
    # 余裕は15画素。中央（159.5）から、15画素を超えて左（右）なら、左（右）に写っている。鼻先の印は、15画素の内。
    assert failed(probes(pillar_left=(1, 1444), pillar_right=(1, 1746), mark_right=(1, 1746), mark_nose=(1, 1445))) == []
    assert failed(probes(mark_nose=(1, 1745))) == [] and failed(probes(mark_nose=(1, 1746))) == ["mirror"]
    assert failed(probes(pillar_left=(1, 0), pillar_right=(1, 3190))) == []  # 画面の端
    # 余裕を変えると、線が動く。
    wide = {**BUDGETS, "scene_mirror_margin_px": 60}
    assert [name for name, ok, _ in scene_reference.scene_checks({"scene": SCENE}, wide, PALETTE) if not ok] == ["mirror"]
    none = {**BUDGETS, "scene_mirror_margin_px": 0}
    assert [name for name, ok, _ in scene_reference.scene_checks(probes(pillar_left=(1, 1594), mark_nose=(1, 1595)), none, PALETTE) if not ok] == []


def test_scene_reference_messages_say_what_was_seen():
    by_name = {name: message for name, _, message in scene_reference.scene_checks(scene(sky=12, track=34, car=56, ink_outside=78, ink_inside=0), BUDGETS, PALETTE)}
    assert "12" in by_name["backdrop"] and "5000" in by_name["backdrop"]
    assert "34" in by_name["scene3d"] and "56" in by_name["scene3d"] and "8000" in by_name["scene3d"] and "300" in by_name["scene3d"]
    assert "78" in by_name["scene_same"] and "0" in by_name["back_ink"]
    problems = scene_reference.probe_problems(probes(pillar_left=(180, 2052), mark_nose=(0, 0))["scene"], 15)
    assert len(problems) == 2 and "pillar_left" in problems[0] and "+45.7" in problems[0] and "中央より左" in problems[0]
    assert "mark_nose" in problems[1] and "写っていない" in problems[1]
    assert scene_reference.probe_problems(SCENE, 15) == []
    wrong = PALETTE[:7] + [0] + PALETTE[8:]
    message = dict((name, text) for name, _, text in scene_reference.scene_checks(scene(palette=wrong), BUDGETS, PALETTE))["palette"]
    assert "[7]" in message  # 違う番号


@pytest.mark.parametrize("result", [{}, {"ticks": 120}, {"scene": None}, {"scene": []}, {"scene": "scene"}, {"scene": {}}, None, [], "result"])
def test_scene_reference_result_without_the_scene_fails_every_check(result):
    # 古い形の結果（scene が無い）。何も見ずに通さない。
    assert failed(result) == list(scene_reference.SCENE_CHECKS)


def test_scene_reference_palette_that_could_not_be_read_never_passes():
    # 道具が、定義データのパレットを読めなかったら、アプリの申告が、どんな値でも、合格にしない。
    checks = scene_reference.scene_checks({"scene": SCENE}, BUDGETS, None, "（読めなかった：no such file）")
    assert [name for name, ok, _ in checks if not ok] == ["palette"]
    assert "読めなかった" in dict((name, message) for name, _, message in checks)["palette"]
    assert failed(scene(palette=None), want_palette=None) == ["palette"]


# --- 道具の値（下限と余裕） ---
def test_scene_reference_budgets_it_needs_are_named_and_checked():
    assert scene_reference.BUDGET_KEYS == ("scene_sky_min_px", "scene_track_min_px", "scene_car_min_px", "scene_mirror_margin_px")
    assert scene_reference.missing_budgets(BUDGETS) == []
    assert scene_reference.missing_budgets({}) == list(scene_reference.BUDGET_KEYS)
    assert scene_reference.missing_budgets({**BUDGETS, "scene_car_min_px": 2.5}) == ["scene_car_min_px"]
    assert scene_reference.missing_budgets({**BUDGETS, "scene_sky_min_px": True, "scene_mirror_margin_px": -1}) == ["scene_sky_min_px", "scene_mirror_margin_px"]
    with pytest.raises(KeyError):  # 値が無いまま、判定しない（黙って、0 を下限にしない）
        scene_reference.scene_checks({"scene": SCENE}, {}, PALETTE)


# --- 道具が、パレットを、定義データから自分で読む ---
def write(path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if type(value) is str else json.dumps(value), encoding="utf-8")


def test_scene_reference_reads_the_real_palette_by_itself_and_agrees_with_the_loader_of_the_app():
    colors, why = scene_reference.expected_palette()
    assert why == "" and colors == PALETTE and type(colors) is list and len(colors) == 32
    assert scene_reference.expected_palette(pack="extreme") == (PALETTE, "")  # 試験用データ（extreme）は、パレットを持たない
    assert scene_reference.PALETTES_FILE == "palettes.json" and (ROOT / "clipping_point" / "data" / scene_reference.PALETTES_FILE).is_file()


def test_scene_reference_palette_of_a_pack_replaces_the_same_id(tmp_path):
    data, packs = tmp_path / "data", tmp_path / "testpacks"
    write(data / "palettes.json", {"_notes": {}, "palettes": [{"id": "evening", "colors": [1, 2, 3]}, {"id": "noon", "colors": [4, 5, 6]}]})
    write(packs / "night" / "palettes.json", {"palettes": [{"id": "evening", "colors": [7, 8, 9]}, {"id": "dawn", "colors": [10]}]})
    write(packs / "plain" / "cars.json", {"cars": []})
    assert scene_reference.expected_palette("evening", None, data, packs) == ([1, 2, 3], "")
    assert scene_reference.expected_palette("noon", None, data, packs) == ([4, 5, 6], "")
    assert scene_reference.expected_palette("evening", "night", data, packs) == ([7, 8, 9], "")  # 同じ id は、差し替え
    assert scene_reference.expected_palette("noon", "night", data, packs) == ([4, 5, 6], "")  # 重ねなかった項目は、そのまま
    assert scene_reference.expected_palette("dawn", "night", data, packs) == ([10], "")  # 新しい id は、足す
    assert scene_reference.expected_palette("evening", "plain", data, packs) == ([1, 2, 3], "")  # パレットを持たない試験用データ


@pytest.mark.parametrize("content", [b"{", b"[1]", b'{"palettes": 5}', b'{"palettes": [5]}', b'{"palettes": [{"id": "evening"}]}', b'{"palette": []}', b"\xff\xfe"])
def test_scene_reference_palette_file_it_cannot_read_gives_no_colours_and_a_reason(tmp_path, content):
    data = tmp_path / "data"
    data.mkdir()
    (data / "palettes.json").write_bytes(content)
    colors, why = scene_reference.expected_palette("evening", None, data, tmp_path / "testpacks")
    assert colors is None and "palettes.json" in why


def test_scene_reference_missing_palette_file_or_id_gives_no_colours_and_a_reason(tmp_path):
    colors, why = scene_reference.expected_palette("evening", None, tmp_path / "no_such_data", tmp_path / "testpacks")
    assert colors is None and "palettes.json" in why
    write(tmp_path / "data" / "palettes.json", {"palettes": [{"id": "noon", "colors": [1]}]})
    colors, why = scene_reference.expected_palette("evening", None, tmp_path / "data", tmp_path / "testpacks")
    assert colors is None and "evening" in why


# --- 最後の1行に出す値 ---
def test_scene_reference_words_for_the_last_line():
    assert scene_reference.scene_words({"scene": SCENE}) == "sky=21000 track=30000 car=2400 ink=3500/0 digest=123456789"
    assert scene_reference.scene_words({}) == "sky=None track=None car=None ink=None/None digest=None"
