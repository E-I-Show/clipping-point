import sys

import pyxel

frame = 0


def update():
    global frame
    frame += 1
    if frame == 1:
        print("HELLO sys.platform=%s version=%s impl=%s" % (sys.platform, sys.version.split()[0], sys.implementation.name))
        print("HELLO pyxel.VERSION=%s" % pyxel.VERSION)
    if frame == 30:
        print("SPIKE_DONE frame=%d" % frame)


def draw():
    pyxel.cls(1)
    pyxel.text(8, 8, "CLIPPING POINT WEB SPIKE", 7)
    pyxel.text(8, 20, "FRAME %d" % frame, 10)
    pyxel.rect(8, 40, 40, 20, 8)
    pyxel.circ(100, 70, 20, 11)


pyxel.init(160, 120, title="hello", fps=30)
pyxel.run(update, draw)
