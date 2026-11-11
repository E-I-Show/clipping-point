"""Does the SDL dummy/disk audio driver make the audio callback run in headless mode?"""
import os, sys, time
import pyxel
pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
pyxel.sounds[0].set("a2a2a2a2", "s", "7", "n", 30)
pyxel.play(0, 0, loop=True)
out = []
t0 = time.perf_counter()
for i in range(40):
    pyxel.flip()
    if i % 10 == 9:
        out.append((round(time.perf_counter() - t0, 3), pyxel.play_pos(0)))
print("DRIVER", os.environ.get("SDL_AUDIODRIVER"), out)
sys.exit(0)
