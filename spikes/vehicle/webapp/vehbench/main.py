"""Browser (Pyodide) timing of the vehicle model.  Prints RESULT_JSON lines and SPIKE_DONE."""
import json
import sys
import time

import bench_core
import pyxel

frame = 0
stage = 0
CONFIGS = ((False, 1), (False, 2), (False, 4), (True, 1), (True, 2))
tick_ms = []          # time of a 6-car tick measured inside real update() calls
cars = None


def update():
    global frame, stage, cars
    frame += 1
    if frame < 10:
        return
    if stage == 0:
        print("RESULT_JSON env " + json.dumps({"python": sys.version, "platform": sys.platform}))
        # very first call (cold) of one game-second, to see the warm-up factor
        f = bench_core.make_field(False, 2)
        a = time.perf_counter(); bench_core.one_second(f, 0); b = time.perf_counter()
        print("RESULT_JSON cold_first_second_ms " + json.dumps(round((b - a) * 1000.0, 3)))
        stage = 1
    elif 1 <= stage <= len(CONFIGS):
        lite, n = CONFIGS[stage - 1]
        print("RESULT_JSON bench " + json.dumps(bench_core.bench(lite, n, reps=300, warm=20)))
        stage += 1
    elif stage == len(CONFIGS) + 1:
        # second pass of the main configuration (has the engine sped up further?)
        print("RESULT_JSON bench_second_pass " + json.dumps(bench_core.bench(False, 2, reps=300, warm=5)))
        stage += 1
    elif stage == len(CONFIGS) + 2:
        print("RESULT_JSON fingerprint " + json.dumps(bench_core.fingerprint()))
        cars = bench_core.make_field(False, 2)
        stage += 1
    elif stage == len(CONFIGS) + 3:
        # in-loop: one real 60 Hz update = 6 cars x 1 tick, 600 frames
        import math
        n = len(tick_ms)
        st = 0.09 * math.sin(n * 0.035)
        th = 0.9 if (n % 240) < 170 else 0.0
        br = 0.0 if (n % 240) < 170 else 0.7
        a = time.perf_counter()
        for car in cars:
            car.step(st, th, br)
        tick_ms.append((time.perf_counter() - a) * 1000.0)
        if len(tick_ms) >= 1200:
            s = sorted(tick_ms)
            mean = sum(s) / len(s)
            print("RESULT_JSON inloop_tick_ms " + json.dumps({"n": len(s), "mean": round(mean, 5), "median": round(s[600], 5), "p95": round(s[1140], 5),
                                                             "max": round(s[-1], 5), "pct_of_16_7ms_mean": round(mean / 16.6667 * 100, 3),
                                                             "timer_resolution_ms": bench_core.timer_res_ms()}))
            stage += 1
    else:
        if stage < 99:
            print("SPIKE_DONE frame=%d" % frame)
        stage = 99


def draw():
    pyxel.cls(0)
    pyxel.text(4, 4, "VEHICLE BENCH stage %d frame %d" % (stage, frame), 7)


pyxel.init(160, 120, title="vehbench", fps=60)
pyxel.run(update, draw)
