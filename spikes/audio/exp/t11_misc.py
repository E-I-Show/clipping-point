"""Clipping behaviour (disk driver), per-call costs, pure-Python interface checks."""
import json
import sys
import time
from pathlib import Path

import pyxel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "proto"))
import audio_iface as ai  # noqa: E402
import sound_data as sd  # noqa: E402

pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
T0 = time.perf_counter()
res = {}

# ---- pure-Python interface checks (no pyxel needed for these)
res["detune_900rpm"] = ai.rpm_to_detune(900, sd.ENGINE_REF_RPM)
res["detune_7500rpm"] = ai.rpm_to_detune(7500, sd.ENGINE_REF_RPM)
res["detune_ref"] = ai.rpm_to_detune(sd.ENGINE_REF_RPM, sd.ENGINE_REF_RPM)
assert res["detune_ref"] == 0 and isinstance(res["detune_900rpm"], int)
p = ai.NearestPicker(switch_ratio=0.8, min_hold_ticks=20)
seq = []
for t in range(120):
    d0 = 10.0
    d1 = 30.0 - t * 0.3  # car 1 approaches: equal at t=67, 0.8x at t=73.3
    seq.append(p.pick([d0, d1]))
first_switch = seq.index(1)
res["picker_first_switch_tick"] = first_switch
res["picker_switch_count"] = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
assert 73 <= first_switch <= 75 and res["picker_switch_count"] == 1
# flapping input: two cars alternate being nearest by 5 % every tick -> must not switch
p = ai.NearestPicker()
seq = [p.pick([10.0, 10.5] if t % 2 else [10.5, 10.0]) for t in range(200)]
res["picker_flap_switches"] = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
assert res["picker_flap_switches"] == 0
res["squeal_gain_table"] = [(s / 10, round(ai.squeal_gain(s / 10, 0.30), 3)) for s in range(0, 11, 2)]
res["distance_gain_table"] = [(d, round(ai.distance_gain(d), 3)) for d in (0, 6, 12, 24, 40, 60)]

# ---- call costs
snd = pyxel.Sound()
snd.mml("T600 Q100 @0 V127 @GLI1{*,*} O0 L24 C")
ch = pyxel.channels[0]
N = 20000
t = time.perf_counter()
for i in range(N):
    ch.play(snd, loop=True)
res["us_play_sound_obj"] = round((time.perf_counter() - t) / N * 1e6, 2)
t = time.perf_counter()
for i in range(N):
    ch.play("T600 Q100 @0 V127 @GLI1{*,*} O0 L24 C", loop=True)
res["us_play_mml_string"] = round((time.perf_counter() - t) / N * 1e6, 2)
t = time.perf_counter()
for i in range(N):
    ch.play_pos()
res["us_play_pos"] = round((time.perf_counter() - t) / N * 1e6, 2)
t = time.perf_counter()
for i in range(N):
    ch.detune = ai.rpm_to_detune(3000.0 + i, sd.ENGINE_REF_RPM)
    ch.gain = 0.2
res["us_detune_gain_with_log2"] = round((time.perf_counter() - t) / N * 1e6, 2)
tone = pyxel.tones[0]
wt64 = list(range(16)) * 4
t = time.perf_counter()
for i in range(N):
    tone.wavetable[:] = wt64
res["us_wavetable_assign_64"] = round((time.perf_counter() - t) / N * 1e6, 2)
pyxel.stop()

# ---- clipping: 4 channels, each triangle at gain 0.5 (sum 2.0), slightly detuned
marks = {}
if len(sys.argv) > 1 and sys.argv[1] == "clip":
    tri = pyxel.Sound()
    tri.mml("T60 Q100 @0 V127 O3 C1")
    for _ in range(20):
        pyxel.flip()
    marks["t_start"] = time.perf_counter() - T0
    for i in range(4):
        pyxel.channels[i].gain = 0.5
        pyxel.channels[i].detune = i * 7
        pyxel.channels[i].play(tri)
    for _ in range(60):
        pyxel.flip()
    pyxel.stop()
    for _ in range(10):
        pyxel.flip()
    # single channel at gain 1.0 and 2.0
    pyxel.channels[0].detune = 0
    pyxel.channels[0].gain = 1.0
    marks["t_g1"] = time.perf_counter() - T0
    pyxel.channels[0].play(tri)
    for _ in range(30):
        pyxel.flip()
    pyxel.stop()
    for _ in range(10):
        pyxel.flip()
    pyxel.channels[0].gain = 2.0
    marks["t_g2"] = time.perf_counter() - T0
    pyxel.channels[0].play(tri)
    for _ in range(30):
        pyxel.flip()
    pyxel.stop()
    for _ in range(10):
        pyxel.flip()
    marks["t_end"] = time.perf_counter() - T0
res["marks"] = marks
(HERE / "out_t11.json").write_text(json.dumps(res, indent=1))
for k, v in res.items():
    print(k, v)
sys.exit(0)
