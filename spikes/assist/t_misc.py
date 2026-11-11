"""(1) cost of one InputAssist.step, (2) running the compensation at 30 Hz instead of 60 Hz,
(3) config validation negative tests, (4) adapter helpers.  Writes result_misc.json."""
import json, math, time, copy
import input_assist as ia
from sim import make_car, G, DT, KMH, InputAssist, run_laps
import sim
from common import settle_on_circle

res = {}
# ---- 1. cost -------------------------------------------------------------------------------
car = make_car("shirogane"); car.reset(0, 0, 0, 30.0)
for _ in range(60): car.step(0.03, 0.5, 0.0)
for label, analog, on in (("analog, assist on", True, True), ("digital, assist on", False, True), ("analog, assist off", True, False)):
    a = InputAssist(preset="analog" if analog else "digital", assist_on=on)
    best = 1e9
    for rep in range(5):
        t0 = time.perf_counter()
        for i in range(20000):
            a.step(0.4 if analog else 1.0, 0.7 if analog else 1.0, 0.0, car, analog, analog, analog)
        best = min(best, (time.perf_counter() - t0) / 20000)
    res.setdefault("step_cost_us", {})[label] = round(best * 1e6, 2)
print("step cost (us):", res["step_cost_us"])

# ---- 2. 30 Hz compensation -----------------------------------------------------------------
class Every2(object):
    """Runs the wrapped assist every 2nd tick with dt = 2/60 and holds its outputs in between."""
    def __init__(self, inner): self.inner = inner; self.n = 0; self.out = (0.0, 0.0, 0.0)
    def __getattr__(self, k): return getattr(self.inner, k)
    def reset(self): self.inner.reset(); self.n = 0
    def step(self, st, th, bk, car, sa=True, ta=True, ba=True, mu=1.0, dt=DT):
        if self.n % 2 == 0:
            self.out = self.inner.step(st, th, bk, car, sa, ta, ba, mu, 2 * DT)
        self.n += 1
        return self.out

def stop(decim, mu=1.0):
    car = make_car("shirogane"); car.reset(0, 0, 0, 100 / KMH)
    a = InputAssist(preset="digital", assist_on=True); a = Every2(a) if decim else a
    x0 = car.x; lock = 0; n = 0
    while car.speed > 0.05 and n < 3000:
        cmd, th, bk = a.step(0.0, 0.0, 1.0, car, False, False, False, mu); car.step(cmd, th, bk, mu); n += 1
        lock += min(car.wheel_util) < -1.0
    return round(car.x - x0, 1), lock
def exit_(decim):
    car = make_car("shirogane"); R = 30.0; settle_on_circle(car, R, math.sqrt(0.75 * G * R), 10.0)
    st0 = car.steer; v0 = car.speed; a = InputAssist(preset="digital", assist_on=True); a.thr = 0.3; a = Every2(a) if decim else a; pk = 0.0
    for i in range(180):
        _, th, bk = a.step(0.0, 1.0, 0.0, car, False, False, False); car.step(st0, th, bk); pk = max(pk, abs(car.body_slip))
    return round(math.degrees(pk), 1), round((car.speed - v0) * KMH, 1)
res["rate_30hz"] = {"stop_100_0_m_and_lock_ticks": {"60Hz": stop(False), "30Hz": stop(True), "60Hz_mu0.5": stop(False, 0.5), "30Hz_mu0.5": stop(True, 0.5)},
                    "exit_peak_beta_deg_and_dv3s": {"60Hz": exit_(False), "30Hz": exit_(True)}}
print(res["rate_30hz"])
# laps with the compensation at 30 Hz: patch the factory used by run_laps
orig = sim.InputAssist
rows = []
for decim in (False, True):
    sim.InputAssist = (lambda *a, **k: Every2(orig(*a, **k))) if decim else orig
    for cid in ("kazane", "shirogane"):
        for analog in (True, False):
            tot = {"spins": 0, "off2": 0, "off4": 0, "walls": 0, "resets": 0}; clean = 0; fl = []
            for seed in (1, 2, 3):
                r = run_laps(cid, analog, "full", laps=3, seed=seed, driver_kw={"skill": 0.76}, cs_car_rate=True)
                for k in tot: tot[k] += r["fly"][k]
                clean += r["clean_laps"]; fl += r["flying"]
            row = {"hz": 30 if decim else 60, "car": cid, "input": "analog" if analog else "digital", "clean_laps_of_9": clean,
                   "mean_flying": round(sum(fl) / len(fl), 2) if fl else None}
            row.update(tot); rows.append(row); print(row)
sim.InputAssist = orig
res["laps_30hz_vs_60hz"] = rows

# ---- 3. config validation: broken data must be rejected ------------------------------------
cases = []
def bad(name, fn):
    c = copy.deepcopy(ia.DEFAULT_CONFIG); fn(c)
    try:
        ia.validate_config(c); cases.append((name, "ACCEPTED (bad)"))
    except ia.AssistConfigError as e:
        cases.append((name, "rejected"))
    except Exception as e:
        cases.append((name, "unexpected %s" % type(e).__name__))
bad("unknown top key", lambda c: c.__setitem__("foo", 1))
bad("missing items", lambda c: c.pop("items"))
bad("4 stages", lambda c: c["items"]["steer_curve"]["values"]["steer_k"].pop())
bad("non monotonic", lambda c: c["items"]["steer_limit"]["values"]["limit_km"].__setitem__(2, 9.0))
bad("NaN", lambda c: c["items"]["deadzone"]["values"]["steer_dz"].__setitem__(0, float("nan")))
bad("bool as number", lambda c: c["items"]["deadzone"]["values"]["steer_dz"].__setitem__(0, True))
bad("curve k > 1", lambda c: c["items"]["steer_curve"]["values"]["steer_k"].__setitem__(4, 1.5))
bad("zero time", lambda c: c["items"]["pedal_speed"]["values"]["thr_t_up"].__setitem__(4, 0.0))
bad("non ASCII label", lambda c: c["items"]["counter"].__setitem__("label", "カウンター"))
bad("preset stage 5", lambda c: c["presets"]["analog"].__setitem__("counter", 5))
bad("preset missing item", lambda c: c["presets"]["digital"].pop("deadzone"))
bad("unknown fixed key", lambda c: c["fixed"].__setitem__("zzz", 1.0))
bad("limit_mode typo", lambda c: c["fixed"].__setitem__("limit_mode", "phys"))
bad("reversed pair", lambda c: c["fixed"].__setitem__("cs_slide1", 0.5))
bad("wrong version", lambda c: c.__setitem__("version", 2))
try:
    InputAssist({"steer_curve": 7}); cases.append(("level out of range", "ACCEPTED (bad)"))
except ia.AssistConfigError: cases.append(("level out of range", "rejected"))
try:
    InputAssist({"nope": 1}); cases.append(("unknown level item", "ACCEPTED (bad)"))
except ia.AssistConfigError: cases.append(("unknown level item", "rejected"))
ok = ia.load_config("assist_config.json") == ia.DEFAULT_CONFIG
res["validation"] = {"cases": len(cases), "rejected": sum(1 for c in cases if c[1] == "rejected"), "detail": cases, "file_round_trip_equal": ok}
print("validation:", res["validation"]["rejected"], "/", len(cases), "file round trip", ok)

# ---- 4. adapter helpers --------------------------------------------------------------------
res["adapter"] = {"stick_from_device(-32768)": ia.stick_from_device(-32768), "stick_from_device(16384)": round(ia.stick_from_device(16384), 4),
                  "pedals_from_stick_y(-0.6)": ia.pedals_from_stick_y(-0.6), "pedals_from_stick_y(0.8)": ia.pedals_from_stick_y(0.8),
                  "digital_axis(L)": ia.digital_axis(True, False), "digital_axis(both)": ia.digital_axis(True, True),
                  "is_two_valued([0,1,1,0])": ia.is_two_valued([0, 1, 1, 0]), "is_two_valued([0,0.4,1])": ia.is_two_valued([0, 0.4, 1])}
print(res["adapter"])
json.dump(res, open("result_misc.json", "w"), indent=1)
