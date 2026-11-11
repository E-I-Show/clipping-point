"""Pyxel Cube draw-time benchmark shared by native and web. pyxel.init must already be done (320x240).

Scene = the one used by the earlier native probe (pyxel_probe/bench_cube.py):
a bumpy ground grid of 2*n^2 triangles (optionally textured with a 64x64 checker) + 12 boxes ("6 cars").
"""

import math
import random
import time

import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3

W, H = 320, 240


def make_ground(n, size, textured):
    pos, idx, uvs = [], [], []
    step = size / n
    rnd = random.Random(1)
    for j in range(n + 1):
        for i in range(n + 1):
            pos += [i * step - size / 2, rnd.uniform(0, 1.5), j * step - size / 2]
            uvs += [i % 2, j % 2]
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + n + 1
            d = c + 1
            idx += [a, c, b, b, c, d]
    p = Primitive(Primitive.MODE_TRIANGLES, pos, idx, [], uvs if textured else [], Primitive.CULL_NONE)
    p.compute_normals()
    return p, len(idx) // 3


def make_checker():
    img = pyxel.Image(64, 64)
    for y in range(64):
        for x in range(64):
            img.pset(x, y, 13 if (x // 8 + y // 8) % 2 else 5)
    return img


class Scene(Node):
    def __init__(self, prim, col_img, cars):
        super().__init__()
        self.prim_ = prim
        self.col_img = col_img
        self.cars = cars
        self.shading = Shading(pyxel.colors)
        self.camera = Camera()
        self.camera.clear_color = 12
        self.camera.fov = 60
        self.camera.near = 0.5
        self.camera.far = 2000.0

    def on_draw(self):
        self.prim(Mat4.IDENTITY, self.prim_, self.col_img)
        for k in range(self.cars):
            m = Mat4.from_translation(Vec3(-6 + k * 2.5, 1.2, -20 - k * 6))
            self.box(m, Vec3(1.7, 1.2, 4.2), 8 + k)
            self.box(m * Mat4.from_translation(Vec3(0, 0.8, -0.2)), Vec3(1.5, 0.6, 2.0), 7)


def make_scene(n_side, textured, cars=6):
    prim, ntri = make_ground(n_side, 600.0, textured)
    return Scene(prim, make_checker() if textured else 13, cars), ntri


def set_camera(sc, f):
    a = f * 3.0
    eye = Vec3(math.sin(math.radians(a)) * 120, 3.0, math.cos(math.radians(a)) * 120)
    sc.camera.transform = Mat4.look_at(eye, Vec3(0, 1.0, 0))


def bench(n_side, textured, cars=6, frames=120):
    sc, ntri = make_scene(n_side, textured, cars)
    t0 = time.perf_counter()
    for f in range(frames):
        set_camera(sc, f)
        sc.update()
        sc.draw(0, 0, W, H)
    ms = (time.perf_counter() - t0) / frames * 1000
    return ntri, ms


def run_suite(frames=120):
    rows = []
    for textured in (False, True):
        for n in (16, 32, 45, 64):
            ntri, ms = bench(n, textured, 6, frames)
            rows.append({"textured": textured, "tris": ntri, "draw_ms": round(ms, 3)})
    distinct = sorted(set(pyxel.pget(x, y) for x in range(0, W, 16) for y in range(0, H, 16)))
    # 2D cost reference: cls + 40 text draws (HUD-like)
    t0 = time.perf_counter()
    for f in range(200):
        pyxel.cls(1)
        for k in range(40):
            pyxel.text(4 + (k % 4) * 78, 4 + (k // 4) * 8, "LAP 1/3 1:02.345", 7)
    hud_ms = (time.perf_counter() - t0) / 200 * 1000
    return {"frames": frames, "rows": rows, "distinct_colors_on_screen": distinct, "cls_plus_40_text_ms": round(hud_ms, 3)}
