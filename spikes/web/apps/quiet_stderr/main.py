import sys
import warnings

import pyxel

frame = 0


def update():
    global frame
    frame += 1
    if frame == 10:
        print("this line goes to stderr and has no Traceback header", file=sys.stderr)
        warnings.warn("a warning on stderr")
    if frame == 30:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "FRAME %d" % frame, 7)


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)

