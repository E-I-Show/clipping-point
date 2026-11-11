import json, math, sys, time
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Mesh
import common as C
from world import World, W, H

pyxel.init(W, H, headless=True)
out = {}
def bench(fn, n=200):
    for _ in range(5): fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter() - t0) * 1000)
    ts.sort(); return {"median_ms": round(ts[len(ts) // 2], 3), "p95_ms": round(ts[int(len(ts) * 0.95)], 3)}
def grab(img):
    return [img.pget(x, y) for y in range(H) for x in range(W)]

w = World("evening")
x, z, h = w.place_cars(8.0)
cams = {"chase": w.cam_chase(x, z, h), "bumper": w.cam_bumper(x, z, h),
        "tv_wide": w.cam_tv(*w.track_pose(w.car_s[2], 0.0), post_s=13.0, side=-1, height=6.0, frame_m=16.0)}

# ---- 1. brake lamp by rewriting the swatch texel of the car texture at runtime
car = w.cars[0]; tex = car.model  # texture image is held by the mesh; keep our own reference instead
tex0 = C.make_car_texture(C.RED); car2 = C.Car(tex0); w.root.add_child(car2); car2.set_pose(x - 3 * math.cos(h), 0, z - 3 * math.sin(h), h)
w.cars[0].visible = False
w.set_camera(*cams["chase"])
i = C.SW["tail"]
res = {}
for label, col in (("on", C.BRAKE), ("off", C.RED_D)):
    tex0.rect((i % 8) * 4, (i // 8) * 4, 4, 4, col)
    w.draw_scene(); px = grab(w.buf)
    res[label] = {"BRAKE_px": px.count(C.BRAKE), "RED_D_px": px.count(C.RED_D)}
    pyxel.blt(0, 0, w.buf, 0, 0, W, H); pyxel.screen.save(f"out/e06_brake_{label}.png", 2)
out["brake_lamp_texel_rewrite"] = res
car2.visible = False; w.cars[0].visible = True

# ---- 2. z-fighting between ground plane and track (coplanar-ish, gap below track)
res = {}
for gap in (0.05, 0.02, 0.2):
    w.root.remove_child(w.ground)
    gb = C.build_ground(tile=50.0, y=-gap)
    w.ground = Node.from_mesh(Mesh([gb.primitive()], [Mat4.IDENTITY], [-1], ["ground"], w.atlas)); w.root.add_child(w.ground)
    for near in (0.3, 0.1):
        w.camera.near = near
        for name, cam in cams.items():
            w.set_camera(*cam)
            for n in w.cars + [w.sprites, w.props]: n.visible = False
            w.ground.visible = False; w.buf.cls(C.PINK); w.draw_3d_only(); a = grab(w.buf)
            w.ground.visible = True; w.buf.cls(C.PINK); w.draw_3d_only(); b = grab(w.buf)
            cover = sum(1 for p in a if p != C.PINK)
            bad = sum(1 for p, q in zip(a, b) if p != C.PINK and p != q)
            res[f"gap{gap}_near{near}_{name}"] = {"track_px": cover, "px_where_ground_wins": bad}
            for n in w.cars + [w.sprites, w.props]: n.visible = True
w.camera.near = 0.3
out["zfight_ground_vs_track"] = res

# ---- 3. distant texture shimmer: fraction of far-road pixels that change when the camera advances 1.38 m
def shimmer(world, label):
    r = {}
    for n in world.cars + [world.sprites, world.props]: n.visible = False
    frames = []
    for k in range(4):
        px, pz, ph = world.track_pose(8.0 + k * 0.27, 1.2)
        world.set_camera(*world.cam_bumper(px, pz, ph)); world.buf.cls(C.PINK); world.draw_3d_only(); frames.append(grab(world.buf))
    # rows just below the horizon (y 121..135 at 2x = distant ground 15..150 m for h=0.62)
    for y0, y1, name in ((121, 126, "rows121-125(dist>~40m)"), (126, 136, "rows126-135(~13-40m)"), (136, 170, "rows136-169(~4-13m)")):
        tot = ch = 0
        for a, b in zip(frames, frames[1:]):
            for y in range(y0, y1):
                for xx in range(W):
                    tot += 1; ch += a[y * W + xx] != b[y * W + xx]
        r[name] = round(ch / tot, 3)
    for n in world.cars + [world.sprites, world.props]: n.visible = True
    return r
out["shimmer_changed_fraction_noise_textures"] = shimmer(w, "noise")
# flat variant: overwrite atlas road/grass/sand rects with flat colors (lines kept) = what a far LOD texture would look like
x0, y0, ww, hh = C.RECT["road"]
for yy in range(hh):
    for xx in range(ww):
        if w.atlas.pget(x0 + xx, y0 + yy) != C.WHITE: w.atlas.pset(x0 + xx, y0 + yy, C.ASPH_M)
for name, col in (("grass", C.GRASS_M), ("sand", C.SAND_L)):
    x0, y0, ww, hh = C.RECT[name]; w.atlas.rect(x0, y0, ww, hh, col)
out["shimmer_changed_fraction_flat_textures"] = shimmer(w, "flat")
w.set_camera(*cams["bumper"]); w.cars[0].visible = False; w.draw_scene(); w.draw_hud("FLAT TEX"); pyxel.blt(0, 0, w.buf, 0, 0, W, H); pyxel.screen.save("out/e06_flat_textures_bumper.png", 2)
w.cars[0].visible = True

# ---- 4. far cut look + dither fade of far sections
w2 = World("evening")
x, z, h = w2.place_cars(8.0)
for far in (300.0, 120.0):
    w2.camera.far = far
    w2.set_camera(*w2.cam_chase(x, z, h)); w2.draw_scene(); w2.draw_hud(f"FAR {int(far)}"); pyxel.blt(0, 0, w2.buf, 0, 0, W, H); pyxel.screen.save(f"out/e06_far{int(far)}_chase.png", 2)
w2.camera.far = 300.0

# ---- 5. per-color flat primitives vs swatch texture for the car
body = C.build_car_body(); texc = C.make_car_texture(C.RED)
groups = {}
for t in range(body.tri_count):
    u, v = body.uv[t * 6], body.uv[t * 6 + 1]
    col = texc.pget(int(u * 32), int(v * 32))
    groups.setdefault(col, []).extend(body.pos[t * 9:t * 9 + 9])
flat_prims = []
for col, pos in groups.items():
    p = Primitive(Primitive.MODE_TRIANGLES, pos, list(range(len(pos) // 3))); p.compute_normals(); flat_prims.append((col, p))
out["car_flat_groups"] = {str(c): len(p) // 9 for c, p in groups.items()}
tex_body = body.primitive(); wheel = C.build_wheel().primitive()
class FlatCar(Node):
    def on_draw(self):
        for col, p in flat_prims: self.prim(Mat4.IDENTITY, p, col)
        for n in C.WHEEL_NAMES: self.prim(C.wheel_transform(n), wheel, texc)
class TexCarImm(Node):
    def on_draw(self):
        self.prim(Mat4.IDENTITY, tex_body, texc)
        for n in C.WHEEL_NAMES: self.prim(C.wheel_transform(n), wheel, texc)
def car_scene(make):
    root = Node(); root.shading = w.shading; root.camera = Camera(); root.camera.clear_color = C.ASPH_M; root.camera.fov = 40
    root.camera.transform = Mat4.look_at(Vec3(-11, 5.0, 13), Vec3(0, 0.5, 0))
    for i in range(6):
        c = make(); c.transform = C.car_transform((i % 3 - 1) * 5.5, 0, (i // 3 - 0.5) * 6.0, i * 1.0); root.add_child(c)
    return root
rf = car_scene(FlatCar); rt = car_scene(TexCarImm); rr = car_scene(lambda: C.Car(texc, shadow=False))
out["car6_draw_ms"] = {"flat_per_color_prims(immediate)": bench(lambda: rf.draw(0, 0, W, H)), "swatch_texture(immediate prim)": bench(lambda: rt.draw(0, 0, W, H)), "swatch_texture(retained Node.from_mesh)": bench(lambda: rr.draw(0, 0, W, H))}
rf.draw(0, 0, W, H); a = grab(pyxel.screen); rt.draw(0, 0, W, H); b = grab(pyxel.screen)
out["car_flat_vs_texture_pixel_diff"] = sum(1 for p, q in zip(a, b) if p != q)

# ---- 6. GLB probe (example asset): what from_glb gives with a custom 32-color palette
import os
glb = "/usr/local/lib/python3.13/site-packages/pyxel/examples/cube/assets/garden_coin.glb"
m = Mesh.from_glb(glb)
info = {"primitives": len(m.primitives), "names": list(m.names)[:6], "col_img_type": type(m.col_img).__name__, "motions": len(m.motions)}
if not isinstance(m.col_img, int):
    im = m.col_img; info["tex_size"] = [im.width, im.height]
    hist = {}
    for yy in range(im.height):
        for xx in range(im.width):
            c = im.pget(xx, yy); hist[c] = hist.get(c, 0) + 1
    info["tex_index_hist_with_32color_evening_palette"] = dict(sorted(hist.items()))
info["tris"] = sum(len(p.indices) // 3 for p in m.primitives if p is not None)
info["has_normals"] = [len(p.normals) for p in m.primitives if p is not None][:3]
out["glb_probe_garden_coin"] = info
json.dump(out, open("out/e06_misc.json", "w"), indent=1)
for k, v in out.items(): print(k, "=", json.dumps(v))
