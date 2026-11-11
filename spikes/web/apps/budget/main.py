"""Integrated frame budget in the browser: fps=60, each update() runs the representative
6-car physics tick `mult` times (mult=10 stands in for a model + AI ten times heavier),
draw() renders the 8,192-triangle textured scene on every 2nd call (30 fps rendering).

URL hash: #mult=1&n=900&render=2   (render=1 draws every call, 2 every 2nd call)
"""

import json
import time

import bench_core
import cube_bench
import js
import pyxel

params = {"mult": 1, "n": 900, "render": 2}
for part in str(js.location.hash).lstrip("#").split("&"):
    if "=" in part:
        k, v = part.split("=", 1)
        params[k] = int(v)

perf = time.perf_counter
fleet = [bench_core.Car(i) for i in range(6)]
DT = 1.0 / 60.0
tick = 0
update_ms = []
draw_ms = []
update_at = []
scene = None
draw_calls = 0
done = False


def stats(xs):
    s = sorted(xs)
    n = len(s)
    return {"n": n, "mean": round(sum(s) / n, 3), "median": round(s[n // 2], 3), "p95": round(s[int(n * 0.95)], 3), "max": round(s[-1], 3)}


def update():
    global tick, scene, done
    t0 = perf()
    if scene is None:
        scene, _ = cube_bench.make_scene(64, True, 6)
        return
    for _ in range(params["mult"]):
        for c in fleet:
            bench_core.car_tick(c, DT, tick)
    tick += 1
    t1 = perf()
    if tick > 60 and not done:
        update_ms.append((t1 - t0) * 1000)
        update_at.append(t0)
        if len(update_ms) >= params["n"]:
            done = True
            span = update_at[-1] - update_at[0]
            res = {
                "params": params,
                "updates_per_s": round((len(update_at) - 1) / span, 2),
                "renders_per_s": round(len(draw_ms) / span, 2),
                "update_ms": stats(update_ms),
                "render_ms": stats(draw_ms),
                "first_60_ticks_excluded": True,
            }
            print("RESULT_JSON budget " + json.dumps(res))
            print("SPIKE_DONE")


def draw():
    global draw_calls
    draw_calls += 1
    if scene is None or draw_calls % params["render"]:
        return
    t0 = perf()
    cube_bench.set_camera(scene, tick * 0.5)
    scene.update()
    scene.draw(0, 0, 320, 240)
    pyxel.text(4, 4, "BUDGET mult=%d tick=%d" % (params["mult"], tick), 7)
    pyxel.text(4, 12, "SPD %3d RPM %4d" % (fleet[0].vx * 3.6, fleet[0].rpm), 10)
    if tick > 60 and not done:
        draw_ms.append((perf() - t0) * 1000)


pyxel.init(320, 240, title="budget", fps=60)
pyxel.run(update, draw)
