import json, math, sys, time, statistics
import pyxel
from pyxel.cube import Vec3, Mat4
import common as C
import world as WM
from world import World, W, H

pyxel.init(W, H, headless=True)
N = 200
def bench(fn, n=N):
    for _ in range(5): fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return {"median_ms": round(ts[len(ts) // 2], 3), "p95_ms": round(ts[int(len(ts) * 0.95)], 3), "max_ms": round(ts[-1], 3)}

out = {"N": N}
def cams(w):
    x, z, h = w.place_cars(8.0)
    return {"chase": w.cam_chase(x, z, h), "bumper": w.cam_bumper(x, z, h),
            "tv_tele": w.cam_tv(*w.track_pose(w.car_s[2], 0.0), post_s=27.5, side=-1),
            "tv_wide": w.cam_tv(*w.track_pose(w.car_s[2], 0.0), post_s=13.0, side=-1, height=6.0, frame_m=16.0),
            "look_away_up": (Vec3(x, 2.0, z), Vec3(x, 500.0, z + 1.0), 58.0)}

for mode in ("sections", "merged", "immediate"):
    w = World("evening", mode=mode)
    cs = cams(w)
    res = {"tris": dict(w.tri)}
    for culling in ((True, False) if mode != "merged" else (False,)):
        w.culling = culling
        for name, (eye, tgt, fov) in cs.items():
            w.set_camera(eye, tgt, fov)
            r = bench(w.draw_3d_only)
            r["visible_sections"] = w.visible_sections
            res[f"{name}_cull{int(culling)}"] = r
    out[mode] = res
    if mode == "sections":
        # breakdown at chase cam with culling
        w.culling = True; eye, tgt, fov = cs["chase"]; w.set_camera(eye, tgt, fov)
        bd = {}
        parts = {"ground": [w.ground], "props": [w.props], "sprites": [w.sprites], "cars": w.cars, "track": w.sec_nodes}
        saved = {k: [n.visible for n in v] for k, v in parts.items()}
        for k, v in parts.items():
            for kk, vv in parts.items():
                for i, n in enumerate(vv): n.visible = (kk == k) and saved[kk][i]
            bd[k + "_only"] = bench(w.draw_3d_only)
        for kk, vv in parts.items():
            for i, n in enumerate(vv): n.visible = False
        bd["nothing_visible"] = bench(w.draw_3d_only)
        for kk, vv in parts.items():
            for i, n in enumerate(vv): n.visible = saved[kk][i]
        out["breakdown_chase_sections_cull1"] = bd
        # full frame pieces
        w.set_camera(eye, tgt, fov)
        out["full_frame_chase"] = {
            "background_2d": bench(lambda: C.draw_background(w.buf, w.bg, w.cam_heading, w.cam_pitch_up, fov, W, H)),
            "scene(bg+3d)": bench(w.draw_scene),
            "hud": bench(lambda: w.draw_hud("CHASE")),
            "blt_to_screen": bench(lambda: pyxel.blt(0, 0, w.buf, 0, 0, W, H)),
            "set_pose_6cars+visibility": bench(lambda: (w.place_cars(8.0), w.update_visibility())),
        }
        out["mesh_build_ms"] = {}
        t0 = time.perf_counter(); b = C.build_track_section(w.frames, 0, len(w.frames)); t1 = time.perf_counter(); p = b.primitive(); t2 = time.perf_counter()
        out["mesh_build_ms"]["track_builder_python(3520 tris)"] = round((t1 - t0) * 1000, 2)
        out["mesh_build_ms"]["Primitive()+compute_normals"] = round((t2 - t1) * 1000, 2)
        t0 = time.perf_counter(); C._CAR_PRIMS.clear(); C.car_prims(); out["mesh_build_ms"]["car_prims(body+wheel)"] = round((time.perf_counter() - t0) * 1000, 2)
        t0 = time.perf_counter(); C.make_atlas(); out["mesh_build_ms"]["make_atlas_256x256_pset"] = round((time.perf_counter() - t0) * 1000, 2)
        t0 = time.perf_counter(); C.make_background("evening"); out["mesh_build_ms"]["make_background_640x240_pset"] = round((time.perf_counter() - t0) * 1000, 2)

# heavier variant: finer road (4 across, i.e. 3 m wide quads) + small ground tiles
w = World("evening", mode="sections", across=4, ground_tile=25.0)
cs = cams(w)
res = {"tris": dict(w.tri)}
for culling in (True, False):
    w.culling = culling
    for name in ("chase", "bumper", "tv_wide"):
        eye, tgt, fov = cs[name]; w.set_camera(eye, tgt, fov); res[f"{name}_cull{int(culling)}"] = bench(w.draw_3d_only)
out["sections_across4_ground25"] = res
json.dump(out, open("out/e05_perf_native.json", "w"), indent=1)
print(json.dumps(out, indent=1))
