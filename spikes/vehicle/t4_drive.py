"""Q4: do the drivetrains differ?  corner-exit throttle, trail braking, lift-off."""
import json, math
from common import *

def exit_test(cid, throttle=1.0, tcs=False, setup=None, R=30.0, g0=0.75, hold=2.0, tcs_axle=False, tcs_target=0.97):
    car = make_car(cid, setup)
    v = math.sqrt(g0*G*R)
    settle_on_circle(car, R, v, 10.0)
    st = car.steer; r0 = car.yaw_rate; v0 = car.speed; b0 = car.body_slip; k0 = r0/v0
    x0, z0 = car.x, car.z
    lim = TCS(tcs_target, tcs_axle); th = throttle
    rows = {}; peak_b = 0.0; t_lim_f = None; t_lim_r = None; spin_t = None; max_du = 0.0
    for n in range(int(hold*60)):
        car.step(st, th, 0.0)
        if tcs: th = lim(car, throttle)
        t = (n+1)*DT
        sf = max(abs(car.wheel_sy[0]), abs(car.wheel_sy[1])); sr = max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
        if t_lim_f is None and sf > 1.0: t_lim_f = t
        if t_lim_r is None and sr > 1.0: t_lim_r = t
        if spin_t is None and abs(car.body_slip) > math.radians(25): spin_t = t
        peak_b = max(peak_b, abs(car.body_slip)); max_du = max(max_du, car.drive_util)
        if (n+1) % 30 == 0:
            rows["%.1fs" % t] = {"speed_kmh": round(car.speed*KMH, 1), "yaw_ratio": round(car.yaw_rate/r0, 2),
                                 "curv_ratio": round((car.yaw_rate/max(car.speed, 1))/k0, 2),
                                 "beta_deg": round(math.degrees(car.body_slip), 1), "sy_front": round(sf, 2), "sy_rear": round(sr, 2),
                                 "util": [round(u, 2) for u in car.wheel_util], "boost": round(car.boost, 2), "gear": car.gear}
    # distance from the original circle after the hold: >0 = ran wide
    wide = math.hypot(car.x, car.z - R) - R
    if spin_t is not None: verdict = "oversteer / spin"
    elif wide > 1.0 and peak_b < math.radians(12): verdict = "understeer / runs wide"
    else: verdict = "neutral / mild"
    return {"car": cid, "throttle": throttle, "tcs": tcs, "v0_kmh": round(v0*KMH, 1), "beta0_deg": round(math.degrees(b0), 2),
            "dv_kmh_1.5s": round(rows["1.5s"]["speed_kmh"] - v0*KMH, 1), "peak_beta_deg": round(math.degrees(peak_b), 1),
            "t_front_past_peak": t_lim_f, "t_rear_past_peak": t_lim_r, "t_beta_gt_25deg": spin_t, "max_drive_util": round(max_du, 2),
            "ran_wide_m_at_end": round(wide, 2), "verdict": verdict, "rows": rows}

def brake_turn(cid, brake, throttle_hold=False, setup=None, R=60.0, g0=0.70, hold=1.0):
    car = make_car(cid, setup)
    v = math.sqrt(g0*G*R)
    drv = settle_on_circle(car, R, v, 10.0)
    st = car.steer; r0 = car.yaw_rate; v0 = car.speed; k0 = r0/v0; b0 = car.body_slip
    out = {}; peak_b = 0.0
    for n in range(int(hold*60)):
        th = drv.throttle(v) if throttle_hold else 0.0
        car.step(st, th, brake)
        peak_b = max(peak_b, abs(car.body_slip))
        if (n+1) in (30, 60):
            out["%.1fs" % ((n+1)*DT)] = {"curv_ratio": round((car.yaw_rate/max(car.speed, 1))/k0, 2), "yaw_ratio": round(car.yaw_rate/r0, 2),
                                          "beta_deg": round(math.degrees(car.body_slip), 2), "speed_kmh": round(car.speed*KMH, 1),
                                          "loads": [round(x) for x in car.wheel_load], "util": [round(u, 2) for u in car.wheel_util]}
    return {"car": cid, "brake": brake, "beta0_deg": round(math.degrees(b0), 2), "peak_beta_deg": round(math.degrees(peak_b), 2), **out}

if __name__ == "__main__":
    res = {"exit": [], "brake_turn": []}
    print("--- corner exit: R=30 m at 0.75 g, steer held, throttle applied for 2 s ---")
    for cid in CARS + ("mikazuki",):
        for th, tcs, ax in ((1.0, False, False), (0.5, False, False), (1.0, True, False), (1.0, True, True)):
            r = exit_test(cid, th, tcs, tcs_axle=ax, tcs_target=0.90 if ax else 0.97); r["tcs_axle"] = ax; res["exit"].append(r)
            tcs = ("axle.90" if ax else "wheel.97") if tcs else "off"
            print("%-9s thr %.1f tcs %-8s v0 %.1f dv(1.5s) %+5.1f km/h peak beta %5.1f deg  front>peak %s rear>peak %s spin(|b|>25) %s  max util %.2f wide %+.2f m => %s" % (
                cid, th, tcs, r["v0_kmh"], r["dv_kmh_1.5s"], r["peak_beta_deg"], r["t_front_past_peak"] and round(r["t_front_past_peak"], 2),
                r["t_rear_past_peak"] and round(r["t_rear_past_peak"], 2), r["t_beta_gt_25deg"] and round(r["t_beta_gt_25deg"], 2), r["max_drive_util"], r["ran_wide_m_at_end"], r["verdict"]))
            if th == 1.0 and not tcs:
                for k, v in r["rows"].items(): print("      ", k, v)
    print("--- brake / lift in a turn: R=60 m at 0.70 g, steer held for 1 s ---")
    for cid in CARS + ("mikazuki",):
        for label, br, hold in (("hold throttle", 0.0, True), ("lift off", 0.0, False), ("brake 0.3", 0.3, False), ("brake 0.6", 0.6, False)):
            r = brake_turn(cid, br, hold); r["case"] = label; res["brake_turn"].append(r)
            print("%-9s %-13s beta0 %5.2f | 0.5s curv x%.2f beta %6.2f | 1.0s curv x%.2f beta %6.2f deg speed %.1f | util %s" % (
                cid, label, r["beta0_deg"], r["0.5s"]["curv_ratio"], r["0.5s"]["beta_deg"], r["1.0s"]["curv_ratio"], r["1.0s"]["beta_deg"], r["1.0s"]["speed_kmh"], r["0.5s"]["util"]))
    json.dump(res, open("result_t4.json", "w"), indent=1)
