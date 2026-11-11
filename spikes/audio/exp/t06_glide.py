"""Glide vs no glide for the 1-note loop; note length 1/60 s vs 3/60 s; ramp 1200 cents/s. Disk-driver capture.

Run:  SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=$PWD/out_t06.raw python3 t06_glide.py
"""
import json
import sys
import time
from pathlib import Path

import pyxel

HERE = Path(__file__).resolve().parent
pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
T0 = time.perf_counter()
log = {"segments": []}
ch = pyxel.channels[0]
ch.gain = 0.3


def now():
    return time.perf_counter() - T0


def frames(n, fn=None, seg=None):
    for i in range(n):
        if fn:
            seg["cmd"].append((round(now(), 4), fn(i)))
        pyxel.flip()


VARIANTS = {  # all use the default triangle (@0) at O3 C = 130.81 Hz
    "A_noglide_1over60": "T600 Q100 @0 V127 O3 L24 C",
    "B_glide_1over60": "T600 Q100 @0 V127 @GLI1{*,*} O3 L24 C",
    "C_glide_3over60": "T600 Q100 @0 V127 @GLI1{*,*} O3 L8 C",
    "D_legacy_slide_speed2": None,  # Sound.set("c1","t","7","s",2)
}
pyxel.stop()
frames(30)
seg = dict(name="marker", t0=round(now(), 4), cmd=[])
log["segments"].append(seg)
pyxel.play(0, "T120 Q100 @1 V127 O7 C16")
frames(12)
pyxel.stop()
frames(18)

for name, mml in VARIANTS.items():
    snd = pyxel.Sound()
    if mml:
        snd.mml(mml)
    else:
        snd.set("c1", "t", "7", "s", 2)
    seg = dict(name=name, t0=round(now(), 4), cmd=[], base_hz=130.81)
    log["segments"].append(seg)
    ch.detune = 0
    ch.play(snd, loop=True)

    def ramp(i):
        ch.detune = int(2400 * min(max(i - 20, 0), 120) / 120)  # 20 frames flat, 2 s ramp, then hold
        return ch.detune

    frames(170, ramp, seg)
    seg["t1"] = round(now(), 4)
    pyxel.stop()
    frames(18)

(HERE / "out_t06_log.json").write_text(json.dumps(log))
print("DONE", round(now(), 2))
sys.exit(0)
