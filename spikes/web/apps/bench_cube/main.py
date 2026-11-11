import json
import time

import cube_bench
import pyxel

frame = 0
live_scene = None
live_times = []
update_times = []
last_update_t = None


def update():
    global frame, live_scene, last_update_t
    frame += 1
    now = time.perf_counter()
    if last_update_t is not None and frame > 12:
        update_times.append(now - last_update_t)
    last_update_t = now
    if frame == 10:
        res = cube_bench.run_suite(120)
        print("RESULT_JSON cube_batch " + json.dumps(res))
        live_scene, ntri = cube_bench.make_scene(64, True, 6)
        print("LIVE scene tris=%d" % ntri)
    if frame == 10 + 150:
        lt = sorted(live_times)
        ut = sorted(update_times)
        print(
            "RESULT_JSON cube_live "
            + json.dumps(
                {
                    "frames": len(lt),
                    "draw_mean_ms": round(sum(lt) / len(lt) * 1000, 3),
                    "draw_median_ms": round(lt[len(lt) // 2] * 1000, 3),
                    "draw_max_ms": round(lt[-1] * 1000, 3),
                    "update_interval_mean_ms": round(sum(ut) / len(ut) * 1000, 3),
                    "update_interval_median_ms": round(ut[len(ut) // 2] * 1000, 3),
                    "update_interval_max_ms": round(ut[-1] * 1000, 3),
                }
            )
        )
        print("SPIKE_DONE frame=%d" % frame)


def draw():
    if live_scene is None:
        pyxel.cls(0)
        pyxel.text(4, 4, "CUBE BENCH %d" % frame, 7)
        return
    t0 = time.perf_counter()
    cube_bench.set_camera(live_scene, frame)
    live_scene.update()
    live_scene.draw(0, 0, 320, 240)
    live_times.append(time.perf_counter() - t0)
    pyxel.text(4, 4, "8192 TRIS TEXTURED  FRAME %d" % frame, 7)


pyxel.init(320, 240, title="bench_cube", fps=30)
pyxel.run(update, draw)
