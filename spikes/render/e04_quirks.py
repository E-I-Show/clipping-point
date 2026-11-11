import json, math, sys, time
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Mesh
import common as C

pyxel.init(320, 240, headless=True)
sh = C.apply_palette("evening")
out = {}
MARK = C.PINK
def count(col, y0=0, y1=240, img=None):
    g = pyxel.pget if img is None else img.pget
    return sum(1 for y in range(y0, y1) for x in range(320) if g(x, y) == col)

# ---------- (a) near clipping of big ground triangles under the camera
def ground_prim(size, tile):
    b = C.Builder(); n = int(size / tile); h = size / 2
    for iz in range(n):
        for ix in range(n):
            x0, z0 = -h + ix * tile, -h + iz * tile
            b.quad_col((x0, 0, z0), (x0 + tile, 0, z0), (x0 + tile, 0, z0 + tile), (x0, 0, z0 + tile), (0.5, 0.5), (0, 1, 0))
    return b.primitive()
tex1 = pyxel.Image(2, 2); tex1.cls(C.GRASS_M)
res = {}
for tile in (1400.0, 50.0):
    prim = ground_prim(1400.0, tile)
    for near in (0.05, 0.3, 1.0, 3.0):
        for far in (300.0,):
            root = Node(); root.camera = Camera(); root.camera.clear_color = MARK; root.camera.near = near; root.camera.far = far
            root.add_child(Node.from_mesh(Mesh([prim], [Mat4.IDENTITY], [-1], ["g"], tex1)))
            for hgt, pitch_tgt in ((0.62, 0.5), (2.1, 0.9)):
                root.camera.transform = Mat4.look_at(Vec3(3.3, hgt, 7.7), Vec3(33.3, pitch_tgt, 17.7))
                root.draw(0, 0, 320, 240)
                # marker pixels in the bottom 100 rows = holes in the ground near the camera
                res[f"tile{int(tile)}_near{near}_h{hgt}"] = {"holes_bottom_rows140-240": count(MARK, 140, 240), "ground_px": count(C.GRASS_M)}
out["near_clip_ground"] = res
# horizon row where the ground ends with far=300 (camera height 0.62 / 2.1, level camera)
res = {}
prim = ground_prim(1400.0, 50.0)
for hgt in (0.62, 2.1, 8.0):
    for far in (300.0, 150.0, 1000.0):
        root = Node(); root.camera = Camera(); root.camera.clear_color = MARK; root.camera.near = 0.3; root.camera.far = far; root.camera.fov = 60
        root.add_child(Node.from_mesh(Mesh([prim], [Mat4.IDENTITY], [-1], ["g"], tex1)))
        root.camera.transform = Mat4.look_at(Vec3(0, hgt, 0), Vec3(100, hgt, 0))
        root.draw(0, 0, 320, 240)
        top = next((y for y in range(240) if pyxel.pget(160, y) != MARK), None)
        res[f"h{hgt}_far{int(far)}"] = {"first_ground_row_at_center": top, "expected_px_below_horizon": round(hgt / far * (120 / math.tan(math.radians(30))), 2)}
out["far_cut_rows"] = res

# ---------- (b) affine warp: checker road, different quad sizes
chk = pyxel.Image(64, 64)
for y in range(64):
    for x in range(64):
        chk.pset(x, y, C.WHITE if ((x // 8) + (y // 8)) % 2 == 0 else C.ASPH_D)
def road_prim(qw, ql, width=12.0, length=160.0):
    b = C.Builder(); nx = int(round(width / qw)); nz = int(round(length / ql))
    for iz in range(nz):
        for ix in range(nx):
            x0, x1 = iz * ql, (iz + 1) * ql                      # along +x
            z0, z1 = -width / 2 + ix * qw, -width / 2 + (ix + 1) * qw
            # texture: 12 m across = full u; 12 m along = full v (repeat via modulo of the quad origin)
            u0, u1 = (z0 + width / 2) / width, (z1 + width / 2) / width
            v0 = (x0 % 12.0) / 12.0; v1 = v0 + ql / 12.0
            v0c, v1c = min(v0, 0.999), min(v1, 1.0)
            b.quad((x0, 0, z0), (x0, 0, z1), (x1, 0, z1), (x1, 0, z0), ((u0, v0c), (u1, v0c), (u1, v1c), (u0, v1c)), (0, 1, 0))
    return b
names = []
for qw, ql in ((12.0, 12.0), (6.0, 6.0), (6.0, 3.0), (3.0, 3.0), (3.0, 1.5), (1.5, 1.5)):
    b = road_prim(qw, ql)
    root = Node(); root.camera = Camera(); root.camera.clear_color = C.GRASS_D; root.camera.near = 0.3; root.camera.far = 300; root.camera.fov = 62
    root.add_child(Node.from_mesh(Mesh([b.primitive()], [Mat4.IDENTITY], [-1], ["r"], chk)))
    root.camera.transform = Mat4.look_at(Vec3(1.0, 0.62, 1.5), Vec3(31.0, 0.5, 4.5))
    root.draw(0, 0, 320, 240)
    pyxel.text(4, 4, f"quad {qw}x{ql} m  {b.tri_count} tris / 160 m  cam h=0.62", C.YELLOW)
    fn = f"out/e04_affine_{qw}x{ql}.png"; pyxel.screen.save(fn, 2); names.append(fn)
    root.camera.transform = Mat4.look_at(Vec3(1.0, 2.1, 1.5), Vec3(13.0, 0.9, 2.5))
    root.draw(0, 0, 320, 240)
    pyxel.text(4, 4, f"quad {qw}x{ql} m  chase cam h=2.1", C.YELLOW)
    fn = f"out/e04_affine_chase_{qw}x{ql}.png"; pyxel.screen.save(fn, 2); names.append(fn)
out["affine_files"] = names

# ---------- (e) depth buffer across draw() calls
class Box(Node):
    def __init__(self, pos, size, col):
        super().__init__(); self.pos = pos; self.size = size; self.col = col
    def on_draw(self):
        self.shaded(False); self.box(Mat4.from_translation(self.pos), self.size, self.col)
cam = Camera(); cam.clear_color = None; cam.transform = Mat4.look_at(Vec3(0, 0, 10), Vec3(0, 0, 0))
r1 = Node(); r1.camera = cam; r1.add_child(Box(Vec3(0, 0, 5), Vec3(1, 1, 1), C.RED))      # near small
r2 = Node(); r2.camera = cam; r2.add_child(Box(Vec3(0, 0, 0), Vec3(6, 6, 1), C.BLUE))     # far big
pyxel.cls(MARK); r1.draw(0, 0, 320, 240); r2.draw(0, 0, 320, 240)
out["depth_same_camera_two_roots: center pixel (RED=12 kept / BLUE=23 overwritten)"] = pyxel.pget(160, 120)
out["clear_color_None_keeps_background(MARK px)"] = count(MARK)
# two nodes of one root (single draw): depth test works regardless of order
r3 = Node(); r3.camera = cam; r3.add_child(Box(Vec3(0, 0, 5), Vec3(1, 1, 1), C.RED)); r3.add_child(Box(Vec3(0, 0, 0), Vec3(6, 6, 1), C.BLUE))
pyxel.cls(MARK); r3.draw(0, 0, 320, 240); out["depth_single_draw_near_first: center pixel"] = pyxel.pget(160, 120)
# same root drawn twice into the same frame (e.g. main view + again): second draw starts with fresh depth?
pyxel.cls(MARK); r1.draw(0, 0, 320, 240); r1.draw(0, 0, 320, 240); out["same_root_twice_ok_center"] = pyxel.pget(160, 120)

# ---------- (g) viewport sub-rect and target
cam2 = Camera(); cam2.clear_color = C.NAVY; cam2.fov = 35; cam2.transform = Mat4.look_at(Vec3(-5, 2.5, 6), Vec3(0, 0.5, 0))
pv = Node(); pv.camera = cam2; pv.shading = sh
car = C.Car(C.make_car_texture(C.BLUE), shadow=False); pv.add_child(car); car.set_pose(0, 0, 0, 0.3, steer_deg=15)
buf = pyxel.Image(320, 240); buf.cls(MARK)
buf.text(10, 10, "SETTING", C.WHITE)
pv.draw(180, 40, 120, 90, buf)
outside = sum(1 for y in range(240) for x in range(320) if not (180 <= x < 300 and 40 <= y < 130) and buf.pget(x, y) not in (MARK, C.WHITE))
inside_mark = sum(1 for y in range(40, 130) for x in range(180, 300) if buf.pget(x, y) == MARK)
out["viewport: changed px outside rect"] = outside; out["viewport: unclear(MARK) px inside rect"] = inside_mark
buf.rectb(179, 39, 122, 92, C.WHITE)
pyxel.blt(0, 0, buf, 0, 0, 320, 240); pyxel.screen.save("out/e04_viewport_preview.png", 2)
# aspect: wide viewport 240x60 -> is the box still square on screen?
cam3 = Camera(); cam3.clear_color = 0; cam3.transform = Mat4.look_at(Vec3(0, 0, 10), Vec3(0, 0, 0))
r4 = Node(); r4.camera = cam3; r4.add_child(Box(Vec3(0, 0, 0), Vec3(2, 2, 2), C.RED))
pyxel.cls(MARK); r4.draw(40, 100, 240, 60)
xs = [x for x in range(320) if pyxel.pget(x, 130) == C.RED]; ys = [y for y in range(240) if pyxel.pget(160, y) == C.RED]
out["viewport_240x60: box width px, height px"] = [len(xs), len(ys)]
pyxel.cls(MARK); r4.draw(0, 0, 320, 240)
xs = [x for x in range(320) if pyxel.pget(x, 120) == C.RED]; ys = [y for y in range(240) if pyxel.pget(160, y) == C.RED]
out["viewport_320x240: box width px, height px"] = [len(xs), len(ys)]

# ---------- (j) sprite anchor + dither/opacity
img = pyxel.Image(8, 8); img.cls(C.YELLOW)
class S(Node):
    def on_draw(self):
        self.sprite(Vec3(0, 0, 0), img, ((0, 0), (1, 0), (0, 1), (1, 1)), 2.0, 2.0)
r5 = Node(); r5.camera = cam3; r5.add_child(S()); pyxel.cls(MARK); r5.draw(0, 0, 320, 240)
ys = [y for y in range(240) if pyxel.pget(160, y) == C.YELLOW]
out["sprite at origin h=2: rows"] = [min(ys), max(ys)]
class D(Node):
    def on_draw(self):
        self.shaded(False); self.dither(0.5); self.box(Mat4.IDENTITY, Vec3(2, 2, 2), C.RED)
r6 = Node(); r6.camera = cam3; r6.add_child(D()); pyxel.cls(MARK); r6.draw(0, 0, 320, 240)
out["dither(0.5) box: RED px"] = count(C.RED)
r7 = Node(); r7.camera = cam3; b7 = Box(Vec3(0, 0, 0), Vec3(2, 2, 2), C.RED); b7.opacity = 0.5; r7.add_child(b7); pyxel.cls(MARK); r7.draw(0, 0, 320, 240)
out["opacity=0.5 box: RED px"] = count(C.RED)
m = Node.from_mesh(Mesh([Primitive.box(Vec3(2, 2, 2))], [Mat4.IDENTITY], [-1], ["b"], C.RED)); m.opacity = 0.5
r8 = Node(); r8.camera = cam3; r8.add_child(m); pyxel.cls(MARK); r8.draw(0, 0, 320, 240)
out["opacity=0.5 mesh node (no shading): RED px"] = count(C.RED)
m.opacity = 1.0; pyxel.cls(MARK); r8.draw(0, 0, 320, 240); out["opacity=1.0 mesh node: RED px"] = count(C.RED)
json.dump(out, open("out/e04_quirks.json", "w"), indent=1)
for k, v in out.items(): print(k, "=", v)
