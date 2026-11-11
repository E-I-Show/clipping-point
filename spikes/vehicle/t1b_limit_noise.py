"""Q1 (cont.): tick-to-tick zigzag at the cornering limit, on changing surfaces, and in reverse."""
import json, math
from common import *
from t1_stability import flips, zig, cfg  # noqa (re-runs nothing: guarded below)
out = []
for cid in CARS:
    for nsub in (1, 2, 4):
        car = cfg(cid, nsub, 1.0, 0.5)
        R = 30.0; v = math.sqrt(0.84*G*R)
        drv = CircleDriver(car, R, v); lim = TCS()
        ays = []; rs = []; sts = []
        for n in range(60*14):
            st, e = drv.steer()
            car.step(st, lim(car, drv.throttle(v)), 0.0)
            if n >= 60*9: ays.append(car.ay); rs.append(car.yaw_rate); sts.append(car.steer)
        m_ay = sum(ays)/len(ays)
        # alternating surface every 6 ticks while cornering and braking lightly
        car2 = cfg(cid, nsub, 1.0, 0.5); car2.reset(0, 0, 0, 30.0)
        ok = True; pk = 0.0
        for n in range(600):
            mu = 1.0 if (n//6) % 2 == 0 else 0.45
            car2.step(0.06, 0.5 if n < 300 else 0.0, 0.0 if n < 300 else 0.5, mu, DT, 0.0 if (n//6) % 2 == 0 else 1.0)
            pk = max(pk, abs(car2.yaw_rate))
            if not math.isfinite(car2.x + car2.z + car2.heading): ok = False; break
        # reverse gear: back up with steering, then stop
        car3 = cfg(cid, nsub, 1.0, 0.5); car3.reset(0, 0, 0, 0.0); car3.auto = False
        car3.shift(-1)
        for n in range(240): car3.step(0.3, 0.5, 0.0)
        rev = (car3.vx, car3.yaw_rate, car3.gear)
        n = 0
        while n < 600 and (car3.speed != 0.0 or car3.yaw_rate != 0.0): car3.step(0.3, 0.0, 1.0); n += 1
        row = {"car": cid, "substeps": nsub, "limit_ay_g": m_ay/G, "ay_zigzag_rel": zig(ays)/abs(m_ay), "yaw_flip_ratio": flips(rs),
               "yaw_zigzag_rel": zig(rs)/abs(sum(rs)/len(rs)), "surface_switch_finite": ok, "surface_switch_peak_yaw": pk,
               "reverse_vx": rev[0], "reverse_yaw": rev[1], "reverse_gear": rev[2], "reverse_stop_s": n*DT, "reverse_rest": car3.speed == 0.0}
        out.append(row)
        print("%-9s n=%d limit %.3f g ay_zig %.5f yaw_zig %.5f flip %.2f | mu-switch finite %s peak yaw %.2f | reverse vx %.2f yaw %.3f stop %.2fs rest %s" % (
            cid, nsub, row["limit_ay_g"], row["ay_zigzag_rel"], row["yaw_zigzag_rel"], row["yaw_flip_ratio"], ok, pk, rev[0], rev[1], n*DT, row["reverse_rest"]))
json.dump(out, open("result_t1b.json", "w"), indent=1)
