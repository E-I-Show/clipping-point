import json
from pathlib import Path

import numpy as np

import wavtool as wt

HERE = Path(__file__).resolve().parent
x, sr = wt.load_raw(HERE / "out_t06.raw")
log = json.loads((HERE / "out_t06_log.json").read_text())
segs = {s["name"]: s for s in log["segments"]}
onset = int(np.argmax(np.abs(x) > 500))
offset = onset / sr - segs["marker"]["t0"]
res = {"offset_s": round(offset, 4)}


def cmd_at(seg, t):
    last = None
    for tc, v in seg["cmd"]:
        if tc <= t:
            last = v
        else:
            break
    return last


for name, s in segs.items():
    if name == "marker":
        continue
    a = int((s["t0"] + offset) * sr)
    b = int((s["t1"] + offset) * sr)
    y = x[a:b]
    tr = [(t + s["t0"], wt.cents(f, s["base_hz"])) for t, f in wt.f0_zc_track(y, sr)]
    ramp_t0 = s["cmd"][20][0]
    ramp_t1 = s["cmd"][140][0]
    mid = [(t, c) for t, c in tr if ramp_t0 + 0.3 < t < ramp_t1 - 0.3]
    # lag fit
    best = None
    for lag_ms in range(-20, 200):
        err = [c - cmd_at(s, t - lag_ms / 1000) for t, c in mid]
        rmse = float(np.sqrt(np.mean(np.square(err))))
        if best is None or rmse < best[1]:
            best = (lag_ms, rmse, float(np.max(np.abs(err))))
    # smoothness: per-period pitch increments during the ramp
    inc = np.diff([c for _, c in mid])
    # plateaus: runs of consecutive periods that stay within 2 cents
    runs, run_start = [], mid[0][0]
    for (t0, c0), (t1, c1) in zip(mid, mid[1:]):
        if abs(c1 - c0) > 2.0:
            runs.append(t0 - run_start)
            run_start = t1
    flat = [r for r in runs if r > 0.004]
    hold = [c for t, c in tr if ramp_t1 + 0.2 < t < s["t1"] - 0.05]
    y2 = x[int((ramp_t0 + offset + 0.3) * sr): int((ramp_t1 + offset - 0.3) * sr)]
    res[name] = dict(
        best_lag_ms=best[0], rmse_cents=round(best[1], 1), max_abs_err_cents=round(best[2], 1),
        periods=len(mid),
        per_period_step_cents_p50=round(float(np.percentile(np.abs(inc), 50)), 1),
        per_period_step_cents_p95=round(float(np.percentile(np.abs(inc), 95)), 1),
        per_period_step_cents_max=round(float(np.abs(inc).max()), 1),
        flat_plateaus=len(flat), flat_plateau_ms_median=round(float(np.median(flat)) * 1000, 1) if flat else None,
        hold_cents_median=round(float(np.median(hold)), 1),
        max_adjacent_jump_over_peak=round(float(np.abs(np.diff(y2)).max() / np.abs(y2).max()), 3),
    )
(HERE / "out_a06.json").write_text(json.dumps(res, indent=1))
for k, v in res.items():
    print(k, v)
