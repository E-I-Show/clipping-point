"""FR 280 ps (and kazane): too much throttle on corner exit -> the tail steps out -> the driver
answers with the opposite key (digital) / opposite stick (analog).  Countersteer relaxation
stages compared.  Writes result_counter.json."""
import json, math, sys
from sim import make_car, G, DT, KMH, InputAssist, PassThrough, SPIKES
from common import settle_on_circle     # vehicle spike helper (read only)

def run(cid, label, digital=True, counter_stage=None, raw=False, tweak=None, react=9, R=30.0, g0=0.75,
        keep_throttle=False, tcs=False, secs=5.0, speed_stage=None, steer_setup=0):
    car = make_car(cid, {"steering": steer_setup})
    v = math.sqrt(g0 * G * R)
    settle_on_circle(car, R, v, 10.0)
    st0 = car.steer; b0 = car.body_slip
    if raw:
        a = PassThrough()
    else:
        lv = {}
        if counter_stage is not None: lv["counter"] = counter_stage
        if speed_stage is not None: lv["steer_speed"] = speed_stage
        a = InputAssist(lv, preset="digital" if digital else "analog", assist_on=tcs)
        if tweak:
            for k, val in tweak.items():
                assert hasattr(a, k), k
                setattr(a, k, val)
    obs = []                      # delayed observation of (beta - b0, beta rate)
    prev_b = car.body_slip
    phase = "wait"; key = 0.0; th_in = 1.0
    pk = 0.0; pk_other = 0.0; t_detect = None; t_rec = None; max_cs = 0.0; spin = False; lim_max = 0.0
    sgn = 1.0 if b0 <= 0 else -1.0     # left circle: beta < 0 in the slide -> countersteer = right (-)
    n = int(secs * 60)
    for i in range(n):
        db = car.body_slip - b0
        rate = (car.body_slip - prev_b) / DT; prev_b = car.body_slip
        obs.append((db, rate))
        o_db, o_rate = obs[-react - 1] if len(obs) > react else (0.0, 0.0)
        if phase == "wait":
            if abs(o_db) > math.radians(4.0):
                phase = "counter"; t_detect = (i + 1) * DT
        elif phase == "counter":
            # release when the slide angle is clearly coming back, or small again
            if (o_rate * o_db < 0 and abs(o_rate) > math.radians(8.0)) or abs(o_db) < math.radians(3.0):
                phase = "release"
        elif phase == "release":
            if abs(o_db) > math.radians(6.0) and o_rate * o_db > 0:
                phase = "counter"
        if phase == "wait":
            cmd = st0; t2 = 1.0; b2 = 0.0
            if tcs and not raw:
                # same input chain as later, but the steering is held on the settled angle
                _, t2, b2 = a.step(0.0, 1.0, 0.0, car, not digital, not digital, True)
                cmd = st0
        else:
            if not keep_throttle: th_in = 0.0
            if phase == "counter":
                # counter in the direction the tail goes (sign of the observed slide)
                d = -1.0 if o_db < 0 else 1.0
                key = d if digital else max(-1.0, min(1.0, d * min(1.0, abs(o_db) / math.radians(12.0))))
            else:
                key = 0.0
            cmd, t2, b2 = a.step(key, th_in, 0.0, car, not digital, not digital, True)
        car.step(cmd, t2, b2)
        ab = abs(car.body_slip)
        if car.body_slip * (b0 if b0 != 0 else -1) >= 0 or True:
            pass
        # slide side = sign of b0's side (negative for the left circle); other side = overshoot
        if car.body_slip < 0: pk = max(pk, ab)
        else: pk_other = max(pk_other, ab)
        if phase != "wait":
            if cmd * sgn < 0: max_cs = max(max_cs, abs(car.steer))
            lim_max = max(lim_max, getattr(a, "limit", 0.0))
        if ab > math.radians(45): spin = True
        if t_detect is not None and t_rec is None and ab < math.radians(3.0) and abs(car.yaw_rate) < 0.6 and (i + 1) * DT > t_detect + 0.2:
            t_rec = (i + 1) * DT
    return {"car": cid, "config": label, "input": "digital" if digital else "analog",
            "peak_slide_deg": round(math.degrees(pk), 1), "overshoot_other_side_deg": round(math.degrees(pk_other), 1),
            "spin": spin, "detect_s": round(t_detect, 2) if t_detect else None,
            "recovered_s": round(t_rec, 2) if t_rec else None, "max_counter_steer_deg": round(math.degrees(max_cs), 1),
            "max_limit_deg": round(math.degrees(lim_max), 1), "end_kmh": round(car.speed * KMH, 1),
            "end_beta_deg": round(math.degrees(car.body_slip), 1)}

res = []
def show(r):
    res.append(r)
    print("%-9s %-34s %-7s | slide %5.1f other %5.1f spin %-5s rec %-5s cs_steer %5.1f lim %5.1f end %5.1f km/h beta %5.1f" % (
        r["car"], r["config"], r["input"], r["peak_slide_deg"], r["overshoot_other_side_deg"], r["spin"], r["recovered_s"],
        r["max_counter_steer_deg"], r["max_limit_deg"], r["end_kmh"], r["end_beta_deg"]))

for cid in ("shirogane", "kazane"):
    print("--- %s: R30 0.75 g, full throttle (no drive limiter), driver reacts 0.15 s after 4 deg ---" % cid)
    show(run(cid, "no reaction (keys untouched)", react=10 ** 6))
    show(run(cid, "raw (no compensation)", raw=True))
    for stg in range(5):
        show(run(cid, "counter stage %d" % (stg + 1), counter_stage=stg))
    for km in (0.8, 1.3):
        show(run(cid, "stage3 gain1 cs_km=%.2f" % km, counter_stage=2, tweak={"cs_km": km, "cs_gain": 1.0}))
    for rt in (1.0, 2.0, 3.0):
        show(run(cid, "stage3 cs_rate=%.1f" % rt, counter_stage=2, tweak={"cs_rate": rt}))
    for su in (-1, 1):
        show(run(cid, "stage3, car steering setup %+d" % su, counter_stage=2, steer_setup=su))
        show(run(cid, "stage1(off), car steering setup %+d" % su, counter_stage=0, steer_setup=su))
    for react in (6, 15, 24):
        show(run(cid, "stage3, reaction %.2f s" % (react / 60.0), counter_stage=2, react=react))
        show(run(cid, "stage1(off), reaction %.2f s" % (react / 60.0), counter_stage=0, react=react))
    show(run(cid, "analog stage3 (preset)", digital=False, counter_stage=2))
    show(run(cid, "analog stage1 (off)", digital=False, counter_stage=0))
    show(run(cid, "analog raw", digital=False, raw=True))
    show(run(cid, "stage3, throttle kept on", counter_stage=2, keep_throttle=True))
    show(run(cid, "assist ON (drive limiter), no reaction", react=10 ** 6, tcs=True))
json.dump(res, open("result_counter.json", "w"), indent=1)
