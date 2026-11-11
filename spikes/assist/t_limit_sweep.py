"""Sweep of the slip-angle allowance km (limit = ka*L*a/v^2 + km*alpha_peak): full stick for 3 s.
Writes result_limit_sweep.json."""
import json, math
from sim import make_car, G, DT, KMH, CARS, InputAssist

def run(cid, kmh, km, ka, mode, t_full=0.09, secs=3.0):
    car = make_car(cid); v0 = kmh / KMH; car.reset(0, 0, 0, v0)
    a = InputAssist(preset="analog", assist_on=(mode == "hold+assist"))
    a.limit_km = km; a.limit_ka = ka; a.clip_on = False; a.ana_t_full = t_full
    th = 0.3
    for _ in range(30):
        car.step(0.0, th, 0.0); th = max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
    pb = psf = psr = pg = 0.0; t07 = None; lg = 0.0; n = int(secs * 60)
    for i in range(n):
        cmd, t2, b2 = a.step(1.0, th, 0.0, car, True, True, True)
        car.step(cmd, t2, b2)
        th = 0.12 if mode == "coast" else max(0.0, min(0.7, th + 0.05 * (v0 - car.speed)))
        g = abs(car.ay) / G
        pb = max(pb, abs(car.body_slip)); pg = max(pg, g)
        psf = max(psf, abs(car.wheel_sy[0]), abs(car.wheel_sy[1])); psr = max(psr, abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))
        if t07 is None and g >= 0.7: t07 = round((i + 1) * DT, 2)
        if i >= n - 60: lg += g / 60
    return {"car": cid, "kmh": kmh, "km": km, "ka": ka, "mode": mode, "t_full": t_full, "limit_deg": round(math.degrees(a.limit), 2),
            "peak_beta_deg": round(math.degrees(pb), 1), "peak_syf": round(psf, 2), "peak_syr": round(psr, 2),
            "peak_g": round(pg, 2), "last1s_g": round(lg, 2), "t_to_0.7g": t07, "end_kmh": round(car.speed * KMH)}

if __name__ != '__main__':
    CARS = ()
out = []
for cid in CARS:
    for kmh in (100, 140, 180):
        for mode in ("coast", "hold+assist"):
            for km in (0.0, 0.1, 0.2, 0.3, 0.45, 0.65, 1.1):
                r = run(cid, kmh, km, 1.0, mode); out.append(r)
                print("%-9s %3d %-11s km %.2f lim %5.2f | beta %5.1f syf %5.2f syr %5.2f g %4.2f/%4.2f t0.7g %s" % (
                    cid, kmh, mode, km, r["limit_deg"], r["peak_beta_deg"], r["peak_syf"], r["peak_syr"], r["peak_g"], r["last1s_g"], r["t_to_0.7g"]))
print("--- slower stick (ana_t_full) at km 0.3 / 0.65, kazane + shirogane, coast ---")
for cid in ("kazane", "shirogane"):
    for kmh in (100, 180):
        for km in (0.3, 0.65):
            for tf in (0.05, 0.09, 0.25, 0.5):
                r = run(cid, kmh, km, 1.0, "coast", tf); out.append(r)
                print("%-9s %3d km %.2f t_full %.2f | beta %5.1f syf %5.2f syr %5.2f g %4.2f/%4.2f t0.7g %s" % (
                    cid, kmh, km, tf, r["peak_beta_deg"], r["peak_syf"], r["peak_syr"], r["peak_g"], r["last1s_g"], r["t_to_0.7g"]))
json.dump(out, open("result_limit_sweep.json", "w"), indent=1)
