"""Q5: each setup item at both ends -> does the characteristic move the expected way?"""
import json, math
from common import *
from t4_drive import exit_test, brake_turn

def step_steer(car, v_kmh, steer, seconds=3.0):
    car.reset(0, 0, 0, v_kmh/KMH)
    for _ in range(60): car.step(0.0, 0.25, 0.0)
    rs = []
    for n in range(int(seconds*60)):
        car.step(steer, 0.3, 0.0); rs.append(car.yaw_rate)
    ss = sum(rs[-30:])/30; pk = max(rs)
    t90 = next((i+1 for i, r in enumerate(rs) if r >= 0.9*ss), None)
    return {"yaw_ss": ss, "t90_s": None if t90 is None else t90*DT, "overshoot_pct": (pk/ss - 1)*100 if ss else None,
            "yaw_gain_per_rad": ss/steer}

def first_lock(car):
    """ramp the pedal on a straight at 100 km/h: which axle reaches |u| >= 1 first, and at what decel."""
    car.reset(0, 0, 0, 100/KMH)
    for n in range(200):
        b = n/200.0
        car.wvx = 100/KMH; car.wvz = 0.0     # hold the speed so only the pedal changes
        car.step(0.0, 0.0, b)
        uf = -min(car.wheel_util[0], car.wheel_util[1]); ur = -min(car.wheel_util[2], car.wheel_util[3])
        if uf >= 1.0 or ur >= 1.0:
            return {"axle": "front" if uf >= ur else "rear", "pedal": round(b, 3), "decel_g": round(-car.ax/G, 3)}
    return {"axle": None}

res = {}
def show(tag, d): print("   ", tag, d)

for cid in CARS:
    res[cid] = {}
    print("=====", cid)
    for item, stages in (("gear", (-2, 0, 2)), ("wing", (-2, 0, 2)), ("suspension", (-2, 0, 2)), ("brake_bias", (-2, 0, 2)),
                         ("traction", (-2, 0, 2)), ("steering", (-1, 0, 1))):
        res[cid][item] = {}
        print("  --", item)
        for stg in stages:
            setup = {item: stg}
            car = make_car(cid, setup)
            d = {}
            if item == "gear":
                a = accel_run(car, tcs=True)
                d = {"final": round(car.final, 3), "t0_100": round(a["t0_100"], 2), "t0_400m": round(a["t0_400m"], 2), "vmax_kmh": round(a["vmax_kmh"], 1), "top_gear": a["top_gear"], "top_rpm": round(a["top_rpm"])}
            elif item == "wing":
                a = accel_run(car, tcs=True, seconds=70)
                rows, best, fail = circle_ramp(car, 150.0, 28.0, 48.0, rate=0.3)
                v150 = 150/KMH
                d = {"cla": round(car.cla, 2), "cda": round(car.cda, 2), "aero_front": round(car.aero_front, 2),
                     "downforce_N_at_150": round(0.5*1.2*car.cla*v150*v150), "vmax_kmh": round(a["vmax_kmh"], 1),
                     "max_lat_g_R150": round(best, 3), "fail_speed_kmh": fail and round(fail["speed_kmh"], 1), "fail_mode": fail and fail["mode"]}
            elif item == "suspension":
                s1 = step_steer(car, 80, 0.04)
                rows, best, fail = circle_ramp(car, 30.0, 8.0, 22.0)
                rows2, best2, fail2 = circle_ramp(make_car(cid, setup), 30.0, 8.0, 22.0, bump=1.0)
                d = {"tau_load": car.tau_load, "alpha_peak_deg": round(math.degrees(math.atan(1/car.tap_inv)), 2),
                     "step_t90_s": round(s1["t90_s"], 3), "step_overshoot_pct": round(s1["overshoot_pct"], 1),
                     "max_lat_g_smooth": round(best, 3), "max_lat_g_bump1": round(best2, 3)}
            elif item == "brake_bias":
                f = brake_run(car, 100, abs_on=False); a = brake_run(car, 100, abs_on=True)
                bt = brake_turn(cid, 0.3, setup=setup); bt2 = brake_turn(cid, 0.5, setup=setup)
                d = {"front_share": round(car.brake_front, 3), "first_lock": first_lock(make_car(cid, setup)),
                     "dist100_full_m": round(f["dist_m"], 1), "dist100_abs_m": round(a["dist_m"], 1),
                     "turn_brake0.3_curv_x_1s": bt["1.0s"]["curv_ratio"], "turn_brake0.3_beta_1s": bt["1.0s"]["beta_deg"],
                     "turn_brake0.5_curv_x_1s": bt2["1.0s"]["curv_ratio"], "turn_brake0.5_peak_beta": bt2["peak_beta_deg"]}
            elif item == "traction":
                e1 = exit_test(cid, 1.0, False, setup); e2 = exit_test(cid, 0.6, False, setup)
                rows, best, fail = circle_ramp(car, 30.0, 8.0, 22.0)
                near = [r for r in rows if abs(r[2] - 0.7) < 0.02 and r[0] > 5]
                extra = math.degrees(sum(r[3] for r in near)/len(near) - car.L/30.0) if near else None
                lo = brake_turn(cid, 0.0, setup=setup)
                d = {"lsd_lock": car.lsd_lock, "exit_full_dv_1.5s": e1["dv_kmh_1.5s"], "exit_full_peak_beta": e1["peak_beta_deg"], "exit_full": e1["verdict"],
                     "exit_0.6_dv_1.5s": e2["dv_kmh_1.5s"], "exit_0.6_peak_beta": e2["peak_beta_deg"], "exit_0.6_wide_m": e2["ran_wide_m_at_end"],
                     "steady_extra_steer_deg_0.7g": extra and round(extra, 3), "liftoff_curv_x_1s": lo["1.0s"]["curv_ratio"]}
            elif item == "steering":
                c2 = make_car(cid, setup); c2.reset(0, 0, 0, 0)
                n = 0
                while c2.steer < 0.3 and n < 600: c2.step(0.3, 0, 0); n += 1
                s1 = step_steer(car, 60, 0.06)
                d = {"steer_rate": car.steer_rate, "t_0_to_0.3rad_s": round(n*DT, 3), "step_t90_s": round(s1["t90_s"], 3), "overshoot_pct": round(s1["overshoot_pct"], 1)}
            res[cid][item][str(stg)] = d
            show("%+d" % stg, d)
json.dump(res, open("result_t5.json", "w"), indent=1)
