import json

import bench_core
import pyxel

frame = 0


def update():
    global frame
    frame += 1
    if frame == 5:
        print("RESULT_JSON libm_dump " + json.dumps(bench_core.libm_dump()))
    if frame == 7:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(0)


pyxel.init(160, 120, title="libm_dump", fps=30)
pyxel.run(update, draw)
