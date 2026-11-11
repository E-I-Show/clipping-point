"""pyxel.screenshot / pyxel.screencast in the browser: do they download, how long do they block?

URL hash: #scale=1 (GIF scale; 0 = Pyxel default capture_scale)  #fps=60
"""

import json
import time

import cube_bench
import js
import pyxel

params = {"scale": 1, "fps": 60, "at": 660}
for part in str(js.location.hash).lstrip("#").split("&"):
    if "=" in part:
        k, v = part.split("=", 1)
        params[k] = int(v)

frame = 0
scene = None


def update():
    global frame, scene
    frame += 1
    if scene is None:
        scene, _ = cube_bench.make_scene(45, True, 6)
    if frame == params["at"]:
        t0 = time.perf_counter()
        pyxel.screenshot("cap_shot", 1)
        t1 = time.perf_counter()
        if params["scale"]:
            pyxel.screencast("cap_cast", params["scale"])
        else:
            pyxel.screencast("cap_cast")
        t2 = time.perf_counter()
        print("RESULT_JSON capture " + json.dumps({"params": params, "screenshot_ms": round((t1 - t0) * 1000, 1), "screencast_ms": round((t2 - t1) * 1000, 1)}))
    if frame == params["at"] + 60:
        print("SPIKE_DONE")


def draw():
    if scene is None or frame % 2:
        return
    cube_bench.set_camera(scene, frame * 0.5)
    scene.update()
    scene.draw(0, 0, 320, 240)
    pyxel.text(4, 4, "CAPTURE FRAME %d" % frame, 7)


pyxel.init(320, 240, title="capture", fps=params["fps"])
pyxel.run(update, draw)
