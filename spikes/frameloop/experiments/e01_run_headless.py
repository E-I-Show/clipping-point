"""E1: headless pyxel.run basics. Usage: e01_run_headless.py FPS NFRAMES [mode]
mode: quit (pyxel.quit in update) | sysexit3 (sys.exit(3) in update) | raise_update | raise_draw
"""
import sys
import time

import pyxel

fps = int(sys.argv[1])
n = int(sys.argv[2])
mode = sys.argv[3] if len(sys.argv) > 3 else "quit"

updates = 0
draws = 0
t0 = None


def update():
    global updates, t0
    if t0 is None:
        t0 = time.perf_counter()
    updates += 1
    if updates >= n:
        dt = time.perf_counter() - t0
        print(
            f"fps={fps} updates={updates} draws={draws} frame_count={pyxel.frame_count} "
            f"wall={dt:.3f}s -> {(updates - 1) / dt:.1f} updates/s"
        )
        if mode == "quit":
            pyxel.quit()
        elif mode == "sysexit3":
            sys.exit(3)
        elif mode == "raise_update":
            raise RuntimeError("boom in update")
    if mode == "raise_draw" and updates >= n:
        pass


def draw():
    global draws
    draws += 1
    if mode == "raise_draw" and updates >= n:
        raise RuntimeError("boom in draw")


pyxel.init(320, 240, fps=fps, headless=True)
pyxel.run(update, draw)
print("AFTER RUN (should not be reached if quit exits the process)")
