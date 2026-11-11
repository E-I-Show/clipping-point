import pyxel

frame = 0
errors = 0


def update():
    global frame, errors
    frame += 1
    try:
        if frame == 10:
            raise ValueError("the game catches this itself")
    except ValueError:
        errors += 1
    if frame == 30:
        print("SPIKE_DONE errors=%d" % errors)


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "FRAME %d" % frame, 7)


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)

