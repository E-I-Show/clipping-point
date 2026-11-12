"""3Dの場面（cp_app.render）のテスト。Pyxelは使わない。

Pyxel（のモジュール）は、Scene の引数で受ける。ここでは、偽の Pyxel（3Dの口 cube つき）を渡す。偽のノードは、根の draw で、見えている
ノードを、名で決めた色の矩形で塗るだけ。形が、画面のどこに写るか（左右、欠け、深度）は、ここでは見えない。実物のPyxelで描いて数える
のは、道具 run、tour、web-smoke（判定は tools/scene_reference.py）と、selftest-break の、3Dの絵を壊す件。
ここで見ること：
  座標の変換（z の反転と、頂点の順の入れ替えは、to_cube() の1か所だけ。模型の座標の形は、通さない）
  パレットを当てる所、色見本の絵、背景の絵
  場面のノードの組み方（車輪は、車の根の下。判定用の柱と印は、頼まれたときだけ）
  描く口（背景 → カメラと車 → 見えない塊を隠す → 根の draw を1回）と、描くもの（layers）
  判定用の実描画（4枚の順、数え方、判定の後に、柱と印を隠して、コースと車を戻す。例外でも戻す）
  画素を数える計算
  アプリと巡回の口の配線の、守りのテスト（ソースを読む。pyxel は読み込まない）
"""
import ast
import math
import zlib

import pytest

import input_reference
from conftest import ROOT
from cp_app import render
from cp_core import camera, car_shape, mesh, palette
from cp_ui.canvas import SCREEN_H, SCREEN_W
from test_screens import APP_PY, app_method, is_attribute_of, is_self_attribute, self_attribute_values

APP_DIR = ROOT / "clipping_point" / "cp_app"
RENDER_PY = APP_DIR / "render.py"
TOUR_PY = APP_DIR / "tour.py"
DATA = input_reference.load_data()
CAR_ID, TRACK_ID = input_reference.CAR_ID, input_reference.TRACK_ID
PILLAR_COLS = {name: palette.number(role) for name, role in camera.PILLAR_ROLES.items()}
MARK_COLS = {name: palette.number(role) for name, role in car_shape.MARK_ROLES.items()}
# 偽のノードが、名で塗る矩形 (x, y, w, h, 色)。塊は、どれも同じ所（重なる）。地面は、背景の、地平線より下と同じ色なので、塗らない。
PAINT = {
    "chunk": (0, 130, SCREEN_W, 80, palette.ASPHALT_MID),
    "body": (140, 150, 40, 30, palette.RED),
    "wheel": (150, 185, 4, 4, palette.TIRE),
}
TRACK_PX, CAR_PX = SCREEN_W * 80, 40 * 30 + 4 * 4  # 塊と、車（車体と、同じ所に重なる車輪4つ）の画素の数
PROBE_PX = 5 * 20  # 柱と印の1つの、画素の数
PROBE_X = {"pillar_left": 100, "pillar_right": 200, "mark_right": 210, "mark_nose": 157}  # 偽のノードが、柱と印を塗る x（幅5）


class FakeImage:
    """pyxel.Image の代わり。1画素1バイトの絵。呼ばれた描画関数を、calls に残す。"""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.data = bytearray(width * height)
        self.calls = []

    def cls(self, col) -> None:
        self.calls.append(("cls", col))
        self.data[:] = bytes([col]) * len(self.data)

    def rect(self, x, y, w, h, col) -> None:
        self.calls.append(("rect", x, y, w, h, col))
        left, right = max(x, 0), min(x + w, self.width)
        for row in range(max(y, 0), min(y + h, self.height)):
            if left < right:
                self.data[row * self.width + left:row * self.width + right] = bytes([col]) * (right - left)

    def blt(self, x, y, img, u, v, w, h) -> None:
        self.calls.append(("blt", x, y, img, u, v, w, h))
        for row in range(h):
            target_y = y + row
            if not 0 <= target_y < self.height:
                continue
            for column in range(max(0, -x), min(w, self.width - x)):
                self.data[target_y * self.width + x + column] = img.data[(v + row) * img.width + u + column]

    def pget(self, x, y) -> int:
        return self.data[y * self.width + x]

    def data_ptr(self):
        return self.data


class FakeVec3(tuple):
    def __new__(cls, x=0.0, y=0.0, z=0.0):
        return super().__new__(cls, (x, y, z))


class FakeMat4:
    """行列の代わり。掛けた変換を、順に覚えるだけ。"""

    def __init__(self, steps=()) -> None:
        self.steps = tuple(steps)

    def __eq__(self, other) -> bool:
        return isinstance(other, FakeMat4) and self.steps == other.steps

    @staticmethod
    def from_translation(vec):
        return FakeMat4([("translate", tuple(vec))])

    @staticmethod
    def look_at(eye, target):
        return FakeMat4([("look_at", tuple(eye), tuple(target))])

    def rotate_y(self, deg):
        return FakeMat4([*self.steps, ("rotate_y", deg)])


FakeMat4.IDENTITY = FakeMat4()


class FakePrimitive:
    MODE_TRIANGLES = 2
    CULL_NONE, CULL_BACK, CULL_FRONT = 0, 1, 2

    def __init__(self, mode, positions, indices, normals=(), uvs=(), cull=1) -> None:
        self.mode, self.positions, self.indices, self.uvs, self.cull = mode, list(positions), list(indices), list(uvs), cull
        self.normals_computed = False

    def compute_normals(self) -> None:
        self.normals_computed = True

    def points(self) -> list:
        return [tuple(self.positions[index:index + 3]) for index in range(0, len(self.positions), 3)]

    def triangles(self) -> list:
        return [tuple(self.indices[index:index + 3]) for index in range(0, len(self.indices), 3)]

    def cols(self) -> list:
        """UV が指す、色見本の絵の色の番号。頂点の順に、重ねずに並べる。"""
        found = []
        for index in range(0, len(self.uvs), 2):
            u, v = self.uvs[index], self.uvs[index + 1]
            col = int(u * render.SWATCH_IMAGE_PX) // render.SWATCH_PX + int(v * render.SWATCH_IMAGE_PX) // render.SWATCH_PX * render.SWATCH_COLUMNS
            if col not in found:
                found.append(col)
        return found

    def col(self) -> int:
        """UV が指す、色の番号（1色だけの形）。"""
        (only,) = self.cols()
        return only


class FakeMesh:
    def __init__(self, primitives, transforms, parents, names, col_img) -> None:
        self.primitives, self.transforms, self.parents, self.names, self.col_img = primitives, transforms, parents, names, col_img


class FakeCamera:
    def __init__(self) -> None:
        self.transform, self.fov, self.near, self.far, self.clear_color = FakeMat4.IDENTITY, 60.0, 0.1, 1000.0, 0


class FakeShading:
    LEVEL_COUNT = 8

    def __init__(self, colors) -> None:
        self.colors = list(colors)
        self.rows = {}  # 手で直した (色, 段) → (色, 色)

    def __setitem__(self, key, value) -> None:
        col, level = key
        if not (0 <= col < len(self.colors) and 0 <= level < self.LEVEL_COUNT):
            raise IndexError(key)
        self.rows[key] = value


class FakeNode:
    """ノードの代わり。根の draw で、見えているノード（親が隠れていれば、子も隠れる）を、順に塗る。"""

    def __init__(self) -> None:
        self.children, self.visible, self.transform = [], True, FakeMat4.IDENTITY
        self.camera = self.shading = self.mesh = None
        self.name = ""
        self.draws = []  # 根の draw の呼び出し (x, y, w, h, 描き先, 塗ったノードの名の並び)
        self.states = []  # on_draw の中で呼ばれた描画の状態と、形

    @staticmethod
    def from_mesh(mesh_value):
        node = FakeNode()
        node.mesh, node.name, node.transform = mesh_value, mesh_value.names[0], mesh_value.transforms[0]
        return node

    def add_child(self, node) -> None:
        self.children.append(node)

    def on_draw(self) -> None:
        pass

    def shaded(self, on) -> None:
        self.states.append(("shaded", on))

    def prim(self, mat, primitive, col_img) -> None:
        self.states.append(("prim", mat, primitive, col_img))

    def walk(self):
        """見えているノードを、深さ優先で並べる。"""
        if not self.visible:
            return
        yield self
        for child in self.children:
            yield from child.walk()

    def draw(self, x, y, w, h, target) -> None:
        painted = []
        for node in self.walk():
            if node.name in PAINT:
                target.rect(*PAINT[node.name])
                painted.append(node.name)
            node.states = []
            node.on_draw()
            for state in node.states:
                if state[0] != "prim":
                    continue
                for col in state[2].cols():  # 柱と印。色ごとに、決めた x に、幅5、高さ20の矩形を塗る
                    name = next(name for name, number in {**PILLAR_COLS, **MARK_COLS}.items() if number == col)
                    target.rect(PROBE_X[name], 100, 5, 20, col)
                    painted.append(name)
        self.draws.append((x, y, w, h, target, tuple(painted)))


class FakeCube:
    Vec3, Mat4, Primitive, Mesh, Node, Camera, Shading = FakeVec3, FakeMat4, FakePrimitive, FakeMesh, FakeNode, FakeCamera, FakeShading


class FakePyxel:
    """pyxel のモジュールの代わり。3Dの口（cube）と、画像と、パレットだけを持つ。"""

    cube = FakeCube

    def __init__(self) -> None:
        self.colors = list(range(16))  # 始めたばかりの、16色
        self.images = []

    def Image(self, width, height):  # noqa: N802 - pyxel.Image と同じ名
        image = FakeImage(width, height)
        self.images.append(image)
        return image


def built(probes: bool = False) -> tuple:
    """組んだ場面と、渡した偽の Pyxel。"""
    pyxel = FakePyxel()
    scene = render.Scene(pyxel, DATA, CAR_ID, TRACK_ID)
    scene.build(probes=probes)
    return scene, pyxel


def start_pose(scene) -> tuple:
    """スタート位置の、車の位置と向きと、後方追従のカメラ。"""
    x, z, heading = scene.track.start_pose()
    return x, z, heading, scene.chase(x, z, heading)


# --- 座標の変換 ---
def test_render_to_cube_flips_z_and_swaps_the_order_of_the_vertices():
    points, triangles = render.to_cube(((1.0, 2.0, 3.0), (4.0, 5.0, -6.0), (0.0, 0.0, 0.0)), ((0, 1, 2), (2, 1, 0)))
    assert points == ((1.0, 2.0, -3.0), (4.0, 5.0, 6.0), (0.0, 0.0, 0.0))
    assert triangles == ((0, 2, 1), (2, 0, 1))
    # 点だけでも通せる（車の位置、カメラの目と注視点）。
    assert render.to_cube(((10.0, 0.0, 78.0),)) == (((10.0, 0.0, -78.0),), ())


def test_render_to_cube_keeps_the_face_pointing_outwards():
    # 上を向く三角形（ロジックの座標で、(b−a)×(c−a) が +y）は、z を反転して、頂点の順を入れ替えると、Pyxelの3Dの座標でも、上を向く。
    vertices, triangles = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)), ((0, 1, 2),)
    assert mesh.face_normal(vertices, triangles[0])[1] > 0
    flipped, swapped = render.to_cube(vertices, triangles)
    assert mesh.face_normal(flipped, swapped[0])[1] > 0
    # 反転だけ、入れ替えだけでは、裏返る（裏の面を捨てる設定で、描かれなくなる）。
    assert mesh.face_normal(flipped, triangles[0])[1] < 0 and mesh.face_normal(vertices, swapped[0])[1] < 0


def unary_minus_on_z(tree) -> list:
    """ソースの中の、z の符号を反転している所（−z、−何か.z、−何か_z）の行番号。"""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = node.operand
            name = operand.id if isinstance(operand, ast.Name) else operand.attr if isinstance(operand, ast.Attribute) else ""
            if name == "z" or name.endswith("_z"):
                lines.append(node.lineno)
    return lines


def test_render_z_is_flipped_in_one_function_only():
    # 守りのテスト。z の反転を書くのは、cp_app/render.py の to_cube() の1か所だけ。ほかに書くと、打ち消し合って、鏡写しの絵が通る。
    tree = ast.parse(RENDER_PY.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    inside = unary_minus_on_z(functions["to_cube"])
    assert len(inside) == 1 and unary_minus_on_z(tree) == inside
    # Pyxelに触れる層（cp_app）の、ほかのモジュールと、2Dの画面の層（cp_ui）には、無い。3Dの口（cube）に触れるのも、render.py だけ。
    others = sorted(path for directory in (APP_DIR, ROOT / "clipping_point" / "cp_ui") for path in directory.glob("*.py") if path != RENDER_PY)
    assert len(others) >= 10
    for path in others:
        source = path.read_text(encoding="utf-8")
        other = ast.parse(source)
        assert unary_minus_on_z(other) == [], path.name
        touches_cube = [node for node in ast.walk(other) if isinstance(node, ast.Attribute) and node.attr in ("cube", "Vec3", "Mat4")]
        assert touches_cube == [], path.name


def test_render_module_does_not_import_pyxel():
    # pyxel は、頭で読み込まない（引数で受ける）。テストのプロセスに pyxel が入ると、道具 test が、全体を落とす。
    tree = ast.parse(RENDER_PY.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"zlib", "math", "cp_core", "cp_ui"}


# --- 形を、Pyxelの3Dの物にする ---
def test_render_logic_parts_go_through_the_flip_and_model_parts_do_not():
    part = mesh.MeshPart("probe", "yellow", ((0.0, 0.0, 1.0), (1.0, 0.0, 2.0), (0.0, 1.0, 3.0)), ((0, 1, 2),))
    logic = render.logic_primitive(FakeCube, [part])
    assert logic.points() == [(0.0, 0.0, -1.0), (1.0, 0.0, -2.0), (0.0, 1.0, -3.0)] and logic.triangles() == [(0, 2, 1)]
    model = render.model_primitive(FakeCube, [part])
    assert model.points() == [(0.0, 0.0, 1.0), (1.0, 0.0, 2.0), (0.0, 1.0, 3.0)] and model.triangles() == [(0, 1, 2)]
    for primitive in (logic, model):
        # 裏の面は、捨てる。法線は、作っておく。UV は、頂点ごとに、その部品の色の矩形の中心。
        assert primitive.mode == FakePrimitive.MODE_TRIANGLES and primitive.cull == FakePrimitive.CULL_BACK and primitive.normals_computed
        assert primitive.uvs == list(render.swatch_uv(palette.YELLOW)) * 3 and primitive.col() == palette.YELLOW


def test_render_parts_are_merged_into_one_primitive_with_shifted_indices():
    first = mesh.MeshPart("a", "red", ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), ((0, 1, 2),))
    second = mesh.MeshPart("b", "blue", ((0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0), (1.0, 1.0, 5.0)), ((0, 1, 2), (1, 3, 2)))
    primitive = render.model_primitive(FakeCube, [first, second])
    assert len(primitive.points()) == 7 and primitive.triangles() == [(0, 1, 2), (3, 4, 5), (4, 6, 5)]
    assert primitive.uvs[:2] == list(render.swatch_uv(palette.RED)) and primitive.uvs[6:8] == list(render.swatch_uv(palette.BLUE))
    assert len(primitive.uvs) == 2 * 7


def test_render_unknown_color_role_is_an_error():
    with pytest.raises(KeyError):
        render.model_primitive(FakeCube, [mesh.MeshPart("a", "no_such_role", ((0.0, 0.0, 0.0),), ())])


# --- 色見本の絵 ---
def test_render_swatches_hold_every_color_and_the_uv_points_into_its_rectangle():
    pyxel = FakePyxel()
    image = render.make_swatches(pyxel)
    assert (image.width, image.height) == (256, 256) == (render.SWATCH_IMAGE_PX, render.SWATCH_IMAGE_PX)
    for col in range(palette.COLOR_COUNT):
        u, v = render.swatch_uv(col)
        assert 0.0 < u < 1.0 and 0.0 < v < 1.0  # UV は、0〜1に切り詰められる（繰り返せない）
        x, y = int(u * image.width), int(v * image.height)
        # 矩形の中心を指す。隣の色まで、8画素より多く離れている（最近傍の読みで、隣の色を拾わない）。
        assert {image.pget(x + dx, y + dy) for dx in (-8, 0, 8) for dy in (-8, 0, 8)} == {col}
    assert len({render.swatch_uv(col) for col in range(palette.COLOR_COUNT)}) == palette.COLOR_COUNT


# --- パレット ---
def test_render_apply_palette_replaces_the_colors_rebuilds_the_shading_and_keeps_the_lamps_bright():
    pyxel = FakePyxel()
    colors = palette.palette_from_entry(DATA.entry("palettes", palette.EVENING))
    shading = render.apply_palette(pyxel, colors)
    assert pyxel.colors == list(colors.colors) and len(pyxel.colors) == 32
    assert shading.colors == list(colors.colors)  # 陰影の表は、差し替えた後のパレットから作る
    # 陰影で暗くしない色（灯火）は、全部の段で、元の色。ほかの行には、触れない。
    assert set(shading.rows) == {(col, level) for col in colors.unshaded for level in range(FakeShading.LEVEL_COUNT)}
    assert all(shading.rows[(col, level)] == (col, col) for col, level in shading.rows)
    assert colors.unshaded == (palette.CREAM, palette.BRAKE_LAMP)


# --- 背景 ---
def test_render_backdrop_holds_the_sky_bands_from_the_top_and_two_ridges_at_the_horizon():
    pyxel = FakePyxel()
    period = camera.backdrop_period_px(58.0, SCREEN_H)
    image = render.make_backdrop(pyxel, period)
    assert (image.width, image.height) == (period, render.BACKDROP_ROWS) == (1360, 96)
    for x in (0, period // 3, period - 1):
        column = [image.pget(x, y) for y in range(image.height)]
        sky = [col for col in column if col in palette.SKY]
        # 空は、上（天頂の側）から下へ、役割の順。山並みは、空の下。遠い尾根（明るい方）が、近い尾根より上まである。
        assert sky == sorted(sky, key=palette.SKY.index) and column[0] == palette.SKY[0]
        assert column[-1] == palette.MOUNTAIN_DARK and set(column) <= {*palette.SKY, *palette.MOUNTAINS}
        assert column.index(palette.MOUNTAIN_LIGHT) < column.index(palette.MOUNTAIN_DARK)
        assert set(column[column.index(palette.MOUNTAIN_LIGHT):]) <= set(palette.MOUNTAINS)
    assert {image.pget(x, 0) for x in range(period)} == {palette.SKY[0]}  # いちばん上の行は、空だけ（この上を、同じ色で埋める）


def test_render_ridges_close_up_after_one_turn_and_stay_below_the_picture():
    for ridge in render.BACKDROP_RIDGES:
        heights = render.ridge_heights(1360, ridge)
        assert len(heights) == 1360 and 1 <= min(heights) and max(heights) < render.BACKDROP_ROWS
        assert abs(heights[0] - heights[-1]) <= 1  # 継ぎ目が、つながる（1周で、元の高さへ戻る）
        assert max(heights) - min(heights) >= 5  # 平らでない
    far, near = (render.ridge_heights(1360, ridge) for ridge in render.BACKDROP_RIDGES)
    assert all(a > b for a, b in zip(far, near))  # 遠い尾根は、いつも、近い尾根より高い（隠れない）


# --- 地面 ---
def test_render_ground_is_one_part_that_faces_up_below_the_road_and_reaches_past_the_far_plane():
    track = input_reference.make_sim().track
    chunks = track.mesh_chunks()
    ground = render.ground_part(chunks, 300.0)
    assert ground.name == render.GROUND_NAME and ground.role == palette.ROLES[palette.FAR_GROUND]
    assert {vertex[1] for vertex in ground.vertices} == {-render.GROUND_DROP_M} and 0.0 < render.GROUND_DROP_M <= 0.2
    assert all(mesh.face_normal(ground.vertices, triangle)[1] > 0 for triangle in ground.triangles)  # ロジックの座標で、上を向く
    xs, zs = [vertex[0] for vertex in ground.vertices], [vertex[2] for vertex in ground.vertices]
    for chunk in chunks:  # どの塊からも、奥の切り取り面より先まで、地面がある
        assert min(xs) <= chunk.center[0] - chunk.radius - 300.0 and max(xs) >= chunk.center[0] + chunk.radius + 300.0
        assert min(zs) <= chunk.center[1] - chunk.radius - 300.0 and max(zs) >= chunk.center[1] + chunk.radius + 300.0
    # 四角は、決めた大きさより、大きくない。三角形は、四角の2倍。
    columns = len({round(x, 6) for x in xs}) - 1
    rows = len({round(z, 6) for z in zs}) - 1
    assert (max(xs) - min(xs)) / columns <= render.GROUND_TILE_M and (max(zs) - min(zs)) / rows <= render.GROUND_TILE_M
    assert ground.triangle_count == 2 * columns * rows


# --- 場面を組む ---
def test_render_scene_builds_nothing_until_build_is_called():
    pyxel = FakePyxel()
    scene = render.Scene(pyxel, DATA, CAR_ID, TRACK_ID)
    assert scene.built is False and scene.probes is False and pyxel.images == [] and pyxel.colors == list(range(16))
    scene.build()
    assert scene.built is True
    with pytest.raises(RuntimeError):
        scene.build()


def test_render_scene_has_the_ground_the_chunks_and_the_car_under_one_root():
    scene, pyxel = built()
    assert pyxel.colors == list(scene.palette.colors)  # パレットは、組むときに当たる
    root = scene.root
    # 根が、陰影の表と、カメラを持つ。カメラは、描き先を消さない（先に写した背景が、残る）。
    assert root.shading is scene.shading and root.camera is scene.camera and scene.camera.clear_color is None
    chunks = scene.track.mesh_chunks()
    assert [node.name for node in root.children] == ["ground"] + ["chunk"] * len(chunks) + [""]
    assert root.children[0] is scene.ground and root.children[-1] is scene.car_root
    assert [node for _, node in scene.chunks] == root.children[1:-1] and [chunk for chunk, _ in scene.chunks] == list(chunks)
    # 車の根の下に、車体（と屋根）と、車輪4つ。車輪は、車体の子にしない。1つの形を、4輪で共有する。
    assert [node.name for node in scene.car_root.children] == ["body", "wheel", "wheel", "wheel", "wheel"] and scene.car_nodes == scene.car_root.children
    body, *wheels = scene.car_root.children
    assert body.children == [] and len({id(wheel.mesh.primitives[0]) for wheel in wheels}) == 1
    shape = car_shape.build_car_shape(DATA.entry("cars", CAR_ID))
    assert [wheel.transform for wheel in wheels] == [FakeMat4.from_translation(center) for center in shape.wheel_centers]
    # どのノードも、同じ色見本の絵を使う。
    assert {id(node.mesh.col_img) for node in [scene.ground, *root.children[1:-1], *scene.car_root.children]} == {id(scene.swatches)}
    assert scene.stats == {"chunks": 12, "track_triangles": 3660, "ground_triangles": scene.stats["ground_triangles"], "car_triangles": 72}


def test_render_course_and_ground_are_flipped_and_the_car_model_is_not():
    scene, _ = built()
    chunk, node = scene.chunks[0]
    primitive = node.mesh.primitives[0]
    part = chunk.parts[0]
    count = len(part.vertices)
    assert primitive.points()[:count] == [(x, y, -z) for x, y, z in part.vertices]  # ロジックの座標の形は、z を反転
    assert primitive.triangles()[:len(part.triangles)] == [(a, c, b) for a, b, c in part.triangles]  # 頂点の順も、入れ替える
    assert any(z != 0.0 for _, _, z in part.vertices)
    assert sum(len(primitive.triangles()) for _, node in scene.chunks for primitive in node.mesh.primitives) == 3660
    ground = scene.ground.mesh.primitives[0]
    assert all(mesh.face_normal(ground.points(), triangle)[1] > 0 for triangle in ground.triangles())  # 反転の後も、上を向く
    # 模型の座標の形（車体と屋根）は、そのまま。
    shape = car_shape.build_car_shape(DATA.entry("cars", CAR_ID))
    body = scene.car_root.children[0].mesh.primitives[0]
    assert body.points() == [vertex for part in shape.body for vertex in part.vertices]
    assert body.triangles()[:12] == list(shape.body[0].triangles)


def test_render_plain_start_builds_no_probes_and_no_extra_picture():
    # ふつうの起動（検証の口が無い）。柱も、印も、判定用の絵も、作らない。
    scene, pyxel = built(probes=False)
    assert scene.probes is False and not hasattr(scene, "marks") and not hasattr(scene, "pillars") and not hasattr(scene, "scratch")
    assert pyxel.images == [scene.swatches, scene.backdrop]
    assert len(scene.car_root.children) == 5 and len(scene.root.children) == 1 + 12 + 1
    x, z, heading, pose = start_pose(scene)
    with pytest.raises(RuntimeError):
        scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading, (render.PROBES,))
    with pytest.raises(RuntimeError):
        scene.judge(bytes(SCREEN_W * SCREEN_H), (), x, z, heading)


def test_render_probes_are_built_hidden_when_asked_for():
    scene, pyxel = built(probes=True)
    assert scene.probes is True and pyxel.images == [scene.swatches, scene.backdrop, scene.scratch]
    assert (scene.scratch.width, scene.scratch.height) == (SCREEN_W, SCREEN_H)
    # 印は、車の根の下（模型の座標）。柱は、根の下（ロジックの座標）。どちらも、隠してある。
    assert scene.car_root.children[-1] is scene.marks and scene.root.children[-1] is scene.pillars
    assert scene.marks.visible is False and scene.pillars.visible is False
    marks = scene.marks.primitives[0]
    assert marks.points() == [vertex for part in car_shape.mark_parts() for vertex in part.vertices]  # そのまま（反転しない）
    assert marks.triangles() == [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]


# --- 描く口 ---
def test_render_draw_blits_the_backdrop_then_calls_the_root_draw_once():
    scene, _ = built()
    x, z, heading, pose = start_pose(scene)
    target = FakeImage(SCREEN_W, SCREEN_H)
    scene.draw(target, pose, x, z, heading)
    # 背景：遠い地面の色で消し、背景の絵より上を、空のいちばん上の色で埋め、絵を、横に2枚並べて写す。
    horizon = camera.horizon_row(pose, SCREEN_H)
    top = horizon - render.BACKDROP_ROWS
    shift = camera.backdrop_shift_px(pose.heading, scene.backdrop_period)
    assert (horizon, top) == (99, 3)
    assert target.calls[:4] == [
        ("cls", palette.FAR_GROUND), ("rect", 0, 0, SCREEN_W, top, palette.SKY[0]),
        ("blt", shift - scene.backdrop_period, top, scene.backdrop, 0, 0, scene.backdrop_period, render.BACKDROP_ROWS),
        ("blt", shift, top, scene.backdrop, 0, 0, scene.backdrop_period, render.BACKDROP_ROWS),
    ]
    # 3Dは、根の draw を1回（深度の記録は、呼び出しごとに消える）。画面の全体へ、同じ描き先へ。
    assert len(scene.root.draws) == 1
    assert scene.root.draws[0][:5] == (0, 0, SCREEN_W, SCREEN_H, target)
    assert all(node.draws == [] for node in [scene.ground, scene.car_root, *scene.car_root.children, *[node for _, node in scene.chunks]])
    # 空は、地平線より上。地面は、下。
    assert target.pget(0, 0) == palette.SKY[0] and target.pget(0, horizon - 1) in (*palette.SKY, *palette.MOUNTAINS)
    assert target.pget(0, horizon) == palette.FAR_GROUND and target.pget(0, 100) == palette.FAR_GROUND


@pytest.mark.parametrize("x, z, heading", [(60.0, 0.0, 0.0), (245.0, 78.0, 2.37), (-57.2, 80.1, -2.578)])
def test_render_draw_places_the_camera_and_the_car_through_the_flip(x, z, heading):
    scene, _ = built()
    pose = scene.chase(x, z, heading)
    scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
    # カメラの目と注視点は、z を反転して渡す。画角、手前、奥は、カメラの値のまま。
    (ex, ey, ez), (tx, ty, tz) = pose.eye, pose.target
    assert scene.camera.transform == FakeMat4.look_at((ex, ey, -ez), (tx, ty, -tz))
    assert (scene.camera.fov, scene.camera.near, scene.camera.far) == (58.0, 0.3, 300.0)
    # 車の姿勢は、位置（z を反転）へ移してから、向き（度。符号は、そのまま）だけ、Y軸で回す。
    assert scene.car_root.transform == FakeMat4.from_translation((x, 0.0, -z)).rotate_y(math.degrees(heading))
    # 車体と車輪の変換は、動かさない（車の根の変換の下にある）。
    assert scene.car_root.children[0].transform == FakeMat4.IDENTITY


def test_render_draw_hides_the_chunks_the_camera_cannot_see():
    scene, _ = built()
    for x, z, heading in ((60.0, 0.0, 0.0), (245.0, 78.0, 2.37), (66.4, 91.2, math.pi)):
        pose = scene.chase(x, z, heading)
        scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
        want = [camera.chunk_visible(pose, chunk.center[0], chunk.center[1], chunk.radius) for chunk, _ in scene.chunks]
        assert [node.visible for _, node in scene.chunks] == want
        assert 0 < sum(want) and scene.stats["chunks_drawn"] == sum(want)
        drawn = sum(chunk.triangle_count for (chunk, _), seen in zip(scene.chunks, want) if seen)
        assert scene.stats["triangles_drawn"] == drawn + scene.stats["ground_triangles"] + scene.stats["car_triangles"]
    # スタート位置では、後ろの塊が、隠れる。
    x, z, heading, pose = start_pose(scene)
    scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
    assert 0 < scene.stats["chunks_drawn"] < len(scene.chunks)


def painted(scene) -> set:
    """直近の根の draw で、塗られたノードの名。"""
    return set(scene.root.draws[-1][5])


def test_render_draw_shows_only_the_layers_it_is_given():
    scene, _ = built(probes=True)
    x, z, heading, pose = start_pose(scene)
    target = FakeImage(SCREEN_W, SCREEN_H)
    assert render.LAYERS == ("backdrop", "ground", "track", "car", "probes") and render.NORMAL == ("backdrop", "ground", "track", "car")
    scene.draw(target, pose, x, z, heading)  # 既定は、ふだんの実描画（柱と印は、描かない）
    assert painted(scene) == {"chunk", "body", "wheel"} and scene.ground.visible is True
    scene.draw(target, pose, x, z, heading, (render.BACKDROP, render.GROUND))
    assert painted(scene) == set() and scene.ground.visible is True and not any(node.visible for _, node in scene.chunks)
    scene.draw(target, pose, x, z, heading, (render.BACKDROP, render.GROUND, render.TRACK))
    assert painted(scene) == {"chunk"} and not any(node.visible for node in scene.car_nodes)
    scene.draw(target, pose, x, z, heading, (render.PROBES,))
    assert painted(scene) == {"pillar_left", "pillar_right", "mark_right", "mark_nose"} and scene.ground.visible is False
    # 車を隠しても、車の根は、見えたまま（印は、車の根の変換の下に置く）。
    assert scene.car_root.visible is True and scene.marks.visible is True and scene.pillars.visible is True
    with pytest.raises(ValueError):
        scene.draw(target, pose, x, z, heading, ("backdrop", "sky"))


def test_render_draw_without_the_backdrop_clears_the_target_instead():
    scene, _ = built(probes=True)
    x, z, heading, pose = start_pose(scene)
    target = FakeImage(SCREEN_W, SCREEN_H)
    scene.draw(target, pose, x, z, heading, (render.PROBES,))
    assert target.calls[0] == ("cls", render.CLEAR_COL) and not [call for call in target.calls if call[0] == "blt"]
    # 消す色は、柱と印の色とも、空の色とも、違う。
    assert render.CLEAR_COL not in {*PILLAR_COLS.values(), *MARK_COLS.values(), *palette.SKY}


def test_render_probes_are_drawn_unshaded_and_the_pillars_follow_the_car():
    scene, _ = built(probes=True)
    target = FakeImage(SCREEN_W, SCREEN_H)
    seen = []
    for x, z, heading in ((60.0, 0.0, 0.0), (245.0, 78.0, 2.37)):
        scene.draw(target, scene.chase(x, z, heading), x, z, heading, (render.PROBES,))
        for node in (scene.marks, scene.pillars):
            # 陰影を切ってから、形を描く。変換は、掛けない（親のノードの変換の下）。色見本の絵は、場面と同じ。
            assert node.states[0] == ("shaded", False) and [state[0] for state in node.states[1:]] == ["prim"]
            assert node.states[1][1] == FakeMat4.IDENTITY and node.states[1][3] is scene.swatches
        pillars = scene.pillars.primitives[0]
        want = [vertex for part in camera.pillar_parts(x, z, heading) for vertex in part.vertices]
        assert pillars.points() == [(px, py, -pz) for px, py, pz in want]  # 柱は、ロジックの座標（z を反転）
        assert pillars.triangles() == [(0, 2, 1), (0, 3, 2), (4, 6, 5), (4, 7, 6)]
        seen.append(pillars.points())
    assert seen[0] != seen[1]  # 車の位置と向きから、描くたびに作り直す
    assert len(scene.marks.primitives) == 1  # 印は、作り直さない（模型の座標。車の根に付いていく）


# --- 判定用の実描画 ---
def judged(scene, shown=None, rects=()) -> dict:
    x, z, heading, pose = start_pose(scene)
    if shown is None:
        picture = FakeImage(SCREEN_W, SCREEN_H)
        scene.draw(picture, pose, x, z, heading)
        shown = bytes(picture.data)
    return scene.judge(shown, rects, x, z, heading)


def test_render_judge_draws_four_pictures_on_the_scratch_picture_in_the_fixed_order():
    scene, _ = built(probes=True)
    result = judged(scene)
    draws = scene.root.draws[1:]  # 頭の1回は、ふだんの実描画の絵
    assert len(draws) == 4 and all(draw[4] is scene.scratch for draw in draws)
    assert [set(draw[5]) for draw in draws] == [
        set(), {"chunk"}, {"chunk", "body", "wheel"}, {"pillar_left", "pillar_right", "mark_right", "mark_nose"},
    ]
    assert list(result) == ["sky", "track", "car", "ink_inside", "ink_outside", "probes", "palette", "digest"]


def test_render_judge_counts_the_sky_the_course_the_car_and_the_probes():
    scene, pyxel = built(probes=True)
    result = judged(scene)
    # 空は、1枚目（背景と地面）の、空の役割の色の画素。背景の絵は、地平線（99行目）より上。山並みの分だけ、少ない。
    assert 0 < result["sky"] < SCREEN_W * 99 and result["sky"] > SCREEN_W * 40
    assert (result["track"], result["car"]) == (TRACK_PX, CAR_PX)
    # 同じ絵を渡したので、違う画素は、無い。
    assert (result["ink_inside"], result["ink_outside"]) == (0, 0)
    # 柱と印は、色ごとに数える。重心の x は、0.1画素の単位（幅5の矩形の中心は、左の端＋2）。
    assert result["probes"] == {name: {"pixels": PROBE_PX, "x10": (PROBE_X[name] + 2) * 10} for name in ("pillar_left", "pillar_right", "mark_right", "mark_nose")}
    assert result["palette"] == list(scene.palette.colors) == pyxel.colors and all(type(color) is int for color in result["palette"])
    # 3枚目（背景、地面、コース、車）の画素の要約値。渡した絵と、同じ絵。
    picture = FakeImage(SCREEN_W, SCREEN_H)
    x, z, heading, pose = start_pose(scene)
    scene.draw(picture, pose, x, z, heading)
    assert result["digest"] == zlib.crc32(bytes(picture.data)) and type(result["digest"]) is int


def test_render_judge_splits_the_difference_from_the_shown_picture_by_the_rectangles_of_the_2d_commands():
    scene, _ = built(probes=True)
    x, z, heading, pose = start_pose(scene)
    picture = FakeImage(SCREEN_W, SCREEN_H)
    scene.draw(picture, pose, x, z, heading)
    picture.rect(2, 190, 316, 19, palette.BLACK)  # 2Dの描画命令（下地の矩形）
    picture.rect(0, 0, SCREEN_W, 12, palette.NAVY)
    rects = [(2, 190, 316, 19), (0, 0, SCREEN_W, 12)]
    result = scene.judge(bytes(picture.data), rects, x, z, heading)
    assert (result["ink_inside"], result["ink_outside"]) == (316 * 19 + SCREEN_W * 12, 0)
    # 3Dを描かない絵（黒1色に、2Dだけ）を渡すと、矩形の外も、違う。
    blank = FakeImage(SCREEN_W, SCREEN_H)
    blank.rect(2, 190, 316, 19, palette.BLACK)
    result = scene.judge(bytes(blank.data), [(2, 190, 316, 19)], x, z, heading)
    assert result["ink_outside"] > 50_000 and result["ink_inside"] == 316 * 19
    # 車を描かない絵を渡すと、車の画素の分だけ、矩形の外が違う。
    no_car = FakeImage(SCREEN_W, SCREEN_H)
    scene.draw(no_car, pose, x, z, heading, (render.BACKDROP, render.GROUND, render.TRACK))
    assert scene.judge(bytes(no_car.data), (), x, z, heading)["ink_outside"] == CAR_PX


def visible_state(scene) -> tuple:
    return (
        scene.marks.visible, scene.pillars.visible, scene.ground.visible, [node.visible for node in scene.car_nodes],
        [node.visible for _, node in scene.chunks],
    )


def test_render_judge_hides_the_probes_and_shows_the_course_and_the_car_again():
    scene, _ = built(probes=True)
    x, z, heading, pose = start_pose(scene)
    scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
    before = visible_state(scene)
    assert before[:2] == (False, False) and before[2] is True and all(before[3]) and any(before[4])
    judged(scene)
    # 4枚目は、柱と印だけを描く。その後に、戻してある（ブラウザ版は、結果を出した後も動き続ける）。
    assert visible_state(scene) == before
    # 判定の後の、ふだんの実描画に、柱も印も写らない。
    scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
    assert painted(scene) == {"chunk", "body", "wheel"}


@pytest.mark.parametrize("fails_at", [1, 2, 3, 4])
def test_render_judge_restores_the_scene_even_when_a_picture_fails(fails_at):
    scene, _ = built(probes=True)
    x, z, heading, pose = start_pose(scene)
    scene.draw(FakeImage(SCREEN_W, SCREEN_H), pose, x, z, heading)
    before = visible_state(scene)
    real_draw, calls = scene.root.draw, []

    def failing_draw(*args):
        calls.append(args)
        real_draw(*args)
        if len(calls) == fails_at:
            raise RuntimeError("planted")

    scene.root.draw = failing_draw
    with pytest.raises(RuntimeError):
        scene.judge(bytes(SCREEN_W * SCREEN_H), (), x, z, heading)
    assert len(calls) == fails_at
    assert visible_state(scene) == before  # 途中で例外が出ても、柱と印は隠れ、コースと車は、見える


# --- 画素を数える計算 ---
def picture(width: int, height: int, *ink, back: int = 0) -> bytes:
    data = bytearray([back]) * (width * height)
    for x, y, col in ink:
        data[y * width + x] = col
    return bytes(data)


def test_render_count_diff_counts_the_pixels_whose_color_differs():
    first = picture(8, 4, (1, 1, 5), (2, 1, 5), (7, 3, 9))
    assert render.count_diff(first, first) == 0
    assert render.count_diff(first, picture(8, 4)) == 3
    assert render.count_diff(first, picture(8, 4, (1, 1, 5), (2, 1, 6), (0, 0, 1))) == 3  # 色が違う1つ、片方にだけある2つ
    assert render.count_diff(bytes(SCREEN_W * SCREEN_H), bytes([31]) * (SCREEN_W * SCREEN_H)) == SCREEN_W * SCREEN_H
    with pytest.raises(ValueError):
        render.count_diff(first, first[:-1])


def test_render_split_diff_counts_inside_and_outside_the_rectangles():
    first = picture(8, 4)
    second = picture(8, 4, (1, 1, 5), (2, 1, 5), (7, 3, 9), (0, 0, 2))
    assert render.split_diff(first, second, 8, ()) == (0, 4)
    assert render.split_diff(first, second, 8, [(1, 1, 2, 1)]) == (2, 2)
    assert render.split_diff(first, second, 8, [(0, 0, 8, 4)]) == (4, 0)
    # 重なった矩形でも、画素は1度だけ数える。絵の外へ出た矩形は、切り詰める。幅か高さが無い矩形は、何も囲まない。
    assert render.split_diff(first, second, 8, [(1, 1, 2, 1), (0, 0, 3, 2), (2, 1, 1, 1)]) == (3, 1)
    assert render.split_diff(first, second, 8, [(-5, -5, 6, 6), (6, 2, 50, 50)]) == (2, 2)
    assert render.split_diff(first, second, 8, [(1, 1, 0, 1), (1, 1, 2, 0), (20, 20, 2, 2)]) == (0, 4)
    assert render.split_diff(first, first, 8, [(0, 0, 8, 4)]) == (0, 0)
    for width in (0, 5):
        with pytest.raises(ValueError):
            render.split_diff(first, second, width, ())


def test_render_color_centroid_gives_the_count_and_the_mean_x_in_tenths_of_a_pixel():
    pixels = picture(8, 4, (1, 0, 5), (2, 0, 5), (6, 3, 5), (0, 2, 9))
    assert render.color_centroid(pixels, 8, 5) == (3, 30)  # (1 + 2 + 6) ÷ 3 = 3.0
    assert render.color_centroid(pixels, 8, 9) == (1, 0)
    assert render.color_centroid(pixels, 8, 7) == (0, 0)  # 1つも無ければ、(0, 0)
    assert render.color_centroid(picture(8, 2, (0, 0, 3), (1, 1, 3), (1, 0, 3)), 8, 3) == (3, 7)  # 2 ÷ 3 = 0.67 → 0.7
    assert render.color_centroid(picture(8, 1, (0, 0, 3), (1, 0, 3)), 8, 3) == (2, 5)  # 0.5
    assert render.color_centroid(bytes([4]) * (SCREEN_W * SCREEN_H), SCREEN_W, 4) == (SCREEN_W * SCREEN_H, (SCREEN_W - 1) * 5)  # 全面なら、画面の中央
    assert all(type(value) is int for value in render.color_centroid(pixels, 8, 5))


def test_render_read_pixels_reads_one_byte_per_pixel_and_rejects_another_length():
    image = FakeImage(6, 4)
    image.rect(1, 1, 2, 2, 7)
    pixels = render.read_pixels(image)
    assert type(pixels) is bytes and len(pixels) == 24 and pixels[7] == 7 and pixels[0] == 0

    class TwoBytes(FakeImage):
        def data_ptr(self):
            return bytes(self.data) * 2

    with pytest.raises(RuntimeError):
        render.read_pixels(TwoBytes(6, 4))


# --- アプリと巡回の口の配線（守りのテスト。ソースを読む） ---
def calls_to(function, owner: str, name: str) -> list:
    """function の中の、self.<owner>.<name>(...) の呼び出しの一覧。"""
    return [
        call for call in ast.walk(function)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == name and is_self_attribute(call.func.value, owner)
    ]


def method_calls_in_app(name: str) -> list:
    """app.py の全体から、何か.<name>(...) の呼び出しを探す。返すのは [(呼んでいる関数の名, 呼び出し)]。"""
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    return [
        (function.name, call) for function in functions for call in ast.walk(function)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == name
    ]


def test_render_app_draws_the_3d_scene_under_the_2d_commands_through_the_one_draw_function():
    # 守りのテスト。実描画の順は、背景 → 3D（描く口を1回）→ 2Dの描画命令。車の位置と向きは、進めている世界から。
    render_method = app_method("render")
    draws = calls_to(render_method, "scene", "draw")
    assert len(draws) == 1 and is_self_attribute(draws[0].args[0], "back") and not draws[0].keywords
    assert len(draws[0].args) == 5  # 描くもの（layers）は、渡さない（既定＝ふだんの実描画）
    executes = [call for call in ast.walk(render_method) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "execute"]
    assert len(executes) == 1 and is_self_attribute(executes[0].args[1], "back")
    assert draws[0].lineno < executes[0].lineno
    # カメラは、同じ車の位置と向きの、後方追従。
    chases = calls_to(render_method, "scene", "chase")
    assert len(chases) == 1 and draws[0].args[1] is chases[0]
    cars = [
        node for node in ast.walk(render_method)
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "car"
    ]
    assert len(cars) == 1 and isinstance(cars[0].value, ast.Attribute) and cars[0].value.attr == "car" and is_self_attribute(cars[0].value.value, "sim")
    for call in (draws[0], chases[0]):
        assert [(arg.value.id, arg.attr) for arg in call.args[-3:]] == [("car", "x"), ("car", "z"), ("car", "heading")]
    # render() の中で、裏画面を消さない（背景が、全面を埋める）。画面へ写すのは、draw() の1か所。
    assert not [node for node in ast.walk(render_method) if isinstance(node, ast.Attribute) and node.attr in ("cls", "blt")]
    blits = [(name, call) for name, call in method_calls_in_app("blt")]
    assert [name for name, _ in blits] == ["draw"] and is_attribute_of(blits[0][1].func, "pyxel", "blt")


def test_render_app_builds_the_probes_and_judges_only_behind_a_verification_switch():
    # 守りのテスト。ふつうの起動の道で、判定用の柱と印を作らない。判定用の実描画も、呼ばない。
    init = app_method("__init__")
    # (1) 検証の口があるか、は、画面なしで回す口か、外から渡す値があること。1度だけ決める。
    checked = self_attribute_values(init, "checked")
    assert len(checked) == 1 and isinstance(checked[0], ast.BoolOp) and isinstance(checked[0].op, ast.Or)
    assert [ast.unparse(value) for value in checked[0].values] == ["run_config is not None", "probe is not None"]
    # (2) 場面は、Pyxelを始めた後に、1度だけ組む。柱と印を作るかは、検証の口があるか、で決める（True を、直に渡さない）。
    builds = calls_to(init, "scene", "build")
    assert len(builds) == 1 and not builds[0].args
    keywords = {keyword.arg: keyword.value for keyword in builds[0].keywords}
    assert set(keywords) == {"probes", "clock"} and is_self_attribute(keywords["probes"], "checked")
    starts = [call for call in ast.walk(init) if isinstance(call, ast.Call) and is_attribute_of(call.func, "pyxel", "init")]
    assert len(starts) == 1 and starts[0].lineno < builds[0].lineno
    # (3) 判定用の実描画（Scene.judge）を呼ぶのは、scene_report() だけ。先に、裏画面を、いまの世界で描き直す（ふだんの実描画と同じ道）。
    judges = method_calls_in_app("judge")
    assert [name for name, _ in judges] == ["scene_report"]
    report = app_method("scene_report")
    renders = [call for call in ast.walk(report) if isinstance(call, ast.Call) and is_self_attribute(call.func, "render")]
    assert len(renders) == 1 and renders[0].lineno < judges[0][1].lineno
    # (4) scene_report() を呼ぶのは、結果の2つの口（画面なしで回す口と、外から渡す値）だけ。どちらも、検証の口があるときにだけ通る。
    assert sorted(name for name, _ in method_calls_in_app("scene_report")) == ["finish_probe", "finish_run"]
    update = app_method("update")
    for name, switch in (("finish_run", "config"), ("finish_probe", "probe")):
        guards = [
            node for node in ast.walk(update) if isinstance(node, ast.If)
            and any(isinstance(call, ast.Call) and is_self_attribute(call.func, name) for call in ast.walk(node))
        ]
        assert len(guards) == 1 and f"{switch} is not None" in ast.unparse(guards[0].test), name


def test_render_main_makes_one_scene_and_gives_it_to_the_app_and_to_the_tour():
    # 守りのテスト。場面は、main() が1つだけ作って、アプリと、巡回の口へ渡す。車とコースの id は、世界と同じ定数。
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    made = [node for node in ast.walk(main) if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and is_attribute_of(node.value.func, "render", "Scene")]
    assert len(made) == 1 and [ast.unparse(arg) for arg in made[0].value.args] == ["pyxel", "data", "CAR_ID", "TRACK_ID"]
    name = made[0].targets[0].id
    apps = [call for call in ast.walk(main) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "App"]
    tours = [call for call in ast.walk(main) if isinstance(call, ast.Call) and is_attribute_of(call.func, "tour", "run")]
    assert len(apps) == len(tours) == 1
    assert isinstance(apps[0].args[2], ast.Name) and apps[0].args[2].id == name
    assert isinstance(tours[0].args[2], ast.Name) and tours[0].args[2].id == name
    init = app_method("__init__")
    assert [arg.arg for arg in init.args.args][:4] == ["self", "selected", "data", "scene"]
    # 巡回の口は、検証の口。Pyxelを始めた後に、柱と印つきで、場面を組む。
    tour_tree = ast.parse(TOUR_PY.read_text(encoding="utf-8"))
    run = next(node for node in tour_tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    builds = [call for call in ast.walk(run) if isinstance(call, ast.Call) and is_attribute_of(call.func, "scene", "build")]
    starts = [call for call in ast.walk(run) if isinstance(call, ast.Call) and is_attribute_of(call.func, "pyxel", "init")]
    assert len(builds) == len(starts) == 1 and starts[0].lineno < builds[0].lineno
    probes = [keyword.value for keyword in builds[0].keywords if keyword.arg == "probes"]
    assert len(probes) == 1 and isinstance(probes[0], ast.Constant) and probes[0].value is True
