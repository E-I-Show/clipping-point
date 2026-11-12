"""3Dの場面。Pyxelの3D機能（pyxel.cube）に触れるのは、ここだけ。決まりは docs/design/overview.md の「描画」。

このモジュール自身は pyxel をimportしない。Pyxel（のモジュール）は、Scene の引数で受ける（cp_app/canvas_pyxel.py、cp_app/tour.py と同じ形）。
Pyxelの型に頼る物（ノードの子クラス）は、関数の中で作る。偽の Pyxel を渡して、テストできる（tests/test_render.py）。
形（頂点、三角形、色の役割の名）は、純Pythonの層が、数値として作る（cp_core の track、car_shape、camera）。ここは、それを Pyxel の物にするだけ。

座標の決まりは、2つある（cp_core/mesh.py の頭の注）。
  ロジックの座標  コース、地面、カメラの目と注視点、車の位置、判定用の柱。to_cube() を通す（z の符号を反転し、三角形は頂点の順も入れ替える）
  模型の座標      車の模型と、模型に付ける印。そのまま渡す（反転も、入れ替えも、しない）。車の根のノードの変換の下に置く
z の反転と、頂点の順の入れ替えを書くのは、to_cube() の1か所だけ（ほかの所に書くと、打ち消し合って、鏡写しの絵が通る）。
車の姿勢は Mat4.from_translation(Vec3(x, 0, −z)).rotate_y(degrees(向き))。段0は、ピッチとロールを掛けない。

場面（Scene）のノード：
  根 ─ 地面 / 塊ごとのノード / 車の根（位置と向き）─ 車体と屋根、車輪4つ、印（検証の口があるときだけ） / 柱（検証の口があるときだけ）
描く口は、1つ（Scene.draw）。ふだんの実描画も、判定用の実描画の4枚も、巡回の3Dの絵も、ここで描く。
  背景を写す（描くものに無ければ、黒で消す）→ カメラと車を置く → 見えない塊と、描かないものを隠す → 根の draw を1回（背景を消さない設定）
深度の記録は、draw の呼び出しごとに消える。3Dは、1回の呼び出しで描く。2D（仮の表示）は、呼ぶ側が、この後に重ねる。
色は、256×256の1枚の色見本の絵（32色の矩形）を、三角形ごとに、矩形の中の1点をUVで指して出す。部品の中は、1色（模様は入れない）。
パレットを当てる所は apply_palette() の1か所（パレットの差し替え、陰影の表の作り直し、灯火の手直し）。巡回の口も、Scene.build() を通して、ここで当てる。

判定用の実描画（Scene.judge）は、検証の口（画面なしで回す口、巡回の口、ブラウザ版の外から渡す値）があるときだけ、結果を書く直前に呼ぶ。
裏画面とは別の絵へ、同じ描く口で4枚描いて、画素を数える（結果の形は tools/scene_reference.py の頭の注）。
  1枚目  背景と地面。空の役割の色の画素の数
  2枚目  1枚目＋コース。1枚目との、違う画素の数（コースの画素）
  3枚目  2枚目＋車。2枚目との、違う画素の数（車の画素）。呼ぶ側が渡した絵（ふだんの実描画の絵）との、違う画素を、2Dの描画命令の矩形の内と外に分ける
  4枚目  柱と印だけ。色ごとの画素の数と、重心の x
呼ぶ側が、描き直す前の絵（アプリは、周期の中の実描画が描いた裏画面）も渡せば、描き直した後の絵との、違う画素の数も返す。
柱と印（陰影を切った、片面の板）は、build(probes=True) のときだけ作る。ふつうの起動では、柱も、印も、判定用の絵も、作らない。
判定の後は、柱と印を隠し、コースと車を、見える状態に戻す（途中で例外が出ても戻す）。
画素は、絵の data_ptr() でまとめて読む（1画素1バイト、左上から行ごと）。
描いた結果と、測った値は、世界（Sim）へ、何も戻さない。
"""
import zlib
from math import degrees, pi, sin

from cp_core import camera, car_shape, mesh, palette
from cp_core.track import build_track
from cp_ui.canvas import SCREEN_H, SCREEN_W

# 描くもの（描く口の引数 layers に並べる名）。
BACKDROP, GROUND, TRACK, CAR, PROBES = "backdrop", "ground", "track", "car", "probes"
LAYERS = (BACKDROP, GROUND, TRACK, CAR, PROBES)
NORMAL = (BACKDROP, GROUND, TRACK, CAR)  # ふだんの実描画で描くもの
CLEAR_COL = palette.BLACK  # 背景を写さないとき（判定用の4枚目）に、描き先を消す色。柱と印の色とは、違う色
# 色見本の絵。256×256の1枚に、32色を、8列で、1色 SWATCH_PX 角の矩形に並べる（UVは、0〜1に切り詰められ、繰り返せない。試作の記録）。
SWATCH_IMAGE_PX = 256
SWATCH_COLUMNS = 8
SWATCH_PX = SWATCH_IMAGE_PX // SWATCH_COLUMNS
# 地面（コースの外の、遠い地面の色の板）。コースより、少し低く置く。試作の実測では、0.02〜0.2 m 低い板と、コースの間に、深度の競り合いは出ない。
GROUND_NAME = "ground"
GROUND_DROP_M = 0.05
# 割り切り：地面は、コースを囲む範囲（塊の外接の箱に、カメラの奥を足した範囲）を、この大きさの四角に割った板。視点から遠い所も、同じ大きさ。
# 景観物と、細かい版と粗い版の切り替えを作る段1の「コースの描画」の区切りで、見直す。
GROUND_TILE_M = 100.0
# 割り切り：背景は、空の4色の帯（等しい高さ）と、式で作った山並み2本だけの、仮の絵（雲も、時間帯ごとの違いも、景色の形も無い）。
# 絵の高さ、山並みの高さと波の数、波の重ね方の係数（ridge_heights）は、この絵の作り方の一部。遠景を作り込む段1の「コースの描画」の
# 区切りで、時間帯ごとの背景の作り方と一緒に、作り直す（そのときに、寸法を、定義データへ出す）。
BACKDROP_ROWS = 96  # 背景の絵の高さ（画素）。下の端が、地平線。これより上は、空のいちばん上の色で埋める
# 山並み（遠い尾根、近い尾根の順。色は palette.MOUNTAINS の順）。(低い所の高さ, 高い所との差, 1周の波の数, 波の始まりの角度3つ)。高さは画素。
# 遠い尾根は、いつも、近い尾根より高い（隠れない）。空のいちばん下の帯（24画素）が、尾根の上に、見える高さにする。
BACKDROP_RIDGES = ((14, 16, 3, (0.4, 2.1, 4.4)), (5, 8, 7, (1.3, 5.2, 3.0)))
TWO_PI = 2.0 * pi
NONZERO_TO_ONE = bytes([0] + [1] * 255)  # 色の番号の差（0は同じ）を、「違う＝1」に直す表


# --- 座標の変換。z の反転と、頂点の順の入れ替えを書くのは、ここだけ ---
def to_cube(points, triangles=()) -> tuple:
    """ロジックの座標の形を、Pyxelの3Dの座標の形にする。返すのは (点の並び, 三角形の並び)。

    points は、ロジックの座標の点 ((x, y, z), …)。triangles は、頂点の番号の3つ組 ((a, b, c), …)。
    z の符号を反転する（Pyxelの3Dは右手系。反転しないと、左右が鏡写しになる）。反転で、面の向きが裏返るので、三角形は、頂点の順も入れ替える。
    コースのメッシュ、地面、判定用の柱（点と三角形）、車の位置、カメラの目と注視点（点だけ）が、ここを通る。
    模型の座標の形（車の模型と、模型に付ける印）は、通さない。
    """
    return tuple((x, y, -z) for x, y, z in points), tuple((a, c, b) for a, b, c in triangles)


# --- パレット。当てるのは、ここだけ ---
def apply_palette(pyxel, colors: palette.Palette):
    """パレットを当てる。パレットの差し替え、陰影の表の作り直し、灯火の手直し。返すのは、陰影の表（Shading）。

    pyxel.init の後に呼ぶ。陰影で暗くしない色（colors.unshaded。灯火）は、陰影の表の、その番号の行を、全部の段で元の色にする。
    """
    cube = pyxel.cube
    pyxel.colors[:] = list(colors.colors)
    shading = cube.Shading(pyxel.colors)
    for col in colors.unshaded:
        for level in range(cube.Shading.LEVEL_COUNT):
            shading[col, level] = (col, col)
    return shading


# --- 色見本の絵と、UV ---
def swatch_uv(col: int) -> tuple:
    """色見本の絵の、色の番号 col の矩形の、中心の UV。"""
    cell_u, cell_v = col % SWATCH_COLUMNS, col // SWATCH_COLUMNS
    return (cell_u * SWATCH_PX + SWATCH_PX // 2) / SWATCH_IMAGE_PX, (cell_v * SWATCH_PX + SWATCH_PX // 2) / SWATCH_IMAGE_PX


def make_swatches(pyxel):
    """色見本の絵。32色の矩形を並べた、256×256の1枚。"""
    image = pyxel.Image(SWATCH_IMAGE_PX, SWATCH_IMAGE_PX)
    image.cls(palette.BLACK)
    for col in range(palette.COLOR_COUNT):
        image.rect(col % SWATCH_COLUMNS * SWATCH_PX, col // SWATCH_COLUMNS * SWATCH_PX, SWATCH_PX, SWATCH_PX, col)
    return image


# --- 背景 ---
def ridge_heights(period_px: int, ridge) -> list:
    """山並み1本の、列ごとの高さ（画素）。幅 period_px で、ちょうど1周する（継ぎ目が、つながる）。"""
    low, span, waves, (first, second, third) = ridge
    heights = []
    for x in range(period_px):
        angle = TWO_PI * x / period_px
        wave = 0.5 + 0.30 * sin(waves * angle + first) + 0.15 * sin(2 * waves * angle + second) + 0.05 * sin(5 * waves * angle + third)
        heights.append(low + int(span * wave))
    return heights


def make_backdrop(pyxel, period_px: int):
    """背景の絵（空の4色の帯と、山並み2本）。幅は、向きの1周ぶん（period_px）。高さは BACKDROP_ROWS で、下の端が、地平線。

    起動時に1度作る。写すときに、カメラの向きで、横にずらす（Scene.draw）。
    """
    image = pyxel.Image(period_px, BACKDROP_ROWS)
    bands = len(palette.SKY)
    for index, col in enumerate(palette.SKY):  # 上（天頂の側）から、下（地平線の側）へ
        top, bottom = BACKDROP_ROWS * index // bands, BACKDROP_ROWS * (index + 1) // bands
        image.rect(0, top, period_px, bottom - top, col)
    for col, ridge in zip(palette.MOUNTAINS, BACKDROP_RIDGES):  # 遠い尾根、近い尾根の順
        for x, height in enumerate(ridge_heights(period_px, ridge)):
            image.rect(x, BACKDROP_ROWS - height, 1, height, col)
    return image


# --- 形（数値）を、Pyxelの3Dの物にする ---
def _primitive(cube, shapes):
    """形の並び [(頂点, 三角形, 色の番号), …]（Pyxelの3Dの座標）を、1つの Primitive にする。裏の面は、捨てる。

    頂点は、形ごとに共有する。UV は、頂点ごとに、その形の色の矩形の中心（形の中は、1色）。法線は、面ごと。
    """
    positions, indices, uvs = [], [], []
    for vertices, triangles, col in shapes:
        base = len(positions) // 3
        u, v = swatch_uv(col)
        for x, y, z in vertices:
            positions += (x, y, z)
            uvs += (u, v)
        for a, b, c in triangles:
            indices += (base + a, base + b, base + c)
    primitive = cube.Primitive(cube.Primitive.MODE_TRIANGLES, positions, indices, uvs=uvs, cull=cube.Primitive.CULL_BACK)
    primitive.compute_normals()
    return primitive


def logic_primitive(cube, parts):
    """ロジックの座標の部品（cp_core.mesh の MeshPart。コース、地面、柱）を、Primitive にする。to_cube() を通す。"""
    return _primitive(cube, [(*to_cube(part.vertices, part.triangles), palette.number(part.role)) for part in parts])


def model_primitive(cube, parts):
    """模型の座標の部品（車の模型と、模型に付ける印）を、Primitive にする。そのまま渡す（反転も、頂点の順の入れ替えも、しない）。"""
    return _primitive(cube, [(part.vertices, part.triangles, palette.number(part.role)) for part in parts])


def ground_part(chunks, margin_m: float) -> mesh.MeshPart:
    """地面の板。塊の外接の箱に、margin_m（カメラの奥）を足した範囲を、GROUND_TILE_M の四角に割る。ロジックの座標。上を向く。"""
    low_x = min(chunk.center[0] - chunk.radius for chunk in chunks) - margin_m
    high_x = max(chunk.center[0] + chunk.radius for chunk in chunks) + margin_m
    low_z = min(chunk.center[1] - chunk.radius for chunk in chunks) - margin_m
    high_z = max(chunk.center[1] + chunk.radius for chunk in chunks) + margin_m
    columns = max(1, int((high_x - low_x) / GROUND_TILE_M + 0.999))
    rows = max(1, int((high_z - low_z) / GROUND_TILE_M + 0.999))
    step_x, step_z = (high_x - low_x) / columns, (high_z - low_z) / rows
    vertices = [(low_x + step_x * i, -GROUND_DROP_M, low_z + step_z * k) for k in range(rows + 1) for i in range(columns + 1)]
    triangles = []
    across = columns + 1
    for k in range(rows):
        for i in range(columns):
            a, b = k * across + i, (k + 1) * across + i
            triangles += mesh.quad(a, b, b + 1, a + 1)  # (b−a)×(c−a) が、上（+y）を向く順
    return mesh.MeshPart(GROUND_NAME, palette.ROLES[palette.FAR_GROUND], tuple(vertices), tuple(triangles))


def _probe_node_type(cube):
    """柱と印を描くノードの型。Pyxelの型（Node）に頼るので、関数の中で作る。"""

    class ProbeNode(cube.Node):
        """持っている形を、陰影を切って、そのつど描く。変換は、親のノードの変換の下（自分の変換は、動かさない）。"""

        def __init__(self, swatches) -> None:
            super().__init__()
            self.swatches = swatches
            self.primitives = []  # 描く形（Primitive）。柱は、描くたびに作り直す

        def on_draw(self) -> None:
            self.shaded(False)
            for primitive in self.primitives:
                self.prim(cube.Mat4.IDENTITY, primitive, self.swatches)

    return ProbeNode


# --- 画素を数える計算。Pyxelに触れない ---
def read_pixels(image) -> bytes:
    """画像の全部の画素を、まとめて読む。1画素1バイト（色の番号）、左上から行ごと。"""
    pixels = bytes(image.data_ptr())
    if len(pixels) != image.width * image.height:
        raise RuntimeError(f"data_ptr() gave {len(pixels)} bytes for a {image.width}x{image.height} image")
    return pixels


def _difference(first: bytes, second: bytes) -> bytes:
    """2枚の絵の、画素ごとの差（同じ色なら0）。"""
    if len(first) != len(second):
        raise ValueError(f"pictures differ in size ({len(first)} and {len(second)} pixels)")
    return (int.from_bytes(first, "little") ^ int.from_bytes(second, "little")).to_bytes(len(first), "little")


def count_diff(first: bytes, second: bytes) -> int:
    """2枚の絵の、色が違う画素の数。"""
    mixed = _difference(first, second)
    return len(mixed) - mixed.count(0)


def split_diff(first: bytes, second: bytes, width: int, rects) -> tuple:
    """2枚の絵の、色が違う画素を、矩形の内と外に分けて数える。返すのは (内の数, 外の数)。

    rects は (x, y, w, h) の並び（2Dの描画命令の矩形）。重なっていても、画素は1度だけ数える。絵の外へ出た分は、切り詰める。
    """
    changed = _difference(first, second).translate(NONZERO_TO_ONE)
    if width < 1 or len(changed) % width:
        raise ValueError(f"pictures of {len(changed)} pixels are not {width} wide")
    height = len(changed) // width
    covered = bytearray(len(changed))
    for x, y, w, h in rects:
        left, right = max(x, 0), min(x + w, width)
        if left >= right:
            continue
        for row in range(max(y, 0), min(y + h, height)):
            covered[row * width + left:row * width + right] = b"\x01" * (right - left)
    inside = (int.from_bytes(changed, "little") & int.from_bytes(covered, "little")).bit_count()
    return inside, len(changed) - changed.count(0) - inside


def color_centroid(pixels: bytes, width: int, col: int) -> tuple:
    """色 col の画素の (数, 重心の x（0.1画素の単位の整数。四捨五入）)。1つも無ければ (0, 0)。整数だけで計算する。"""
    count = total_x = 0
    for start in range(0, len(pixels), width):
        row = pixels[start:start + width]
        hits = row.count(col)
        if not hits:
            continue
        count += hits
        at = row.find(col)
        while at >= 0:
            total_x += at
            at = row.find(col, at + 1)
    return count, (20 * total_x + count) // (2 * count) if count else 0


class Scene:
    """3Dの場面。作るのは main()。Pyxelの物は、build() で作る（pyxel.init の後に呼ぶ）。"""

    def __init__(self, pyxel, data, car_id: str, track_id: str) -> None:
        self.pyxel = pyxel  # Pyxel（のモジュール）。3Dの口は pyxel.cube
        self.data = data  # 読み込んだ定義（cp_core.datadefs の GameData）。引くのは、build() の中で1度だけ
        self.car_id, self.track_id = car_id, track_id
        self.built = False
        self.probes = False  # 判定用の柱と印を、作ったか
        self.stats = {}  # 場面を組んだときの数（三角形の数、塊の数）と、直近に描いた数。見た目と検証のためのもの。世界へは渡さない

    # --- 組む ---
    def build(self, probes: bool = False, clock=None) -> None:
        """場面を組む。pyxel.init の後に、1度だけ呼ぶ。パレットを当て、色見本の絵、背景の絵、ノードを作る。

        probes が True のとき（検証の口があるとき）だけ、判定用の柱と印と、判定用の絵を作る。
        clock は、実時間（秒）を返す関数（呼ぶ側が渡す。ここでは、時計を読まない）。あれば、メッシュ用の数値を作る時間と、
        場面を組む時間（ms）を、stats に入れる（報告のための値）。
        """
        if self.built:
            raise RuntimeError("the scene is already built")
        pyxel, cube, data = self.pyxel, self.pyxel.cube, self.data
        started_s = clock() if clock is not None else 0.0
        self.palette = palette.palette_from_entry(data.entry("palettes", palette.EVENING))
        self.camera_spec = camera.spec_from_entry(data.entry("cameras", camera.CHASE))
        self.track = build_track(data.entry("tracks", self.track_id))  # 世界と同じ表（同じ中身の項目からは、同じ表が返る）
        shape = car_shape.build_car_shape(data.entry("cars", self.car_id))
        self.shading = apply_palette(pyxel, self.palette)
        self.swatches = make_swatches(pyxel)
        self.backdrop_period = camera.backdrop_period_px(self.camera_spec.fov_deg, SCREEN_H)
        self.backdrop = make_backdrop(pyxel, self.backdrop_period)
        # 根。陰影の表と、カメラを持つ。カメラは、描き先を消さない（先に写した背景が、残る）。
        self.root = cube.Node()
        self.root.shading = self.shading
        self.camera = cube.Camera()
        self.camera.clear_color = None
        self.root.camera = self.camera
        # 地面と、塊ごとのノード（ロジックの座標の形）。
        mesh_started_s = clock() if clock is not None else 0.0
        chunks = self.track.mesh_chunks()
        mesh_s = clock() - mesh_started_s if clock is not None else 0.0
        ground = ground_part(chunks, self.camera_spec.far)
        self.ground = self._add(self.root, logic_primitive(cube, [ground]), GROUND_NAME)
        self.chunks = [(chunk, self._add(self.root, logic_primitive(cube, chunk.parts), "chunk")) for chunk in chunks]
        # 車（模型の座標の形）。車の根（位置と向き）の下に、車体と屋根。車輪は、車体の子にしない（車の根の下に置く）。
        self.car_root = cube.Node()
        self.root.add_child(self.car_root)
        wheel = model_primitive(cube, [shape.wheel])
        self.car_nodes = [self._add(self.car_root, model_primitive(cube, shape.body), "body")]
        for center in shape.wheel_centers:
            self.car_nodes.append(self._add(self.car_root, wheel, "wheel", cube.Mat4.from_translation(cube.Vec3(*center))))
        self.stats = {
            "chunks": len(chunks), "track_triangles": sum(chunk.triangle_count for chunk in chunks),
            "ground_triangles": ground.triangle_count, "car_triangles": shape.triangle_count,
        }
        if probes:
            self._build_probes()
        if clock is not None:
            self.stats["mesh_ms"], self.stats["build_ms"] = round(mesh_s * 1000.0, 3), round((clock() - started_s) * 1000.0, 3)
        self.built = True

    def _add(self, parent, primitive, name: str, transform=None):
        """形1つのノードを作って、parent の下に置く。"""
        cube = self.pyxel.cube
        node = cube.Node.from_mesh(cube.Mesh([primitive], [cube.Mat4.IDENTITY if transform is None else transform], [-1], [name], self.swatches))
        parent.add_child(node)
        return node

    def _build_probes(self) -> None:
        """判定用の柱と印と、判定用の絵を作る。検証の口があるときにだけ呼ぶ（ふつうの起動では、作らない）。"""
        cube = self.pyxel.cube
        probe_node = _probe_node_type(cube)
        # 印は、模型の座標。車の根の変換の下に置く。柱は、ロジックの座標。根の下に置き、形は、描くたびに、車の位置と向きから作り直す。
        self.marks = probe_node(self.swatches)
        self.marks.primitives = [model_primitive(cube, car_shape.mark_parts())]
        self.car_root.add_child(self.marks)
        self.pillars = probe_node(self.swatches)
        self.root.add_child(self.pillars)
        self.marks.visible = self.pillars.visible = False
        self.scratch = self.pyxel.Image(SCREEN_W, SCREEN_H)  # 判定用の絵。裏画面とは別の、同じ大きさの絵
        self.probes = True

    # --- 描く ---
    def chase(self, x: float, z: float, heading: float) -> camera.CameraPose:
        """後方追従のカメラの位置と向き。車の位置と向き（ロジックの座標）から。"""
        return camera.chase_pose(self.camera_spec, x, z, heading)

    def show(self, layers, pose: camera.CameraPose) -> None:
        """描くもの（layers）だけを、見える状態にする。塊は、カメラから見えないものも隠す。"""
        self.ground.visible = GROUND in layers
        drawn = self.stats["ground_triangles"] if GROUND in layers else 0
        shown = 0
        for chunk, node in self.chunks:
            node.visible = TRACK in layers and camera.chunk_visible(pose, chunk.center[0], chunk.center[1], chunk.radius)
            if node.visible:
                shown += 1
                drawn += chunk.triangle_count
        for node in self.car_nodes:
            node.visible = CAR in layers
        if CAR in layers:
            drawn += self.stats["car_triangles"]
        if self.probes:
            self.marks.visible = self.pillars.visible = PROBES in layers
        self.stats["chunks_drawn"], self.stats["triangles_drawn"] = shown, drawn

    def draw(self, target, pose: camera.CameraPose, x: float, z: float, heading: float, layers=NORMAL) -> None:
        """描く口。target（pyxel.Image）へ、layers に並べたものを描く。車の位置 (x, z) と向き heading は、ロジックの座標。

        背景を写し（無ければ、黒で消す）、カメラと車を置き、見えない塊と、描かないものを隠して、根の draw を1回呼ぶ。
        ふだんの実描画も、判定用の実描画も、巡回の3Dの絵も、ここで描く。
        """
        cube = self.pyxel.cube
        unknown = [layer for layer in layers if layer not in LAYERS]
        if unknown:
            raise ValueError(f"unknown layers: {unknown}")
        if PROBES in layers:
            if not self.probes:
                raise RuntimeError("the probes were not built (they exist only when a verification switch is on)")
            self.pillars.primitives = [logic_primitive(cube, camera.pillar_parts(x, z, heading))]
        if BACKDROP in layers:
            self._blit_backdrop(target, pose)
        else:
            target.cls(CLEAR_COL)
        (eye, look), _ = to_cube((pose.eye, pose.target))
        self.camera.transform = cube.Mat4.look_at(cube.Vec3(*eye), cube.Vec3(*look))
        self.camera.fov, self.camera.near, self.camera.far = pose.fov_deg, pose.near, pose.far
        (place,), _ = to_cube(((x, 0.0, z),))
        self.car_root.transform = cube.Mat4.from_translation(cube.Vec3(*place)).rotate_y(degrees(heading))
        self.show(layers, pose)
        self.root.draw(0, 0, SCREEN_W, SCREEN_H, target)

    def _blit_backdrop(self, target, pose: camera.CameraPose) -> None:
        """背景を写す。地平線より下は、遠い地面の色。背景の絵より上は、空のいちばん上の色。横は、カメラの向きでずらす。"""
        horizon = camera.horizon_row(pose, SCREEN_H)
        top = horizon - BACKDROP_ROWS
        target.cls(palette.FAR_GROUND)
        if top > 0:
            target.rect(0, 0, SCREEN_W, top, palette.SKY[0])
        period = self.backdrop_period
        shift = camera.backdrop_shift_px(pose.heading, period)
        for left in (shift - period, shift):  # 絵は、幅 period で、横に繰り返す
            target.blt(left, top, self.backdrop, 0, 0, period, BACKDROP_ROWS)

    # --- 判定用の実描画 ---
    def judge(self, shown: bytes, rects, x: float, z: float, heading: float, before=None) -> dict:
        """判定用の実描画。返すのは、結果の scene（形は tools/scene_reference.py の頭の注。値は、整数と、整数の並び）。

        shown は、ふだんの実描画と同じ道で、同じ車の位置と向きで描いた絵の画素（read_pixels の形。アプリは、3Dと2Dを描いた裏画面）。
        rects は、その絵に重ねた、2Dの描画命令の矩形の並び（重ねていなければ、空）。
        before は、描き直す前の、同じ絵の画素（アプリは、周期の中の実描画が描いた裏画面）。渡せば、shown との違う画素の数を、
        結果の stale に入れる（渡さなければ、鍵を入れない。巡回の3Dの絵には、周期の中の実描画が無い）。
        判定の後は、柱と印を隠し、コースと車を、見える状態に戻す（途中で例外が出ても戻す）。
        """
        if not self.probes:
            raise RuntimeError("the probes were not built (they exist only when a verification switch is on)")
        pose, scratch = self.chase(x, z, heading), self.scratch
        try:
            pictures = []
            for layers in ((BACKDROP, GROUND), (BACKDROP, GROUND, TRACK), NORMAL, (PROBES,)):
                self.draw(scratch, pose, x, z, heading, layers)
                pictures.append(read_pixels(scratch))
        finally:
            self.show(NORMAL, pose)
        first, second, third, fourth = pictures
        inside, outside = split_diff(shown, third, SCREEN_W, rects)
        roles = {**camera.PILLAR_ROLES, **car_shape.MARK_ROLES}
        probes = {}
        for name, role in roles.items():
            pixels, x10 = color_centroid(fourth, SCREEN_W, palette.number(role))
            probes[name] = {"pixels": pixels, "x10": x10}
        stale = {} if before is None else {"stale": count_diff(before, shown)}
        return {
            "sky": sum(first.count(col) for col in palette.SKY),
            "track": count_diff(first, second),
            "car": count_diff(second, third),
            "ink_inside": inside,
            "ink_outside": outside,
            **stale,
            "probes": probes,
            "palette": [int(color) for color in self.pyxel.colors],
            "digest": zlib.crc32(third),
        }
