"""Live capture of the real mixer output via SDL_AUDIODRIVER=disk while Python rewrites detune / gain.

Run:  SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=$PWD/out_t03.raw python3 t03_live.py
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


def now():
    return time.perf_counter() - T0


def frames(n, fn=None, seg=None):
    for i in range(n):
        if fn:
            v = fn(i)
            if seg is not None:
                seg["cmd"].append((round(now(), 4), v))
        pyxel.flip()


def silence(n=18):
    pyxel.stop()
    frames(n)


def begin(name, **kw):
    seg = {"name": name, "t0": round(now(), 4), "cmd": [], **kw}
    log["segments"].append(seg)
    return seg


def end(seg):
    seg["t1"] = round(now(), 4)
    seg["play_pos_end"] = repr(pyxel.play_pos(0))


ch = pyxel.channels[0]
ch.gain = 0.3
ch.detune = 0

# S0 marker: 2093 Hz square beep 0.1 s
silence(30)
seg = begin("S0_marker")
pyxel.play(0, "T120 Q100 @1 V127 O7 C16")  # 0.125 s
frames(12)
end(seg)
silence()

# S1: one long sustained note, detune ramp 0..1200 per frame
LONG = pyxel.Sound()
LONG.mml("T60 Q100 @0 V127 O3 C1&C1&C1&C1")  # C3 = 130.81 Hz, 16 s as ONE note
seg = begin("S1_sustained_detune_ramp", base_hz=130.81)
ch.detune = 0
ch.play(LONG)


def s1(i):
    ch.detune = int(1200 * i / 89)
    return ch.detune


frames(90, s1, seg)
end(seg)
silence()

# S2: 1-note loop (1/60 s note) + detune ramp 0..2400 over 2 s, then hold
LOOP = pyxel.Sound()
LOOP.set("c1", "0", "7", "n", 2)  # legacy c1 = MIDI 48 = C3 = 130.81 Hz, 2 ticks @120/s = 1/60 s
seg = begin("S2_loop_detune_ramp", base_hz=130.81)
ch.detune = 0
ch.play(LOOP, loop=True)


def s2(i):
    ch.detune = int(2400 * min(i, 119) / 119)
    return ch.detune


frames(140, s2, seg)
end(seg)
silence()

# S3: re-play the long note every tick with a new detune
seg = begin("S3_replay_each_tick", base_hz=130.81)


def s3(i):
    ch.detune = int(2400 * min(i, 119) / 119)
    ch.play(LONG)
    return ch.detune


frames(140, s3, seg)
end(seg)
silence()

# S4: staircase for range, base C4 (legacy c2 = MIDI 60 = 261.63 Hz)
LOOP2 = pyxel.Sound()
LOOP2.set("c2", "0", "7", "n", 2)
seg = begin("S4_staircase", base_hz=261.63)
ch.play(LOOP2, loop=True)
STEPS = [-3600, -2400, -1200, 0, 1200, 2400, 3600, 4800]


def s4(i):
    ch.detune = STEPS[min(i // 30, len(STEPS) - 1)]
    return ch.detune


frames(30 * len(STEPS), s4, seg)
end(seg)
silence()
ch.detune = 0

# S5: gain rewrite on one sustained noise note (expect: no effect until next note)
NOISE_LONG = pyxel.Sound()
NOISE_LONG.mml("T60 Q100 @3 V127 O6 C1&C1&C1&C1")
seg = begin("S5_sustained_noise_gain_ramp_down")
ch.gain = 0.3
ch.play(NOISE_LONG)


def s5(i):
    ch.gain = 0.3 * max(0.0, 1 - i / 59)
    return ch.gain


frames(75, s5, seg)
end(seg)
silence()

# S6: gain rewrite on 1-note noise loop (expect: amplitude follows)
NOISE_LOOP = pyxel.Sound()
NOISE_LOOP.mml("T150 Q100 @3 V127 O6 L96 C")  # 2 ticks at T150 = 1/60 s
seg = begin("S6_loop_noise_gain_triangle")
ch.gain = 0.0
ch.play(NOISE_LOOP, loop=True)


def s6(i):
    ch.gain = 0.4 * (i / 60 if i < 60 else max(0.0, 2 - i / 60))
    return ch.gain


frames(125, s6, seg)
end(seg)
silence()

# S7: Tone.gain rewrite on one sustained noise note (source says: polled at 60 Hz)
seg = begin("S7_sustained_noise_tone_gain_triangle")
ch.gain = 0.3
tone = pyxel.tones[3]
g0 = tone.gain
tone.gain = 0.0
ch.play(NOISE_LONG)


def s7(i):
    tone.gain = 0.6 * (i / 60 if i < 60 else max(0.0, 2 - i / 60))
    return tone.gain


frames(125, s7, seg)
end(seg)
tone.gain = g0
silence()

# S8: a 5th channel
seg = begin("S8_fifth_channel")
try:
    extra = pyxel.Channel()
    extra.gain = 0.3
    pyxel.channels.append(extra)
    seg["num_channels_after_append"] = len(pyxel.channels)
    pyxel.play(4, "T120 Q100 @1 V127 O5 A4")  # 880 Hz 0.5 s on channel index 4
    seg["play_ok"] = True
except BaseException as e:
    seg["error"] = f"{type(e).__name__}: {e}"
frames(36)
end(seg)
silence(30)

(HERE / "out_t03_log.json").write_text(json.dumps(log))
print("DONE", round(now(), 2), "s")
sys.exit(0)
