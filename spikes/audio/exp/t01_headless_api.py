"""Headless smoke: call every audio API we plan to use and record what happens."""
import json
import sys
import time
from pathlib import Path

import pyxel

HERE = Path(__file__).resolve().parent
res = {"steps": []}


def step(name, fn):
    try:
        out = fn()
        res["steps"].append({"name": name, "ok": True, "out": repr(out)[:200]})
    except BaseException as e:  # PanicException derives from BaseException
        res["steps"].append({"name": name, "ok": False, "err": f"{type(e).__name__}: {e}"})


pyxel.init(64, 64, fps=1000, headless=True, quit_key=pyxel.KEY_NONE)
res["num"] = dict(ch=pyxel.NUM_CHANNELS, tones=pyxel.NUM_TONES, sounds=pyxel.NUM_SOUNDS, musics=pyxel.NUM_MUSICS)
res["len"] = dict(ch=len(pyxel.channels), tones=len(pyxel.tones), sounds=len(pyxel.sounds), musics=len(pyxel.musics))
res["default_gain"] = [c.gain for c in pyxel.channels]
res["default_detune"] = [c.detune for c in pyxel.channels]
res["default_tones"] = [dict(mode=t.mode, bits=t.sample_bits, wt=list(t.wavetable), gain=t.gain) for t in pyxel.tones]

step("sounds[0].set", lambda: pyxel.sounds[0].set("c2e2g2c3", "s", "7", "n", 20))
step("play(0, 0, loop=True)", lambda: pyxel.play(0, 0, loop=True))
step("play_pos(0) right after", lambda: pyxel.play_pos(0))
step("channels[0].detune = 700", lambda: setattr(pyxel.channels[0], "detune", 700))
step("channels[0].detune = -2400", lambda: setattr(pyxel.channels[0], "detune", -2400))
step("channels[0].detune = 1e6", lambda: setattr(pyxel.channels[0], "detune", 1000000))
step("channels[0].detune = 12.5 (float)", lambda: setattr(pyxel.channels[0], "detune", 12.5))
step("channels[0].gain = 0.0", lambda: setattr(pyxel.channels[0], "gain", 0.0))
step("channels[0].gain = 2.0", lambda: setattr(pyxel.channels[0], "gain", 2.0))
step("channels[0].gain = -1.0", lambda: setattr(pyxel.channels[0], "gain", -1.0))
step("play MML str", lambda: pyxel.play(2, "T120 @1 O4 L16 V100 CEG>C"))
step("channels[1].play(Sound obj)", lambda: pyxel.channels[1].play(pyxel.sounds[0], loop=True))
step("play with resume", lambda: pyxel.play(1, "T200 @3 O2 L32 C", resume=True))
step("play bad MML", lambda: pyxel.play(2, "T120 @1 O4 L16 Z!!"))
step("play ch=7 (out of range)", lambda: pyxel.play(7, 0))
step("play snd=99 (out of range)", lambda: pyxel.play(0, 99))
step("musics[0].set", lambda: pyxel.musics[0].set([0], [0], [], []))
step("playm(0, loop=True)", lambda: pyxel.playm(0, loop=True))
step("stop(3)", lambda: pyxel.stop(3))
step("stop()", lambda: pyxel.stop())
step("gen_bgm", lambda: [len(s) for s in pyxel.gen_bgm(0, 0, 3, 1234)])
step("gen_bgm play=True", lambda: [len(s) for s in pyxel.gen_bgm(6, 0, 0, 7, play=True)])
step("total_sec", lambda: pyxel.sounds[0].total_sec())
step("Sound.save", lambda: pyxel.sounds[0].save(str(HERE / "out_t01_sound.wav"), 1.0))
step("Music.save", lambda: pyxel.musics[0].save(str(HERE / "out_t01_music.wav"), 1.0))

# does playback position advance in headless (no audio device)?
pyxel.stop()
pyxel.play(0, 0, loop=True)
pos = []
t0 = time.perf_counter()
for i in range(300):
    pyxel.flip()
    if i % 60 == 0:
        pos.append((round(time.perf_counter() - t0, 3), pyxel.play_pos(0)))
res["play_pos_over_flips"] = repr(pos)
t0 = time.perf_counter()
time.sleep(0.5)
res["play_pos_after_sleep_0.5"] = repr(pyxel.play_pos(0))

# cost of the per-tick writes
ch = pyxel.channels[0]
t0 = time.perf_counter()
for i in range(100000):
    ch.detune = i & 1023
    ch.gain = 0.1
res["us_per_detune_gain_write_pair"] = (time.perf_counter() - t0) / 100000 * 1e6
t0 = time.perf_counter()
for i in range(100000):
    c = pyxel.channels[0]
res["us_per_pyxel_channels_index"] = (time.perf_counter() - t0) / 100000 * 1e6

(HERE / "out_t01.json").write_text(json.dumps(res, indent=1))
bad = [s for s in res["steps"] if not s["ok"]]
print(json.dumps(res, indent=1))
sys.exit(0)
