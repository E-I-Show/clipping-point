"""E5: own loop without pyxel.run. Usage: e05_manual_loop.py FPS NFRAMES MODE
MODE: flip   -> update(); draw(); pyxel.flip() each frame
      noflip -> update(); draw() only (never call flip)
"""
import sys
import time

import pyxel

fps = int(sys.argv[1])
n = int(sys.argv[2])
mode = sys.argv[3]

pyxel.init(320, 240, fps=fps, headless=True)
K = pyxel.KEY_SPACE
btnp_frames = []
fc_seen = []
t0 = time.perf_counter()
for i in range(n):
    if i == 3:
        pyxel.set_btn(K, True)
    if i == 6:
        pyxel.set_btn(K, False)
    # "update"
    if pyxel.btnp(K):
        btnp_frames.append(i)
    fc_seen.append(pyxel.frame_count)
    # "draw"
    pyxel.cls(i % 16)
    pyxel.text(4, 4, f"FRAME {i}", 7)
    if mode == "flip":
        pyxel.flip()
wall = time.perf_counter() - t0
print(
    f"mode={mode} fps={fps} frames={n} wall={wall:.3f}s -> {n / wall:.0f} frames/s; "
    f"frame_count first/last={fc_seen[0]}/{fc_seen[-1]}; btnp true at loop index {btnp_frames}; btn now={pyxel.btn(K)}"
)
print("reached end of script normally (no pyxel.quit needed)")
