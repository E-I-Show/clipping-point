"""Analyze web2 captures: native (SDL disk driver, 22050 Hz) and web (ScriptProcessor hook, 44100 Hz)."""
import json
import sys
from pathlib import Path

import numpy as np

import wavtool as wt

HERE = Path(__file__).resolve().parent
W = HERE.parent / "web2"


def cmd_at(seg, t):
    last = None
    for tc, v in seg["cmd"]:
        if tc <= t:
            last = v
        else:
            break
    return last


def analyze(raw, logf, sr):
    x = np.fromfile(str(raw), dtype="<i2").astype(np.float64)
    log = json.loads(Path(logf).read_text())
    segs = {s["name"]: s for s in log["segments"]}
    onset = int(np.argmax(np.abs(x) > 500))
    offset = onset / sr - segs["marker"]["t0"]
    res = {"seconds": round(len(x) / sr, 2), "peak": float(np.abs(x).max()), "audio_minus_python_offset_s": round(offset, 4),
           "marker_hz": round(wt.f0_zc(x[onset + 300: onset + 3000], sr), 1)}
    for name, s in segs.items():
        if name == "marker":
            continue
        a, b = int((s["t0"] + offset) * sr), int((s["t1"] + offset + 0.05) * sr)
        y = x[a:b]
        if s["kind"] in ("detune", "replay"):
            tr = [(t + s["t0"], wt.cents(f, s["base_hz"])) for t, f in wt.f0_zc_track(y, sr)]
            r0, r1 = s["cmd"][20][0], s["cmd"][140][0]
            mid = [(t, c) for t, c in tr if r0 + 0.3 < t < r1 - 0.3]
            best = None
            for lag_ms in range(-30, 250):
                err = [c - cmd_at(s, t - lag_ms / 1000) for t, c in mid]
                rmse = float(np.sqrt(np.mean(np.square(err))))
                if best is None or rmse < best[1]:
                    best = (lag_ms, rmse, float(np.max(np.abs(err))))
            inc = np.abs(np.diff([c for _, c in mid]))
            hold = [c for t, c in tr if r1 + 0.25 < t < s["t1"] - 0.05]
            allc = [c for t, c in tr if s["t0"] + 0.1 < t < s["t1"] - 0.05]
            res[name] = dict(lag_ms=best[0], rmse_cents=round(best[1], 1), max_abs_err_cents=round(best[2], 1),
                             step_p50=round(float(np.percentile(inc, 50)), 1), step_p95=round(float(np.percentile(inc, 95)), 1),
                             step_max=round(float(inc.max()), 1), hold_cents=round(float(np.median(hold)), 1),
                             pitch_range_cents=[round(float(min(allc)), 1), round(float(max(allc)), 1)],
                             max_adjacent_jump_over_peak=round(float(np.abs(np.diff(y[int(0.5 * sr):int(2.0 * sr)])).max() / np.abs(y).max()), 3))
        else:
            win = 0.1
            env = []
            for i in range(int((s["t1"] - s["t0"]) / win)):
                t = s["t0"] + i * win
                seg = x[int((t + offset) * sr): int((t + win + offset) * sr)]
                env.append((round(i * win, 1), int(np.sqrt((seg ** 2).mean())), cmd_at(s, t + win / 2)))
            res[name] = env[::2]
    return res


out = {"native_disk_driver": analyze(W / "native_cap.raw", W / "native_log.json", 22050),
       "web_headless_chromium": analyze(W / "dl" / "webcap.raw", W / "web_log.json", 44100)}
(HERE / "out_a10.json").write_text(json.dumps(out, indent=1))
for env, r in out.items():
    print("==", env)
    for k, v in r.items():
        print("  ", k, v)
