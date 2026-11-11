"""Q3 plausibility: 0-100, top speed, 100-0, steady-state max lateral g.  Q4a understeer gradient."""
import json, math
from common import *
out = {}
for cid in CARS + ("mikazuki",):
    car = make_car(cid)
    r = {}
    a = accel_run(car, tcs=False); b = accel_run(car, tcs=True)
    r["accel_full_throttle"] = a; r["accel_tcs_driver"] = b
    r["brake_100_full_pedal"] = brake_run(car, 100, abs_on=False)
    r["brake_100_abs_driver"] = brake_run(car, 100, abs_on=True)
    r["brake_200_abs_driver"] = brake_run(car, 200 if cid not in ("x",) else 150, abs_on=True)
    for R, v0, v1 in ((30.0, 8.0, 22.0), (80.0, 15.0, 35.0)):
        rows, best, fail = circle_ramp(car, R, v0, v1)
        # understeer gradient: steer needed beyond Ackermann at given lateral g
        ack = car.L / R
        grad = {}
        for target in (0.3, 0.5, 0.7, 0.85):
            near = [row for row in rows if abs(row[2] - target) < 0.02 and row[0] > 5]
            if near:
                st = sum(x[3] for x in near)/len(near)
                grad["%.2fg" % target] = {"steer_deg": round(math.degrees(st), 3), "extra_deg": round(math.degrees(st - ack), 3),
                                          "body_slip_deg": round(math.degrees(sum(x[4] for x in near)/len(near)), 2),
                                          "slipF_deg": round(math.degrees(sum(x[5] for x in near)/len(near)), 2),
                                          "slipR_deg": round(math.degrees(sum(x[6] for x in near)/len(near)), 2)}
        r["circle_R%d" % R] = {"max_lat_g": round(best, 3), "ackermann_deg": round(math.degrees(ack), 3), "by_g": grad, "fail": fail}
    out[cid] = r
    print(cid)
    print("  0-100 full %.2f s / tcs %.2f s ; 0-400m full %.2f / tcs %.2f ; vmax %.1f km/h (gear %d, %.0f rpm)" % (
        a["t0_100"], b["t0_100"], a["t0_400m"], b["t0_400m"], a["vmax_kmh"], a["top_gear"], a["top_rpm"]))
    print("  100-0 full pedal %.1f m (peak %.2f g) / abs %.1f m (peak %.2f g) ; 200-0 abs %.1f m" % (
        r["brake_100_full_pedal"]["dist_m"], r["brake_100_full_pedal"]["peak_decel_g"], r["brake_100_abs_driver"]["dist_m"],
        r["brake_100_abs_driver"]["peak_decel_g"], r["brake_200_abs_driver"]["dist_m"]))
    for k in ("circle_R30", "circle_R80"):
        c = r[k]
        print("  %s max %.3f g, ackermann %.2f deg, fail=%s" % (k, c["max_lat_g"], c["ackermann_deg"], c["fail"]))
        for g, v in c["by_g"].items(): print("     ", g, v)
json.dump(out, open("result_t3.json", "w"), indent=1)
