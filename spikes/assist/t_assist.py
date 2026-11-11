"""ASSIST ON vs OFF in controlled manoeuvres (digital pedals: 0/1 only, rise time from the preset).
  a. straight-line stop 100 -> 0 km/h (mu 1.0 / 0.5), and steering while braking
  b. corner exit: R30 at 0.75 g, throttle key down, steering held
  c. corner entry: R60 at 0.85 g, lift (and brake key), steering held
  d. standing start
  e. false detection of "countersteer" in a slalom without sliding
Writes result_assist.json."""
import json, math
from sim import make_car, G, DT, KMH, CARS, InputAssist
from common import settle_on_circle

res = {}
def mk(on, **tw):
    a = InputAssist(preset="digital", assist_on=on)
    for k, v in tw.items():
        assert hasattr(a, k), k
        setattr(a, k, v)
    return a

print("--- a. stop from 100 km/h, brake key held ---")
res["stop"] = []
for cid in CARS:
    for mu in (1.0, 0.5):
        row = {"car": cid, "mu": mu}
        for on in (False, True):
            car = make_car(cid); car.reset(0, 0, 0, 100 / KMH); a = mk(on); x0 = None; lock = 0; n = 0
            while car.speed > 0.05 and n < 3000:
                cmd, th, bk = a.step(0.0, 0.0, 1.0, car, False, False, False, mu)
                if x0 is None: x0 = car.x
                car.step(cmd, th, bk, mu); n += 1
                if min(car.wheel_util) < -1.0: lock += 1
            tag = "on" if on else "off"
            row["dist_%s_m" % tag] = round(car.x - x0, 1); row["lock_ticks_%s" % tag] = lock; row["ticks_%s" % tag] = n
            # steer while braking: hold the left key for 1.5 s
            car = make_car(cid); car.reset(0, 0, 0, 100 / KMH); a = mk(on)
            for i in range(90):
                cmd, th, bk = a.step(1.0, 0.0, 1.0, car, False, False, False, mu)
                car.step(cmd, th, bk, mu)
            row["steer+brake_lateral_m_%s" % tag] = round(car.z, 2)
            row["steer+brake_beta_deg_%s" % tag] = round(math.degrees(car.body_slip), 1)
        res["stop"].append(row); print(row)

print("--- b. corner exit: R30 0.75 g, throttle key down for 3 s, steering held ---")
res["exit"] = []
for cid in CARS:
    for label, on, tw in (("off", False, {}), ("on", True, {}), ("on, no lateral term (u<=0.97 only)", True, {"tcs_u_lo_rear": 0.97, "tcs_u_lo_front": 0.97})):
        car = make_car(cid); R = 30.0; v = math.sqrt(0.75 * G * R); settle_on_circle(car, R, v, 10.0)
        st0 = car.steer; v0 = car.speed; a = mk(on, **tw); a.thr = 0.3; pk = 0.0; spin = None; x_wide = 0.0; tmin = 1.0
        for i in range(180):
            _, th, bk = a.step(0.0, 1.0, 0.0, car, False, False, False)
            car.step(st0, th, bk)
            pk = max(pk, abs(car.body_slip))
            if spin is None and abs(car.body_slip) > math.radians(25): spin = round((i + 1) * DT, 2)
            if i > 20: tmin = min(tmin, th)
            if i == 89: dv15 = (car.speed - v0) * KMH
        row = {"car": cid, "assist": label, "peak_beta_deg": round(math.degrees(pk), 1), "spin_at_s": spin, "dv_1.5s_kmh": round(dv15, 1),
               "dv_3s_kmh": round((car.speed - v0) * KMH, 1), "min_throttle_out": round(tmin, 2),
               "ran_wide_m": round(math.hypot(car.x, car.z - R) - R, 1)}
        res["exit"].append(row); print(row)

print("--- c. corner entry: R60 0.85 g steady, then lift / brake key, steering held 2 s ---")
res["entry"] = []
for cid in CARS:
    for pedal in ("lift", "brake"):
        for label, on, tw in (("off", False, {}), ("on", True, {}), ("on, no engine-drag control", True, {"coast_thr": 0.0}),
                              ("on, no rear-slide brake limit", True, {"abs_u_lo_rear": 0.97})):
            car = make_car(cid); R = 60.0; v = math.sqrt(0.85 * G * R); settle_on_circle(car, R, v, 10.0)
            st0 = car.steer; a = mk(on, **tw); a.thr = 0.4; pk = 0.0; spin = None; v0 = car.speed; bmin = 1.0
            for i in range(120):
                _, th, bk = a.step(0.0, 0.0, 1.0 if pedal == "brake" else 0.0, car, False, False, False)
                car.step(st0, th, bk)
                pk = max(pk, abs(car.body_slip))
                if spin is None and abs(car.body_slip) > math.radians(25): spin = round((i + 1) * DT, 2)
            row = {"car": cid, "pedal": pedal, "assist": label, "peak_beta_deg": round(math.degrees(pk), 1), "spin_at_s": spin,
                   "speed_lost_kmh": round((v0 - car.speed) * KMH, 1)}
            res["entry"].append(row); print(row)

print("--- d. standing start, throttle key down (mu 1.0 / 0.5) ---")
res["launch"] = []
for cid in CARS:
    for mu in (1.0, 0.5):
        row = {"car": cid, "mu": mu}
        for on in (False, True):
            car = make_car(cid); car.reset(0, 0, 0, 0); a = mk(on); t = 0; spin_ticks = 0; t80 = None
            while t < 2400 and t80 is None:
                cmd, th, bk = a.step(0.0, 1.0, 0.0, car, False, False, False, mu); car.step(cmd, th, bk, mu); t += 1
                if car.drive_util > 1.0: spin_ticks += 1
                if car.speed * KMH >= 80: t80 = round(t * DT, 2)
            row["t0_80_%s" % ("on" if on else "off")] = t80; row["wheelspin_ticks_%s" % ("on" if on else "off")] = spin_ticks
        res["launch"].append(row); print(row)

print("--- e. slalom without sliding: is 'countersteer' ever detected? (analog sine, 70 / 95 % of full stick) ---")
res["slalom"] = []
for cid in CARS:
    for kmh in (80, 140):
        for amp in (0.7, 0.95):
            car = make_car(cid); v0 = kmh / KMH; car.reset(0, 0, 0, v0); a = InputAssist(preset="analog", assist_on=True)
            th = 0.3; cs = 0; sl = 0; pk = 0.0; psr = 0.0; n = 600
            for i in range(n):
                stick = amp * math.sin(2 * math.pi * 0.5 * i * DT)
                cmd, t2, b2 = a.step(stick, th, 0.0, car, True, True, True)
                car.step(cmd, t2, b2); th = max(0.0, min(0.8, th + 0.05 * (v0 - car.speed)))
                cs += a.counter; sl += a.slide > 0; pk = max(pk, abs(car.body_slip)); psr = max(psr, abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
            row = {"car": cid, "kmh": kmh, "stick_amp": amp, "counter_ticks": cs, "slide_ticks": sl, "of_ticks": n,
                   "peak_beta_deg": round(math.degrees(pk), 1), "peak_rear_sy": round(psr, 2)}
            res["slalom"].append(row); print(row)
json.dump(res, open("result_assist.json", "w"), indent=1)
