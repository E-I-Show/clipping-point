"""Each adjustable item moved to its ends (stages 1 / 3 / 5), everything else on the preset.
Lap statistics on Akane Short (flying laps only).  Writes result_sweep.json."""
import json, sys
import t_laps
from t_laps import agg

out = []
SK = 0.76
def run(cid, analog, item, stage):
    r = agg(cid, analog, "full", SK, "%s=%d" % (item, stage + 1), levels={item: stage}, cs_car_rate=True)
    r["item"] = item; r["stage"] = stage + 1; out.append(r)
    print("%-9s %-7s %-16s stage %d | clean %d/9 spin %2d off2 %2d off4 %2d wall %2d reset %d | best clean %s mean %s" % (
        cid, r["input"], item, stage + 1, r["clean_laps"], r["spins"], r["off_2wheels"], r["off_4wheels"], r["wall_hits"], r["resets"],
        r["best_clean_lap"], r["mean_flying_lap"])); sys.stdout.flush()

for cid in ("kazane", "shirogane"):
    for analog, items in ((True, ("steer_limit", "counter", "steer_curve", "steer_speed", "throttle_curve", "brake_curve", "deadzone")),
                          (False, ("steer_limit", "counter", "steer_speed", "pedal_speed"))):
        for item in items:
            for stage in (0, 2, 4):
                run(cid, analog, item, stage)
json.dump(out, open("result_sweep.json", "w"), indent=1)
