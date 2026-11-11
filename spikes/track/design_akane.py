"""Akane Short design tool (spike). Pure Python, stdlib only.

Builds the course from straight / arc primitives, closes the loop by solving
three straight lengths (x closure, z closure, total length), then samples
control points and writes akane_short.json (without the baked ideal line;
run bake_ideal.py afterwards).

All numbers here are PROVISIONAL (kari no atai).
Convention: plane (x, z), heading 0 = +x, +pi/2 = +z, left normal = (-sin h, cos h).
Angles of arcs: + = left turn (heading increases), - = right turn.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET_LENGTH = 1800.0

# (kind, name, value, width, bank_deg)
#   S: value = length in m, or None when solved by closure
#   A: value = (radius m, signed angle deg)
PRIMS = [
    ("S", "A1", None, 12.0, 0.0),            # start line -> T1 (solved)
    ("A", "T1", (68.0, -95.0), 11.5, 2.0),
    ("S", "S12", 40.0, 10.5, 0.0),
    ("A", "T2", (50.0, +95.0), 10.5, 2.0),
    ("S", "S23", 25.0, 10.5, 0.0),
    ("A", "T3", (80.0, -40.0), 10.5, 1.5),   # kink before hairpin 1
    ("S", "S34", 60.0, 10.5, 0.0),
    ("A", "T4", (16.0, -180.0), 11.0, 3.0),  # hairpin 1 (right)
    ("S", "S45", 20.0, 10.5, 0.0),
    ("A", "T5", (110.0, +40.0), 11.0, 1.5),  # fast left sweeper onto the back straight
    ("S", "B", None, 11.0, 0.0),             # back straight (solved)
    ("A", "T6", (50.0, -100.0), 10.5, 2.0),  # into the infield
    ("S", "S67", 70.0, 10.5, 0.0),
    ("A", "T7", (15.0, +180.0), 11.0, 3.0),  # hairpin 2 (left)
    ("S", "S78", 45.0, 10.5, 0.0),
    ("A", "T8", (58.0, -120.0), 10.5, 2.0),
    ("S", "S89", None, 10.5, 0.0),           # solved (z closure)
    ("A", "T9", (72.0, -140.0), 11.5, 2.0),  # long final corner
    ("S", "A2", 120.0, 12.0, 0.0),           # T9 exit -> start line
]
UNKNOWN = ["A1", "S89", "B"]

# outside run-off (gravel width m) per corner, PROVISIONAL
GRAVEL_OUT = {"T1": 10.0, "T2": 5.0, "T3": 6.0, "T4": 8.0, "T5": 8.0,
              "T6": 6.0, "T7": 8.0, "T8": 5.0, "T9": 8.0}


def trans_len(r, ang_deg):
    """Length of the entry / exit transition (linear curvature ramp). PROVISIONAL rule."""
    th = math.radians(abs(ang_deg))
    return min(20.0, 0.8 * r, r * th / 3.0)


def arc_heading(r, ang_deg, u):
    """Heading change after distance u into an arc piece with transitions."""
    th = math.radians(abs(ang_deg))
    lt = trans_len(r, ang_deg)
    ln = r * th + lt
    if u < lt:
        a = u * u / (2.0 * lt * r)
    elif u > ln - lt:
        a = th - (ln - u) ** 2 / (2.0 * lt * r)
    else:
        a = lt / (2.0 * r) + (u - lt) / r
    return a if ang_deg > 0 else -a


def arc_integrate(r, ang_deg, h0, u_end, step=0.02):
    """Position offset (dx, dz) after distance u_end (midpoint rule)."""
    n = max(1, int(math.ceil(u_end / step)))
    du = u_end / n
    x = z = 0.0
    for i in range(n):
        h = h0 + arc_heading(r, ang_deg, (i + 0.5) * du)
        x += du * math.cos(h)
        z += du * math.sin(h)
    return x, z


def walk(prims, lengths):
    """Integrate primitives. Returns pieces [(kind,name,s0,len,x,z,h,value,width,bank)], end pose, total."""
    x = z = 0.0
    h = 0.0
    s = 0.0
    out = []
    for kind, name, value, width, bank in prims:
        if kind == "S":
            ln = lengths[name] if value is None else value
            out.append((kind, name, s, ln, x, z, h, ln, width, bank))
            x += ln * math.cos(h)
            z += ln * math.sin(h)
            s += ln
        else:
            r, ang = value
            ln = r * math.radians(abs(ang)) + trans_len(r, ang)
            out.append((kind, name, s, ln, x, z, h, value, width, bank))
            dx, dz = arc_integrate(r, ang, h, ln)
            x += dx
            z += dz
            h += math.radians(ang)
            s += ln
    return out, (x, z, h), s


def solve3(a, b):
    """Gaussian elimination for 3x3."""
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    n = 3
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def close_loop(prims):
    base = {k: 100.0 for k in UNKNOWN}
    _, (x0, z0, h0), l0 = walk(prims, base)
    if abs(math.degrees(h0) + 360.0) > 1e-6 and abs(math.degrees(h0) - 360.0) > 1e-6:
        raise SystemExit("angles do not sum to +-360 deg: %.3f" % math.degrees(h0))
    cols = []
    for k in UNKNOWN:
        t = dict(base)
        t[k] += 1.0
        _, (x1, z1, _), l1 = walk(prims, t)
        cols.append((x1 - x0, z1 - z0, l1 - l0))
    a = [[cols[j][i] for j in range(3)] for i in range(3)]
    b = [-x0, -z0, TARGET_LENGTH - l0]
    d = solve3(a, b)
    return {k: base[k] + d[i] for i, k in enumerate(UNKNOWN)}


def pose_on_piece(piece, ds):
    kind, name, s0, ln, x, z, h, value, width, bank = piece
    if kind == "S":
        return x + ds * math.cos(h), z + ds * math.sin(h), h
    r, ang = value
    dx, dz = arc_integrate(r, ang, h, ds) if ds > 0.0 else (0.0, 0.0)
    return x + dx, z + dz, h + arc_heading(r, ang, ds)


def elevation(s, total):
    """PROVISIONAL gentle elevation, range about 5 m."""
    u = 2.0 * math.pi * s / total
    return 3.0 + 2.2 * math.sin(u - 1.0) + 0.9 * math.sin(2.0 * u + 0.5)


def arc_offsets(piece):
    """Control point offsets inside an arc piece: transition (0, lt/2, lt), circular part in
    <= 15 deg / 20 m steps, transition (ln-lt, ln-lt/2, ln)."""
    kind, name, s0, ln, x, z, h, value, width, bank = piece
    r, ang = value
    lt = trans_len(r, ang)
    circ = ln - 2.0 * lt
    k = max(1, int(math.ceil(math.degrees(circ / r) / 15.0)), int(math.ceil(circ / 20.0)))
    offs = [0.0, 0.5 * lt] + [lt + circ * i / k for i in range(k + 1)] + [ln - 0.5 * lt, ln]
    return offs


def arc_spacing(piece):
    r, ang = piece[7]
    return 0.5 * trans_len(r, ang), 0


def graded(ln, a_start, a_end, skip_start=False, skip_end=False, max_gap=45.0):
    """Offsets along a straight: spacing grows x2 away from each neighbouring arc
    (a_start / a_end = control point spacing of that arc), then even fill."""
    left = []
    o = 0.0
    step = a_start
    while step < max_gap and o + step < ln * 0.5:
        o += step
        left.append(o)
        step *= 2.0
    right = []
    o = 0.0
    step = a_end
    while step < max_gap and o + step < ln * 0.5:
        o += step
        right.append(ln - o)
        step *= 2.0
    lo = left[-1] if left else 0.0
    hi = right[-1] if right else ln
    mid = []
    gap = hi - lo
    if gap > max_gap:
        m = int(math.ceil(gap / max_gap))
        mid = [lo + gap * i / m for i in range(1, m)]
    elif gap < 0.6 * min(a_start, a_end) and left and right:
        left.pop()          # avoid two nearly coincident points in the middle
    offs = ([] if skip_start else left) + mid + ([] if skip_end else sorted(right))
    return offs


def sample_control_points(pieces, total):
    pts = []
    n = len(pieces)
    for idx, piece in enumerate(pieces):
        kind, name, s0, ln, x, z, h, value, width, bank = piece
        if kind == "A":
            r, ang = value
            offs = arc_offsets(piece)
            bank_signed = bank if ang < 0 else -bank   # bank>0 = left edge higher = banked into a right turn
        else:
            bank_signed = 0.0
            if idx == 0:        # A1: starts at the start line (control point 0), ends at an arc
                a_end = arc_spacing(pieces[idx + 1])[0]
                offs = [0.0] + [o for o in graded(ln, 45.0, a_end) if o > 20.0]
            elif idx == n - 1:  # A2: starts at an arc, ends at the start line (not repeated)
                a_start = arc_spacing(pieces[idx - 1])[0]
                offs = [o for o in graded(ln, a_start, 45.0) if o < ln - 20.0]
            else:
                offs = graded(ln, arc_spacing(pieces[idx - 1])[0], arc_spacing(pieces[idx + 1])[0])
        for o in offs:
            px, pz, _ = pose_on_piece(piece, o)
            s = s0 + o
            pts.append({"x": round(px, 3), "z": round(pz, 3), "y": round(elevation(s, total), 3),
                        "width": width, "bank_deg": bank_signed})
    return pts


def wrap(s, total):
    return round(s % total, 1)


def build():
    lengths = close_loop(PRIMS)
    pieces, end, total = walk(PRIMS, lengths)
    cps = sample_control_points(pieces, total)
    info = {"lengths": lengths, "end": end, "total": total, "pieces": []}
    sides = []
    cameras_at = []
    corners = []
    for piece in pieces:
        kind, name, s0, ln, x, z, h, value, width, bank = piece
        info["pieces"].append({"kind": kind, "name": name, "s0": round(s0, 2), "len": round(ln, 2),
                               "x": round(x, 2), "z": round(z, 2), "h_deg": round(math.degrees(h), 2),
                               "value": value})
        if kind != "A":
            continue
        r, ang = value
        inside = "L" if ang > 0 else "R"
        outside = "R" if ang > 0 else "L"
        s1 = s0 + ln
        corners.append({"name": name, "s0": round(s0, 1), "s1": round(s1, 1), "radius": r, "angle_deg": ang,
                        "transition": round(trans_len(r, ang), 1)})
        # outside run-off first (painter's order: later entries win)
        sides.append({"side": outside, "s0": wrap(s0 - 30.0, total), "s1": wrap(s1 + 25.0, total),
                      "grass": 1.5, "gravel": GRAVEL_OUT[name]})
        sides.append({"side": outside, "s0": wrap(s0 + ln * 0.5, total), "s1": wrap(s1 + 22.0, total), "kerb": 1.0})
        sides.append({"side": inside, "s0": wrap(s0 - 4.0, total), "s1": wrap(s1 + 4.0, total),
                      "kerb": 1.0, "grass": 3.0, "gravel": 0.0})
        cameras_at.append((s0 + ln * 0.5, outside, name))
    # main straight: pit wall on the right (inside of the clockwise loop)
    a2 = pieces[-1]
    a1 = pieces[0]
    sides.append({"side": "R", "s0": wrap(a2[2] + 40.0, total), "s1": wrap(a1[3] - 60.0, total),
                  "kerb": 0.0, "grass": 1.5, "gravel": 0.0})
    # cameras: one per corner outside + straights
    cams = []
    for s, outside, name in cameras_at:
        cams.append({"name": name, "s": wrap(s, total), "d": 16.0 if outside == "L" else -16.0, "h": 4.0})
    back = [p for p in pieces if p[1] == "B"][0]
    cams.append({"name": "BACK", "s": wrap(back[2] + back[3] * 0.5, total), "d": -12.0, "h": 5.0})
    cams.append({"name": "MAIN", "s": wrap(total - 60.0, total), "d": 14.0, "h": 6.0})
    cams.append({"name": "A1", "s": wrap(a1[3] * 0.55, total), "d": 14.0, "h": 5.0})
    cams.sort(key=lambda c: c["s"])
    k = len(cams)
    for i, c in enumerate(cams):
        prev = cams[i - 1]["s"] - (total if i == 0 else 0.0)
        nxt = cams[(i + 1) % k]["s"] + (total if i == k - 1 else 0.0)
        c["from"] = wrap((prev + c["s"]) * 0.5, total)
        c["to"] = wrap((c["s"] + nxt) * 0.5, total)
    # scenery (track coordinates: s, d, h above ground)
    scenery = [
        {"kind": "gantry", "s": 0.0, "d": 0.0, "h": 6.0, "overhead": True},
        {"kind": "stand", "s": wrap(total - 70.0, total), "d": 24.0, "h": 0.0},
        {"kind": "pit", "s": wrap(total - 60.0, total), "d": -16.0, "h": 0.0},
    ]
    for cname, dists in (("T1", (100.0, 50.0)), ("T4", (50.0,)), ("T7", (50.0,))):
        c = [q for q in corners if q["name"] == cname][0]
        for dist in dists:
            side_d = 14.5 if c["angle_deg"] < 0 else -14.5   # on the outside before a corner
            scenery.append({"kind": "board_%d" % dist, "s": wrap(c["s0"] - dist, total), "d": side_d, "h": 0.0})
    for i in range(12):
        scenery.append({"kind": "tree", "s": wrap(back[2] + 20.0 + i * 30.0, total), "d": -22.0, "h": 0.0})
    hp1 = [q for q in corners if q["name"] == "T4"][0]
    hp2 = [q for q in corners if q["name"] == "T7"][0]
    checkpoints = [wrap(hp1["s1"] + 30.0, total), wrap(back[2] + back[3] * 0.5, total), wrap(hp2["s1"] + 30.0, total)]
    data = {
        "format": "clipping-point-track",
        "version": 1,
        "id": "akane_short",
        "name": "AKANE SHORT",
        "time_of_day": "dusk",
        "notes": "PROVISIONAL spike data generated by design_akane.py. Units m, deg. bank_deg>0 = left edge higher.",
        "sample_step": 2.0,
        "closed": True,
        "expected_length": TARGET_LENGTH,
        "length_tolerance": 0.03,
        "control_points": cps,
        "side_default": {"kerb": 0.0, "grass": 4.0, "gravel": 0.0},
        "sides": sides,
        "start": {"s": 0.0, "slots": 6, "first_gap": 6.0, "slot_gap": 7.0, "lateral": 2.6, "pole_side": "L"},
        "checkpoints": checkpoints,
        "cameras": cams,
        "scenery": scenery,
        "corners": corners,
    }
    return data, info


if __name__ == "__main__":
    data, info = build()
    out = os.path.join(HERE, "akane_short.json")
    # keep a previously baked ideal line only if --keep-ideal is given
    if "--keep-ideal" in sys.argv and os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            old = json.load(f)
        if "ideal" in old:
            data["ideal"] = old["ideal"]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    with open(os.path.join(HERE, "out_design_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1)
    print("control points:", len(data["control_points"]), "primitive total:", round(info["total"], 3))
    print("solved:", {k: round(v, 2) for k, v in info["lengths"].items()})
    print("end pose:", [round(v, 6) for v in info["end"]])
    for p in info["pieces"]:
        print("  %-4s %-4s s0=%7.1f len=%6.1f" % (p["kind"], p["name"], p["s0"], p["len"]))
