"""Bake the ideal line (lateral offsets) into the track JSON and estimate lap times (spike tool).
All car numbers are PROVISIONAL."""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import track as T  # noqa: E402

PS = 735.5
# PROVISIONAL car table: peak power * drivetrain efficiency * average-power factor
CARS = {
    "A_SHIROGANE_FR_280ps_1340kg": {"power_w": 280 * PS * 0.85 * 0.92, "mass": 1340 + 70, "a_trac_g": 0.60, "cda": 0.62},
    "A_ARASHI_4WD_280ps_1390kg": {"power_w": 280 * PS * 0.80 * 0.92, "mass": 1390 + 70, "a_trac_g": 0.95, "cda": 0.64},
    "B_TSUBAME_FF_165ps_1040kg": {"power_w": 165 * PS * 0.87 * 0.92, "mass": 1040 + 70, "a_trac_g": 0.55, "cda": 0.60},
    "B_KAZANE_FR_145ps_960kg": {"power_w": 145 * PS * 0.87 * 0.92, "mass": 960 + 70, "a_trac_g": 0.58, "cda": 0.56},
}


def car_params(c, lat_g):
    return {"a_lat": lat_g * T.G, "a_brake": lat_g * T.G, "a_trac": c["a_trac_g"] * T.G,
            "power_w": c["power_w"], "mass": c["mass"], "cda": c["cda"], "crr": 0.015, "v_cap": 75.0}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "akane_short.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.pop("ideal", None)
    tr = T.Track(data)
    margin = 1.3
    t0 = time.perf_counter()
    d = T.relax_racing_line(tr, margin=margin)
    t_relax = time.perf_counter() - t0
    k = tr.n // 2
    stations = [round(d[int(round(i * tr.n / float(k))) % tr.n], 3) for i in range(k)]
    data["ideal"] = {"baked_length": round(tr.length, 3), "margin": margin, "d": stations,
                     "notes": "lateral offsets at k = len(d) equally spaced stations, PROVISIONAL"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    tr2 = T.load_track(path)
    res = {"relax_seconds": t_relax, "stations": k, "rows": []}
    center = [0.0] * tr.n
    for name, c in CARS.items():
        for lat in (1.0, 1.05, 1.1):
            t0 = time.perf_counter()
            pi = T.speed_profile(tr2, tr2._ideal_d, car_params(c, lat))
            t_prof = time.perf_counter() - t0
            pc = T.speed_profile(tr2, center, car_params(c, lat))
            res["rows"].append({"car": name, "lat_g": lat, "lap_ideal_s": round(pi["lap_time"], 2),
                                "lap_center_s": round(pc["lap_time"], 2),
                                "v_min_kmh": round(pi["v_min"] * 3.6, 1), "v_max_kmh": round(pi["v_max"] * 3.6, 1),
                                "line_length_m": round(pi["line_length"], 1), "profile_ms": round(t_prof * 1000, 2)})
    ref = T.speed_profile(tr2, tr2._ideal_d)
    res["ref_car_lap_s"] = round(ref["lap_time"], 2)
    kap = ref["kappa"]
    res["line_min_radius_m"] = round(1.0 / max(abs(v) for v in kap), 1)
    res["max_abs_d"] = round(max(abs(v) for v in tr2._ideal_d), 2)
    # per-corner minimum target speed of the reference car
    res["corner_speeds_kmh"] = []
    for c in tr2.corners:
        i0 = int(c["s0"] / tr2.ds)
        i1 = int(c["s1"] / tr2.ds)
        res["corner_speeds_kmh"].append({"name": c["name"],
                                         "v_min": round(min(ref["v"][i % tr2.n] for i in range(i0, i1 + 1)) * 3.6, 1)})
    with open(os.path.join(HERE, "out_ideal.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    print("relax %.2f s, line min radius %.1f m, max |d| %.2f" % (t_relax, res["line_min_radius_m"], res["max_abs_d"]))
    for r in res["rows"]:
        print("%-30s lat %.2fg  ideal %6.2f s  center %6.2f s  vmin %5.1f vmax %5.1f km/h  line %.1f m  profile %.1f ms"
              % (r["car"], r["lat_g"], r["lap_ideal_s"], r["lap_center_s"], r["v_min_kmh"], r["v_max_kmh"],
                 r["line_length_m"], r["profile_ms"]))
    print("corner v_min (ref car):", res["corner_speeds_kmh"])


if __name__ == "__main__":
    main()
