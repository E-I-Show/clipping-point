"""Verification of track.py + akane_short.json (spike). Writes out_verify.json.
Run: python3 verify_track.py            (pure Python, stdlib only)"""
import copy
import json
import math
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import track as T  # noqa: E402

PATH = os.path.join(HERE, "akane_short.json")
R = {}
FAIL = []


def check(name, cond, detail=""):
    if not cond:
        FAIL.append("%s %s" % (name, detail))
    return cond


def best_of(fn, repeat=5):
    best = 1e30
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def main():
    rnd = random.Random(12345)
    # ---------------------------------------------------------------- load
    t_full = best_of(lambda: T.load_track(PATH), 5)
    t_light = best_of(lambda: T.load_track(PATH, validate=False), 5)
    tr = T.load_track(PATH)
    n = tr.n
    L = tr.length
    st = tr.stats()
    R["load"] = {"validate_true_ms": round(t_full * 1000, 1), "validate_false_ms": round(t_light * 1000, 1),
                 "intersection_tests": tr.intersection_tests,
                 "json_bytes": os.path.getsize(PATH)}
    # ---------------------------------------------------------------- A. shape
    corners = []
    for c in tr.corners:
        i0 = int((c["s0"] - 10) / tr.ds)
        i1 = int((c["s1"] + 10) / tr.ds)
        ks = [abs(tr._k[i % n]) for i in range(i0, i1 + 1)]
        corners.append({"name": c["name"], "nominal_radius": c["radius"], "angle_deg": c["angle_deg"],
                        "s0": c["s0"], "s1": c["s1"], "table_min_radius": round(1.0 / max(ks), 2)})
    # straights: runs with |kappa| < 1/1000
    flags = [abs(k) < 1e-3 for k in tr._k]
    start = flags.index(False)
    runs = []
    cur = 0
    begin = None
    for q in range(1, n + 1):
        i = (start + q) % n
        if flags[i]:
            if cur == 0:
                begin = i
            cur += 1
        elif cur:
            runs.append((round(cur * tr.ds, 1), round(begin * tr.ds, 1)))
            cur = 0
    runs = sorted([r for r in runs if r[0] >= 15.0], reverse=True)
    # clearance between walls of different legs
    wl = tr._edge_polyline("L")
    wr = tr._edge_polyline("R")
    walls = [(p[0], p[1], i) for i, p in enumerate(wl)] + [(p[0], p[1], i) for i, p in enumerate(wr)]
    mind = (1e9, 0, 0)
    gap_samples = int(60.0 / tr.ds)
    for a in range(0, len(walls), 2):
        ax, az, ia = walls[a]
        for b in range(a + 1, len(walls), 2):
            bx, bz, ib = walls[b]
            sep = abs(ia - ib)
            if min(sep, n - sep) < gap_samples:
                continue
            d2 = (ax - bx) ** 2 + (az - bz) ** 2
            if d2 < mind[0]:
                mind = (d2, ia, ib)
    R["shape"] = {"length_m": round(L, 3), "n": n, "ds": round(tr.ds, 6), "min_radius_m": round(st["min_radius"], 2),
                  "min_radius_s": round(st["min_radius_s"], 1), "y_min": round(st["y_min"], 2),
                  "y_max": round(st["y_max"], 2), "max_grade": round(st["max_grade"], 4),
                  "width_min": st["width_min"], "width_max": st["width_max"],
                  "turning_deg": round(st["turning_deg"], 3), "corners": corners,
                  "straights_m_and_start_s": runs[:8],
                  "min_wall_to_wall_clearance_m": round(math.sqrt(mind[0]), 2),
                  "clearance_between_s": [round(mind[1] * tr.ds), round(mind[2] * tr.ds)],
                  "bbox_x": [round(min(tr._x), 1), round(max(tr._x), 1)],
                  "bbox_z": [round(min(tr._z), 1), round(max(tr._z), 1)],
                  "control_points": len(json.load(open(PATH))["control_points"])}
    check("length", abs(L - 1800.0) <= 54.0)
    check("corners", len(tr.corners) == 9)
    # ---------------------------------------------------------------- B. query correctness
    err_s = err_d = err_y = err_h = 0.0
    bad = 0
    count = 20000
    for _ in range(count):
        s = rnd.uniform(0.0, L)
        i = int(s / tr.ds) % n
        lo = -tr._ewr[i]
        hi = tr._ewl[i]
        d = rnd.uniform(lo, hi)
        x, z, h, y = tr.pose_at(s, d)
        hint = (i + rnd.randint(-6, 6)) % n
        q = tr.query(x, z, hint)
        es = abs((q.s - s + 0.5 * L) % L - 0.5 * L)
        err_s = max(err_s, es)
        err_d = max(err_d, abs(q.d - d))
        err_y = max(err_y, abs(q.y - y))
        err_h = max(err_h, abs(T._wrap_pi(q.heading - h)))
        if es > 0.01 or not q.converged:
            bad += 1
    gbad = 0
    gerr = 0.0
    gcount = 2000
    for _ in range(gcount):
        s = rnd.uniform(0.0, L)
        i = int(s / tr.ds) % n
        d = rnd.uniform(-tr._half[i], tr._half[i])     # on the asphalt
        x, z, h, y = tr.pose_at(s, d)
        q = tr.query(x, z)
        es = abs((q.s - s + 0.5 * L) % L - 0.5 * L)
        gerr = max(gerr, es)
        if es > 0.01:
            gbad += 1
    R["query_roundtrip"] = {"hinted_points": count, "hinted_bad": bad, "max_err_s_m": err_s, "max_err_d_m": err_d,
                            "max_err_y_m": err_y, "max_err_heading_rad": err_h,
                            "global_points_on_asphalt": gcount, "global_bad": gbad, "global_max_err_s_m": gerr}
    check("roundtrip", bad == 0 and gbad == 0, "bad=%d gbad=%d" % (bad, gbad))

    # continuity: drive several laps along extreme lateral offsets / zig-zag with hint chaining
    def drive(offset_fn, speed, laps=1.0):
        s = 0.0
        hint = None
        prev = None
        max_jump = 0.0
        max_dy = 0.0
        prev_y = None
        steps = 0
        notconv = 0
        step = speed * T.DT
        while s < laps * L:
            i = int((s % L) / tr.ds) % n
            d = offset_fn(s, i)
            x, z, _, _ = tr.pose_at(s, d)
            q = tr.query(x, z, hint)
            hint = q.index
            if prev is not None:
                ds_ = (q.s - prev + 0.5 * L) % L - 0.5 * L
                max_jump = max(max_jump, abs(ds_ - step))
                max_dy = max(max_dy, abs(q.y - prev_y))
            prev = q.s
            prev_y = q.y
            if not q.converged:
                notconv += 1
            s += step
            steps += 1
        return {"steps": steps, "max_abs(ds_query - ds_true)_m": round(max_jump, 4), "max_dy_per_step_m": round(max_dy, 4),
                "not_converged": notconv}
    cont = {}
    cont["left_wall_80mps"] = drive(lambda s, i: tr._ewl[i], 80.0)
    cont["right_wall_80mps"] = drive(lambda s, i: -tr._ewr[i], 80.0)
    cont["zigzag_30mps"] = drive(lambda s, i: (tr._ewl[i] if int(s / 7.0) % 2 else -tr._ewr[i]), 30.0)
    cont["center_10mps"] = drive(lambda s, i: 0.0, 10.0)
    R["query_continuity"] = cont
    for k, v in cont.items():
        # along a wall on the inside of a hairpin s advances faster than the car, so compare loosely
        check("continuity " + k, v["not_converged"] == 0)

    # hairpins: points between the legs, hint from each leg must stay on its own leg
    hp = {}
    for c in tr.corners:
        if abs(c["angle_deg"]) < 170:
            continue
        inside = 1.0 if c["angle_deg"] > 0 else -1.0
        res = {"tests": 0, "stayed_on_hinted_leg": 0, "global_picks_entry_leg": 0, "global_picks_exit_leg": 0}
        for back in (5.0, 15.0, 30.0, 45.0):
            sa = c["s0"] - back          # entry leg
            sb = c["s1"] + back          # exit leg
            ia = int(sa / tr.ds) % n
            ib = int(sb / tr.ds) % n
            wa = (tr._ewl[ia] if inside > 0 else tr._ewr[ia])
            # a point at the inner wall of the entry leg (closest approach to the other leg)
            x, z, _, _ = tr.pose_at(sa, inside * wa)
            qa = tr.query(x, z, ia)
            qb = tr.query(x, z, ib)
            qg = tr.query(x, z)
            res["tests"] += 2
            if abs(qa.s - sa) < 0.05:
                res["stayed_on_hinted_leg"] += 1
            # hinted from the exit leg: must stay near the exit leg (within the walk limit)
            if abs((qb.s - sb + 0.5 * L) % L - 0.5 * L) <= 16 * tr.ds + 2.0:
                res["stayed_on_hinted_leg"] += 1
            if abs(qg.s - sa) < abs(qg.s - sb):
                res["global_picks_entry_leg"] += 1
            else:
                res["global_picks_exit_leg"] += 1
        hp[c["name"]] = res
        check("hairpin " + c["name"], res["stayed_on_hinted_leg"] == res["tests"])
    R["hairpin_leg_tests"] = hp

    # far off course: walk outwards / inwards from the hairpin apex and from a straight
    far = {}
    for label, s0 in (("hairpin_T4_apex", 0.5 * (tr.corners[3]["s0"] + tr.corners[3]["s1"])),
                      ("hairpin_T7_apex", 0.5 * (tr.corners[6]["s0"] + tr.corners[6]["s1"])),
                      ("back_straight", tr.corners[4]["s1"] + 100.0)):
        for side in (1.0, -1.0):
            hint = int(s0 / tr.ds) % n
            max_ds = 0.0
            first_bad = None
            max_index_move = 0
            prev_s = s0
            x0, z0, h0, _ = tr.pose_at(s0, 0.0)
            for k in range(0, 301):
                dist = k * 0.5
                x = x0 - side * dist * math.sin(h0)
                z = z0 + side * dist * math.cos(h0)
                q = tr.query(x, z, hint)
                mv = abs(q.index - hint)
                max_index_move = max(max_index_move, min(mv, n - mv))
                hint = q.index
                dsq = abs((q.s - prev_s + 0.5 * L) % L - 0.5 * L)
                max_ds = max(max_ds, dsq)
                prev_s = q.s
                if not q.converged and first_bad is None:
                    first_bad = dist
            far["%s_%s" % (label, "left" if side > 0 else "right")] = {
                "moved_m": 150.0, "max_ds_per_0.5m_step": round(max_ds, 2),
                "final_s_minus_start": round((prev_s - s0 + 0.5 * L) % L - 0.5 * L, 1),
                "first_not_converged_at_m": first_bad, "max_index_move_per_call": max_index_move}
            check("far index move", max_index_move <= 16)
    R["far_off_course"] = far

    # fine steps: s, d, y must be continuous everywhere inside the walls (no jumps at segment joints)
    step = 0.02
    max_ds = max_dd = max_dy = 0.0
    worst = None
    fine_n = 30000
    for _ in range(fine_n):
        s = rnd.uniform(0.0, L)
        i = int(s / tr.ds) % n
        d = rnd.uniform(-tr._ewr[i] + 0.05, tr._ewl[i] - 0.05)
        x, z, h, y = tr.pose_at(s, d)
        a = rnd.uniform(0.0, 2.0 * math.pi)
        q0 = tr.query(x, z, i)
        q1 = tr.query(x + step * math.cos(a), z + step * math.sin(a), q0.index)
        ds_ = abs((q1.s - q0.s + 0.5 * L) % L - 0.5 * L)
        if ds_ > max_ds:
            max_ds = ds_
            worst = [round(s, 1), round(d, 2)]
        max_dd = max(max_dd, abs(q1.d - q0.d))
        max_dy = max(max_dy, abs(q1.y - q0.y))
    R["fine_step_continuity"] = {"points": fine_n, "step_m": step, "max_ds_m": round(max_ds, 5),
                                 "max_ds_at_s_d": worst, "max_dd_m": round(max_dd, 5), "max_dy_m": round(max_dy, 6),
                                 "max_dy_over_step": round(max_dy / step, 4)}
    check("fine continuity", max_ds < 0.2 and max_dd < 0.021 and max_dy < 0.01)

    # surfaces across a section with every band (T1 outside)
    c1 = tr.corners[0]
    sm = 0.5 * (c1["s0"] + c1["s1"])
    prof = []
    last = None
    dmin = -tr._ewr[int(sm / tr.ds)]
    dmax = tr._ewl[int(sm / tr.ds)]
    k = 0
    while dmin + k * 0.05 <= dmax:
        d = dmin + k * 0.05
        x, z, _, _ = tr.pose_at(sm, d)
        q = tr.query(x, z, int(sm / tr.ds))
        if q.surface != last:
            prof.append([round(d, 2), q.surface])
            last = q.surface
        check("surface_at", tr.surface_at(q.s, q.d) == q.surface)
        k += 1
    R["surface_profile_T1_mid"] = {"s": round(sm, 1), "from_right_wall_to_left_wall": prof,
                                   "wall_right": round(-dmin, 2), "wall_left": round(dmax, 2)}
    # ---------------------------------------------------------------- C. timing
    pts = []
    s = 0.0
    while s < L:
        i = int(s / tr.ds) % n
        d = 3.0 * math.sin(s / 40.0)
        x, z, _, _ = tr.pose_at(s, d)
        pts.append((x, z))
        s += 1.0          # 1 m per call = 60 m/s at 60 Hz
    reps = 60

    def run_hint():
        hint = 0
        qf = tr.query
        for _ in range(reps):
            for x, z in pts:
                hint = qf(x, z, hint).index
    t = best_of(run_hint, 3)
    calls = reps * len(pts)
    timing = {"query_hint_us": round(t / calls * 1e6, 3), "query_hint_calls": calls}
    sub = pts[::37]

    def run_global():
        for x, z in sub:
            tr.query(x, z)
    t = best_of(run_global, 3)
    timing["query_global_us"] = round(t / len(sub) * 1e6, 1)
    timing["query_global_calls"] = len(sub)
    ss = [rnd.uniform(0, L) for _ in range(100000)]

    def run_pose():
        f = tr.pose_at
        for v in ss:
            f(v, 1.5)
    timing["pose_at_us"] = round(best_of(run_pose, 3) / len(ss) * 1e6, 3)

    def run_ideal():
        f = tr.ideal
        for v in ss:
            f(v)
    timing["ideal_us"] = round(best_of(run_ideal, 3) / len(ss) * 1e6, 3)

    def run_surface():
        f = tr.surface_at
        for v in ss:
            f(v, 5.6)
    timing["surface_at_us"] = round(best_of(run_surface, 3) / len(ss) * 1e6, 3)

    def run_empty():
        for v in ss:
            pass
    timing["loop_overhead_us"] = round(best_of(run_empty, 3) / len(ss) * 1e6, 3)
    R["timing_native"] = timing
    # ---------------------------------------------------------------- D. laps
    def s_of_t(t, s_start):
        return s_start + 30.0 * t - (10.0 / 0.7) * (math.cos(0.7 * t) - 1.0)

    s_start = tr.start_sd(0)[0]          # pole slot, behind the line
    lt = T.LapTracker(tr, s_start, 0)
    tick = 0
    naive = []
    prev_rel = (s_start - tr.start_s) % L
    while len(lt.lap_times) < 5 and tick < 60 * 600:
        tick += 1
        s_now = s_of_t(tick * T.DT, s_start) % L
        lt.update(s_now, tick)
        rel = (s_now - tr.start_s) % L
        if rel < prev_rel - 0.5 * L:
            naive.append(tick * T.DT)
        prev_rel = rel
    # true crossing times by bisection
    truth = []
    base = s_start if s_start < 0.5 * L else s_start - L   # unwrapped start (negative, behind line)
    for k in range(0, 6):
        target = k * L + tr.start_s
        lo, hi = 0.0, 1000.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if s_of_t(mid, base) < target:
                lo = mid
            else:
                hi = mid
        truth.append(0.5 * (lo + hi))
    true_laps = [truth[i + 1] - truth[i] for i in range(5)]
    naive_laps = [naive[i + 1] - naive[i] for i in range(5)]
    R["lap_timing"] = {"true_lap_s": [round(v, 5) for v in true_laps],
                       "tracker_lap_s": [round(v, 5) for v in lt.lap_times[:5]],
                       "max_err_interpolated_ms": round(max(abs(a - b) for a, b in zip(true_laps, lt.lap_times)) * 1000, 4),
                       "max_err_tick_quantised_ms": round(max(abs(a - b) for a, b in zip(true_laps, naive_laps)) * 1000, 3),
                       "sector_count_per_lap": len(tr.gates_rel),
                       "sectors_first_lap_s": [round(v, 3) for v in lt.sector_times[:len(tr.gates_rel)]]}
    check("lap interpolation", R["lap_timing"]["max_err_interpolated_ms"] < 0.5)

    # reverse over the line, wrong way round, cut (teleport)
    def run_script(s_list, s0):
        tk = T.LapTracker(tr, s0, 0)
        for i, s in enumerate(s_list):
            tk.update(s % L, i + 1)
        return tk
    line = tr.start_s
    seq = [line - 10 + 1.0 * i for i in range(21)]                    # cross forward
    seq += [line + 10 - 1.0 * i for i in range(1, 21)]                # reverse back over the line
    seq += [line - 10 + 1.0 * i for i in range(1, 21)]                # forward again
    a = run_script(seq, line - 10)
    back = [line + 10 - 1.0 * i for i in range(0, int(L) + 40)]       # whole lap backwards
    b = run_script(back, line + 10)
    fwd = [line - 5 + 1.0 * i for i in range(0, int(2 * L) + 20)]     # two honest laps
    c = run_script(fwd, line - 5)
    # forward a little, then reverse over the line and come back the short way to "finish"
    cheat = [line - 5 + 1.0 * i for i in range(0, 60)] + [line + 54 - 1.0 * i for i in range(1, 120)] \
        + [line - 65 + 1.0 * i for i in range(1, 120)]
    d = run_script(cheat, line - 5)
    # teleport from just after the line to just before it
    tele = [line - 5 + 1.0 * i for i in range(0, 30)] + [line - 300 + 1.0 * i for i in range(0, 330)]
    e = run_script(tele, line - 5)
    # skip a checkpoint by jumping over it (s jump 100 m) then finish the lap
    cp0 = tr.checkpoints[0]
    skip = [line - 5 + 1.0 * i for i in range(0, int(cp0 - line) - 40)]
    skip += [cp0 + 60 + 1.0 * i for i in range(0, int(L - cp0) - 40)]
    f = run_script(skip, line - 5)
    R["lap_rules"] = {
        "forward_reverse_forward": {"laps": a.lap, "start_events": sum(1 for ev in a.events if ev[0] == "start")},
        "full_lap_backwards": {"laps": b.lap, "progress_m": round(b.progress, 1)},
        "two_honest_laps": {"laps": c.lap, "timed": len(c.lap_times)},
        "reverse_then_recross": {"laps": d.lap},
        "teleport_back_300m_then_cross": {"laps": e.lap, "jump_events": sum(1 for ev in e.events if ev[0] == "jump")},
        "jump_over_checkpoint": {"laps": f.lap, "timed": len(f.lap_times),
                                 "jump_events": sum(1 for ev in f.events if ev[0] == "jump")},
    }
    check("lap rules", a.lap == 0 and b.lap == 0 and c.lap == 2 and len(c.lap_times) == 2 and d.lap == 0
          and e.lap == 0 and len(f.lap_times) == 0, json.dumps(R["lap_rules"]))
    # ---------------------------------------------------------------- E. walls
    wall = {"single_impact_30mps": []}
    sref = tr.corners[4]["s1"] + 120.0           # back straight
    i = int(sref / tr.ds)
    for ang in (5, 15, 30, 60, 90):
        x, z, h, _ = tr.pose_at(sref, tr._ewl[i] - 0.2)
        a_ = h + math.radians(ang)
        vx = 30.0 * math.cos(a_)
        vz = 30.0 * math.sin(a_)
        x += vx * T.DT
        z += vz * T.DT
        q = tr.query(x, z, i)
        x2, z2, vx2, vz2, hit, imp = T.resolve_wall(q, x, z, vx, vz, a_)
        q2 = tr.query(x2, z2, q.index)
        pen2, _ = T.car_wall_contact(q2, a_, 2.1, 0.85)
        wall["single_impact_30mps"].append({"angle_deg": ang, "hit": hit, "impact_normal_speed": round(imp, 2),
                                            "speed_after": round(math.hypot(vx2, vz2), 2),
                                            "penetration_after_m": round(pen2, 4)})
        check("wall single", hit and pen2 < 1e-6)
    # ballistic slide: constant-velocity body, no steering, through the T4 hairpin and along a straight
    for label, s0, speed in (("into_hairpin_T4_25mps", tr.corners[3]["s0"] - 20.0, 25.0),
                             ("into_T1_45mps", tr.corners[0]["s0"] - 30.0, 45.0)):
        x, z, h, _ = tr.pose_at(s0, 0.0)
        vx = speed * math.cos(h)
        vz = speed * math.sin(h)
        hint = int(s0 / tr.ds)
        max_pen = 0.0
        hits = 0
        first_hit_tick = None
        trace = []
        for tick in range(1, 241):
            x += vx * T.DT
            z += vz * T.DT
            q = tr.query(x, z, hint)
            hint = q.index
            yaw = math.atan2(vz, vx) if (vx or vz) else h
            x, z, vx, vz, hit, imp = T.resolve_wall(q, x, z, vx, vz, yaw)
            if hit:
                hits += 1
                if first_hit_tick is None:
                    first_hit_tick = tick
                q = tr.query(x, z, hint)
                pen, _ = T.car_wall_contact(q, yaw, 2.1, 0.85)
                max_pen = max(max_pen, pen)
            if tick % 30 == 0:
                trace.append([tick, round(q.s, 1), round(q.d, 2), round(math.hypot(vx, vz), 2), q.surface])
        wall[label] = {"hit_ticks": hits, "first_hit_tick": first_hit_tick, "max_penetration_after_resolve_m": round(max_pen, 4),
                       "trace_tick_s_d_speed_surface": trace}
        check("wall slide " + label, hits > 0 and max_pen < 0.05, str(max_pen))
    R["wall"] = wall
    # ---------------------------------------------------------------- F. car vs car
    cases = {"side_by_side_1.6m": (0, 0, 0.0, 0, 1.6, 0.0), "nose_to_tail_4.0m": (0, 0, 0.0, 4.0, 0, 0.0),
             "t_bone": (0, 0, 0.0, 2.6, 0, math.pi / 2), "diag_corner": (0, 0, 0.0, 3.9, 1.5, 0.3),
             "clear_side_1.8m": (0, 0, 0.0, 0, 1.8, 0.0), "clear_tail_4.3m": (0, 0, 0.0, 4.3, 0, 0.0),
             "staggered_overlap": (0, 0, 0.0, 2.5, 1.5, 0.0)}
    cc = {}
    for k, v in cases.items():
        o = T.obb_overlap(*v)
        c_ = T.circles_overlap(*v)
        cc[k] = {"obb_depth": round(o[0], 3), "obb_n": [round(o[1], 2), round(o[2], 2)],
                 "circles_depth": round(c_[0], 3), "circles_n": [round(c_[1], 2), round(c_[2], 2)]}
    pairs = [(rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-3, 3), rnd.uniform(-3, 3),
              rnd.uniform(-3, 3)) for _ in range(20000)]
    agree = sum(1 for p in pairs if (T.obb_overlap(*p)[0] > 0) == (T.circles_overlap(*p)[0] > 0))

    def run_obb():
        f = T.obb_overlap
        for p in pairs:
            f(*p)

    def run_circ():
        f = T.circles_overlap
        for p in pairs:
            f(*p)
    cc["timing_us"] = {"obb": round(best_of(run_obb, 3) / len(pairs) * 1e6, 3),
                       "circles": round(best_of(run_circ, 3) / len(pairs) * 1e6, 3),
                       "random_pairs": len(pairs), "overlap_agreement": round(agree / float(len(pairs)), 4)}
    a_ = {"x": 0.0, "z": 0.0, "vx": 30.0, "vz": 0.0, "mass": 1410.0}
    b_ = {"x": 3.9, "z": 0.4, "vx": 24.0, "vz": 0.0, "mass": 1110.0}
    p_before = a_["mass"] * a_["vx"] + b_["mass"] * b_["vx"]
    depth, nx, nz = T.obb_overlap(a_["x"], a_["z"], 0.0, b_["x"], b_["z"], 0.0)
    closing = T.resolve_car_pair(a_, b_, depth, nx, nz)
    depth2 = T.obb_overlap(a_["x"], a_["z"], 0.0, b_["x"], b_["z"], 0.0)[0]
    p_after = a_["mass"] * a_["vx"] + b_["mass"] * b_["vx"]
    cc["rear_end_30_vs_24"] = {"depth_before": round(depth, 3), "depth_after": round(depth2, 6),
                               "closing_speed": round(closing, 2), "va_after": round(a_["vx"], 2),
                               "vb_after": round(b_["vx"], 2),
                               "momentum_error": abs(p_after - p_before)}
    check("car pair", depth > 0 and depth2 <= 1e-9 and abs(p_after - p_before) < 1e-6)
    R["car_vs_car"] = cc
    # ---------------------------------------------------------------- G. mesh
    mesh = {}
    cam_stations = [k * 20.0 for k in range(int(L / 20.0))]
    for label, kw in (("uniform_2m", {"max_len": 2.0, "angle_tol_deg": 90.0}),
                      ("uniform_4m", {"max_len": 4.0, "angle_tol_deg": 90.0}),
                      ("adaptive_12m_3deg", {"max_len": 12.0, "angle_tol_deg": 3.0}),
                      ("adaptive_20m_5deg", {"max_len": 20.0, "angle_tol_deg": 5.0})):
        t0 = time.perf_counter()
        chunks = T.build_mesh(tr, **kw)
        dt_build = time.perf_counter() - t0
        tris = sum(c["triangles"] for c in chunks)
        by_part = {}
        verts = 0
        for c in chunks:
            for name, pr in c["parts"].items():
                by_part[name] = by_part.get(name, 0) + len(pr["indices"]) // 3
                verts += len(pr["positions"]) // 3
        # visible: chunk-level culling, 300 m, horizontal half angle 42 deg (4:3, 60 deg vertical fov + margin)
        cent = []
        for c in chunks:
            for name, pr in c["parts"].items():
                pos = pr["positions"]
                idx = pr["indices"]
                for k in range(0, len(idx), 3):
                    a, b, c2 = idx[k], idx[k + 1], idx[k + 2]
                    cent.append(((pos[3 * a] + pos[3 * b] + pos[3 * c2]) / 3.0,
                                 (pos[3 * a + 2] + pos[3 * b + 2] + pos[3 * c2 + 2]) / 3.0))
        vis_tri = []
        vis_chunk = []
        in_range = []
        cosh = math.cos(math.radians(42.0))
        for s in cam_stations:
            x, z, h, _ = tr.pose_at(s, 0.0)
            x -= 6.0 * math.cos(h)       # chase camera 6 m behind
            z -= 6.0 * math.sin(h)
            fx = math.cos(h)
            fz = math.sin(h)
            cnt = 0
            rng = 0
            for cx, cz in cent:
                dx = cx - x
                dz = cz - z
                d2 = dx * dx + dz * dz
                if d2 > 90000.0:
                    continue
                rng += 1
                if dx * fx + dz * fz >= cosh * math.sqrt(d2):
                    cnt += 1
            vis_tri.append(cnt)
            in_range.append(rng)
            cc_ = 0
            for c in chunks:
                dx = c["center"][0] - x
                dz = c["center"][2] - z
                dist = math.hypot(dx, dz)
                if dist - c["radius"] > 300.0:
                    continue
                # cone test with the bounding sphere (conservative)
                if dist > c["radius"]:
                    ang = math.acos(max(-1.0, min(1.0, (dx * fx + dz * fz) / dist)))
                    if ang - math.asin(min(1.0, c["radius"] / dist)) > math.radians(42.0):
                        continue
                cc_ += c["triangles"]
            vis_chunk.append(cc_)
        mesh[label] = {"triangles": tris, "vertices": verts, "chunks": len(chunks), "by_part": by_part,
                       "build_ms": round(dt_build * 1000, 1),
                       "within_300m_mean": round(sum(in_range) / len(in_range)), "within_300m_max": max(in_range),
                       "in_view_triangle_level_mean": round(sum(vis_tri) / len(vis_tri)),
                       "in_view_triangle_level_max": max(vis_tri),
                       "in_view_chunk_level_mean": round(sum(vis_chunk) / len(vis_chunk)),
                       "in_view_chunk_level_max": max(vis_chunk), "camera_positions": len(cam_stations)}
    # winding check: ground normals up, wall normals towards the centerline (both z conventions)
    wind = {}
    for flip in (False, True):
        chunks = T.build_mesh(tr, flip_z=flip)
        up_bad = wall_bad = total = wall_total = 0
        for c in chunks:
            for name, pr in c["parts"].items():
                pos = pr["positions"]
                idx = pr["indices"]
                for k in range(0, len(idx), 3):
                    a, b, c2 = idx[k], idx[k + 1], idx[k + 2]
                    ax, ay, az = pos[3 * a:3 * a + 3]
                    bx, by, bz = pos[3 * b:3 * b + 3]
                    cx, cy, cz = pos[3 * c2:3 * c2 + 3]
                    ux, uy, uz = bx - ax, by - ay, bz - az
                    vx, vy, vz = cx - ax, cy - ay, cz - az
                    nx_, ny_, nz_ = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                    if name == "wall":
                        wall_total += 1
                        mx = (ax + bx + cx) / 3.0
                        mz = (az + bz + cz) / 3.0 * (-1.0 if flip else 1.0)
                        q = tr.query(mx, mz, int(0.5 * (c["s0"] + c["s1"]) / tr.ds), max_walk=40)
                        if not q.converged:
                            wall_bad += 1
                        px, pz, _, _ = tr.pose_at(q.s, 0.0)
                        tx_ = px - mx
                        tz_ = (pz - mz) * (-1.0 if flip else 1.0)
                        if nx_ * tx_ + nz_ * tz_ <= 0.0:
                            wall_bad += 1
                    else:
                        total += 1
                        if ny_ <= 0.0:
                            up_bad += 1
        wind["flip_z_%s" % flip] = {"ground_triangles": total, "ground_facing_down": up_bad,
                                    "wall_triangles": wall_total, "wall_facing_away": wall_bad}
        check("winding", up_bad == 0 and wall_bad == 0 and total > 0 and wall_total > 0)
    mesh["winding_right_handed_y_up"] = wind
    R["mesh"] = mesh
    # ---------------------------------------------------------------- H. validation must fail
    base = json.load(open(PATH))

    def mutate(fn):
        d = copy.deepcopy(base)
        fn(d)
        return d

    def set_(path, value):
        def f(d):
            o = d
            for k in path[:-1]:
                o = o[k]
            o[path[-1]] = value
        return f

    def fig8(d):
        d.pop("ideal", None)
        pts = []
        for k in range(48):
            a = 2 * math.pi * k / 48
            pts.append({"x": 150 * math.sin(a), "z": 80 * math.sin(2 * a), "y": 0.0, "width": 10.0, "bank_deg": 0.0})
        d["control_points"] = pts
        d["sides"] = []
        d["cameras"] = []
        d["scenery"] = []
        d["corners"] = []
        d.pop("expected_length", None)
        d["checkpoints"] = [200.0, 400.0, 600.0]

    def loop_twice(d):
        d.pop("ideal", None)
        pts = []
        for k in range(64):
            a = 4 * math.pi * k / 64
            r = 120 + 30 * k / 64.0
            pts.append({"x": r * math.cos(a), "z": r * math.sin(a), "y": 0.0, "width": 10.0, "bank_deg": 0.0})
        d["control_points"] = pts
        d["sides"] = []
        d["cameras"] = []
        d["scenery"] = []
        d.pop("expected_length", None)

    def kink(d):
        d.pop("ideal", None)
        d["scenery"] = []
        d["cameras"] = []
        # push the control point nearest to the T7 apex 5 m outwards -> very tight local radius
        c7 = tr.corners[6]
        ax, az, ah, _ = tr.pose_at(0.5 * (c7["s0"] + c7["s1"]), 0.0)
        cps = d["control_points"]
        i = min(range(len(cps)), key=lambda k: (cps[k]["x"] - ax) ** 2 + (cps[k]["z"] - az) ** 2)
        side = -1.0 if c7["angle_deg"] > 0 else 1.0
        cps[i]["x"] += side * 5.0 * -math.sin(ah)
        cps[i]["z"] += side * 5.0 * math.cos(ah)

    def poke_through(d):
        d.pop("ideal", None)
        d["scenery"] = []
        d["cameras"] = []
        d.pop("expected_length", None)
        # stretch hairpin 2 (T7) along its legs until it crosses the main straight: winding stays -1
        c7 = tr.corners[6]
        _, _, hleg, _ = tr.pose_at(c7["s0"] - 5.0, 0.0)
        for cp in d["control_points"]:
            q = tr.query(cp["x"], cp["z"])
            if c7["s0"] - 1.0 <= q.s <= c7["s1"] + 1.0 and abs(q.d) < 0.5:
                cp["x"] += 90.0 * math.cos(hleg)
                cp["z"] += 90.0 * math.sin(hleg)

    def repeat_first(d):
        d["control_points"].append(dict(d["control_points"][0]))

    def open_gap(d):
        d.pop("ideal", None)
        del d["control_points"][-9:]
        del d["control_points"][0:3]

    def big_runoff(d):
        d["scenery"] = []
        # right side of the straight into hairpin 1: the return leg runs 32 m to the right
        d["sides"].append({"side": "R", "s0": tr.corners[2]["s1"] + 5.0, "s1": tr.corners[3]["s0"] - 6.0, "gravel": 30.0})

    def inner_wide(d):
        d["sides"].append({"side": "R", "s0": tr.corners[3]["s0"], "s1": tr.corners[3]["s1"], "grass": 12.0})

    cases = [
        ("unknown top key", set_(["speed_limit"], 1), "E_UNKNOWN_KEY"),
        ("unknown control point key", set_(["control_points", 3, "radius"], 5.0), "E_UNKNOWN_KEY"),
        ("unknown side key", set_(["sides", 0, "sand"], 2.0), "E_UNKNOWN_KEY"),
        ("missing key", lambda d: d.pop("start"), "E_MISSING_KEY"),
        ("negative width", set_(["control_points", 5, "width"], -10.0), "E_WIDTH"),
        ("zero width", set_(["control_points", 5, "width"], 0.0), "E_WIDTH"),
        ("width as string", set_(["control_points", 5, "width"], "10"), "E_TYPE"),
        ("bool as number", set_(["control_points", 5, "y"], True), "E_TYPE"),
        ("NaN coordinate", set_(["control_points", 5, "x"], float("nan")), "E_TYPE"),
        ("bank too steep", set_(["control_points", 5, "bank_deg"], 40.0), "E_RANGE"),
        ("closed false", set_(["closed"], False), "E_NOT_CLOSED"),
        ("first point repeated at end", repeat_first, "E_DUPLICATE_POINT"),
        ("open gap in control points", open_gap, "E_NOT_CLOSED"),
        ("wrong version", set_(["version"], 2), "E_VERSION"),
        ("wrong format", set_(["format"], "x"), "E_FORMAT"),
        ("figure 8 (self intersection)", fig8, "E_WINDING|E_SELF_INTERSECTION"),
        ("double loop", loop_twice, "E_WINDING"),
        ("hairpin pokes through the main straight", poke_through, "E_SELF_INTERSECTION"),
        ("kink (tiny radius)", kink, "E_MIN_RADIUS"),
        ("length out of tolerance", set_(["expected_length"], 2000.0), "E_LENGTH"),
        ("run-off overlaps other leg", big_runoff, "E_CORRIDOR_OVERLAP"),
        ("inner run-off beyond centre of curvature", inner_wide, "E_FOLD"),
        ("negative kerb", set_(["sides", 0, "gravel"], -1.0), "E_RANGE"),
        ("side range beyond length", set_(["sides", 0, "s1"], 99999.0), "E_RANGE"),
        ("bad side name", set_(["sides", 0, "side"], "X"), "E_RANGE"),
        ("checkpoints out of order", lambda d: d["checkpoints"].reverse(), "E_CHECKPOINTS"),
        ("single checkpoint", set_(["checkpoints"], [900.0]), "E_CHECKPOINTS"),
        ("grid on a curve", set_(["start", "s"], tr.corners[0]["s0"] + 60.0), "E_GRID"),
        ("grid off the asphalt", set_(["start", "lateral"], 5.8), "E_GRID"),
        ("camera gap", set_(["cameras", 2, "to"], base["cameras"][2]["to"] - 30.0), "E_CAMERA"),
        ("camera on the road", lambda d: d["cameras"][2].update({"d": 0.0, "h": 1.0}), "E_CAMERA"),
        ("scenery inside walls", lambda d: d["scenery"][-1].update({"d": 3.0}), "E_SCENERY"),
        ("unknown scenery kind", lambda d: d["scenery"][-1].update({"kind": "ufo"}), "E_UNKNOWN_KIND"),
        ("stale ideal line", set_(["ideal", "baked_length"], 1700.0), "E_IDEAL_STALE"),
        ("ideal off the road", lambda d: d["ideal"]["d"].__setitem__(10, 9.0), "E_IDEAL_OFF_ROAD"),
    ]
    neg = []
    for name, fn, code in cases:
        d = mutate(fn)
        got = "LOADED_WITHOUT_ERROR"
        try:
            T.Track(d)
        except T.TrackError as ex:
            got = ex.code
        except Exception as ex:      # any other exception is a hole in the validation
            got = "CRASH:" + type(ex).__name__
        ok = got in code.split("|")
        neg.append({"case": name, "expected": code, "got": got, "ok": ok})
        check("negative " + name, ok, got)
    # duplicate key and NaN in the raw text
    raw = open(PATH, encoding="utf-8").read()
    tmp = os.path.join(HERE, "out_tmp_bad.json")
    for name, text, code in (("duplicate key in text", raw.replace('"version": 1,', '"version": 1, "version": 1,', 1), "E_DUPLICATE_KEY"),
                             ("NaN literal in text", raw.replace('"sample_step": 2.0', '"sample_step": NaN', 1), "E_TYPE")):
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        got = "LOADED_WITHOUT_ERROR"
        try:
            T.load_track(tmp)
        except T.TrackError as ex:
            got = ex.code
        except Exception as ex:
            got = "CRASH:" + type(ex).__name__
        neg.append({"case": name, "expected": code, "got": got, "ok": got == code})
        check("negative " + name, got == code, got)
    os.remove(tmp)
    R["validation_negative_tests"] = {"cases": len(neg), "passed": sum(1 for v in neg if v["ok"]), "detail": neg}
    check("negative count", len(neg) >= 30)
    # ---------------------------------------------------------------- I. grid, cameras, ideal
    R["grid"] = [{"slot": g, "s": round(tr.start_sd(g)[0], 2), "d": tr.start_sd(g)[1],
                  "pose": [round(v, 3) for v in tr.start_pose(g)]} for g in range(tr.grid_slots)]
    cams = [tr.camera_for(k * 5.0) for k in range(int(L / 5.0))]
    R["cameras"] = {"count": len(tr.cameras), "uncovered_samples": sum(1 for v in cams if v < 0),
                    "switches_per_lap": sum(1 for a, b in zip(cams, cams[1:] + cams[:1]) if a != b)}
    check("cameras", R["cameras"]["uncovered_samples"] == 0 and len(tr.cameras) > 0)
    ideal_ok = all(abs(tr.ideal(k * 3.0)[0]) <= tr._half[int(k * 3.0 / tr.ds) % n] for k in range(int(L / 3.0)))
    R["ideal_api"] = {"baked": tr.has_baked_ideal, "inside_asphalt": ideal_ok,
                      "ideal(0)": [round(v, 3) for v in tr.ideal(0.0)],
                      "ideal_points": len(tr.ideal_points())}
    check("ideal", tr.has_baked_ideal and ideal_ok)
    R["failures"] = FAIL
    with open(os.path.join(HERE, "out_verify.json"), "w", encoding="utf-8") as f:
        json.dump(R, f, indent=1)
    print(json.dumps(R, indent=1))
    print("FAILURES:", len(FAIL))
    for f_ in FAIL:
        print("  FAIL", f_)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
