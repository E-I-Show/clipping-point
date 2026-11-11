import json

import bench_core
import pyxel

frame = 0


def update():
    global frame
    frame += 1
    if frame == 5:
        print("RESULT_JSON libm " + json.dumps(bench_core.libm_probe()))
        print("RESULT_JSON libm_first " + json.dumps(bench_core.libm_first_diffs()))
        print("RESULT_JSON determinism " + json.dumps(bench_core.determinism_run()))
        print("RESULT_JSON determinism_nolibm " + json.dumps(bench_core.determinism_run_nolibm()))
    if frame == 7:
        print("SPIKE_DONE frame=%d" % frame)


def draw():
    pyxel.cls(0)
    pyxel.text(4, 4, "DETERMINISM %d" % frame, 7)


pyxel.init(160, 120, title="determinism", fps=30)
pyxel.run(update, draw)
