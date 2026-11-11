"""Analyze out_t03.raw (real mixer output captured by the SDL disk driver) against out_t03_log.json."""
import json
from pathlib import Path

import numpy as np

import wavtool as wt

HERE = Path(__file__).resolve().parent
x, sr = wt.load_raw(HERE / "out_t03.raw")
log = json.loads((HERE / "out_t03_log.json").read_text())
segs = {s["name"]: s for s in log["segments"]}
res = {"samples": len(x), "seconds": round(len(x) / sr, 3), "peak": float(np.abs(x).max())}

onset = int(np.argmax(np.abs(x) > 500))
offset = onset / sr - segs["S0_marker"]["t0"]  # audio_time = python_time + offset
res["marker_onset_audio_s"] = round(onset / sr, 4)
res["audio_minus_python_offset_s"] = round(offset, 4)
res["marker_f0_hz"] = round(wt.f0_zc(x[onset + 200 : onset + 2200], sr), 1)


def cut(seg, pad0=0.0, pad1=0.0):
    a = int((seg["t0"] + offset + pad0) * sr)
    b = int((seg["t1"] + offset + pad1) * sr)
    return x[max(a, 0) : b], max(a, 0) / sr - offset  # samples, python-time of first sample


def cmd_at(seg, t):
    last = None
    for tc, v in seg["cmd"]:
        if tc <= t:
            last = v
        else:
            break
    return last


def ztrack(seg):
    y, t_first = cut(seg, 0.0, 0.05)
    return [(t + t_first, f) for t, f in wt.f0_zc_track(y, sr)]


# S1: sustained note, detune rewritten every tick -> pitch must not move if detune is read at note start only
s = segs["S1_sustained_detune_ramp"]
tr = [(t, f) for t, f in ztrack(s) if s["t0"] + 0.1 < t < s["t1"] - 0.05]
fs = np.array([f for _, f in tr])
res["S1_sustained_note_detune_0_to_1200"] = dict(
    periods=len(fs), f_min=round(float(fs.min()), 2), f_max=round(float(fs.max()), 2),
    f_median=round(float(np.median(fs)), 2), spread_cents=round(float(wt.cents(fs.max(), fs.min())), 1),
    expected_if_ignored_hz=s["base_hz"], commanded_detune_at_end=s["cmd"][-1][1])


def lag_fit(s, tr, base):
    pts = [(t, wt.cents(f, base)) for t, f in tr if f > 0]
    t_lo, t_hi = s["cmd"][0][0] + 0.25, s["cmd"][-1][0] - 0.4  # inside the ramp
    best = None
    for lag_ms in range(-20, 200, 1):
        lag = lag_ms / 1000
        err = [c - cmd_at(s, t - lag) for t, c in pts if t_lo < t < t_hi and cmd_at(s, t - lag) is not None]
        if len(err) < 20:
            continue
        rmse = float(np.sqrt(np.mean(np.square(err))))
        if best is None or rmse < best[1]:
            best = (lag, rmse, len(err), float(np.max(np.abs(err))))
    return dict(best_lag_ms=round(best[0] * 1000), rmse_cents=round(best[1], 1), n=best[2],
                max_abs_err_cents=round(best[3], 1))


for key, name in (("S2_loop_1over60s_note", "S2_loop_detune_ramp"), ("S3_replay_each_tick", "S3_replay_each_tick")):
    s = segs[name]
    tr = ztrack(s)
    r = lag_fit(s, tr, s["base_hz"])
    t_end = s["cmd"][-1][0]
    hold = [f for t, f in tr if t_end - 0.25 < t < t_end]
    r["hold_f_hz"] = round(float(np.median(hold)), 2)
    r["hold_expected_hz"] = round(s["base_hz"] * 4, 2)
    r["hold_err_cents"] = round(float(wt.cents(np.median(hold), s["base_hz"] * 4)), 1)
    # pitch staircase: how long does each distinct pitch last (= effective update period)
    pts = [(t, wt.cents(f, s["base_hz"])) for t, f in tr if s["t0"] + 0.3 < t < s["t0"] + 1.8]
    runs, start = [], pts[0]
    for a, b in zip(pts, pts[1:]):
        if abs(b[1] - a[1]) > 6:  # a step of more than 6 cents between consecutive periods
            runs.append(b[0] - start[0])
            start = b
    r["pitch_step_interval_ms_median"] = round(float(np.median(runs)) * 1000, 1) if runs else None
    r["pitch_step_interval_ms_minmax"] = [round(min(runs) * 1000, 1), round(max(runs) * 1000, 1)] if runs else None
    r["pitch_steps_in_1.5s"] = len(runs)
    y, _ = cut(s, 0.15, -0.15)
    r["peak"] = float(np.abs(y).max())
    r["max_adjacent_jump_over_peak"] = round(float(np.abs(np.diff(y)).max() / (np.abs(y).max() + 1e-9)), 3)
    rm, w = wt.rms_track(y, sr, win=0.004)
    r["rms4ms_min_over_median"] = round(float(rm.min() / np.median(rm)), 3)
    res[key] = r

# reference click level: same measure on the untouched sustained note
y, _ = cut(segs["S1_sustained_detune_ramp"], 0.15, -0.15)
rm, _ = wt.rms_track(y, sr, win=0.004)
res["S1_reference_continuity"] = dict(
    max_adjacent_jump_over_peak=round(float(np.abs(np.diff(y)).max() / np.abs(y).max()), 3),
    rms4ms_min_over_median=round(float(rm.min() / np.median(rm)), 3))

# S4 staircase: range and accuracy
s = segs["S4_staircase"]
steps = []
for d in [-3600, -2400, -1200, 0, 1200, 2400, 3600, 4800]:
    ts = [t for t, v in s["cmd"] if v == d]
    a, b = ts[0] + 0.12, ts[-1] - 0.01
    y = x[int((a + offset) * sr) : int((b + offset) * sr)]
    exp = s["base_hz"] * 2 ** (d / 1200)
    f = wt.f0_zc(y, sr)
    steps.append(dict(detune=d, expected_hz=round(exp, 2), measured_hz=round(float(f), 2),
                      err_cents=round(float(wt.cents(f, exp)), 1), rms=round(float(np.sqrt((y**2).mean())), 0)))
res["S4_staircase_base_261.63Hz"] = steps


def env(name, win=0.050):
    s = segs[name]
    out = []
    for i in range(int((s["t1"] - s["t0"]) / win)):
        a = s["t0"] + i * win
        y = x[int((a + offset) * sr) : int((a + win + offset) * sr)]
        c = cmd_at(s, a + win / 2)
        out.append((round(i * win, 2), round(float(np.sqrt((y**2).mean()))), None if c is None else round(c, 3)))
    return out[::2]


res["S5_sustained_noise__channel_gain_0.3_to_0 (t, rms, commanded)"] = env("S5_sustained_noise_gain_ramp_down")
res["S6_loop_noise__channel_gain_0_0.4_0 (t, rms, commanded)"] = env("S6_loop_noise_gain_triangle")
res["S7_sustained_noise__TONE_gain_0_0.6_0 (t, rms, commanded)"] = env("S7_sustained_noise_tone_gain_triangle")

s = segs["S8_fifth_channel"]
y, _ = cut(s, 0.1, -0.2)
res["S8_fifth_channel"] = dict(info={k: v for k, v in s.items() if k != "cmd"},
                               rms=round(float(np.sqrt((y**2).mean()))), f0_hz=round(float(wt.f0_zc(y, sr)), 1))

(HERE / "out_a03.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res))
