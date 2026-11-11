"""(incident counts = flying laps only; the standing-start lap is excluded)
Lap comparison on Akane Short: 4 cars x analog / digital driver x compensation modes.
  full  = compensation + ASSIST ON, steer = compensation only (ASSIST OFF), raw = no compensation
  (raw analog is run twice: same stick gain as the others, and a low gain tuned for the raw mapping)
Writes result_laps.json."""
import json, sys, time
from sim import run_laps, CARS

SEEDS = (1, 2, 3)
LAPS = 3
def agg(cid, analog, mode, skill, label=None, **kw):
    tot = {"spins": 0, "off2": 0, "off4": 0, "walls": 0, "resets": 0, "clean_laps": 0, "laps_done": 0}
    bests = []; cleans = []; flying = []
    dk = dict(kw.pop("driver_kw", {})); dk["skill"] = skill
    for seed in SEEDS:
        r = run_laps(cid, analog, mode, laps=LAPS, seed=seed, driver_kw=dk, **kw)
        for k in tot: tot[k] += r["fly"][k] if k in r["fly"] else r[k]
        tot["laps_done"] -= 1          # lap 0 (standing start) is not a flying lap
        if r["best_clean"] is not None: cleans.append(r["best_clean"])
        flying += r["flying"]
    row = {"car": cid, "input": "analog" if analog else "digital", "mode": label or mode, "skill": skill,
           "flying_laps_done": max(0, tot["laps_done"]), "of": LAPS * len(SEEDS), "clean_laps": tot["clean_laps"],
           "spins": tot["spins"], "off_2wheels": tot["off2"], "off_4wheels": tot["off4"], "wall_hits": tot["walls"],
           "resets": tot["resets"], "best_clean_lap": min(cleans) if cleans else None,
           "mean_flying_lap": round(sum(flying) / len(flying), 2) if flying else None, "driver_est_lap": r["driver_est_lap"]}
    return row

def show(r):
    print("%-9s %-7s %-22s skill %.2f | laps %d/%d clean %d spin %2d off2 %2d off4 %2d wall %2d reset %2d | best clean %s mean %s (plan %.1f)" % (
        r["car"], r["input"], r["mode"], r["skill"], r["flying_laps_done"], r["of"], r["clean_laps"], r["spins"], r["off_2wheels"],
        r["off_4wheels"], r["wall_hits"], r["resets"], r["best_clean_lap"], r["mean_flying_lap"], r["driver_est_lap"]))
    sys.stdout.flush()

if __name__ == "__main__":
    t0 = time.time(); out = []
    for cid in CARS:
        for analog in (True, False):
            for skill in (0.72, 0.80):
                for mode, label, kw in (("full", "full", {"cs_car_rate": True}),
                                        ("full", "full(car rate fixed)", {}),
                                        ("steer", "steer only", {"cs_car_rate": True}),
                                        ("raw", "raw", {})):
                    r = agg(cid, analog, mode, skill, label, **kw); out.append(r); show(r)
                if analog:
                    r = agg(cid, analog, "raw", skill, "raw, low stick gain", driver_kw={"kp": 1.5}); out.append(r); show(r)
    json.dump(out, open("result_laps.json", "w"), indent=1)
    print("seconds", round(time.time() - t0, 1))
