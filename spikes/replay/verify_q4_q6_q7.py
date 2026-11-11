"""Q4 transport (seek / rewind / slow / fast / lap cue / events), Q6 time attack ring + ghost,
Q7 TV camera selection. Every check asserts; results go to q467.json. Exit code != 0 on failure."""
import json
import math
import random
import sys
import time

import mkreplay
import replay as R
import replay_cam as C
import synth

out = {}
checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + str(detail)) if detail else ""))


track = synth.Track()
L = track.length
sim = synth.simulate(6, 300.0, 5, track=track)
rp0, _ = mkreplay.build(6, 0, 3, sim=sim)
rp = R.load_cpr(R.dump_cpr(rp0), mkreplay.CATALOG)
ticks = sim["ticks"]
NT = (rp.n_samples - 1) * 3

# ------------------------------------------------------------------ Q4 transport
pl = R.Player(rp)
rng = random.Random(1)
# (a) random seek == fresh player at the same position (no hidden state)
ok = True
t0 = time.perf_counter()
N = 2000
for _ in range(N):
    q = rng.randrange(0, pl.end + 1)
    pl.seek_q(q)
    a = [pl.pose(c) for c in range(6)]
    p2 = R.Player(rp)
    p2.seek_q(q)
    b = [p2.pose(c) for c in range(6)]
    ok = ok and a == b
t_seek = (time.perf_counter() - t0) / N
check("random seek is pure index arithmetic (2000 random positions equal a fresh player)", ok)
out["seek_plus_2x6_poses_us"] = t_seek * 1e6

# (b) forward x1 then rewind: identical poses at identical positions
pl.seek_q(0)
fwd = {}
frames_x1 = 0
while True:
    fwd[pl.pos] = [pl.pose(c) for c in range(6)]
    frames_x1 += 1
    if pl.advance(R.SPEEDS["x1"]):
        break
pl.seek_q(max(fwd))            # the end is clamped; restart the rewind from the last drawn position
back_ok = True
n_back = 0
while True:
    if pl.pos in fwd:
        back_ok = back_ok and fwd[pl.pos] == [pl.pose(c) for c in range(6)]
        n_back += 1
    if pl.advance(R.SPEEDS["rew"]):
        break
check("rewind reproduces forward playback exactly", back_ok and n_back > frames_x1 - 3, "%d frames compared" % n_back)
out["frames_x1"] = frames_x1

# (c) slow / fast frame counts and step sizes
counts = {}
for name in ("x1/2", "x1/4", "x2", "x4"):
    pl.seek_q(0)
    n = 1
    maxstep = 0.0
    prev = pl.pose(0)
    while not pl.advance(R.SPEEDS[name]):
        n += 1
        p = pl.pose(0)
        maxstep = max(maxstep, math.hypot(p[0] - prev[0], p[2] - prev[2]))
        prev = p
    counts[name] = (n, maxstep)
check("slow 1/2 shows 2x frames, 1/4 shows 4x, x2 half, x4 quarter",
      abs(counts["x1/2"][0] - 2 * frames_x1) <= 2 and abs(counts["x1/4"][0] - 4 * frames_x1) <= 4
      and abs(counts["x2"][0] - frames_x1 / 2) <= 2 and abs(counts["x4"][0] - frames_x1 / 4) <= 2,
      {k: v[0] for k, v in counts.items()})
out["frame_counts"] = {k: v[0] for k, v in counts.items()}
out["max_step_per_frame_m"] = {k: v[1] for k, v in counts.items()}

# (d) lap cue: lap table from events, seek to lap start, car is at the line
lap_ok = True
worst = 0.0
n_laps = 0
for c in range(6):
    starts = rp.lap_start_ticks(c)
    for k in range(2, len(starts) + 1):
        lap_ok = lap_ok and pl.seek_lap(c, k) and pl.pos == starts[k - 1] * R.Q_PER_TICK
        s = ticks[c][starts[k - 1]][15] % L
        d = min(s, L - s)
        worst = max(worst, d)
        n_laps += 1
check("lap cue: seek_lap lands on the tick the car crossed the line", lap_ok and n_laps >= 12 and worst < 1.5,
      "%d lap starts, worst distance from line %.2f m" % (n_laps, worst))
# next / previous lap buttons
pl.seek_tick(rp.lap_start_ticks(0)[2] + 200)
pl.next_lap(0, -1)
a = pl.pos // 4 == rp.lap_start_ticks(0)[2]
pl.next_lap(0, -1)
b = pl.pos // 4 == rp.lap_start_ticks(0)[1]
pl.next_lap(0, +1)
c_ = pl.pos // 4 == rp.lap_start_ticks(0)[2]
check("previous-lap goes to this lap's start, again goes one lap back, next-lap goes forward", a and b and c_)

# (e) lap_at / rank_at by bisect == brute force truth
ok_lap = ok_rank = True
for _ in range(3000):
    t = rng.randrange(0, NT)
    order = sorted(range(6), key=lambda c: -ticks[c][t][15])
    for c in range(6):
        truth_lap = max(1, int(ticks[c][t][15] // L))        # s starts just below L
        if rp.lap_at(c, t) != truth_lap:
            ok_lap = False
        if rp.rank_at(c, t) != order.index(c) + 1:
            ok_rank = False
check("lap number at any time by bisect on the lap table (3000 random ticks x 6 cars)", ok_lap)
check("race position at any time by bisect on position events", ok_rank)

# (f) events fire exactly once during forward play at any speed
for name in ("x1", "x1/4", "x4"):
    pl.seek_q(0)
    seen = []
    last = -1
    while True:
        t = pl.pos // R.Q_PER_TICK
        seen.extend(rp.events_between(last, t))
        last = t
        if pl.advance(R.SPEEDS[name]):
            break
    t = pl.pos // R.Q_PER_TICK
    seen.extend(rp.events_between(last, t))
    expect = [e for e in rp.events if e[0] <= t]
    check("events fire exactly once in order at %s" % name, seen == expect, "%d events" % len(seen))
out["n_events"] = len(rp.events)
out["event_types"] = {str(k): sum(1 for e in rp.events if e[1] == k) for k in sorted(set(e[1] for e in rp.events))}

# (g) cost of pose()
for interp in ("lerp", "hermite"):
    pl.seek_q(0)
    t0 = time.perf_counter()
    n = 0
    while not pl.advance(8):
        for c in range(6):
            pl.pose(c, interp)
        n += 1
    out["pose_6cars_us_per_frame_" + interp] = (time.perf_counter() - t0) / n * 1e6
print("pose cost per frame (6 cars) us:", out["pose_6cars_us_per_frame_lerp"], out["pose_6cars_us_per_frame_hermite"])

# ------------------------------------------------------------------ Q6 time attack ring + ghost
ta = synth.simulate(1, 640.0, 11, track=track, events_rate=0.3)
st = ta["ticks"][0]
q = mkreplay.quant_for(track)
ring = R.LapRing(q, n_keep=5)
cross = {e[0]: e[4] for e in ta["events"] if e[1] == R.EV_LAP}
# the first crossing of the line (start of lap 1) is not an EV_LAP in the synthetic race: find it
first_cross = next(t for t in range(ta["n_ticks"]) if st[t][15] >= L)
max_buf = 0
for t in range(ta["n_ticks"]):
    if t == first_cross:
        ring.cross_line(t)
    elif t in cross:
        # lap time measured line to line
        ring.cross_line(t, int(round((t - ring.lap_start) * 1000 / 60)))
    ring.tick(st[t][:15])
    max_buf = max(max_buf, len(ring.buf))
n_done = ring.lap_no
check("ring keeps exactly the last 5 completed laps", len(ring.laps) == 5 and n_done >= 8 and
      [l[3] for l in ring.laps] == list(range(n_done - 4, n_done + 1)), "completed %d laps, kept %s" % (n_done, [l[3] for l in ring.laps]))
h1 = mkreplay.base_header(1, "time_attack", "TA TEST")
tar = ring.build_replay(h1)
tar2 = R.load_cpr(R.dump_cpr(tar), mkreplay.CATALOG)
check("ring replay survives the file round trip", bytes(tar2.samples) == bytes(tar.samples) and tar2.events == tar.events)
lt = tar2.lap_table(0)
check("ring replay lap table lists the 5 kept laps", len(lt) == 5 and [e[1] for e in lt] == [l[3] for l in ring.laps])
# poses of the ring replay equal the truth (re-based time axis)
base = ring.first_sample * 3
tp = R.Player(tar2)
worst = 0.0
for k in range(0, (tar2.n_samples - 1) * 3, 7):
    tp.seek_tick(k)
    p = tp.pose(0)
    tr = st[base + k]
    worst = max(worst, math.hypot(p[0] - tr[0], p[2] - tr[2]))
check("ring replay poses match the drive after re-basing the time axis", worst < 0.25, "worst %.1f mm" % (worst * 1000))
out["ring"] = {"laps_done": n_done, "kept": [l[3] for l in ring.laps], "max_buf_bytes": max_buf,
               "final_buf_bytes": len(ring.buf), "ring_file_bytes": len(R.dump_cpr(tar)),
               "lap_ms": [l[2] for l in ring.laps]}
# best lap ghost
best_ms = min(int(round((b - a) * 1000 / 60)) for a, b in zip([first_cross] + sorted(cross), sorted(cross)))
g = ring.best_ghost(h1)
gdata = R.dump_cpr(g)
g2 = R.load_cpr(gdata, mkreplay.CATALOG)
gh = g2.header["ghost"]
check("ghost is the fastest lap (even if it fell out of the 5-lap ring)", gh["lap_ms"] == best_ms and g2.header["mode"] == "ghost",
      "best lap no %d of %d, %d ms, kept laps %s" % (ring.best[1], n_done, best_ms, [l[3] for l in ring.laps]))
gp = R.GhostPlayer(g2)
gs, ge = ring.best[2], ring.best[3]
worst = 0.0
for k in range(0, ge - gs + 1):
    p = gp.pose_at(k)
    tr = st[gs + k]
    worst = max(worst, math.hypot(p[0] - tr[0], p[2] - tr[2]))
check("ghost pose at 'ticks since the line' matches that lap of the drive", worst < 0.25, "worst %.1f mm over %d ticks" % (worst * 1000, ge - gs + 1))
check("ghost hides itself after its lap ends", gp.pose_at(ge - gs + 3) is None and gp.pose_at(-1) is None)
out["ghost"] = {"lap_ms": gh["lap_ms"], "n_samples": g2.n_samples, "raw_bytes": len(g2.samples), "file_bytes": len(gdata),
                "base64_chars": len(R.to_base64(gdata)), "t0_tick": gh["t0_tick"], "worst_mm": worst * 1000}
# same drive with a 2-lap ring: the best lap (no 7) has left the ring, the ghost must be identical
ring2 = R.LapRing(q, n_keep=2)
for t in range(ta["n_ticks"]):
    if t == first_cross:
        ring2.cross_line(t)
    elif t in cross:
        ring2.cross_line(t, int(round((t - ring2.lap_start) * 1000 / 60)))
    ring2.tick(st[t][:15])
gb = ring2.best_ghost(h1)
check("best lap ghost is kept after that lap has left the ring (2-lap ring, best lap %d, kept %s)" % (ring2.best[1], [l[3] for l in ring2.laps]),
      ring2.best[1] not in [l[3] for l in ring2.laps] and bytes(gb.samples) == bytes(g.samples) and gb.header["ghost"] == g.header["ghost"])
# ghost cut out of a 6-car race replay with the same function
lt0 = rp.lap_table(1)
s_t, e_t = lt0[0][0], lt0[1][0]
g6 = R.make_ghost(rp.header, rp.samples, 6, 1, 3, s_t, e_t, lt0[1][2])
gp6 = R.GhostPlayer(R.load_cpr(R.dump_cpr(g6), mkreplay.CATALOG))
worst = 0.0
for k in range(0, e_t - s_t + 1, 2):
    p = gp6.pose_at(k)
    tr = ticks[1][s_t + k]
    worst = max(worst, math.hypot(p[0] - tr[0], p[2] - tr[2]))
check("ghost cut from a 6-car race replay (car 1, lap 2) matches the drive", worst < 0.25, "worst %.1f mm" % (worst * 1000))

# ------------------------------------------------------------------ Q7 TV cameras
ti = C.TrackIndex(track.px, track.pz)
# locate(): replay pose -> distance along the lap, against the synthetic truth
errs = []
pl.seek_q(0)
hint = None
t0 = time.perf_counter()
n = 0
s_list = []
while True:
    p = pl.pose(0)
    hint = ti.locate(p[0], p[2], hint)
    s_list.append((pl.pos // 4, hint, p))
    n += 1
    if pl.advance(8):
        break
t_loc = (time.perf_counter() - t0) / n
for (t, s, p) in s_list:
    d = (s - ticks[0][t][15] + L / 2) % L - L / 2
    errs.append(abs(d))
t0 = time.perf_counter()
for i in range(200):
    ti.locate(s_list[i * 7][2][0], s_list[i * 7][2][2])
t_glob = (time.perf_counter() - t0) / 200
check("lap distance recovered from the recorded position (hinted search)", max(errs) < 3.0, "max %.2f m" % max(errs))
out["locate"] = {"max_err_m": max(errs), "hinted_pose_plus_locate_us": t_loc * 1e6, "global_locate_us": t_glob * 1e6}

cams = C.auto_cameras(track.px, track.pz, L, n=10)
dirr = C.TvDirector(cams, L)
cuts = []
fovs = []
dists = []
shots = []
last_cut_t = None
for (t, s, p) in s_list:
    cam, cut = dirr.update(s, 1 / 30)
    fov, d = dirr.zoom(cam, p, 1 / 30, cut)
    fovs.append(fov)
    dists.append(d)
    if cut:
        if last_cut_t is not None:
            shots.append((t - last_cut_t) / 60.0)
        last_cut_t = t
        cuts.append((t, cam))
laps0 = len(rp.lap_table(0))
total_s = s_list[-1][0] / 60.0
dist_m = ticks[0][s_list[-1][0]][15] - ticks[0][0][15]
expected_cuts = dist_m / (L / 10)
check("TV: one cut per camera stretch for a normally driven car", abs(len(cuts) - expected_cuts) <= 3 + 2 * len(sim["marks"]["spin"]),
      "%d cuts over %.0f m (%.1f stretches), shortest shot %.2f s" % (len(cuts), dist_m, expected_cuts, min(shots)))
fs = sorted(fovs)
ds = sorted(dists)
out["tv"] = {"n_cams": 10, "cuts": len(cuts), "expected": expected_cuts, "shortest_shot_s": min(shots),
             "median_shot_s": sorted(shots)[len(shots) // 2],
             "fov_deg": {"min": fs[0], "p50": fs[len(fs) // 2], "max": fs[-1]},
             "dist_m": {"min": ds[0], "p50": ds[len(ds) // 2], "max": ds[-1]},
             "fov_clamped_frac": sum(1 for f in fovs if f <= 5.001 or f >= 54.999) / len(fovs)}
# flicker test: car parked / wobbling across a boundary (+-3 m at 1.5 Hz for 10 s), and a focus toggle
boundary = cams[3]["s_from"]


def count_cuts(hyst, min_hold, sfun, secs=10.0):
    d = C.TvDirector(cams, L, hyst=hyst, min_hold=min_hold)
    n = 0
    for i in range(int(secs * 30)):
        _, cut = d.update(sfun(i / 30.0), 1 / 30)
        n += cut
    return n - 1


wob = lambda t: boundary + 3.0 * math.sin(2 * math.pi * 1.5 * t)
creep = lambda t: boundary - 20 + 4.0 * t + 6.0 * math.sin(2 * math.pi * 0.7 * t)   # passes with back-and-forth
r = {"wobble_no_guard": count_cuts(0.0, 0.0, wob), "wobble_hyst10": count_cuts(10.0, 0.0, wob),
     "wobble_hold_only": count_cuts(0.0, 1.0, wob), "wobble_both": count_cuts(10.0, 1.0, wob),
     "creep_no_guard": count_cuts(0.0, 0.0, creep), "creep_hyst10": count_cuts(10.0, 0.0, creep),
     "creep_both": count_cuts(10.0, 1.0, creep)}
check("TV: hysteresis removes boundary flicker (wobble +-3 m: %d cuts unguarded -> %d)" % (r["wobble_no_guard"], r["wobble_both"]),
      r["wobble_no_guard"] >= 20 and r["wobble_both"] == 0 and r["creep_both"] == 1, r)
out["tv"]["flicker"] = r
# rewind: the same director run backwards makes the same number of cuts (symmetric rule)
dirr.reset()
cuts_b = sum(dirr.update(s, 1 / 30)[1] for (t, s, p) in reversed(s_list))
check("TV: director also works in rewind", abs(cuts_b - len(cuts)) <= 4, "%d cuts backwards vs %d forwards" % (cuts_b, len(cuts)))
out["tv"]["cuts_rewind"] = cuts_b
# other cameras need only the pose
pl.seek_tick(3000)
p = pl.pose(2)
e1, tg = C.chase_camera(p)
e2, f2, u2 = C.onboard_camera(p)
e3, t3 = C.heli_camera(p)
dot = sum(f2[i] * u2[i] for i in range(3))
check("chase / on-board / heli cameras are functions of the interpolated pose only",
      abs(math.dist(e1, p[:3]) - math.hypot(6.0, 2.0)) < 0.2 and abs(dot) < 1e-9 and abs(e3[1] - p[1] - 45.0) < 1e-9)

out["checks"] = [{"name": n, "ok": ok, "detail": str(d)} for n, ok, d in checks]
json.dump(out, open("q467.json", "w"), indent=1)
bad = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(bad)))
sys.exit(1 if bad or len(checks) < 20 else 0)
