"""mkreplay.py -- build a Replay from the synthetic drive (shared by the verify scripts)."""
import replay as R
import synth

CAR_IDS = ["tsubame_1600", "kazane_rs", "shirogane_gtt", "arashi_4t", "kazane_rs", "tsubame_1600"]
CATALOG = {"courses": {"akane_short": {"layouts": ["normal"], "data_ver": 1}},
           "cars": ["tsubame_1600", "kazane_rs", "shirogane_gtt", "arashi_4t"]}


def base_header(n_cars, mode="race", title="TEST RACE"):
    cars = []
    for c in range(n_cars):
        cars.append({"car": CAR_IDS[c % 6], "color": c, "name": "YOU" if c == 0 else "AI%d" % c,
                     "driver": "player" if c == 0 else "ai", "grid": c + 1,
                     "setup": {"gear": 2, "wing": 2, "susp": 2, "brake": 2, "lsd": 2, "steer": 1,
                               "mt": 0, "assist": 1}})
    return {"app": "CLIPPING POINT", "app_ver": "0.1.0", "mode": mode,
            "course": {"id": "akane_short", "layout": "normal", "data_ver": 1},
            "laps": 5, "difficulty": "NORMAL", "player_car": 0, "start_tick": 0,
            "cars": cars, "saved_at": "2026-11-11T02:30:00Z", "title": title}


def quant_for(track, **kw):
    mins, maxs = track.bbox()
    return R.Quant.for_bbox(mins, maxs, **kw)


def build(n_cars=6, seconds=300.0, sample_div=3, seed=1, sim=None, track=None, quant_kw=None):
    """returns (replay, sim). sim['ticks'][car][tick] is the 60 Hz ground truth."""
    if sim is None:
        sim = synth.simulate(n_cars, seconds, seed, track=track)
    q = quant_for(sim["track"], **(quant_kw or {}))
    rec = R.Recorder(n_cars, q, sample_div)
    ticks = sim["ticks"]
    for t in range(sim["n_ticks"]):
        rec.tick([ticks[c][t][:15] for c in range(n_cars)])
    for e in sim["events"]:
        rec.add_event(*e)
    h = base_header(n_cars)
    # summary for the list screen
    for c in range(n_cars):
        laps = [e[4] for e in sim["events"] if e[1] == R.EV_LAP and e[2] == c]
        h["cars"][c]["laps_ms"] = laps
        h["cars"][c]["best_ms"] = min(laps) if laps else 0
        h["cars"][c]["total_ms"] = sum(laps)
    last = sim["n_ticks"] - 1
    order = sorted(range(n_cars), key=lambda c: -ticks[c][last][15])
    h["result"] = {"order": order}
    return rec.finish(h), sim
