import sys, time
from pathlib import Path
import pyxel
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "proto"))
import audio_iface as ai
pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
from pyxel_audio import PyxelAudio
a = PyxelAudio(8)
f = ai.AudioFrame(scene=ai.Scene.RACE, player=ai.CarAudio(engine=0, rpm=5000, throttle=0.7, slip=0.5, speed=30),
                  others=[ai.CarAudio(engine=1, rpm=4000, throttle=1, dist=10 + i * 7) for i in range(5)])
a.update(f)
N = 20000
t = time.perf_counter()
for i in range(N):
    f.player.rpm = 3000 + (i % 4000)
    a.update(f)
print("hot loop us/update (race, 5 others):", round((time.perf_counter() - t) / N * 1e6, 2))
sys.exit(0)
