import pyxel

frame = 0


def update():
    global frame
    frame += 1  # runs happily but never reports success


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "FRAME %d" % frame, 7)


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)

