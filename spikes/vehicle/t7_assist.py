"""Q7: quantities for assists without a wheel-rotation DOF (+ a few extra checks used in the report)."""
import json, math
import vehicle
from common import *
from t4_drive import exit_test

res = {}

# ---- 1. ABS quantity: car.brake_util (max over wheels of -u) --------------------------------
print("--- brake: full pedal vs brake_util-limited (ABS-like) ---")
res["abs"] = []
for cid in CARS:
    for mu in (1.0, 0.5):
        f = brake_run(make_car(cid), 100, False, mu); a = brake_run(make_car(cid), 100, True, mu)
        # steer while braking: lateral offset after 1.5 s with 0.06 rad steer
        lat = {}
        for label, use_abs in (("full", False), ("abs", True)):
            car = make_car(cid); car.reset(0, 0, 0, 100/KMH); ctl = ABS(); b = 1.0; lock_ticks = 0
            for n in range(90):
                car.step(0.06, 0.0, b, mu)
                if use_abs: b = ctl(car)
                if car.wheel_util[0] < -1.0 or car.wheel_util[1] < -1.0: lock_ticks += 1
            lat[label] = (round(car.z, 2), lock_ticks)
        row = {"car": cid, "mu": mu, "dist_full_m": round(f["dist_m"], 1), "dist_abs_m": round(a["dist_m"], 1),
               "steer_while_braking_lateral_m_full": lat["full"][0], "front_lock_ticks_full": lat["full"][1],
               "steer_while_braking_lateral_m_abs": lat["abs"][0], "front_lock_ticks_abs": lat["abs"][1]}
        res["abs"].append(row); print(row)

# ---- 2. TCS quantity: car.drive_util --------------------------------------------------------
print("--- launch: full throttle vs drive_util-limited (TCS-like) ---")
res["tcs"] = []
for cid in CARS:
    for mu in (1.0, 0.5):
        out = {}
        for label, tcs in (("full", False), ("tcs", True)):
            car = make_car(cid); car.reset(0, 0, 0, 0); ctl = TCS(); th = 1.0; t = 0; spin_ticks = 0; t80 = None
            while t < 60*40 and t80 is None:
                car.step(0.0, th, 0.0, mu); t += 1
                if tcs: th = ctl(car)
                if car.drive_util > 1.0: spin_ticks += 1
                if car.speed*KMH >= 80: t80 = t*DT
            out[label] = (t80, spin_ticks)
        row = {"car": cid, "mu": mu, "t0_80_full_s": out["full"][0], "wheelspin_ticks_full": out["full"][1],
               "t0_80_tcs_s": out["tcs"][0], "wheelspin_ticks_tcs": out["tcs"][1]}
        res["tcs"].append(row); print(row)

# ---- 3. spin onset: which quantity warns first ----------------------------------------------
print("--- spin onset on corner exit (R=30, 0.75 g, full throttle, steer held) ---")
res["spin_onset"] = []
for cid in ("kazane", "shirogane", "mikazuki"):
    car = make_car(cid); R = 30.0; v = math.sqrt(0.75*G*R)
    settle_on_circle(car, R, v, 10.0)
    st = car.steer; b0 = car.body_slip; ye0 = car.yaw_err
    ev = {}
    prev_b = car.body_slip
    for n in range(150):
        car.step(st, 1.0, 0.0); t = (n+1)*DT
        bdot = (car.body_slip - prev_b)/DT; prev_b = car.body_slip
        sr = max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
        checks = {"drive_util>1": car.drive_util > 1.0, "drive_util_axle>0.7": car.drive_util_axle > 0.7,
                  "rear sy>1 (past peak)": sr > 1.0, "|yaw_err - yaw_err0|>0.10 rad/s": abs(car.yaw_err - ye0) > 0.10,
                  "|beta_rate|>0.15 rad/s": abs(bdot) > 0.15, "|beta-beta0|>4deg": abs(car.body_slip - b0) > math.radians(4),
                  "|beta|>25deg (spin)": abs(car.body_slip) > math.radians(25)}
        for k, c in checks.items():
            if c and k not in ev: ev[k] = round(t, 3)
    row = {"car": cid, "first_time_s": ev}
    res["spin_onset"].append(row); print(row)

# ---- 4. can a simple assist built from these quantities save it? ----------------------------
print("--- same exit with a simple assist: throttle cut by rear slip + countersteer by beta / yaw_err ---")
res["save"] = []
for cid in ("kazane", "shirogane", "mikazuki"):
    for mode in ("none", "throttle_only", "throttle+countersteer"):
        car = make_car(cid); R = 30.0; v = math.sqrt(0.75*G*R)
        settle_on_circle(car, R, v, 10.0)
        st0 = car.steer; b0 = car.body_slip; ye0 = car.yaw_err; th = 1.0; peak = 0.0; v0 = car.speed
        for n in range(180):
            st = st0
            if mode != "none":
                sr = max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
                # throttle: back off when the outer driven wheel is near its limit or the rear is past the peak
                lim = 1.0
                uo = max(car.wheel_util[2], car.wheel_util[3]) if car.front_drive < 1.0 else 0.0
                uo = min(car.wheel_util[2], car.wheel_util[3]) if car.front_drive < 1.0 else 0.0   # less loaded-> larger u; use the smaller = outer
                if uo > 0.55: lim = max(0.1, th*0.55/uo)
                if sr > 0.9: lim = min(lim, max(0.0, 1.0 - (sr - 0.9)*2.0))
                th = min(1.0, lim, th + 0.05) if lim < th else min(1.0, th + 0.05)
            if mode == "throttle+countersteer":
                st = st0 + 1.5*(car.body_slip - b0) - 0.25*(car.yaw_err - ye0)
            car.step(st, th, 0.0)
            peak = max(peak, abs(car.body_slip))
        row = {"car": cid, "assist": mode, "peak_beta_deg": round(math.degrees(peak), 1), "dv_kmh_3s": round((car.speed - v0)*KMH, 1),
               "end_beta_deg": round(math.degrees(car.body_slip), 1)}
        res["save"].append(row); print(row)

# ---- 5. how forgiving: ellipse strictness (tuning knob) --------------------------------------
print("--- tuning knob: CU2 (ellipse strictness) / K_SPIN on the kazane + shirogane exit ---")
res["knob"] = []
for cu2, kspin in ((0.94, 4.0), (0.80, 4.0), (0.60, 4.0), (0.94, 1.5), (0.70, 1.5)):
    vehicle.CU2 = cu2; vehicle.KY1 = math.sqrt(1 - cu2); vehicle.K_SPIN = kspin
    for cid in ("kazane", "shirogane"):
        for th in (1.0, 0.7):
            r = exit_test(cid, th)
            row = {"CU2": cu2, "K_SPIN": kspin, "car": cid, "throttle": th, "peak_beta_deg": r["peak_beta_deg"], "dv_1.5s": r["dv_kmh_1.5s"], "verdict": r["verdict"]}
            res["knob"].append(row); print(row)
vehicle.CU2 = 0.94; vehicle.KY1 = math.sqrt(1 - 0.94); vehicle.K_SPIN = 4.0

# ---- 6. gear setup: in-gear / roll-on metric --------------------------------------------------
print("--- gear setup: roll-on from a steady speed (AT), full throttle ---")
res["gear_rollon"] = []
for cid in CARS:
    for stg in (-2, 0, 2):
        row = {"car": cid, "gear_stage": stg}
        for v0, v1 in ((40, 80), (60, 110), (100, 160)):
            car = make_car(cid, {"gear": stg}); car.reset(0, 0, 0, v0/KMH)
            for n in range(120):                     # hold the speed with part throttle (turbo spooled as in a corner exit)
                car.step(0.0, 0.25, 0.0); car.wvx = v0/KMH; car.wvz = 0.0
            g0 = car.gear; f0 = None; t = 0; ctl = TCS(); th = 1.0
            while car.speed*KMH < v1 and t < 60*60:
                car.step(0.0, th, 0.0); th = ctl(car); t += 1
                if t == 30: f0 = car.drive_force
            row["%d-%d_s" % (v0, v1)] = round(t*DT, 2); row["gear_at_%d" % v0] = g0; row["force_N_0.5s_from_%d" % v0] = round(f0)
        res["gear_rollon"].append(row); print(row)

# ---- 7. traction setup on a milder exit (0.5 g) -----------------------------------------------
print("--- traction setup: exit at 0.5 g (R=40), full throttle, steer held 2 s ---")
res["traction_mild"] = []
for cid in CARS:
    for stg in (-2, 0, 2):
        r = exit_test(cid, 1.0, False, {"traction": stg}, R=40.0, g0=0.5)
        row = {"car": cid, "traction": stg, "dv_1.5s": r["dv_kmh_1.5s"], "peak_beta_deg": r["peak_beta_deg"], "wide_m": r["ran_wide_m_at_end"], "verdict": r["verdict"],
               "util_0.5s": r["rows"]["0.5s"]["util"]}
        res["traction_mild"].append(row); print(row)

# ---- 8. lite (2-wheel) vs full --------------------------------------------------------------
print("--- lite model vs full model ---")
res["lite"] = []
for cid in CARS:
    row = {"car": cid}
    for label, lite in (("full", False), ("lite", True)):
        car = make_car(cid, lite=lite)
        a = accel_run(car, tcs=True, seconds=25)
        b = brake_run(make_car(cid, lite=lite), 100, True)
        rows, best, fail = circle_ramp(make_car(cid, lite=lite), 30.0, 8.0, 22.0)
        car2 = make_car(cid, lite=lite); R = 30.0; v = math.sqrt(0.75*G*R); settle_on_circle(car2, R, v, 10.0)
        st = car2.steer; pk = 0.0; v0 = car2.speed
        for n in range(120):
            car2.step(st, 1.0, 0.0); pk = max(pk, abs(car2.body_slip))
        row[label] = {"t0_100": round(a["t0_100"], 2), "dist100_abs": round(b["dist_m"], 1), "max_lat_g_R30": round(best, 3),
                      "exit_peak_beta_deg": round(math.degrees(pk), 1), "exit_dv_2s": round((car2.speed - v0)*KMH, 1)}
    res["lite"].append(row); print(row)
json.dump(res, open("result_t7.json", "w"), indent=1)
