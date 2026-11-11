import json, math
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Mesh
import common as C
pyxel.init(320, 240, headless=True)
sh = C.apply_palette("evening")
out = {}
tex = C.make_car_texture(C.RED)
mesh = C.make_car_mesh(tex)
out["mesh.col_img is tex"] = mesh.col_img is tex
root = Node(); root.shading = sh; root.camera = Camera(); root.camera.clear_color = C.ASPH_M; root.camera.fov = 30
root.camera.transform = Mat4.look_at(Vec3(-6.5, 1.6, 2.2), Vec3(0, 0.6, 0))
model = Node.from_mesh(mesh); root.add_child(model)
def cnt():
    root.draw(0, 0, 320, 240)
    h = {}
    for y in range(240):
        for x in range(320):
            c = pyxel.pget(x, y); h[c] = h.get(c, 0) + 1
    return {k: h.get(k, 0) for k in (C.BRAKE, C.RED_D, C.RED, C.BLUE)}
i = C.SW["tail"]
out["retained: before"] = cnt()
tex.rect((i % 8) * 4, (i // 8) * 4, 4, 4, C.BLUE)
out["retained: after tex.rect(tail=BLUE) on the original Image"] = cnt()
pyxel.screen.save("out/e07_tail_blue.png", 2)
# body color change through the same texture
j = C.SW["body"]; tex.rect((j % 8) * 4, (j // 8) * 4, 4, 4, C.BLUE)
out["retained: after body swatch -> BLUE"] = cnt()
# mesh.col_img reassign after Node.from_mesh
tex2 = C.make_car_texture(C.YELLOW); mesh.col_img = tex2
h = cnt(); out["retained: after mesh.col_img = tex2 (YELLOW body) [RED px, BLUE px]"] = h
root.draw(0, 0, 320, 240); out["yellow_px_after_reassign"] = sum(1 for y in range(240) for x in range(320) if pyxel.pget(x, y) == C.YELLOW)
# shaded(False) inside on_draw for a separate lamp primitive (immediate)
lamp = C.Builder(); lamp.quad_col((-2.11, 0.62, -0.6), (-2.11, 0.62, 0.6), (-2.11, 0.74, 0.6), (-2.11, 0.74, -0.6), (0.5, 0.5), (-1, 0, 0)); lamp_p = lamp.primitive()
class Lamp(Node):
    on = True
    def on_draw(self):
        self.shaded(False)
        self.prim(Mat4.IDENTITY, lamp_p, C.PINK if self.on else C.RED_D)
l = Lamp(); root.add_child(l); root.draw(0, 0, 320, 240)
out["immediate unshaded lamp: PINK px"] = sum(1 for y in range(240) for x in range(320) if pyxel.pget(x, y) == C.PINK)
pyxel.screen.save("out/e07_lamp_unshaded.png", 2)
# shaded state leak check: does shaded(False) in one node affect siblings drawn after? (model drawn before; add another after)
class After(Node):
    def on_draw(self):
        self.box(Mat4.from_translation(Vec3(0, 2.0, 0)), Vec3(0.5, 0.5, 0.5), C.GRASS_M)
root.add_child(After()); root.draw(0, 0, 320, 240)
hh = {}
for y in range(240):
    for x in range(320):
        c = pyxel.pget(x, y); hh[c] = hh.get(c, 0) + 1
out["box after unshaded node: GRASS_D/GRASS_M/GRASS_L px (shaded if more than one)"] = [hh.get(C.GRASS_D, 0), hh.get(C.GRASS_M, 0), hh.get(C.GRASS_L, 0)]
json.dump(out, open("out/e07_dyn_tex.json", "w"), indent=1)
for k, v in out.items(): print(k, "=", v)
