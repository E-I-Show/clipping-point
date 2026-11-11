"""Static tables + open-loop steering tests in the vehicle model (no course).
  1. response-curve table (cubic blend vs power)
  2. speed-dependent limit table
  3. full stick at speed: does the front axle stay near its peak?  (limit modes compared)
  4. digital tap / hold on a straight
Writes result_steer.json."""
import json
import math
from sim import make_car, G, DT, KMH, CARS, InputAssist, PassThrough
import input_assist as ia

res = {}

# ---- 1. curves -------------------------------------------------------------------------------
rows = []
for k in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
    p = ia.cubic_k_to_power(k)
    rows.append({"k": k, "slope_at_centre": round(1 - k, 2), "equiv_power_p": round(p, 3),
                 "cubic": [round(ia.curve_cubic(x, k), 3) for x in (0.1, 0.25, 0.5, 0.75, 0.9)],
                 "power": [round(ia.curve_power(x, p), 3) for x in (0.1, 0.25, 0.5, 0.75, 0.9)]})
res["curves_x_0.1_0.25_0.5_0.75_0.9"] = rows
for r in rows:
    print(r)

# ---- 2. limit table --------------------------------------------------------------------------
car = make_car("shirogane")
ap = math.atan(1.0 / car.tap_inv)
tab = []
for kmh in (0, 20, 40, 60, 80, 100, 120, 150, 180, 220, 260):
    v = kmh / KMH
    row = {"kmh": kmh, "kinematic_L*a/v^2_deg": round(math.degrees(min(0.55, car.L * car.mu_tire * G / v / v)) if v > 0 else 31.5, 2)}
    for st in range(5):
        a = InputAssist({"steer_limit": st}, preset="analog")
        car.reset(0, 0, 0, v)
        row["physics_stage%d_deg" % (st + 1)] = round(math.degrees(a.base_limit(car)), 2)
    row["simple_deg"] = round(math.degrees(ia.speed_limit_simple(v, 0.55, 11.0, 0.10)), 2)
    tab.append(row)
    print(row)
res["limit_table_shirogane"] = tab
res["alpha_peak_deg"] = round(math.degrees(ap), 2)


# ---- 3. full stick at speed ------------------------------------------------------------------
def full_stick(cid, kmh, mode, digital=False, secs=3.0, assist_on=False, coast=False):
    car = make_car(cid)
    v0 = kmh / KMH
    car.reset(0, 0, 0, v0)
    if mode == "raw":
        a = PassThrough()
    else:
        a = InputAssist(preset="digital" if digital else "analog", assist_on=assist_on)
        if mode == "simple":
            a.limit_mode = "simple"; a.clip_on = False
        elif mode == "physics_wide":
            a.limit_km = 1.10; a.limit_ka = 1.30; a.clip_on = False
        elif mode == "physics_mid":
            a.clip_on = False
        elif mode == "physics_tight":
            a.limit_km = 0.38; a.limit_ka = 0.80; a.clip_on = False
        elif mode == "physics_mid+clip":
            pass
        elif mode == "clip_only":
            a.limit_mode = "none"
        else:
            raise ValueError(mode)
    th = 0.3
    for _ in range(30):
        car.step(0.0, th, 0.0)
        th = max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
    pk_syf = pk_syr = pk_g = pk_b = 0.0
    st_syf = st_g = 0.0
    nst = 0
    spin = None
    pk_steer = 0.0
    n = int(secs * 60)
    for i in range(n):
        cmd, t2, b2 = a.step(1.0, th, 0.0, car, not digital, True, True)
        car.step(cmd, t2, b2)
        th = 0.12 if coast else max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
        syf = max(abs(car.wheel_sy[0]), abs(car.wheel_sy[1]))
        syr = max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
        g = abs(car.ay) / G
        pk_syf = max(pk_syf, syf); pk_syr = max(pk_syr, syr); pk_g = max(pk_g, g)
        pk_b = max(pk_b, abs(car.body_slip)); pk_steer = max(pk_steer, abs(car.steer))
        if spin is None and abs(car.body_slip) > math.radians(25):
            spin = round((i + 1) * DT, 2)
        if i >= n - 60:
            st_syf += syf; st_g += g; nst += 1
    return {"car": cid, "kmh": kmh, "mode": mode, "throttle": "coast0.12" if coast else ("hold+assist" if assist_on else "hold"),
            "peak_steer_deg": round(math.degrees(pk_steer), 2),
            "peak_front_sy": round(pk_syf, 2), "last1s_front_sy": round(st_syf / nst, 2),
            "peak_rear_sy": round(pk_syr, 2), "peak_lat_g": round(pk_g, 2), "last1s_lat_g": round(st_g / nst, 2),
            "peak_beta_deg": round(math.degrees(pk_b), 1), "spin_at_s": spin,
            "end_kmh": round(car.speed * KMH, 1)}


MODES = ("raw", "simple", "physics_wide", "physics_mid", "physics_tight", "physics_mid+clip", "clip_only")
res["full_stick"] = []
print("--- full stick (analog) held 3 s ---")
for cid in CARS:
    for kmh in (60, 100, 140, 180):
        for mode in MODES:
            for kw in ({}, {"assist_on": True}, {"coast": True}):
                if mode == "raw" and kw.get("assist_on"):
                    continue
                r = full_stick(cid, kmh, mode, **kw)
                res["full_stick"].append(r)
res["full_stick_digital"] = []
for cid in CARS:
    for kmh in (60, 100, 140, 180):
        for kw in ({}, {"assist_on": True}, {"coast": True}):
            r = full_stick(cid, kmh, "physics_mid+clip", digital=True, **kw)
            r["mode"] = "digital_preset"
            res["full_stick_digital"].append(r)
for x in res["full_stick"] + res["full_stick_digital"]:
    print("%-9s %3d %-17s %-11s | steer %5.1f syf %6.2f /%5.2f syr %6.2f g %4.2f /%4.2f beta %5.1f spin %s" % (
        x["car"], x["kmh"], x["mode"], x["throttle"], x["peak_steer_deg"], x["peak_front_sy"], x["last1s_front_sy"],
        x["peak_rear_sy"], x["peak_lat_g"], x["last1s_lat_g"], x["peak_beta_deg"], x["spin_at_s"]))


# ---- 4. digital tap / hold on a straight ------------------------------------------------------
def tap(cid, kmh, ticks, mode, speed_stage=2, secs=3.0):
    car = make_car(cid)
    v0 = kmh / KMH
    car.reset(0, 0, 0, v0)
    a = PassThrough() if mode == "raw" else InputAssist({"steer_speed": speed_stage}, preset="digital", assist_on=False)
    th = 0.3
    for _ in range(30):
        car.step(0.0, th, 0.0)
        th = max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
    z0 = car.z
    pk_steer = pk_r = pk_b = pk_syf = pk_syr = pk_g = 0.0
    spin = False
    for i in range(int(secs * 60)):
        key = 1.0 if i < ticks else 0.0
        cmd, t2, b2 = a.step(key, th, 0.0, car, False, True, True)
        car.step(cmd, t2, b2)
        th = max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
        pk_steer = max(pk_steer, abs(car.steer)); pk_r = max(pk_r, abs(car.yaw_rate))
        pk_b = max(pk_b, abs(car.body_slip)); pk_g = max(pk_g, abs(car.ay) / G)
        pk_syf = max(pk_syf, abs(car.wheel_sy[0]), abs(car.wheel_sy[1]))
        pk_syr = max(pk_syr, abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
        if abs(car.body_slip) > math.radians(25):
            spin = True
    return {"car": cid, "kmh": kmh, "key_ms": round(ticks * DT * 1000), "mode": mode, "speed_stage": speed_stage + 1,
            "peak_steer_deg": round(math.degrees(pk_steer), 2), "frac_of_limit": round(pk_steer / max(1e-9, a.limit), 2) if mode != "raw" else round(pk_steer / 0.55, 2),
            "peak_yaw_deg_s": round(math.degrees(pk_r), 1), "peak_lat_g": round(pk_g, 2),
            "heading_change_deg": round(math.degrees(car.heading), 1), "lateral_m_3s": round(car.z - z0, 2),
            "peak_beta_deg": round(math.degrees(pk_b), 1), "peak_front_sy": round(pk_syf, 2), "peak_rear_sy": round(pk_syr, 2),
            "spin": spin, "final_yaw_rate": round(car.yaw_rate, 4)}


res["tap"] = []
print("--- digital tap on a straight ---")
for cid in ("kazane", "shirogane"):
    for kmh in (120, 180):
        for ticks in (3, 6, 12, 30):
            for mode, stg in (("raw", 2), ("assist", 0), ("assist", 2), ("assist", 4)):
                r = tap(cid, kmh, ticks, mode, stg)
                res["tap"].append(r)
                print(r)

# hold: time to 50 / 95 % of the limit, and the fraction after a 50 ms tap, per stage
res["hold"] = []
print("--- digital hold: time to reach the limit ---")
for stg in range(5):
    for kmh in (40, 120):
        car = make_car("kazane")
        car.reset(0, 0, 0, kmh / KMH)
        a = InputAssist({"steer_speed": stg}, preset="digital", assist_on=False)
        a.clip_on = False
        t50 = t95 = None
        f3 = None
        for i in range(120):
            cmd, t2, b2 = a.step(1.0, 0.0, 0.0, car, False, True, True)
            # hold the speed: only the actuator is of interest here
            car.steer += max(-car.steer_rate * DT, min(car.steer_rate * DT, cmd - car.steer))
            fr = car.steer / a.limit
            if i == 2:
                f3 = fr
            if t50 is None and fr >= 0.5:
                t50 = (i + 1) * DT
            if t95 is None and fr >= 0.95:
                t95 = (i + 1) * DT
        # release
        tr = None
        for i in range(120):
            cmd, t2, b2 = a.step(0.0, 0.0, 0.0, car, False, True, True)
            car.steer += max(-car.steer_rate * DT, min(car.steer_rate * DT, cmd - car.steer))
            if tr is None and car.steer / a.limit <= 0.05:
                tr = (i + 1) * DT
        row = {"steer_speed_stage": stg + 1, "kmh": kmh, "limit_deg": round(math.degrees(a.limit), 2),
               "frac_after_50ms": round(f3, 3), "t50_s": round(t50, 3) if t50 else None, "t95_s": round(t95, 3) if t95 else None,
               "release_to_5pct_s": round(tr, 3) if tr else None, "car_rate_limited": a.limit / a.dig_t_full * 1.28 > car.steer_rate}
        res["hold"].append(row)
        print(row)

json.dump(res, open("result_steer.json", "w"), indent=1)
print("wrote result_steer.json")
