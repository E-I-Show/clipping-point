import json, math, sys, time
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Mesh
import common as C

pyxel.init(320, 240, headless=True)
out = {}
out["default_colors_len"] = len(pyxel.colors)
pal = C.make_palette("evening")
pyxel.colors[:] = pal
out["colors_len_after"] = len(pyxel.colors)
# Image accepts 16..31?
img = pyxel.Image(8, 8)
for i in range(32):
    img.pset(i % 8, i // 8, i)
out["image_pget_0_31"] = [img.pget(i % 8, i // 8) for i in range(32)]
img.pset(0, 0, 40); out["pset_40_with_32_colors"] = img.pget(0, 0)
# Image.set with hex string only allows 0-f? try
try:
    img.set(0, 0, ["0123456789abcdef"]); out["image_set_hex_ok"] = True
except BaseException as e:
    out["image_set_hex_ok"] = repr(e)
# Shading table dump
t0 = time.perf_counter(); sh = Shading(pyxel.colors); out["shading_build_ms"] = (time.perf_counter() - t0) * 1000
out["LEVEL_COUNT"] = Shading.LEVEL_COUNT
out["direction_default"] = [sh.direction.x, sh.direction.y, sh.direction.z]
table = {i: [list(sh[i, l]) for l in range(8)] for i in range(32)}
out["table_evening"] = table
# quality metrics: flat rows (no change across levels), rows where darkest == base
flat_rows = [i for i in range(32) if len({tuple(e) for e in table[i]}) == 1]
out["rows_all_flat"] = flat_rows
out["distinct_steps_per_color"] = {i: len({tuple(e) for e in table[i]}) for i in range(32)}
out["base_level_is_self"] = {i: table[i][5] == [i, i] for i in range(32)}
# chart: rows = color, cols = level, dithered 8x7 cells
pyxel.cls(0)
for i in range(32):
    col, row = i // 16, i % 16
    for l in range(8):
        a, b = sh[i, l]
        for y in range(13):
            for x in range(17):
                px, py = 20 + col * 160 + l * 17 + x, 8 + row * 14 + y
                pyxel.pset(px, py, a if (px + py) % 2 == 0 else b)
    pyxel.text(4 + col * 160, 12 + row * 14, f"{i:2d}", 5)
pyxel.screen.save("out/e02_shading_chart_evening.png", 3)
# manual edit + build() resets
sh[C.RED, 0] = (C.BLUE, C.BLUE); out["setitem_readback"] = list(sh[C.RED, 0])
sh.build(pyxel.colors); out["after_build_reset"] = list(sh[C.RED, 0])
try:
    sh[40, 0]; out["index_oob"] = "no error"
except BaseException as e:
    out["index_oob"] = type(e).__name__ + ": " + str(e)
try:
    sh[C.RED, 8]; out["level_oob"] = "no error"
except BaseException as e:
    out["level_oob"] = type(e).__name__ + ": " + str(e)

# ---- textured faces get shading? draw a textured box (single-color texture using color 20..) and count distinct pairs per face
tex = pyxel.Image(4, 4); tex.cls(C.BLUE)  # index 23 (>15)
scene = Node(); scene.shading = sh; scene.camera = Camera(); scene.camera.clear_color = 0
scene.camera.transform = Mat4.look_at(Vec3(3, 2.5, 4), Vec3(0, 0, 0))
mode = {"m": "tex"}
class T(Node):
    def on_draw(self):
        if mode["m"] == "tex": self.box(Mat4.IDENTITY, Vec3(2, 2, 2), tex)
        elif mode["m"] == "flat": self.box(Mat4.IDENTITY, Vec3(2, 2, 2), C.BLUE)
        elif mode["m"] == "tex_unshaded":
            self.shaded(False); self.box(Mat4.IDENTITY, Vec3(2, 2, 2), tex)
t = T(); scene.add_child(t)
def hist():
    h = {}
    for y in range(0, 240):
        for x in range(0, 320):
            c = pyxel.pget(x, y); h[c] = h.get(c, 0) + 1
    return dict(sorted(h.items()))
for m in ("tex", "flat", "tex_unshaded"):
    mode["m"] = m; scene.draw(0, 0, 320, 240); out["hist_box_" + m] = hist()
    pyxel.screen.save(f"out/e02_box_{m}.png", 2)
# ---- does pyxel.pal affect Cube?
mode["m"] = "flat"; pyxel.pal(C.BLUE, C.RED); scene.draw(0, 0, 320, 240); out["hist_flat_with_pal(BLUE->RED)"] = hist()
mode["m"] = "tex"; scene.draw(0, 0, 320, 240); out["hist_tex_with_pal(BLUE->RED)"] = hist()
pyxel.pal()
# target image with its own pal
buf = pyxel.Image(320, 240); buf.pal(C.BLUE, C.RED); mode["m"] = "flat"; scene.draw(0, 0, 320, 240, buf)
h = {}
for y in range(240):
    for x in range(320):
        c = buf.pget(x, y); h[c] = h.get(c, 0) + 1
out["hist_target_image_pal"] = dict(sorted(h.items())); buf.pal()
# blt with pal: 2D blt of buffer to screen with pal -> works as usual?
buf.pal(); scene.draw(0, 0, 320, 240, buf); pyxel.pal(C.BLUE, C.RED); pyxel.cls(0); pyxel.blt(0, 0, buf, 0, 0, 320, 240); pyxel.pal(); out["hist_blt_with_pal"] = hist()
# ---- per-node Shading remap for body color variants
sh2 = Shading(pyxel.colors)
for l in range(8):
    a, b = sh2[C.RED, l]; 
    sh2[C.BLUE, l] = sh[C.RED, l]   # BLUE texels now render as the RED ramp
t.shading = sh2; mode["m"] = "tex"; scene.draw(0, 0, 320, 240); out["hist_tex_with_node_shading_remap(BLUE->RED ramp)"] = hist()
pyxel.screen.save("out/e02_box_remap.png", 2)
t.shading = None
# ---- palette swap procedure timing
res = {}
for tod in ("noon", "overcast", "evening"):
    t0 = time.perf_counter(); C.apply_palette(tod, sh); res[tod] = (time.perf_counter() - t0) * 1000
out["apply_palette_ms"] = res
for tod in ("noon", "overcast"):
    C.apply_palette(tod, sh)
    pyxel.cls(0)
    for i in range(32):
        col, row = i // 16, i % 16
        for l in range(8):
            a, b = sh[i, l]
            for y in range(13):
                for x in range(17):
                    px, py = 20 + col * 160 + l * 17 + x, 8 + row * 14 + y
                    pyxel.pset(px, py, a if (px + py) % 2 == 0 else b)
        pyxel.text(4 + col * 160, 12 + row * 14, f"{i:2d}", 5)
    pyxel.screen.save(f"out/e02_shading_chart_{tod}.png", 3)
    out["table_" + tod] = {i: [list(sh[i, l]) for l in range(8)] for i in range(32)}
json.dump(out, open("out/e02_palette.json", "w"), indent=1)
for k, v in out.items():
    if not k.startswith("table_"): print(k, "=", v)
print("TABLE evening:")
for i in range(32): print(i, table[i])
