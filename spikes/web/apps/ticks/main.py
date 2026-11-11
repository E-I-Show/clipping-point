"""Measure how often update() and draw() are really called in the browser.

Parameters come from the URL hash:  #fps=60&load=0&skip=0&n=600&phys=0
  fps   value passed to pyxel.init
  load  busy-wait milliseconds inside each *executed* draw (simulates a heavy 3D draw)
  skip  1 = draw() does its work only on every 2nd call (the "render at 30, tick at 60" plan)
  n     number of update() calls to record
  phys  busy-wait milliseconds inside each update (simulates physics + AI)
"""

import json
import time

import js
import pyxel

params = {"fps": 60, "load": 0, "skip": 0, "n": 600, "phys": 0}
for part in str(js.location.hash).lstrip("#").split("&"):
    if "=" in part:
        k, v = part.split("=", 1)
        params[k] = float(v) if "." in v else int(v)

N = params["n"]
update_t = []
draw_t = []
draw_work_t = []
events = []  # "u" / "d" sequence
frame_counts = []
draw_calls = 0
reported = False
perf = time.perf_counter


def busy(ms):
    end = perf() + ms / 1000.0
    x = 0
    while perf() < end:
        x += 1
    return x


def stats(xs):
    s = sorted(xs)
    n = len(s)
    return {
        "n": n,
        "mean": round(sum(s) / n, 3),
        "median": round(s[n // 2], 3),
        "p05": round(s[int(n * 0.05)], 3),
        "p95": round(s[int(n * 0.95)], 3),
        "min": round(s[0], 3),
        "max": round(s[-1], 3),
    }


def update():
    global reported
    if len(update_t) < N + 30:
        update_t.append(perf())
        events.append("u")
        frame_counts.append(pyxel.frame_count)
        if params["phys"]:
            busy(params["phys"])
    elif not reported:
        reported = True
        # drop the first 30 updates (startup)
        ut = update_t[30:]
        t_span = ut[-1] - ut[0]
        d_in = [t for t in draw_work_t if ut[0] <= t <= ut[-1]]
        dc_in = [t for t in draw_t if ut[0] <= t <= ut[-1]]
        u_int = [(b - a) * 1000 for a, b in zip(ut, ut[1:])]
        d_int = [(b - a) * 1000 for a, b in zip(d_in, d_in[1:])]
        # how many updates happen between consecutive draw() calls
        runs = {}
        cur = 0
        for e in events[30:]:
            if e == "u":
                cur += 1
            else:
                runs[cur] = runs.get(cur, 0) + 1
                cur = 0
        fc = frame_counts[30:]
        res = {
            "params": params,
            "span_s": round(t_span, 3),
            "updates_per_s": round((len(ut) - 1) / t_span, 2),
            "draw_calls_per_s": round(len(dc_in) / t_span, 2),
            "draw_work_per_s": round(len(d_in) / t_span, 2),
            "update_interval_ms": stats(u_int),
            "draw_work_interval_ms": stats(d_int) if len(d_int) > 5 else None,
            "updates_between_draw_calls": runs,
            "frame_count_step_set": sorted(set(b - a for a, b in zip(fc, fc[1:]))),
            "interval_histogram_ms": {
                str(k): sum(1 for v in u_int if k <= v < k + 4) for k in range(0, 60, 4)
            },
        }
        print("RESULT_JSON ticks " + json.dumps(res))
        print("SPIKE_DONE")


def draw():
    global draw_calls
    draw_calls += 1
    draw_t.append(perf())
    events.append("d")
    if params["skip"] and draw_calls % 2 == 0:
        return  # leave the previous image on screen
    draw_work_t.append(perf())
    if params["load"]:
        busy(params["load"])
    pyxel.cls(1)
    pyxel.text(4, 4, "TICKS fps=%d load=%s skip=%d" % (params["fps"], params["load"], params["skip"]), 7)
    pyxel.text(4, 14, "updates %d draws %d" % (len(update_t), draw_calls), 10)
    pyxel.rect((draw_calls * 2) % 300, 100, 20, 20, 8)


pyxel.init(320, 240, title="ticks", fps=params["fps"])
pyxel.run(update, draw)
