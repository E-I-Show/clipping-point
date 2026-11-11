"""E7: built-in screencast GIF timing. Usage: e07_gif.py FPS RENDER_EVERY SECONDS OUT.gif"""
import os
import sys
import time

import pyxel

fps, every, secs, out = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), os.path.abspath(sys.argv[4])
pyxel.init(320, 240, fps=fps, capture_sec=10, headless=True)
n = int(fps * secs)
for i in range(n):
    if i % every == 0:
        pyxel.cls(1)
        pyxel.rect(i % 300, 100, 20, 20, 8 + (i // every) % 7)
        pyxel.text(4, 4, f"T={i / fps:5.2f}", 7)
    pyxel.flip()
t0 = time.perf_counter()
pyxel.screencast(out, 1)
enc = time.perf_counter() - t0
from PIL import Image

im = Image.open(out)
durs = []
try:
    while True:
        durs.append(im.info.get("duration", 0))
        im.seek(im.tell() + 1)
except EOFError:
    pass
hist = {}
for d in durs:
    hist[d] = hist.get(d, 0) + 1
print(
    f"fps={fps} render_every={every} recorded={secs}s: gif frames={len(durs)} durations(ms)->count={hist} "
    f"total playback={sum(durs)/1000:.2f}s size={os.path.getsize(out)/1024:.0f} KB encode={enc*1000:.0f} ms"
)
