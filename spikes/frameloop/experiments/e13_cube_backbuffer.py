"""E13: can a Pyxel Cube scene be rendered into an offscreen Image (back buffer) and then
blitted to the screen every frame? Uses the structure of examples/cube/c01_hello_cube.py."""
import os
import time

import pyxel
from pyxel.cube import Camera, Mat4, Node, Shading, Vec3

W, H = 320, 240


class Scene(Node):
    def __init__(self):
        super().__init__()
        self.shading = Shading(pyxel.colors)
        self.camera = Camera()
        self.camera.clear_color = 1
        self.camera.transform = Mat4.look_at(Vec3(0.0, 78.0, 104.0), Vec3.ZERO)
        self.angle = 0.0

    def on_draw(self):
        spin = Mat4.from_euler(Vec3(self.angle, self.angle * 1.7, 0.0))
        for i, col in enumerate((8, 9, 10, 11, 12, 14)):
            pos = Vec3(pyxel.cos(i * 60) * 52.0, 10.0, pyxel.sin(i * 60) * 52.0)
            self.box(Mat4.from_translation(pos) * spin, Vec3(15.6, 15.6, 15.6), col)


pyxel.init(W, H, fps=1000, capture_sec=0, headless=True)
scene = Scene()
back = pyxel.Image(W, H)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

pyxel.cls(0)
scene.draw(0, 0, W, H, back)  # render into the back buffer only
screen_untouched = all(pyxel.pget(x, y) == 0 for x in range(0, W, 8) for y in range(0, H, 8))
back_colors = sorted({back.pget(x, y) for x in range(0, W, 2) for y in range(0, H, 2)})
pyxel.blt(0, 0, back, 0, 0, W, H)
same = all(pyxel.pget(x, y) == back.pget(x, y) for x in range(0, W, 3) for y in range(0, H, 3))
pyxel.screen.save(os.path.join(out, "e13_cube_backbuffer.png"), 1)
print(f"screen untouched while drawing to target: {screen_untouched}; colours in back buffer: {back_colors}; screen == back after blt: {same}")

N = 300
t0 = time.perf_counter()
for i in range(N):
    scene.angle = i * 3.0
    scene.draw(0, 0, W, H, back)
t_target = (time.perf_counter() - t0) / N
t0 = time.perf_counter()
for i in range(N):
    scene.angle = i * 3.0
    scene.draw(0, 0, W, H)
t_screen = (time.perf_counter() - t0) / N
print(f"scene.draw (6 boxes) into target Image: {t_target*1e6:.0f} us; directly to screen: {t_screen*1e6:.0f} us ({N} draws each, native)")
