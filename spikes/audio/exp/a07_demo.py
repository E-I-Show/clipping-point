"""Analyze the full demo capture (all channels mixed)."""
import json
from pathlib import Path

import numpy as np

import wavtool as wt

HERE = Path(__file__).resolve().parent
x, sr = wt.load_raw(HERE / "out_t07_demo.raw")
r = json.loads((HERE / "out_t07_demo_result.json").read_text())
onset = int(np.argmax(np.abs(x) > 60))
t_tick0 = onset / sr  # menu BGM starts at tick 0
res = dict(seconds=round(len(x) / sr, 2), peak=float(np.abs(x).max()), clipped_samples=int((np.abs(x) >= 32767).sum()),
           onset_s=round(t_tick0, 3), play_pos_distinct_values=r["play_pos_distinct_values"],
           play_pos_first=r["play_pos_ch0_first"][:4], update_us_mean=r["update_us_mean"], update_us_p99=r["update_us_p99"])


def win(t0, t1):
    return x[int((t_tick0 + t0 / 60) * sr): int((t_tick0 + t1 / 60) * sr)]


def rms(y):
    return round(float(np.sqrt((y ** 2).mean())), 0)


sections = [("menu_bgm", 5, 55), ("idle", 75, 98), ("blip1", 100, 112), ("accel_gear1", 200, 285), ("accel_gear3", 400, 475),
            ("cruise", 485, 498), ("slide_peak", 535, 555), ("cruise2", 595, 615), ("curb", 622, 638), ("contact", 640, 652),
            ("curb_after_contact", 664, 678), ("offroad", 705, 735), ("paused", 805, 835), ("replay", 910, 1010),
            ("result", 1030, 1100), ("silent_end", 1118, 1136)]
res["section_rms"] = {n: rms(win(a, b)) for n, a, b in sections}
res["section_peak"] = {n: float(np.abs(win(a, b)).max()) for n, a, b in sections}
# spectra of selected sections
res["peaks_idle"] = wt.spectrum_peaks(win(75, 98), sr, 6)
res["peaks_gear1_end(7000rpm)"] = wt.spectrum_peaks(win(280, 289), sr, 6)
res["peaks_slide"] = wt.spectrum_peaks(win(540, 550), sr, 8)
(HERE / "out_a07.json").write_text(json.dumps(res, indent=1))
for k, v in res.items():
    print(k, v)
