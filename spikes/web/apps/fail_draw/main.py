import pyxel

frame = 0


def update():
    global frame
    frame += 1
    if frame == 40:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    if frame == 20:
        raise ValueError("boom in draw at frame 20")


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)
