"""Timing of track.py inside Pyxel (native headless or browser). Display side only: track.py stays pure."""
import json
import math
import os
import sys
import time

import pyxel

import track as T

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = sys.platform == "emscripten"


def best_of(fn, repeat=3):
    out = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        out.append(time.perf_counter() - t0)
    return out


def measure():
    path = os.path.join(HERE, "akane_short.json")
    res = {"platform": sys.platform, "python": sys.version.split()[0]}
    t = best_of(lambda: T.load_track(path), 3)
    res["load_validate_ms_first_best"] = [round(t[0] * 1000, 1), round(min(t) * 1000, 1)]
    t = best_of(lambda: T.load_track(path, validate=False), 3)
    res["load_light_ms_best"] = round(min(t) * 1000, 1)
    tr = T.load_track(path)
    pts = []
    s = 0.0
    while s < tr.length:
        x, z, _, _ = tr.pose_at(s, 3.0 * math.sin(s / 40.0))
        pts.append((x, z))
        s += 1.0

    def run_hint():
        hint = 0
        qf = tr.query
        for _ in range(10):
            for x, z in pts:
                hint = qf(x, z, hint).index
    t = best_of(run_hint, 4)
    calls = 10 * len(pts)
    res["query_hint_us_first_best"] = [round(t[0] / calls * 1e6, 3), round(min(t) / calls * 1e6, 3)]
    res["query_hint_calls"] = calls
    sub = pts[::37]

    def run_global():
        for x, z in sub:
            tr.query(x, z)
    t = best_of(run_global, 3)
    res["query_global_us_best"] = round(min(t) / len(sub) * 1e6, 1)
    ss = [(i * 7.919) % tr.length for i in range(20000)]

    def run_pose():
        f = tr.pose_at
        for v in ss:
            f(v, 1.5)
    res["pose_at_us_best"] = round(min(best_of(run_pose, 3)) / len(ss) * 1e6, 3)

    def run_ideal():
        f = tr.ideal
        for v in ss:
            f(v)
    res["ideal_us_best"] = round(min(best_of(run_ideal, 3)) / len(ss) * 1e6, 3)

    def run_surface():
        f = tr.surface_at
        for v in ss:
            f(v, 5.6)
    res["surface_at_us_best"] = round(min(best_of(run_surface, 3)) / len(ss) * 1e6, 3)
    res["speed_profile_ms_best"] = round(min(best_of(lambda: T.speed_profile(tr, tr._ideal_d), 3)) * 1000, 2)
    res["build_mesh_adaptive_ms_best"] = round(min(best_of(lambda: T.build_mesh(tr), 3)) * 1000, 1)
    pairs = [((i * 0.37) % 6 - 3, (i * 0.73) % 6 - 3, (i * 0.11) % 6 - 3, (i * 0.53) % 6 - 3, (i * 0.91) % 6 - 3,
              (i * 0.29) % 6 - 3) for i in range(5000)]

    def run_obb():
        f = T.obb_overlap
        for p in pairs:
            f(*p)
    res["obb_us_best"] = round(min(best_of(run_obb, 3)) / len(pairs) * 1e6, 3)
    t = best_of(lambda: T.relax_racing_line(tr), 1)
    res["relax_racing_line_s"] = round(t[0], 2)
    # fingerprint of query results (to compare native vs browser)
    acc = 0.0
    hint = 0
    for x, z in pts[::5]:
        q = tr.query(x, z, hint)
        hint = q.index
        acc += q.s * 1e-3 + q.d + q.y + q.heading + q.curvature
    res["query_sum"] = repr(acc)
    res["length"] = repr(tr.length)
    return res


class App:
    def __init__(self):
        if WEB:
            pyxel.init(160, 120, title="trackbench", fps=60, quit_key=pyxel.KEY_NONE)
        else:
            pyxel.init(160, 120, title="trackbench", fps=60, quit_key=pyxel.KEY_NONE, headless=True)
        self.frame = 0
        pyxel.run(self.update, self.draw)

    def update(self):
        self.frame += 1
        if self.frame == 10:
            res = measure()
            print("SPIKE_RESULT " + json.dumps(res))
            print("SPIKE_DONE")
            if not WEB:
                with open(os.path.join(HERE, "..", "..", "out_bench_native_pyxel.json"), "w") as f:
                    json.dump(res, f, indent=1)
                sys.stdout.flush()
                pyxel.quit()

    def draw(self):
        pyxel.cls(1)
        pyxel.text(4, 4, "TRACK BENCH %d" % self.frame, 7)


App()
