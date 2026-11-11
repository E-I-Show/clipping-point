"""E9: Pyxel draws its own overlays (perf monitor, mouse cursor) INTO pyxel.screen after draw().
If draw() skips repainting on alternate frames, do those overlays smear? And does a back-buffer blit fix it?
Usage: e09_overlay_smear.py MODE   (MODE: skip | backbuffer)"""
import os
import sys
import time

import pyxel

mode = sys.argv[1]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
pyxel.init(320, 240, fps=1000, capture_sec=0, headless=True)
pyxel.mouse(True)
pyxel.perf_monitor(True)
back = pyxel.Image(320, 240)

nonbg_counts = []
for i in range(40):
    pyxel.set_mouse_pos(20 + i * 6, 120)
    render = i % 2 == 0
    if mode == "skip":
        if render:
            pyxel.cls(1)
    else:
        if render:
            back.cls(1)  # the expensive scene render would go here, into the back buffer
        pyxel.blt(0, 0, back, 0, 0, 320, 240)  # every frame: cheap full repaint
    pyxel.flip()  # finish_draw_frame draws perf monitor + cursor into pyxel.screen
    # count pixels on the cursor row band that are not background
    cnt = sum(1 for x in range(320) for y in range(118, 130) if pyxel.pget(x, y) != 1)
    nonbg_counts.append(cnt)
pyxel.screen.save(os.path.join(out, f"e09_{mode}.png"), 2)
print(f"mode={mode}: non-background pixels in cursor band after each frame: {nonbg_counts[:12]} ... max={max(nonbg_counts)}")

# cost of the per-frame blit
t0 = time.perf_counter()
N = 2000
for _ in range(N):
    pyxel.blt(0, 0, back, 0, 0, 320, 240)
dt = (time.perf_counter() - t0) / N
print(f"pyxel.blt 320x240 Image->screen: {dt * 1e6:.1f} us per call (native, {N} calls)")
