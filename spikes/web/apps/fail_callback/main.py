import js
import pyxel
from pyodide.ffi import create_proxy

frame = 0
keep = []


def bad_callback():
    raise KeyError("boom inside a JS-called Python callback")


def update():
    global frame
    frame += 1
    if frame == 10:
        p = create_proxy(bad_callback)
        keep.append(p)
        js.setTimeout(p, 10)
    if frame == 60:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "FRAME %d" % frame, 7)


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)

