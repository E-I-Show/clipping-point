"""Dummy audio driver (SDL_AUDIODRIVER=dummy): resume semantics, playm leaving other channels alone, play_pos steps."""
import json
import sys
import time
from pathlib import Path

import pyxel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "proto"))
import sound_data as sd  # noqa: E402

pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
from pyxel_audio import PyxelAudio  # noqa: E402

audio = PyxelAudio(8)
res = {}
ch = pyxel.channels[2]


def poll(sec, step=0.01):
    out = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < sec:
        p = ch.play_pos()
        out.append((round(time.perf_counter() - t0, 3), None if p is None else (p[0], round(p[1], 3))))
        time.sleep(step)
    return out


one = audio.snd_sfx["contact"]
res["contact_total_sec"] = one.total_sec()
res["curb_total_sec"] = audio.snd_curb.total_sec()
# A: loop, then a one-shot with resume=True
ch.play(audio.snd_curb, loop=True)
time.sleep(0.25)
ch.play(one, resume=True)
a = poll(0.8, 0.02)
res["A_loop_then_oneshot_resume"] = a[::2]
res["A_still_playing_after_oneshot"] = a[-1][1] is not None
ch.stop()
time.sleep(0.1)
# B: nothing playing, one-shot with resume=True
ch.play(one, resume=True)
b = poll(0.7, 0.02)
res["B_oneshot_resume_from_silence_ends"] = b[-1][1] is None
res["B_last_non_none_t"] = max(t for t, p in b if p is not None)
# C: loop, then a one-shot WITHOUT resume
ch.play(audio.snd_curb, loop=True)
time.sleep(0.25)
ch.play(one)
c = poll(0.7, 0.02)
res["C_loop_then_oneshot_no_resume_ends"] = c[-1][1] is None
# D: two one-shots in a row with resume=True over a loop -> loop still comes back?
ch.play(audio.snd_curb, loop=True)
time.sleep(0.1)
ch.play(one, resume=True)
time.sleep(0.1)
ch.play(audio.snd_sfx["shift"], resume=True)
d = poll(0.8, 0.02)
res["D_two_oneshots_resume_loop_back"] = d[-1][1] is not None
res["D_trace"] = d[::3]
ch.stop()

# E: playm with empty seqs leaves the other channels untouched
pyxel.stop()
pyxel.channels[0].play(audio.snd_engine[0], loop=True)
time.sleep(0.1)
pyxel.playm(1, loop=True)  # replay music: seqs on channels 4 and 5 only
time.sleep(0.1)
res["E_playing_after_playm_replay"] = [i for i in range(8) if pyxel.play_pos(i) is not None]
res["E_music_seqs"] = [list(s) for s in pyxel.musics[1].seqs]
pyxel.stop()

# F: play_pos granularity = audio callback buffer
snd = pyxel.Sound()
snd.mml("T60 Q100 @0 V20 O3 C1&C1&C1")
pyxel.channels[0].play(snd)
vals = []
t0 = time.perf_counter()
while time.perf_counter() - t0 < 1.0:
    p = pyxel.channels[0].play_pos()
    if p and (not vals or vals[-1] != p[1]):
        vals.append(p[1])
    time.sleep(0.0005)
steps = [round((b - a) * 1000, 2) for a, b in zip(vals, vals[1:])]
res["F_play_pos_step_ms_distinct"] = sorted(set(steps))
res["F_play_pos_steps_count"] = len(steps)
pyxel.stop()
(HERE / "out_t09.json").write_text(json.dumps(res, indent=1))
for k, v in res.items():
    print(k, v)
sys.exit(0)
