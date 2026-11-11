"""Render tones / SFX with Sound.save (WAV) and analyze them. Also: resume semantics with the dummy driver."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pyxel

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "proto"))
import sound_data as sd  # noqa: E402
import wavtool as wt  # noqa: E402

pyxel.init(64, 64, fps=60, headless=True, quit_key=pyxel.KEY_NONE)
from pyxel_audio import PyxelAudio  # noqa: E402

audio = PyxelAudio(8)
res = {}
OUT = HERE / "wav"
OUT.mkdir(exist_ok=True)


def render(name, mml, sec):
    s = pyxel.Sound()
    s.mml(mml)
    p = OUT / f"{name}.wav"
    s.save(str(p), sec)
    x, sr = wt.load_wav(p)
    return s, x, sr


# ---- WAV format + pitch of plain notes (Sound.save renders with a fresh channel: gain 0.125, detune 0, loop on)
s, x, sr = render("ref_A4_square", "T120 Q100 @1 V127 O4 A1", 1.0)
res["wav_format"] = dict(sr=sr, samples=len(x), peak=float(np.abs(x).max()))
res["A4_square_hz"] = round(wt.f0_zc(x[2000:20000], sr), 2)
s, x, sr = render("ref_legacy", "T120 Q100 @0 V127 O2 C1", 1.0)
res["MML_O2C_triangle_hz(expect 65.41)"] = round(wt.f0_zc(x[2000:20000], sr), 2)
leg = pyxel.Sound()
leg.set("c0 a2", "t", "7", "n", 60)
leg.save(str(OUT / "ref_legacy_c0_a2.wav"), 1.0)
x, sr = wt.load_wav(OUT / "ref_legacy_c0_a2.wav")
res["legacy_c0_hz(expect 65.41)"] = round(wt.f0_zc(x[1000:10000], sr), 2)
res["legacy_a2_hz(expect 440)"] = round(wt.f0_zc(x[12500:21000], sr), 2)

# ---- engine tones: MML Y (cents) stands in for Channel.detune, which Sound.save cannot see
eng = {}
for eid, e in enumerate(sd.ENGINES):
    for rpm in (900, 3000, 6000, 7500):
        cents = round(1200 * np.log2(rpm / sd.ENGINE_REF_RPM))
        mml = f"T600 Q100 @{e['tone']} V127 Y{cents} O0 L24 C"
        s, x, sr = render(f"engine_{e['name']}_{rpm}", mml, 1.5)
        firing = rpm / 30.0
        f = wt.f0_autocorr(x[4000:4000 + int(sr * max(0.2, 8 / firing))], sr, fmin=firing / 1.4, fmax=firing * 1.4)
        pk = wt.spectrum_peaks(x[4000:4000 + 16384], sr, 7)
        eng[f"{e['name']}_{rpm}"] = dict(expected_firing_hz=round(firing, 2), measured_hz=round(float(f), 2),
                                         err_cents=round(float(wt.cents(f, firing)), 1),
                                         rms=round(float(np.sqrt((x ** 2).mean()))), peaks=pk)
res["engine"] = eng
res["engine_wavetables"] = {k: v[2] for k, v in sd.TONES.items() if v[0] == 0}

# ---- tyre noise candidates
noise = {}
for name, mml in {
    "squeal_data": sd.SQUEAL_LOOP_MML,
    "short_O9B_Y2400": "T600 Q100 @6 V127 O9 L24 Y2400 B",
    "short_O9B_Y0": "T600 Q100 @6 V127 O9 L24 B",
    "short_O7C": "T600 Q100 @6 V127 O7 L24 C",
    "hiss_data": sd.HISS_LOOP_MML,
    "long_O9B": "T600 Q100 @7 V127 O9 L24 B",
}.items():
    s, x, sr = render(f"noise_{name}", mml, 1.0)
    seg = x[2000:2000 + 16384]
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fr = np.fft.rfftfreq(len(seg), 1 / sr)
    centroid = float((sp * fr).sum() / sp.sum())
    noise[name] = dict(rms=round(float(np.sqrt((x ** 2).mean()))), centroid_hz=round(centroid),
                       peaks=wt.spectrum_peaks(seg, sr, 6))
res["noise"] = noise

# ---- one-shot effects
sfx = {}
for name, mml in sd.SFX.items():
    s = pyxel.Sound()
    s.mml(mml)
    total = s.total_sec()
    s2, x, sr = render(f"sfx_{name}", mml + " R1", total + 0.3)  # pad with a rest so the loop does not restart
    n = int(total * sr)
    env, w = wt.rms_track(x[:n], sr, 0.02)
    d = dict(total_sec=round(total, 3), peak=float(np.abs(x[:n]).max()), rms_20ms=[int(v) for v in env][:16])
    if name.startswith("count"):
        d["hz"] = round(wt.f0_zc(x[500:int(sr * 0.15)], sr), 1)
    sfx[name] = d
s = pyxel.Sound()
s.mml(sd.CURB_LOOP_MML)
sfx["curb_loop"] = dict(total_sec=round(s.total_sec(), 4))
s.save(str(OUT / "sfx_curb_loop.wav"), 0.6)
res["sfx"] = sfx

# ---- load-time validation examples
bad = {}
for name, mml in {"typo": "T120 @1 O4 L16 Z", "unclosed": "[CDE", "bad_len": "C5", "octave": "O10 C"}.items():
    try:
        pyxel.Sound().mml(mml)
        bad[name] = "accepted"
    except BaseException as e:
        bad[name] = f"{type(e).__name__}: {e}"
res["bad_mml"] = bad
s = pyxel.Sound()
s.mml("T120 @9 O4 C")  # tone index beyond the list
try:
    pyxel.play(0, s)
    res["tone_out_of_range_play"] = "accepted (falls back to tone 0 per channel.rs)"
except BaseException as e:
    res["tone_out_of_range_play"] = f"{type(e).__name__}: {e}"
pyxel.stop()
s.mml("T120 O4 [C]")
res["infinite_loop_total_sec"] = s.total_sec()

(HERE / "out_t08.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res))
sys.exit(0)
