"""巡回の口（cp_app.tour）のテスト。Pyxelは使わない。

画素を照らす関数（矩形の外の画素、内の画素が無い、余白の画素、空白だけの文字）には、画素の並びを直に与える。
巡回の流れ（描く、数える、保存する、結果ファイルを書く）は、偽の Pyxel（純Pythonで矩形を塗るだけの画像）で通す。
3Dの絵（見本ごとに、描く、保存する、判定用の実描画を回す）は、偽の場面（FakeScene）を渡して通す（None を渡して、3Dを飛ばす形にしない）。
3Dの場面そのもの（座標の変換、描く口、判定）のテストは tests/test_render.py。
実物のPyxelの画素と照らすこと（文字の大きさの式、線、縁だけの矩形）は、道具 tour と selftest-break が見る。
"""
import json
import math

import pytest

import input_reference
from cp_app import tour
from cp_app.canvas_pyxel import execute
from cp_ui import fixtures
from cp_ui.canvas import FONT_H, FONT_W, SCREEN_H, SCREEN_W, Canvas, LineCommand, RectCommand, TextCommand
from cp_ui.screens import COL_BACK, SCREENS

W, H = 12, 8  # 画素を照らす関数に与える、小さな絵の大きさ


def picture(*ink, back: int = 0, width: int = W, height: int = H) -> bytes:
    """back で埋めた絵に、ink（(x, y) か (x, y, 色)）を置く。"""
    data = bytearray([back]) * (width * height)
    for x, y, *col in ink:
        data[y * width + x] = col[0] if col else 7
    return bytes(data)


# --- 画素を照らす関数 ---
def test_tour_blank_picture_has_no_ink():
    assert tour.count_ink(picture(), W, H, 0, (2, 2, 4, 3)) == (0, 0)


def test_tour_ink_inside_the_rectangle_counts_as_inside():
    pixels = picture((2, 2), (5, 2), (2, 4), (5, 4), (3, 3))  # 矩形は x=2〜5、y=2〜4。四隅と中
    assert tour.count_ink(pixels, W, H, 0, (2, 2, 4, 3)) == (0, 5)


@pytest.mark.parametrize("point", [(1, 2), (6, 2), (2, 1), (2, 5), (0, 0), (11, 7)])
def test_tour_ink_one_pixel_outside_the_rectangle_counts_as_outside(point):
    # 左、右、上、下へ1画素。絵の隅。
    assert tour.count_ink(picture(point, (3, 3)), W, H, 0, (2, 2, 4, 3)) == (1, 1)


def test_tour_pixels_are_read_row_by_row_from_the_top_left():
    pixels = picture((1, 0))
    assert pixels[1] == 7 and pixels[W] == 0
    assert tour.count_ink(pixels, W, H, 0, (1, 0, 1, 1)) == (0, 1)
    assert tour.count_ink(pixels, W, H, 0, (0, 1, 1, 1)) == (1, 0)


def test_tour_only_pixels_that_differ_from_the_background_count():
    # 背景が1なら、色1の画素は数えず、色0の画素は数える（命令の色が0のとき、検査用の裏画面は1で消す）。
    pixels = picture((3, 3, 0), (8, 6, 0), (4, 3, 1), back=1)
    assert tour.count_ink(pixels, W, H, 1, (2, 2, 4, 3)) == (1, 1)
    # 背景を0と読めば、色0の2画素のほかは、全部がインク。矩形（12画素）の内に、色0が1つ。
    assert tour.count_ink(pixels, W, H, 0, (2, 2, 4, 3)) == (W * H - 12 - 1, 12 - 1)


def test_tour_rectangle_that_sticks_out_of_the_picture_is_clipped():
    pixels = picture((0, 0), (11, 7), (5, 3))
    assert tour.count_ink(pixels, W, H, 0, (-5, -5, 8, 8)) == (2, 1)  # 左上へはみ出た矩形。(0,0) だけが内
    assert tour.count_ink(pixels, W, H, 0, (10, 6, 50, 50)) == (2, 1)  # 右下へはみ出た矩形。(11,7) だけが内
    assert tour.count_ink(pixels, W, H, 0, (-100, -100, 5, 5)) == (3, 0)  # 丸ごと外


@pytest.mark.parametrize("rect", [(2, 2, 0, 3), (2, 2, 4, 0), (2, 2, -1, 3), (2, 2, 4, -2)])
def test_tour_rectangle_without_area_holds_nothing(rect):
    assert tour.count_ink(picture((3, 3)), W, H, 0, rect) == (1, 0)


def test_tour_margin_ink_is_the_ink_outside_the_screen_rectangle():
    # 全体の絵の数え方。余白2の絵で、画面の内（x=2〜9、y=2〜5）に3つ、余白に2つ。
    pixels = picture((2, 2), (9, 5), (5, 3), (1, 3), (10, 7))
    margin_ink, screen_ink = tour.count_ink(pixels, W, H, 0, (2, 2, W - 4, H - 4))
    assert (margin_ink, screen_ink) == (2, 3)


def test_tour_picture_of_the_wrong_length_is_an_error():
    with pytest.raises(ValueError):
        tour.count_ink(picture()[:-1], W, H, 0, (0, 0, 1, 1))
    with pytest.raises(ValueError):
        tour.count_ink(picture(), W, H + 1, 0, (0, 0, 1, 1))


# --- 命令ごとの判定 ---
def test_tour_command_with_ink_inside_and_none_outside_is_fine():
    assert tour.command_problems(TextCommand(0, 0, "AB", 7), 0, 20) == []
    assert tour.command_problems(RectCommand(0, 0, 4, 4, 1), 0, 16) == []


def test_tour_ink_outside_the_rectangle_is_a_problem():
    assert tour.command_problems(TextCommand(0, 0, "AB", 7), 3, 20) == ["ink_outside"]


def test_tour_no_ink_inside_the_rectangle_is_a_problem():
    # 残したのに、描かれていない命令。
    assert tour.command_problems(TextCommand(0, 0, "AB", 7), 0, 0) == ["no_ink"]
    assert tour.command_problems(RectCommand(0, 0, 4, 4, 1), 0, 0) == ["no_ink"]
    assert tour.command_problems(LineCommand(0, 0, 4, 0, 1), 0, 0) == ["no_ink"]
    assert tour.command_problems(TextCommand(0, 0, "ティック", 7), 0, 0) == ["no_ink"]  # 内蔵フォントが描かない字


def test_tour_command_drawn_somewhere_else_has_both_problems():
    assert tour.command_problems(LineCommand(0, 0, 4, 0, 1), 5, 0) == ["ink_outside", "no_ink"]


@pytest.mark.parametrize("text", [" ", "   ", " \n ", "\n"])
def test_tour_blank_text_may_have_no_ink(text):
    command = TextCommand(0, 0, text, 7)
    assert tour.is_blank_text(command)
    assert tour.command_problems(command, 0, 0) == []
    assert tour.command_problems(command, 2, 0) == ["ink_outside"]  # 空白だけでも、矩形の外の画素は問題


def test_tour_text_with_one_visible_character_is_not_blank():
    assert not tour.is_blank_text(TextCommand(0, 0, "  .  ", 7))
    assert not tour.is_blank_text(TextCommand(0, 0, "\t", 7))  # 空白と改行のほかは、空白に数えない
    assert not tour.is_blank_text(RectCommand(0, 0, 4, 4, 1))


def test_tour_check_background_differs_from_the_color_of_the_command():
    for col in range(0, 32):
        assert tour.back_for(col) != col
    assert (tour.back_for(0), tour.back_for(1), tour.back_for(7)) == (1, 0, 0)


# --- 環境変数 ---
def test_tour_no_config_without_cp_tour():
    assert tour.read_config({}) is None
    assert tour.read_config({"CP_TOUR": ""}) is None
    # CP_TOUR が無ければ、ほかの値は読まない（画面なしで回す口の邪魔をしない）。
    assert tour.read_config({"CP_SMOKE": "/tmp/result.json", "CP_TOUR_DIR": "relative", "CP_TOUR_ONLY": "nosuch"}) is None


def test_tour_config_holds_the_result_file_the_shot_dir_and_the_screen():
    assert tour.read_config({"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "/tmp/t"}) == tour.TourConfig("/tmp/t/result.json", "/tmp/t", "")
    config = tour.read_config({"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "/tmp/t", "CP_TOUR_ONLY": "placeholder"})
    assert config.only == "placeholder"
    # 3Dの絵だけを回す名。画面の名と、重ならない。
    config = tour.read_config({"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "/tmp/t", "CP_TOUR_ONLY": "scene"})
    assert config.only == tour.SCENE_ONLY == "scene" and tour.SCENE_ONLY not in SCREENS


@pytest.mark.parametrize(
    "env",
    [
        {"CP_TOUR": "out/tour/result.json", "CP_TOUR_DIR": "/tmp/t"},  # 結果ファイルが相対パス
        {"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "out/tour"},  # 置き場が相対パス
        {"CP_TOUR": "/tmp/t/result.json"},  # 置き場が無い
        {"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": ""},
        {"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "/tmp/t", "CP_TOUR_ONLY": "no_such_screen"},  # 無い画面の名
        {"CP_TOUR": "/tmp/t/result.json", "CP_TOUR_DIR": "/tmp/t", "CP_SMOKE": "/tmp/t/run.json"},  # 2つの口を同時に開く
        {"CP_TOUR": "relative.json", "CP_TOUR_DIR": "/tmp/t", "CP_SMOKE": "/tmp/t/run.json"},
    ],
)
def test_tour_bad_config_is_an_error_at_startup(env):
    with pytest.raises(ValueError):
        tour.read_config(env)


# --- 巡回の流れ。偽の Pyxel で通す ---
class FakeImage:
    """pyxel.Image の代わり。1画素1バイトの絵に、矩形を塗るだけ。文字は、空白でない字ごとに、3×5のかたまりを塗る。"""

    glyph_w = FONT_W - 1  # 1字のインクの幅。実物の内蔵フォントと同じ3

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.data = bytearray(width * height)
        self.saved = []  # (パス, 拡大率, 保存した時の画素)

    def cls(self, col):
        self.data[:] = bytes([col]) * len(self.data)

    def pset(self, x, y, col):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.data[y * self.width + x] = col

    def rect(self, x, y, w, h, col):
        for py in range(y, y + h):
            for px in range(x, x + w):
                self.pset(px, py, col)

    def rectb(self, x, y, w, h, col):
        for px in range(x, x + w):
            self.pset(px, y, col)
            self.pset(px, y + h - 1, col)
        for py in range(y, y + h):
            self.pset(x, py, col)
            self.pset(x + w - 1, py, col)

    def line(self, x1, y1, x2, y2, col):
        assert x1 == x2 or y1 == y2, "偽の画像は、縦か横の線だけを描く"
        self.rect(min(x1, x2), min(y1, y2), abs(x2 - x1) + 1, abs(y2 - y1) + 1, col)

    def text(self, x, y, s, col):
        for row, line in enumerate(s.split("\n")):
            for index, ch in enumerate(line):
                if ch != " ":
                    self.rect(x + FONT_W * index, y + FONT_H * row, self.glyph_w, FONT_H - 1, col)

    def blt(self, x, y, img, u, v, w, h):
        for row in range(h):  # 写す範囲は、どちらの絵でも内に収まっている前提
            source, target = (v + row) * img.width + u, (y + row) * self.width + x
            self.data[target:target + w] = img.data[source:source + w]

    def save(self, path, scale):
        self.saved.append((path, scale, bytes(self.data)))

    def data_ptr(self):
        return self.data


class FakePyxel:
    """pyxel のモジュールの代わり。run も flip も quit も持たない（呼べば AttributeError）。"""

    KEY_NONE = 0
    VERSION = "fake"
    image_type = FakeImage

    def __init__(self) -> None:
        self.inits = []
        self.images = []

    def init(self, *args, **kwargs):
        self.inits.append((args, kwargs))

    def Image(self, width, height):  # noqa: N802 - pyxel.Image と同じ名
        image = self.image_type(width, height)
        self.images.append(image)
        return image


SKY_COL, GROUND_COL = 16, 6  # 偽の場面が塗る色（空と地面）。仮の表示が使わない色


class FakeScene:
    """3Dの場面（cp_app.render の Scene）の代わり。Pyxelの3Dには触れない。描く口は、絵を、空と地面の2色で塗り、車の位置に点を打つだけ。

    コースの表は、本物（純Python）。呼ばれた順を、log に残す。
    """

    def __init__(self, log=None) -> None:
        self.track = input_reference.make_sim().track
        self.log = [] if log is None else log
        self.stats = {"chunks": 12}
        self.judged = []  # judge() へ渡された (絵の画素, 矩形の並び, x, z, 向き)

    def build(self, probes=False, clock=None) -> None:
        self.log.append(("build", probes, clock is not None))

    def chase(self, x, z, heading):
        return ("pose", x, z, heading)

    def draw(self, target, pose, x, z, heading, layers=None) -> None:
        assert pose == ("pose", x, z, heading)
        self.log.append(("draw", round(x, 3), round(z, 3), round(heading, 3), layers))
        target.cls(GROUND_COL)
        target.rect(0, 0, SCREEN_W, 100, SKY_COL)
        target.pset(int(x) % SCREEN_W, 120 + int(z) % 100, 7)  # 見本ごとに、違う絵になるように
        self.stats = {**self.stats, "chunks_drawn": 9, "triangles_drawn": 2972}

    def judge(self, shown, rects, x, z, heading) -> dict:
        self.log.append(("judge", round(x, 3), round(z, 3), round(heading, 3)))
        self.judged.append((shown, tuple(rects), x, z, heading))
        return {"sky": shown.count(SKY_COL), "track": 40000, "car": 5000, "ink_inside": 0, "ink_outside": 0, "probes": {}, "palette": [], "digest": 1}


def run_tour(tmp_path, pyxel=None, only: str = "", scene=None):
    pyxel = pyxel or FakePyxel()
    config = tour.TourConfig(str(tmp_path / "result.json"), str(tmp_path), only)
    return pyxel, tour.run(pyxel, config, scene or FakeScene())


def test_tour_run_starts_pyxel_without_a_window(tmp_path):
    pyxel, _ = run_tour(tmp_path)
    assert len(pyxel.inits) == 1
    args, kwargs = pyxel.inits[0]
    assert args == (SCREEN_W, SCREEN_H) and kwargs["headless"] is True


def test_tour_run_writes_one_entry_per_screen_and_variant(tmp_path):
    _, result = run_tour(tmp_path)
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8")) == result
    assert not (tmp_path / "result.json.tmp").exists()
    assert [(shot["screen"], shot["variant"]) for shot in result["shots"]] == [("placeholder", "typical"), ("placeholder", "extreme")]
    # 命令の数は、ふつうの値で16（文字9、下地の矩形5、縁だけの矩形1、線1）。極端な値は、知らせの1行の分、文字と下地の矩形が1つずつ多い。
    for shot, commands in zip(result["shots"], (16, 18), strict=True):
        assert shot["commands"] == shot["checked"] == commands  # どの命令も、1つずつ照らしている
        assert shot["margin_ink"] == 0 and shot["screen_ink"] > 0
        assert shot["command_problems"] == [] and shot["violations"] == []
        assert shot["file"] == f"{shot['screen']}_{shot['variant']}.png"
    assert (result["margin"], result["scale"]) == (16, 2)


def test_tour_run_saves_the_whole_picture_cut_to_the_screen_size(tmp_path):
    pyxel, result = run_tour(tmp_path)
    whole, single, shot = pyxel.images
    assert (whole.width, whole.height) == (single.width, single.height) == (SCREEN_W + 32, SCREEN_H + 32)
    assert (shot.width, shot.height) == (SCREEN_W, SCREEN_H)
    # 保存するのは、画面の大きさの画像だけ。全体の絵そのもの（余白つき）と、命令を1つずつ描く裏画面は、保存しない。
    assert whole.saved == [] and single.saved == []
    assert [(path, scale) for path, scale, _ in shot.saved[:2]] == [
        (str(tmp_path / "placeholder_typical.png"), 2), (str(tmp_path / "placeholder_extreme.png"), 2),
    ]
    # 保存した絵は、全部の命令を描いた絵（最後の1つだけを描いた絵ではない）。背景と違う画素の数が、数えた値と同じ。
    for (_, _, pixels), entry in zip(shot.saved[:2], result["shots"], strict=True):
        assert len(pixels) - pixels.count(COL_BACK) == entry["screen_ink"]


def saved_pictures(pyxel) -> list:
    """保存した、画面の絵の画素。保存した順（3Dの絵は、その後ろに保存されるので、含めない）。"""
    return [pixels for path, _, pixels in pyxel.images[2].saved if not path.rsplit("/", 1)[-1].startswith(tour.SCENE_FILE_HEAD)]


def test_tour_run_clears_the_whole_picture_before_each_screen(tmp_path):
    # 作った時に、全部の画素を別の色で埋めてある偽の画像で回す（前の件の絵が残っている状態に当たる）。
    # 全体の絵を、描く前に消していれば、保存した絵も、数えた値も、きれいな画像で回したときと同じになる。
    class Dirty(FakeImage):
        def __init__(self, width: int, height: int) -> None:
            super().__init__(width, height)
            self.data[:] = bytes([9]) * len(self.data)  # 仮の表示が使わない色

    clean, clean_result = run_tour(tmp_path)
    dirty = FakePyxel()
    dirty.image_type = Dirty
    _, dirty_result = run_tour(tmp_path, dirty)
    assert len(saved_pictures(clean)) == 2
    assert saved_pictures(dirty) == saved_pictures(clean)
    for clean_shot, dirty_shot in zip(clean_result["shots"], dirty_result["shots"]):
        assert {**dirty_shot, "check_ms": 0} == {**clean_shot, "check_ms": 0}  # 時間のほかは同じ


def test_tour_run_draws_each_variant_with_its_own_fixture(tmp_path):
    # 変種を取り違えていないこと。極端な値の絵は、ふつうの値の絵と違い、画面の内の画素の数が多い（文字が長い）。
    pyxel, result = run_tour(tmp_path)
    typical, extreme = saved_pictures(pyxel)
    assert typical != extreme
    ink = {shot["variant"]: shot["screen_ink"] for shot in result["shots"]}
    assert ink["extreme"] > ink["typical"] > 0


@pytest.mark.parametrize("variant", fixtures.VARIANTS)
def test_tour_run_saves_the_picture_of_the_variant_in_the_file_name(tmp_path, variant):
    # 保存した絵が、その変種の見本データで、画面を1度だけ描いた絵と、同じ画素であること
    # （前の件の絵が混ざっていない。別の変種の絵でもない）。
    pyxel, result = run_tour(tmp_path)
    index = [shot["variant"] for shot in result["shots"]].index(variant)
    canvas = Canvas()
    SCREENS["placeholder"](canvas, fixtures.build("placeholder", variant))
    want = FakeImage(SCREEN_W, SCREEN_H)
    want.cls(COL_BACK)
    execute(canvas.commands, want)
    path, _, pixels = pyxel.images[2].saved[index]
    assert path == str(tmp_path / f"placeholder_{variant}.png")
    assert pixels == bytes(want.data)


def test_tour_run_can_be_limited_to_one_screen(tmp_path, monkeypatch):
    monkeypatch.setitem(tour.SCREENS, "other", tour.SCREENS["placeholder"])
    monkeypatch.setitem(fixtures.BUILDERS, "other", fixtures.BUILDERS["placeholder"])
    _, result = run_tour(tmp_path)
    assert [shot["screen"] for shot in result["shots"]] == ["placeholder", "placeholder", "other", "other"]
    _, result = run_tour(tmp_path, only="other")
    assert [(shot["screen"], shot["variant"]) for shot in result["shots"]] == [("other", "typical"), ("other", "extreme")]


def test_tour_run_writes_no_result_file_when_a_screen_fails_midway(tmp_path):
    class FailsOnTheSecondSave(FakeImage):
        def save(self, path, scale):
            if self.saved:
                raise RuntimeError("planted")
            super().save(path, scale)

    pyxel = FakePyxel()
    pyxel.image_type = FailsOnTheSecondSave
    with pytest.raises(RuntimeError):
        run_tour(tmp_path, pyxel)
    # 結果ファイルは、全部の画面を回した後にだけ書く。
    assert not (tmp_path / "result.json").exists() and not (tmp_path / "result.json.tmp").exists()


# --- 3Dの絵。偽の場面で通す ---
def test_tour_run_builds_the_scene_with_the_probes_after_starting_pyxel(tmp_path):
    # 場面は、Pyxelを始めた後に、組む（パレットも、ここで当たる）。巡回の口は、検証の口なので、判定用の柱と印も作る。
    log = []

    class LoggingPyxel(FakePyxel):
        def init(self, *args, **kwargs):
            log.append(("init",))
            super().init(*args, **kwargs)

    run_tour(tmp_path, LoggingPyxel(), scene=FakeScene(log))
    assert log[:2] == [("init",), ("build", True, True)]
    assert [entry[0] for entry in log].count("build") == 1


def test_tour_run_shoots_every_scene_sample_after_the_screens(tmp_path):
    scene = FakeScene()
    pyxel, result = run_tour(tmp_path, scene=scene)
    names = [sample[0] for sample in tour.SCENE_SHOTS]
    assert names == ["straight", "corner", "wall"]
    assert [entry["name"] for entry in result["scenes"]] == names
    assert [entry["file"] for entry in result["scenes"]] == [f"scene_{name}.png" for name in names]
    # 画像は、画面の絵の後ろに、同じ拡大率で保存する。
    saved = pyxel.images[2].saved
    assert [(path, scale) for path, scale, _ in saved[2:]] == [(str(tmp_path / f"scene_{name}.png"), 2) for name in names]
    # 見本ごとに、描く（ふだんの実描画と同じ描く口。描くものは、既定）→ 判定、の順。車の位置と向きは、コースの表から引いた値。
    steps = [entry for entry in scene.log if entry[0] in ("draw", "judge")]
    assert [entry[0] for entry in steps] == ["draw", "judge"] * 3
    for sample, draw, judge, entry in zip(tour.SCENE_SHOTS, steps[0::2], steps[1::2], result["scenes"], strict=True):
        x, z, heading = tour.scene_pose(scene.track, sample)
        assert draw == ("draw", round(x, 3), round(z, 3), round(heading, 3), None)
        assert judge == ("judge", round(x, 3), round(z, 3), round(heading, 3))
        assert (entry["x_mm"], entry["z_mm"], entry["heading_mrad"]) == (round(x * 1000), round(z * 1000), round(heading * 1000))
        assert (entry["chunks_drawn"], entry["triangles_drawn"]) == (9, 2972)
    assert result["scene_stats"]["chunks"] == 12


def test_tour_run_judges_the_very_picture_it_saved(tmp_path):
    # 判定用の実描画へ渡す絵は、保存した絵と同じ画素（別に描き直した絵ではない）。2Dの描画命令は、重ねていない（矩形は、空）。
    scene = FakeScene()
    pyxel, result = run_tour(tmp_path, scene=scene)
    saved = [pixels for _, _, pixels in pyxel.images[2].saved[2:]]
    assert len(saved) == len(scene.judged) == 3 and len(set(saved)) == 3  # 見本ごとに、違う絵
    for pixels, (shown, rects, _, _, _), entry in zip(saved, scene.judged, result["scenes"], strict=True):
        assert shown == pixels and rects == ()
        assert entry["scene"]["sky"] == pixels.count(SKY_COL) == SCREEN_W * 100


def test_tour_run_can_be_limited_to_the_scenes_or_to_one_screen(tmp_path):
    pyxel, result = run_tour(tmp_path, only=tour.SCENE_ONLY)
    assert result["shots"] == [] and len(result["scenes"]) == 3
    assert [path for path, _, _ in pyxel.images[2].saved] == [str(tmp_path / f"scene_{sample[0]}.png") for sample in tour.SCENE_SHOTS]
    scene = FakeScene()
    _, result = run_tour(tmp_path, only="placeholder", scene=scene)
    assert len(result["shots"]) == 2 and result["scenes"] == []
    assert [entry[0] for entry in scene.log] == ["build"]  # 場面は組む（パレットを当てる）が、3Dの絵は描かない


def test_tour_run_writes_no_result_file_when_a_scene_fails_midway(tmp_path):
    class FailsOnTheSecondJudge(FakeScene):
        def judge(self, shown, rects, x, z, heading):
            if self.judged:
                raise RuntimeError("planted")
            return super().judge(shown, rects, x, z, heading)

    with pytest.raises(RuntimeError):
        run_tour(tmp_path, scene=FailsOnTheSecondJudge())
    assert not (tmp_path / "result.json").exists() and not (tmp_path / "result.json.tmp").exists()


def distance_from(heading: float, angle: float) -> float:
    """向き heading と、角度 angle の差（rad。折り返して、0〜π）。"""
    return abs((heading - angle + math.pi) % (2.0 * math.pi) - math.pi)


def test_tour_scene_samples_are_a_straight_a_corner_and_a_place_by_the_wall():
    # 見本は、仮の周回路の寸法で決めた値。コースが変わって、狙った所から外れたら、ここで落ちる。
    track = input_reference.make_sim().track
    poses = {sample[0]: tour.scene_pose(track, sample) for sample in tour.SCENE_SHOTS}
    assert len(poses) == len(tour.SCENE_SHOTS) == 3  # 名は、重ならない
    queries = {name: track.query(x, z, None) for name, (x, z, _) in poses.items()}
    # 直線。スタート位置（向き0、z=0）。
    x, z, heading = poses["straight"]
    start_x, start_z, start_heading = track.start_pose()
    assert (round(x, 6), round(z, 6), round(heading, 6)) == (round(start_x, 6), round(start_z, 6), round(start_heading, 6))
    assert abs(heading) < 1e-6 and abs(z) < 1e-6 and abs(queries["straight"].curvature) < 1e-6
    # コーナーの途中。舗装の上。向きが π/4〜3π/4 の間で、z が0でない（向きの符号の誤りと、z の反転の付け忘れが、絵に出る）。
    x, z, heading = poses["corner"]
    assert abs(queries["corner"].curvature) > 0.01 and queries["corner"].surface == "asphalt"
    assert math.pi / 4 < heading < 3 * math.pi / 4 and abs(z) > 10.0
    # 壁の近く。芝の上で、右の壁まで3 m以内。壁の側へ向いている（コースの向きより、右）。
    x, z, heading = poses["wall"]
    assert queries["wall"].surface == "grass" and 0.0 < queries["wall"].to_wall_right < 3.0
    assert distance_from(heading, queries["wall"].heading) > 0.3
    assert (heading - queries["wall"].heading + math.pi) % (2.0 * math.pi) - math.pi < 0.0
    # 向きが、0、π/2、π（と −π/2）のどれからも、0.3 rad以上離れている。
    assert all(distance_from(heading, angle) >= 0.3 for angle in (0.0, math.pi / 2, math.pi, -math.pi / 2))


def problems_of(result: dict) -> list:
    return [(entry["kind"], entry["problem"]) for shot in result["shots"] for entry in shot["command_problems"]]


def test_tour_run_reports_an_outline_drawn_wider_than_its_command(tmp_path):
    # 縁だけの矩形を、命令より2ピクセル広く描く。
    class WideOutlines(FakeImage):
        def rectb(self, x, y, w, h, col):
            super().rectb(x, y, w + 2, h, col)

    pyxel = FakePyxel()
    pyxel.image_type = WideOutlines
    _, result = run_tour(tmp_path, pyxel)
    assert problems_of(result) == [("rectb", "ink_outside")] * 2


def test_tour_run_reports_commands_that_were_recorded_but_not_drawn(tmp_path):
    class NoText(FakeImage):
        def text(self, x, y, s, col):
            pass

    pyxel = FakePyxel()
    pyxel.image_type = NoText
    _, result = run_tour(tmp_path, pyxel)
    assert problems_of(result) == [("text", "no_ink")] * 19  # 文字の命令は、ふつうの値で9つ、極端な値で10（知らせの1行）
    # 全体の数（余白の画素、画面が空でないこと）だけでは、見えない。
    assert all(shot["margin_ink"] == 0 and shot["screen_ink"] > 0 for shot in result["shots"])


def test_tour_run_reports_a_line_drawn_at_another_place(tmp_path):
    class ShiftedLines(FakeImage):
        def line(self, x1, y1, x2, y2, col):
            super().line(x1, y1 + 1, x2, y2 + 1, col)

    pyxel = FakePyxel()
    pyxel.image_type = ShiftedLines
    _, result = run_tour(tmp_path, pyxel)
    assert problems_of(result) == [("line", "ink_outside"), ("line", "no_ink")] * 2


def test_tour_run_reports_text_wider_than_the_computed_ink_box_even_on_a_filled_bar(tmp_path):
    # 文字の大きさの計算が、実物より1ピクセル狭い場合に当たる（偽の画像が、1字を4ピクセルの幅で塗る）。
    # タイトルの文字は、帯（塗りつぶした矩形）の上にある。全部を描いた後に「どの矩形にも入らない画素」を数える形では、見えない。
    class WideGlyphs(FakeImage):
        glyph_w = FONT_W

    pyxel = FakePyxel()
    pyxel.image_type = WideGlyphs
    _, result = run_tour(tmp_path, pyxel)
    assert problems_of(result) == [("text", "ink_outside")] * 19  # 文字の命令の全部（ふつうの値で9つ、極端な値で10）
    assert all(shot["margin_ink"] == 0 for shot in result["shots"])


def test_tour_shoot_sees_ink_in_the_background_color(tmp_path, monkeypatch):
    # 背景と同じ色で描く文字。全体の絵では数えられないが、命令ごとの照合は、違う色で消した裏画面へ描くので、見える。
    def dark(canvas, view):
        canvas.rect(0, 0, 40, 10, 1)
        canvas.text(2, 2, "AB", COL_BACK)

    class WideGlyphs(FakeImage):
        glyph_w = FONT_W

    monkeypatch.setitem(tour.SCREENS, "dark", dark)
    monkeypatch.setitem(fixtures.BUILDERS, "dark", lambda variant: None)
    images = [WideGlyphs(SCREEN_W + 32, SCREEN_H + 32), WideGlyphs(SCREEN_W + 32, SCREEN_H + 32), WideGlyphs(SCREEN_W, SCREEN_H)]
    entry = tour.shoot("dark", "typical", *images, str(tmp_path))
    assert [(problem["index"], problem["problem"]) for problem in entry["command_problems"]] == [(1, "ink_outside")]
    assert entry["command_problems"][0]["text"] == "AB" and entry["command_problems"][0]["bounds"] == [2, 2, 7, 5]
    assert entry["checked"] == 2


def test_tour_shoot_counts_ink_in_the_margin_and_keeps_the_overflow_check(tmp_path, monkeypatch):
    def leaks(canvas, view):
        canvas.rect(-4, 0, 10, 10, 7)  # 画面の左へ4ピクセル出る

    monkeypatch.setitem(tour.SCREENS, "leaks", leaks)
    monkeypatch.setitem(fixtures.BUILDERS, "leaks", lambda variant: None)
    images = [FakeImage(SCREEN_W + 32, SCREEN_H + 32), FakeImage(SCREEN_W + 32, SCREEN_H + 32), FakeImage(SCREEN_W, SCREEN_H)]
    entry = tour.shoot("leaks", "typical", *images, str(tmp_path))
    assert (entry["margin_ink"], entry["screen_ink"]) == (40, 60)
    assert [violation["kind"] for violation in entry["violations"]] == ["off_screen"]
    assert entry["command_problems"] == []  # 命令の矩形どおりに描かれてはいる


# --- 画素の読み方の確かめ ---
def test_tour_reader_check_passes_for_one_byte_per_pixel_in_row_order():
    tour.check_reader(FakeImage(20, 10))


def test_tour_reader_check_fails_for_another_layout():
    class ColumnOrder(FakeImage):
        def data_ptr(self):  # 列ごとに並べ替えて返す
            return bytes(self.data[y * self.width + x] for x in range(self.width) for y in range(self.height))

    class TwoBytes(FakeImage):
        def data_ptr(self):
            return bytes(self.data) * 2

    with pytest.raises(RuntimeError):
        tour.check_reader(ColumnOrder(20, 10))
    with pytest.raises(RuntimeError):
        tour.check_reader(TwoBytes(20, 10))
