import json

import bench_core
import pyxel

frame = 0
status = "WAIT"


def update():
    global frame, status
    frame += 1
    if frame == 10:
        res = bench_core.run_speed_suite(1.0, 5)
        print("RESULT_JSON speed " + json.dumps(res))
        # second pass a few seconds later: has the wasm engine tiered up further?
        res2 = bench_core.run_speed_suite(1.0, 3)
        print("RESULT_JSON speed_second_pass " + json.dumps(res2))
        status = "DONE"
    if frame == 12:
        print("SPIKE_DONE frame=%d" % frame)


def draw():
    pyxel.cls(0)
    pyxel.text(4, 4, "BENCH PY %s %d" % (status, frame), 7)


pyxel.init(160, 120, title="bench_py", fps=30)
pyxel.run(update, draw)
