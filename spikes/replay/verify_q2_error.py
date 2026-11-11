"""Q2: quantization + interpolation error of 20 Hz / 30 Hz records drawn at 30 fps (and at every
60 Hz tick = what slow motion shows), linear vs Catmull-Rom (cubic Hermite with finite-difference
velocities). Ground truth = the 60 Hz synthetic drive. Writes q2_error.json."""
import json
import math
import sys

import mkreplay
import replay as R
import synth

FOCAL_PX = 120.0 / math.tan(math.radians(30.0))   # 240 px tall, 60 deg vertical fov -> 207.8 px/rad
CHASE_DIST = 6.0


def stats(v):
    if not v:
        return None
    v = sorted(v)
    n = len(v)
    return {"n": n, "rms": math.sqrt(sum(x * x for x in v) / n), "p50": v[n // 2], "p99": v[int(n * 0.99)],
            "max": v[-1]}


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def run(sim, div, interp, tick_step):
    rp, _ = mkreplay.build(len(sim["ticks"]), 0, div, sim=sim)
    rp = R.load_cpr(R.dump_cpr(rp))          # go through the file so the numbers are of decoded data
    pl = R.Player(rp)
    n_cars = rp.n_cars
    nt = (rp.n_samples - 1) * div
    win = {}
    for (t, c) in sim["marks"]["contact"]:
        for k in range(t - 6, t + 13):
            win[(c, k)] = "contact"
    for (t, c) in sim["marks"]["offtrack"]:
        for k in range(t - 3, t + 215):
            win[(c, k)] = "offtrack"
    for (t, c) in sim["marks"]["spin"]:
        for k in range(t - 3, t + 100):
            win[(c, k)] = "spin"
    acc = {k: {"pos": [], "yaw": [], "pitch": [], "roll": [], "disp": [], "speed": []}
           for k in ("all", "normal", "contact", "spin", "offtrack")}
    onsample = {"pos": [], "yaw": [], "pitch": [], "roll": [], "steer": [], "rpm": []}
    prev = [None] * n_cars
    for t in range(180, nt, tick_step):       # skip the 3 s on the grid
        pl.seek_tick(t)
        for c in range(n_cars):
            p = pl.pose(c, interp)
            tr = sim["ticks"][c][t]
            e = math.sqrt((p[0] - tr[0]) ** 2 + (p[1] - tr[1]) ** 2 + (p[2] - tr[2]) ** 2)
            ey = abs(math.degrees(wrap(p[3] - tr[3])))
            ep = abs(math.degrees(p[4] - tr[4]))
            er = abs(math.degrees(p[5] - tr[5]))
            kind = win.get((c, t), "normal")
            for k in ("all", kind):
                a = acc[k]
                a["pos"].append(e)
                a["yaw"].append(ey)
                a["pitch"].append(ep)
                a["roll"].append(er)
                tn, tp = sim["ticks"][c][t + 1], sim["ticks"][c][t - 1]
                vtrue = math.sqrt((tn[0] - tp[0]) ** 2 + (tn[1] - tp[1]) ** 2 + (tn[2] - tp[2]) ** 2) * 30.0
                a["speed"].append(abs(p[14] - vtrue) * 3.6)
            if prev[c] is not None:
                pp, pt, pk = prev[c]
                d = math.sqrt(((p[0] - pp[0]) - (tr[0] - pt[0])) ** 2 + ((p[2] - pp[2]) - (tr[2] - pt[2])) ** 2)
                acc["all"]["disp"].append(d)
                if kind == pk:
                    acc[kind]["disp"].append(d)
            prev[c] = (p, tr, kind)
            if t % div == 0:
                onsample["pos"].append(e)
                onsample["yaw"].append(ey)
                onsample["pitch"].append(ep)
                onsample["roll"].append(er)
                onsample["steer"].append(abs(math.degrees(p[6] - tr[6])))
                onsample["rpm"].append(abs(p[7] - tr[7]))
    out = {"div": div, "hz": 60 // div, "interp": interp, "tick_step": tick_step,
           "by_window": {k: {m: stats(v) for m, v in a.items()} for k, a in acc.items()},
           "on_sample_ticks(quantization only)": {m: stats(v) for m, v in onsample.items()}}
    a = acc["all"]
    out["screen_px"] = {
        "chase_cam_6m_pos_p99": stats(a["pos"])["p99"] / CHASE_DIST * FOCAL_PX,
        "chase_cam_6m_pos_max": stats(a["pos"])["max"] / CHASE_DIST * FOCAL_PX,
        "onboard_yaw_max": math.radians(stats(a["yaw"])["max"]) * FOCAL_PX,
        "onboard_pitch_max": math.radians(stats(a["pitch"])["max"]) * FOCAL_PX,
        "onboard_roll_max_at_edge(160px)": math.radians(stats(a["roll"])["max"]) * 160.0,
    }
    return out


def yaw_rate_stats(sim):
    r = []
    for c in range(len(sim["ticks"])):
        st = sim["ticks"][c]
        for t in range(181, len(st)):
            r.append(abs(st[t][3] - st[t - 1][3]) * 60.0)
    s = stats(r)
    return {k: (math.degrees(v) if k != "n" else v) for k, v in s.items()}


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
    sim = synth.simulate(6, seconds, 1)
    res = {"seconds": seconds, "n_cars": 6, "focal_px_per_rad": FOCAL_PX,
           "incidents": {k: len(v) for k, v in sim["marks"].items()},
           "truth_yaw_rate_deg_s": yaw_rate_stats(sim),
           "quant": mkreplay.quant_for(sim["track"]).to_json(), "runs": []}
    for div in (3, 2):
        for interp in ("lerp", "hermite"):
            for step in (2, 1):               # 2 = the 30 fps render ticks, 1 = every tick (slow motion)
                r = run(sim, div, interp, step)
                res["runs"].append(r)
                a = r["by_window"]
                print("%2d Hz %-7s step%d | pos mm all rms %.2f p99 %.2f max %.1f | normal max %.1f contact max %.1f spin max %.1f"
                      " | yaw deg all rms %.4f max %.3f spin max %.3f contact max %.3f | disp mm rms %.2f max %.1f | speed kmh rms %.2f max %.2f" % (
                          r["hz"], interp, step,
                          a["all"]["pos"]["rms"] * 1000, a["all"]["pos"]["p99"] * 1000, a["all"]["pos"]["max"] * 1000,
                          a["normal"]["pos"]["max"] * 1000, a["contact"]["pos"]["max"] * 1000, a["spin"]["pos"]["max"] * 1000,
                          a["all"]["yaw"]["rms"], a["all"]["yaw"]["max"], a["spin"]["yaw"]["max"], a["contact"]["yaw"]["max"],
                          a["all"]["disp"]["rms"] * 1000, a["all"]["disp"]["max"] * 1000,
                          a["normal"]["speed"]["rms"], a["normal"]["speed"]["max"]))
    json.dump(res, open("q2_error.json", "w"), indent=1)
    q = res["runs"][0]["on_sample_ticks(quantization only)"]
    print("quantization only (20 Hz, on sample ticks):", {k: (round(v["rms"], 5), round(v["max"], 5)) for k, v in q.items()})


if __name__ == "__main__":
    main()
