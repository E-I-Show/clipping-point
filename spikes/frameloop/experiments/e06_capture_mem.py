"""E6: memory growth of the built-in screencast ring buffer (fps * capture_sec screens) in headless runs.
Usage: e06_capture_mem.py FPS CAPTURE_SEC NFRAMES"""
import resource
import sys
import time

import pyxel

fps, cap, n = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
pyxel.init(320, 240, fps=fps, capture_sec=cap, headless=True)
rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
t0 = time.perf_counter()
for i in range(n):
    pyxel.cls(i % 16)
    pyxel.flip()
wall = time.perf_counter() - t0
rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"fps={fps} capture_sec={cap} frames={n}: wall={wall:.2f}s ({n/wall:.0f} frames/s) maxrss {rss0/1024:.0f} MB -> {rss1/1024:.0f} MB (+{(rss1-rss0)/1024:.0f} MB)")
