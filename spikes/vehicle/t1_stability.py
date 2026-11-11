"""Q1: which formulation is stable at 60 Hz.  Varies substeps / stopping clamp / v_reg."""
import json, math, itertools
from common import *

def flips(seq):
    """sign changes of the first difference per sample (0..1): 1.0 = pure tick-to-tick zigzag."""
    d = [b - a for a, b in zip(seq, seq[1:])]
    d = [x for x in d if abs(x) > 1e-9]
    if len(d) < 3: return 0.0
    return sum(1 for a, b in zip(d, d[1:]) if a*b < 0) / (len(d) - 1)

def zig(seq):
    """mean |second difference| = size of the tick-to-tick zigzag."""
    if len(seq) < 3: return 0.0
    return sum(abs(c - 2*b + a) for a, b, c in zip(seq, seq[1:], seq[2:])) / (len(seq) - 2)

def cfg(cid, nsub, clamp, vreg):
    car = make_car(cid, substeps=nsub)
    car.stop_clamp = clamp; car.v_reg = vreg
    return car

def s_rest(car):
    car.reset(3.0, -2.0, 0.7, 0.0)
    for n in range(300):
        car.step(0.5*math.sin(n*0.2), 0.0, 1.0 if (n//30) % 2 else 0.0)
    return {"drift": abs(car.x-3.0)+abs(car.z+2.0)+abs(car.heading-0.7), "speed": car.speed, "yaw": car.yaw_rate}

def s_brake_stop(car):
    car.reset(0, 0, 0, 60/KMH)
    hist = []; n = 0; stop_tick = None
    while n < 600:
        car.step(0.2, 0.0, 1.0); n += 1
        hist.append(car.vx)
        if stop_tick is None and car.speed == 0.0 and car.yaw_rate == 0.0: stop_tick = n
    neg = min(hist)
    return {"stop_s": None if stop_tick is None else stop_tick*DT, "min_vx": neg, "final_speed": car.speed,
            "vx_flips_last": flips(hist[-120:]), "finite": math.isfinite(car.x)}

def s_coast_lock(car):
    car.reset(0, 0, 0, 5.0)
    rs = []; ays = []; n = 0; rest = None; peak_r = 0.0
    while n < 60*90:
        car.step(0.5, 0.0, 0.0); n += 1
        if 0.05 < car.speed < 3.0:
            rs.append(car.yaw_rate); ays.append(car.ay)
        peak_r = max(peak_r, abs(car.yaw_rate))
        if car.speed == 0.0 and car.yaw_rate == 0.0: rest = n*DT; break
    return {"rest_s": rest, "yaw_flip_ratio": round(flips(rs), 3), "yaw_zigzag": zig(rs), "ay_zigzag": zig(ays),
            "peak_yaw": peak_r, "finite": math.isfinite(car.x)}

def s_creep_circle(car):
    car.reset(0, 0, 0, 0.0)
    rs = []; xs = []
    for n in range(60*20):
        th = max(0.0, min(0.3, 0.5*(2.0 - car.speed)))
        car.step(0.5, th, 0.0)
        if n >= 60*14:
            rs.append(car.yaw_rate); xs.append((car.x, car.z, car.speed))
    mean_r = sum(rs)/len(rs); v = sum(p[2] for p in xs)/len(xs)
    radius = v/mean_r if mean_r else float("inf")
    # kinematic radius of the CG for front steer 0.5 rad
    Rr = car.L/math.tan(0.5); kin = math.hypot(Rr, car.b)
    return {"speed": v, "radius_m": radius, "kinematic_radius_m": kin, "yaw_flip_ratio": round(flips(rs), 3),
            "yaw_zigzag_rel": zig(rs)/abs(mean_r) if mean_r else None}

def s_donut(car):
    car.reset(0, 0, 0, 0.0)
    for n in range(300): car.step(0.5, 1.0, 0.0)
    peak = (car.speed, car.yaw_rate)
    e_prev = None; gain = 0.0; n = 0; rest = None
    while n < 60*40:
        car.step(0.0, 0.0, 0.0); n += 1
        e = 0.5*car.m*car.speed**2 + 0.5*car.iz*car.yaw_rate**2
        if e_prev is not None: gain = max(gain, e - e_prev)
        e_prev = e
        if car.speed == 0.0 and car.yaw_rate == 0.0: rest = n*DT; break
    return {"after_5s": peak, "max_energy_gain_per_tick_J": gain, "rest_s": rest, "finite": math.isfinite(car.x + car.z + car.heading)}

def slalom(car, record=False):
    car.reset(0, 0, 0, 120/KMH)
    tr = []
    for n in range(600):
        car.step(0.03*math.sin(2*math.pi*0.5*n*DT), 0.6, 0.0)
        if record: tr.append((car.x, car.z, car.heading))
    for n in range(120): car.step(0.05, 0.0, 0.6)
    return (car.x, car.z, car.heading, car.speed)

def limit_exit(car):
    """corner at ~0.85 g then full throttle with steer held: a limit manoeuvre for convergence."""
    R = 30.0; v = math.sqrt(0.80*G*R)
    drv = settle_on_circle(car, R, v, 8.0)
    st = car.steer
    for n in range(120): car.step(st, 1.0, 0.0)
    return (car.x, car.z, car.heading, car.speed, car.yaw_rate, car.body_slip)

if __name__ == "__main__":
    out = {"low_speed": [], "convergence": []}
    print("--- low speed / standstill (car, substeps, stop_clamp, v_reg) ---")
    for cid in ("kazane", "shirogane"):
        for nsub, clamp, vreg in ((1, 1.0, 0.5), (2, 1.0, 0.5), (4, 1.0, 0.5), (1, 0.0, 0.5), (2, 0.0, 0.5), (4, 0.0, 0.5),
                                  (1, 0.0, 2.0), (2, 0.0, 2.0), (4, 0.0, 2.0), (1, 0.0, 4.0), (2, 0.0, 4.0), (1, 1.0, 2.0), (2, 1.0, 2.0)):
            row = {"car": cid, "substeps": nsub, "stop_clamp": clamp, "v_reg": vreg}
            try:
                row["rest"] = s_rest(cfg(cid, nsub, clamp, vreg))
                row["brake_stop"] = s_brake_stop(cfg(cid, nsub, clamp, vreg))
                row["coast_lock"] = s_coast_lock(cfg(cid, nsub, clamp, vreg))
                row["creep"] = s_creep_circle(cfg(cid, nsub, clamp, vreg))
                row["donut"] = s_donut(cfg(cid, nsub, clamp, vreg))
            except Exception as ex:
                row["error"] = repr(ex)
            out["low_speed"].append(row)
            if "error" in row:
                print(cid, nsub, clamp, vreg, "ERROR", row["error"]); continue
            print("%-9s n=%d clamp=%.0f vreg=%.1f | rest drift %.1e spd %.1e | brake: stop %s s min_vx %.4f final %.1e | coast: rest %s s flip %.2f zig %.4f peak_yaw %.2f | creep: R %.2f (kin %.2f) flip %.2f zigrel %.4f | donut: gain %.1f J rest %s finite %s" % (
                cid, nsub, clamp, vreg, row["rest"]["drift"], row["rest"]["speed"],
                row["brake_stop"]["stop_s"], row["brake_stop"]["min_vx"], row["brake_stop"]["final_speed"],
                row["coast_lock"]["rest_s"], row["coast_lock"]["yaw_flip_ratio"], row["coast_lock"]["yaw_zigzag"], row["coast_lock"]["peak_yaw"],
                row["creep"]["radius_m"], row["creep"]["kinematic_radius_m"], row["creep"]["yaw_flip_ratio"], row["creep"]["yaw_zigzag_rel"] or -1,
                row["donut"]["max_energy_gain_per_tick_J"], row["donut"]["rest_s"], row["donut"]["finite"]))

    print("--- convergence against substeps=16 (final state difference) ---")
    for cid in CARS:
        ref_s = slalom(cfg(cid, 16, 1.0, 0.5)); ref_l = limit_exit(cfg(cid, 16, 1.0, 0.5))
        for nsub in (1, 2, 4, 8):
            a = slalom(cfg(cid, nsub, 1.0, 0.5)); b = limit_exit(cfg(cid, nsub, 1.0, 0.5))
            row = {"car": cid, "substeps": nsub,
                   "slalom_pos_err_m": math.hypot(a[0]-ref_s[0], a[1]-ref_s[1]), "slalom_heading_err_deg": math.degrees(abs(wrap(a[2]-ref_s[2]))),
                   "exit_pos_err_m": math.hypot(b[0]-ref_l[0], b[1]-ref_l[1]), "exit_heading_err_deg": math.degrees(abs(wrap(b[2]-ref_l[2]))),
                   "exit_speed_err": abs(b[3]-ref_l[3]), "exit_body_slip_deg": math.degrees(b[5]), "ref_body_slip_deg": math.degrees(ref_l[5])}
            out["convergence"].append(row)
            print("%-9s n=%d slalom pos err %.3f m head %.3f deg | limit-exit pos err %.3f m head %.2f deg (beta %.1f vs ref %.1f deg)" % (
                cid, nsub, row["slalom_pos_err_m"], row["slalom_heading_err_deg"], row["exit_pos_err_m"], row["exit_heading_err_deg"],
                row["exit_body_slip_deg"], row["ref_body_slip_deg"]))
    json.dump(out, open("result_t1.json", "w"), indent=1)
