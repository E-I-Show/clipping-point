import asyncio

import pyxel

frame = 0
tasks = []


async def bad_task():
    await asyncio.sleep(0.05)
    raise KeyError("boom inside an asyncio task")


def update():
    global frame
    frame += 1
    if frame == 10:
        tasks.append(asyncio.ensure_future(bad_task()))
    if frame == 60:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "FRAME %d" % frame, 7)


pyxel.init(160, 120, title="failtest", fps=30)
pyxel.run(update, draw)

