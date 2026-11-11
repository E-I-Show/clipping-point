# Render spike app: same prototype scene, measured inside the Pyxel loop.
# Browser: pyxel.run. Native: headless flip loop. 3D + HUD go to a back buffer, then blt.
import json
import math
import sys
import time

import pyxel

import common as C
from world import H, W, World

WEB = sys.platform == "emscripten"
N = 90  # measured draws per case
PER_FRAME = 6

t_boot = time.perf_counter()
pyxel.init(W, H, title="CLIPPING POINT render spike", fps=60, quit_key=pyxel.KEY_NONE, headless=not WEB)
t0 = time.perf_counter()
world = World("evening", mode="sections")
t_world = (time.perf_counter() - t0) * 1000

x, z, h = world.place_cars(8.0)
CAMS = {
    "chase": world.cam_chase(x, z, h),
    "bumper": world.cam_bumper(x, z, h),
    "tv_tele": world.cam_tv(*world.track_pose(world.car_s[2], 0.0), post_s=27.5, side=-1),
    "tv_wide": world.cam_tv(*world.track_pose(world.car_s[2], 0.0), post_s=13.0, side=-1, height=6.0, frame_m=16.0),
}
CASES = []
for order in ("ground_first", "ground_last"):
    for cull in (1, 0):
        for cam in CAMS:
            CASES.append((order, cull, cam))
results = {}
state = {"case": 0, "times": [], "done": False, "frames": 0, "moving": []}


def stats(ts):
    ts = sorted(ts)
    return {"median_ms": round(ts[len(ts) // 2], 3), "p95_ms": round(ts[int(len(ts) * 0.95)], 3), "max_ms": round(ts[-1], 3)}


def full_frame(label):
    world.draw_scene()
    world.draw_hud(label)


def update():
    state["frames"] += 1


def draw():
    if not state["done"]:
        order, cull, cam = CASES[state["case"]]
        if not state["times"]:
            if order == "ground_last" and world.root.children[0] is world.ground:
                world.root.remove_child(world.ground)
                world.root.add_child(world.ground)
            world.culling = bool(cull)
            world.cars[0].visible = cam != "bumper"
            world.set_camera(*CAMS[cam])
        for _ in range(PER_FRAME):
            t = time.perf_counter()
            full_frame(cam.upper())
            state["times"].append((time.perf_counter() - t) * 1000)
        if len(state["times"]) >= N:
            results[f"{order}/cull{cull}/{cam}"] = stats(state["times"][6:])
            state["times"] = []
            state["case"] += 1
            if state["case"] >= len(CASES):
                # moving camera along the track (chase), 120 frames: per-frame cost incl. python-side pose updates
                world.culling = True
                world.cars[0].visible = True
                mv = []
                for k in range(120):
                    t = time.perf_counter()
                    px, pz, ph = world.place_cars(8.0 + k * 0.27)   # 1.38 m per frame = 150 km/h at 30 fps
                    world.set_camera(*world.cam_chase(px, pz, ph))
                    full_frame("CHASE")
                    mv.append((time.perf_counter() - t) * 1000)
                results["moving_chase_full_frame(update poses+visibility+bg+3d+hud)"] = stats(mv)
                px, pz, ph = world.place_cars(8.0)
                world.set_camera(*world.cam_chase(px, pz, ph))
                full_frame("CHASE")
                out = {"platform": sys.platform, "python": sys.version.split()[0], "N": N - 6, "world_build_ms": round(t_world, 1),
                       "tris": world.tri, "results": results}
                print("RESULT " + json.dumps(out))
                print("SPIKE_DONE")
                state["done"] = True
    pyxel.blt(0, 0, world.buf, 0, 0, W, H)


if WEB:
    pyxel.run(update, draw)
else:
    while not state["done"]:
        update()
        draw()
        pyxel.flip()
    pyxel.screen.save("native_final.png", 2)
    sys.exit(0)
