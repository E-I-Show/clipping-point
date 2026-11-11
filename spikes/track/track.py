"""CLIPPING POINT track spike: course representation and queries.

Pure Python, standard library only (never imports pyxel).

Conventions (shared with the vehicle / control spikes):
  - plane coordinates (x, z), height y (up positive)
  - heading: +x = 0, +z = +pi/2 (atan2(dz, dx))
  - left normal of a heading h is (-sin h, cos h); lateral offset d is positive to the left
  - curvature = d(heading)/ds, positive for a left turn
  - units m, s, rad; fixed step DT = 1/60 s
All tuning numbers in this file are PROVISIONAL.
"""
import json
import math

FORMAT = "clipping-point-track"
VERSION = 1
DT = 1.0 / 60.0
G = 9.81
SURFACES = ("asphalt", "kerb", "grass", "gravel")
DENSE_STEP = 0.25          # m, spline evaluation spacing before arc-length resampling
MIN_RADIUS = 8.0           # m, load-time check
MAX_GRADE = 0.12           # load-time check
MAX_BANK_DEG = 15.0
FOLD_MARGIN = 0.15         # require 1 - |kappa| * wall_inner >= this
TAPER_SAMPLES = 2          # moving-average radius for side band widths

_TOP_REQUIRED = ("format", "version", "id", "name", "sample_step", "closed", "control_points",
                 "side_default", "sides", "start", "checkpoints")
_TOP_OPTIONAL = ("time_of_day", "notes", "expected_length", "length_tolerance", "cameras",
                 "scenery", "ideal", "corners")
_SCENERY_KINDS = ("gantry", "stand", "pit", "board_100", "board_50", "tree", "sign", "tyrewall")


class TrackError(ValueError):
    """Load-time validation error. .code is a stable identifier for tests."""

    def __init__(self, code, message):
        ValueError.__init__(self, "%s: %s" % (code, message))
        self.code = code


# ---------------------------------------------------------------------------
# schema helpers
# ---------------------------------------------------------------------------

def _num(v, where, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TrackError("E_TYPE", "%s: number expected, got %r" % (where, v))
    v = float(v)
    if v != v or v in (float("inf"), float("-inf")):
        raise TrackError("E_TYPE", "%s: finite number expected" % where)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise TrackError("E_RANGE", "%s: %r outside [%r, %r]" % (where, v, lo, hi))
    return v


def _keys(obj, where, required, optional=()):
    if not isinstance(obj, dict):
        raise TrackError("E_TYPE", "%s: object expected" % where)
    unknown = sorted(set(obj) - set(required) - set(optional))
    if unknown:
        raise TrackError("E_UNKNOWN_KEY", "%s: unknown keys %s" % (where, unknown))
    missing = sorted(set(required) - set(obj))
    if missing:
        raise TrackError("E_MISSING_KEY", "%s: missing keys %s" % (where, missing))


def _no_dup_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise TrackError("E_DUPLICATE_KEY", "duplicate key %r" % k)
        d[k] = v
    return d


def _bad_const(name):
    raise TrackError("E_TYPE", "non-finite constant %s in JSON" % name)


def load_track(path, validate=True):
    """Build a Track from a JSON file. validate=False skips the heavy geometric checks only."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=_no_dup_pairs, parse_constant=_bad_const)
    return Track(data, validate=validate)


def _wrap_pi(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a <= -math.pi:
        a += 2.0 * math.pi
    return a


# ---------------------------------------------------------------------------
# closed splines (dense evaluation, about DENSE_STEP apart)
# ---------------------------------------------------------------------------

SPLINE = "cubic"     # "cubic" = periodic C2 cubic spline (default), "catmull-rom" = centripetal C1


def _solve_cyclic(lower, diag, upper, rhs):
    """Cyclic tridiagonal system (Sherman-Morrison on top of the Thomas algorithm)."""
    n = len(diag)
    gamma = -diag[0]
    dd = list(diag)
    dd[0] = diag[0] - gamma
    dd[n - 1] = diag[n - 1] - lower[0] * upper[n - 1] / gamma
    u = [0.0] * n
    u[0] = gamma
    u[n - 1] = upper[n - 1]

    def thomas(d):
        c2 = [0.0] * n
        d2 = [0.0] * n
        c2[0] = upper[0] / dd[0]
        d2[0] = d[0] / dd[0]
        for i in range(1, n):
            m = dd[i] - lower[i] * c2[i - 1]
            c2[i] = upper[i] / m
            d2[i] = (d[i] - lower[i] * d2[i - 1]) / m
        x = [0.0] * n
        x[n - 1] = d2[n - 1]
        for i in range(n - 2, -1, -1):
            x[i] = d2[i] - c2[i] * x[i + 1]
        return x

    y = thomas(rhs)
    q = thomas(u)
    f = (y[0] + lower[0] * y[n - 1] / gamma) / (1.0 + q[0] + lower[0] * q[n - 1] / gamma)
    return [y[i] - f * q[i] for i in range(n)]


def _dense_periodic_cubic(px, pz, py, pw, pb):
    """Periodic C2 cubic spline, chord-length parametrisation. Curvature is continuous."""
    n = len(px)
    h = [max(1e-6, math.hypot(px[(i + 1) % n] - px[i], pz[(i + 1) % n] - pz[i])) for i in range(n)]
    lower = [h[i - 1] for i in range(n)]
    diag = [2.0 * (h[i - 1] + h[i]) for i in range(n)]
    upper = [h[i] for i in range(n)]
    second = []
    for p in (px, pz, py):
        rhs = [6.0 * ((p[(i + 1) % n] - p[i]) / h[i] - (p[i] - p[i - 1]) / h[i - 1]) for i in range(n)]
        second.append(_solve_cyclic(lower, diag, upper, rhs))
    dense = []
    for k in range(n):
        j = (k + 1) % n
        hk = h[k]
        m = max(2, int(math.ceil(hk / DENSE_STEP)))
        for q in range(m):
            u = q / float(m)
            a = (1.0 - u) * hk
            b = u * hk
            vals = []
            for p, mm in zip((px, pz, py), second):
                vals.append(mm[k] * a * a * a / (6.0 * hk) + mm[j] * b * b * b / (6.0 * hk)
                            + (p[k] / hk - mm[k] * hk / 6.0) * a + (p[j] / hk - mm[j] * hk / 6.0) * b)
            dense.append((vals[0], vals[1], vals[2], pw[k] + u * (pw[j] - pw[k]), pb[k] + u * (pb[j] - pb[k])))
    return dense


def _dense_catmull_rom(px, pz, py, pw, pb):
    """Centripetal Catmull-Rom (C1). Kept for comparison: curvature jumps at control points."""
    n = len(px)
    dk = []
    for i in range(n):
        j = (i + 1) % n
        dk.append(math.sqrt(max(1e-6, math.hypot(px[j] - px[i], pz[j] - pz[i]))))
    dense = []
    for k in range(n):
        i0 = (k - 1) % n
        i2 = (k + 1) % n
        i3 = (k + 2) % n
        d01 = dk[i0]
        d12 = dk[k]
        d23 = dk[i2]
        coef = []
        for p in (px, pz, py):
            p0 = p[i0]
            p1 = p[k]
            p2 = p[i2]
            p3 = p[i3]
            t1 = d12 * ((p1 - p0) / d01 - (p2 - p0) / (d01 + d12) + (p2 - p1) / d12)
            t2 = d12 * ((p2 - p1) / d12 - (p3 - p1) / (d12 + d23) + (p3 - p2) / d23)
            coef.append((p1, t1, p2, t2))
        m = max(2, int(math.ceil(d12 * d12 / DENSE_STEP)))
        for j in range(m):
            u = j / float(m)
            u2 = u * u
            u3 = u2 * u
            h00 = 2.0 * u3 - 3.0 * u2 + 1.0
            h10 = u3 - 2.0 * u2 + u
            h01 = -2.0 * u3 + 3.0 * u2
            h11 = u3 - u2
            c = coef[0]
            x = h00 * c[0] + h10 * c[1] + h01 * c[2] + h11 * c[3]
            c = coef[1]
            z = h00 * c[0] + h10 * c[1] + h01 * c[2] + h11 * c[3]
            c = coef[2]
            y = h00 * c[0] + h10 * c[1] + h01 * c[2] + h11 * c[3]
            dense.append((x, z, y, pw[k] + u * (pw[i2] - pw[k]), pb[k] + u * (pb[i2] - pb[k])))
    return dense


# ---------------------------------------------------------------------------
# query result
# ---------------------------------------------------------------------------

class TrackQuery(object):
    """Result of Track.query().

    index       segment number (sample i .. i+1), 0 <= index < track.n
    s           distance along the centerline (m), 0 <= s < track.length
    d           lateral offset (m), left of travel direction positive
    y           road surface height at (s, d) including bank
    heading     centerline direction (rad, (-pi, pi])
    curvature   centerline curvature (1/m), left turn positive
    surface     "asphalt" / "kerb" / "grass" / "gravel"
    half_left / half_right   centerline -> asphalt edge (m)
    wall_left / wall_right   centerline -> wall (m)
    to_wall_left / to_wall_right   distance from the point to each wall (negative = beyond the wall)
    grade       dy/ds of the centerline; bank_slope = dy/dd (tan of bank);
                bank_rate = d(bank_slope)/ds (twist). Slope of the surface along the track
                direction at offset d is (grade + d * bank_rate) / (1 - curvature * d).
    converged   False when the local walk hit its step limit (point outside the valid corridor)
    """
    __slots__ = ("index", "s", "d", "y", "heading", "curvature", "surface",
                 "half_left", "half_right", "wall_left", "wall_right",
                 "to_wall_left", "to_wall_right", "grade", "bank_slope", "bank_rate", "converged")

    def as_dict(self):
        return dict((k, getattr(self, k)) for k in self.__slots__)


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------

class Track(object):
    def __init__(self, data, validate=True):
        self._check_schema(data)
        self.id = data["id"]
        self.name = data["name"]
        self.step_nominal = float(data["sample_step"])
        self._build_centerline(data["control_points"])
        self._build_sides(data["side_default"], data["sides"])
        self._build_derived()
        # geometry first, so a broken centerline is reported as such
        self._check_local_geometry()
        if "expected_length" in data:
            tol = float(data.get("length_tolerance", 0.03))
            exp = float(data["expected_length"])
            if abs(self.length - exp) > tol * exp:
                raise TrackError("E_LENGTH", "length %.1f m outside %.1f +-%.0f%%" % (self.length, exp, tol * 100))
        if validate:
            self._check_intersections()
        self._build_start(data["start"])
        self._build_checkpoints(data["checkpoints"])
        self.cameras = self._build_cameras(data.get("cameras", []))
        self.scenery = self._build_scenery(data.get("scenery", []))
        self.corners = data.get("corners", [])
        self._build_ideal(data.get("ideal"))

    # -- schema ------------------------------------------------------------
    def _check_schema(self, data):
        _keys(data, "track", _TOP_REQUIRED, _TOP_OPTIONAL)
        if data["format"] != FORMAT:
            raise TrackError("E_FORMAT", "format %r" % (data["format"],))
        if data["version"] != VERSION:
            raise TrackError("E_VERSION", "version %r (supported %d)" % (data["version"], VERSION))
        if data["closed"] is not True:
            raise TrackError("E_NOT_CLOSED", "only closed circuits are supported (closed must be true)")
        _num(data["sample_step"], "sample_step", 0.5, 8.0)
        cps = data["control_points"]
        if not isinstance(cps, list) or len(cps) < 4:
            raise TrackError("E_TOO_FEW_POINTS", "need at least 4 control points")
        for i, c in enumerate(cps):
            w = "control_points[%d]" % i
            _keys(c, w, ("x", "z", "y", "width", "bank_deg"))
            _num(c["x"], w + ".x")
            _num(c["z"], w + ".z")
            _num(c["y"], w + ".y", -500.0, 500.0)
            if _num(c["width"], w + ".width") <= 0.0:
                raise TrackError("E_WIDTH", "%s.width must be > 0" % w)
            _num(c["width"], w + ".width", 4.0, 30.0)
            _num(c["bank_deg"], w + ".bank_deg", -MAX_BANK_DEG, MAX_BANK_DEG)
        n = len(cps)
        gaps = []
        for i in range(n):
            a = cps[i]
            b = cps[(i + 1) % n]
            gaps.append(math.hypot(b["x"] - a["x"], b["z"] - a["z"]))
        for i, g in enumerate(gaps):
            if g < 0.5:
                raise TrackError("E_DUPLICATE_POINT", "control_points[%d] and its successor are %.3f m apart "
                                 "(do not repeat the first point at the end)" % (i, g))
        srt = sorted(gaps[:-1])
        if gaps[-1] > 4.0 * srt[-1]:
            raise TrackError("E_NOT_CLOSED", "closing gap last->first is %.1f m, longest other gap %.1f m"
                             % (gaps[-1], srt[-1]))
        sd = data["side_default"]
        _keys(sd, "side_default", ("kerb", "grass", "gravel"))
        for k in ("kerb", "grass", "gravel"):
            _num(sd[k], "side_default." + k, 0.0, 60.0)
        if not isinstance(data["sides"], list):
            raise TrackError("E_TYPE", "sides: list expected")
        for i, r in enumerate(data["sides"]):
            w = "sides[%d]" % i
            _keys(r, w, ("side", "s0", "s1"), ("kerb", "grass", "gravel"))
            if r["side"] not in ("L", "R"):
                raise TrackError("E_RANGE", "%s.side must be 'L' or 'R'" % w)
            _num(r["s0"], w + ".s0", 0.0)
            _num(r["s1"], w + ".s1", 0.0)
            if not any(k in r for k in ("kerb", "grass", "gravel")):
                raise TrackError("E_MISSING_KEY", "%s: needs kerb / grass / gravel" % w)
            for k in ("kerb", "grass", "gravel"):
                if k in r:
                    _num(r[k], "%s.%s" % (w, k), 0.0, 60.0)
        st = data["start"]
        _keys(st, "start", ("s", "slots", "first_gap", "slot_gap", "lateral", "pole_side"))
        _num(st["s"], "start.s", 0.0)
        if isinstance(st["slots"], bool) or not isinstance(st["slots"], int) or not 1 <= st["slots"] <= 32:
            raise TrackError("E_RANGE", "start.slots must be an int 1..32")
        _num(st["first_gap"], "start.first_gap", 0.0, 100.0)
        _num(st["slot_gap"], "start.slot_gap", 3.0, 50.0)
        _num(st["lateral"], "start.lateral", 0.0, 20.0)
        if st["pole_side"] not in ("L", "R"):
            raise TrackError("E_RANGE", "start.pole_side must be 'L' or 'R'")
        cp = data["checkpoints"]
        if not isinstance(cp, list) or len(cp) < 2:
            raise TrackError("E_CHECKPOINTS", "need at least 2 checkpoints besides the start line")
        for i, v in enumerate(cp):
            _num(v, "checkpoints[%d]" % i, 0.0)
        for i, c in enumerate(data.get("cameras", [])):
            w = "cameras[%d]" % i
            _keys(c, w, ("s", "d", "h", "from", "to"), ("name",))
            for k in ("s", "from", "to"):
                _num(c[k], "%s.%s" % (w, k), 0.0)
            _num(c["d"], w + ".d", -200.0, 200.0)
            _num(c["h"], w + ".h", 0.0, 200.0)
        for i, c in enumerate(data.get("scenery", [])):
            w = "scenery[%d]" % i
            _keys(c, w, ("kind", "s", "d", "h"), ("rot_deg", "scale", "overhead"))
            if c["kind"] not in _SCENERY_KINDS:
                raise TrackError("E_UNKNOWN_KIND", "%s.kind %r" % (w, c["kind"]))
            _num(c["s"], w + ".s", 0.0)
            _num(c["d"], w + ".d", -300.0, 300.0)
            _num(c["h"], w + ".h", -50.0, 200.0)
        if "ideal" in data:
            _keys(data["ideal"], "ideal", ("baked_length", "d"), ("margin", "notes"))
            _num(data["ideal"]["baked_length"], "ideal.baked_length", 1.0)
            if not isinstance(data["ideal"]["d"], list) or len(data["ideal"]["d"]) < 8:
                raise TrackError("E_TYPE", "ideal.d: list of >= 8 numbers expected")
            for i, v in enumerate(data["ideal"]["d"]):
                _num(v, "ideal.d[%d]" % i, -30.0, 30.0)

    # -- centerline: closed spline through the control points -> uniform arc-length table
    def _build_centerline(self, cps):
        n = len(cps)
        px = [float(c["x"]) for c in cps]
        pz = [float(c["z"]) for c in cps]
        py = [float(c["y"]) for c in cps]
        pw = [float(c["width"]) for c in cps]
        pb = [math.tan(math.radians(float(c["bank_deg"]))) for c in cps]
        if SPLINE == "cubic":
            dense = _dense_periodic_cubic(px, pz, py, pw, pb)
        else:
            dense = _dense_catmull_rom(px, pz, py, pw, pb)
        m = len(dense)
        cum = [0.0] * (m + 1)
        for i in range(m):
            a = dense[i]
            b = dense[(i + 1) % m]
            cum[i + 1] = cum[i] + math.hypot(b[0] - a[0], b[1] - a[1])
        total = cum[m]
        nn = max(8, int(round(total / self.step_nominal)))
        ds = total / nn
        xs = [0.0] * nn
        zs = [0.0] * nn
        ys = [0.0] * nn
        ws = [0.0] * nn
        bs = [0.0] * nn
        j = 0
        for i in range(nn):
            s = i * ds
            while cum[j + 1] < s:
                j += 1
            seg = cum[j + 1] - cum[j]
            u = (s - cum[j]) / seg if seg > 0.0 else 0.0
            a = dense[j]
            b = dense[(j + 1) % m]
            xs[i] = a[0] + u * (b[0] - a[0])
            zs[i] = a[1] + u * (b[1] - a[1])
            ys[i] = a[2] + u * (b[2] - a[2])
            ws[i] = a[3] + u * (b[3] - a[3])
            bs[i] = a[4] + u * (b[4] - a[4])
        self.n = nn
        self.ds = ds
        self.length = total
        self._x = xs
        self._z = zs
        self._y = ys
        self._w = ws
        self._bank = bs     # tan(bank), dy/dd

    # -- side bands: kerb / grass / gravel / wall per side -------------------
    def _build_sides(self, default, ranges):
        n = self.n
        ds = self.ds
        length = self.length
        raw = {}
        for side in ("L", "R"):
            for k in ("kerb", "grass", "gravel"):
                raw[side, k] = [float(default[k])] * n
        for i, r in enumerate(ranges):
            s0 = float(r["s0"])
            s1 = float(r["s1"])
            if s0 > length or s1 > length:
                raise TrackError("E_RANGE", "sides[%d]: s0/s1 beyond track length %.1f" % (i, length))
            if s0 == s1:
                raise TrackError("E_RANGE", "sides[%d]: empty range" % i)
            i0 = int(math.ceil(s0 / ds - 1e-9))
            i1 = int(math.floor(s1 / ds + 1e-9))
            if s0 > s1:           # wraps through the start line
                idx = list(range(i0, n)) + list(range(0, min(i1, n - 1) + 1))
            else:
                idx = list(range(i0, min(i1, n - 1) + 1))
            for k in ("kerb", "grass", "gravel"):
                if k in r:
                    arr = raw[r["side"], k]
                    v = float(r[k])
                    for j in idx:
                        arr[j % n] = v
        t = TAPER_SAMPLES
        half = [0.5 * w for w in self._w]
        self._half = half
        self._band = {}
        for side in ("L", "R"):
            sm = {}
            for k in ("kerb", "grass", "gravel"):
                arr = raw[side, k]
                sm[k] = [sum(arr[(i + o) % n] for o in range(-t, t + 1)) / (2 * t + 1.0) for i in range(n)]
            ek = [half[i] + sm["kerb"][i] for i in range(n)]
            eg = [ek[i] + sm["grass"][i] for i in range(n)]
            ew = [eg[i] + sm["gravel"][i] for i in range(n)]
            self._band[side] = (ek, eg, ew)
        self._ekl, self._egl, self._ewl = self._band["L"]
        self._ekr, self._egr, self._ewr = self._band["R"]

    # -- derived per-sample values -------------------------------------------
    def _build_derived(self):
        n = self.n
        x = self._x
        z = self._z
        y = self._y
        ds = self.ds
        tx = [0.0] * n
        tz = [0.0] * n
        hd = [0.0] * n
        kap = [0.0] * n
        grade = [0.0] * n
        for i in range(n):
            a = (i - 1) % n
            b = (i + 1) % n
            dx = x[b] - x[a]
            dz = z[b] - z[a]
            ln = math.hypot(dx, dz)
            tx[i] = dx / ln
            tz[i] = dz / ln
            grade[i] = (y[b] - y[a]) / (2.0 * ds)
            h_in = math.atan2(z[i] - z[a], x[i] - x[a])
            h_out = math.atan2(z[b] - z[i], x[b] - x[i])
            kap[i] = _wrap_pi(h_out - h_in) / ds
        # unwrapped heading (continuous); hd[0] in (-pi, pi]
        hd[0] = math.atan2(tz[0], tx[0])
        for i in range(1, n):
            hd[i] = hd[i - 1] + _wrap_pi(math.atan2(tz[i], tx[i]) - hd[i - 1])
        self.turning = hd[n - 1] + _wrap_pi(hd[0] - hd[n - 1]) - hd[0]   # +-2*pi for a simple loop
        self._tx = tx
        self._tz = tz
        self._h = hd
        self._k = kap
        self._grade = grade
        # per-segment deltas (segment i runs from sample i to i+1)
        nxt = [(i + 1) % n for i in range(n)]
        self._dh = [_wrap_pi(hd[nxt[i]] - hd[i]) for i in range(n)]
        self._dk = [kap[nxt[i]] - kap[i] for i in range(n)]
        self._dy = [y[nxt[i]] - y[i] for i in range(n)]
        self._dxs = [x[nxt[i]] - x[i] for i in range(n)]
        self._dzs = [z[nxt[i]] - z[i] for i in range(n)]
        # quadratic term of the wedge equation: a = -dot(E, T1 - T0)
        self._qa = [-(self._dxs[i] * (tx[nxt[i]] - tx[i]) + self._dzs[i] * (tz[nxt[i]] - tz[i])) for i in range(n)]

    # -- start / grid ----------------------------------------------------------
    def _build_start(self, st):
        self.start_s = float(st["s"])
        if self.start_s >= self.length:
            raise TrackError("E_RANGE", "start.s beyond track length")
        self.grid_slots = int(st["slots"])
        self._grid = []
        sign = 1.0 if st["pole_side"] == "L" else -1.0
        for k in range(self.grid_slots):
            s = (self.start_s - float(st["first_gap"]) - k * float(st["slot_gap"])) % self.length
            d = sign * float(st["lateral"]) * (1.0 if k % 2 == 0 else -1.0)
            i = int(s / self.ds) % self.n
            if abs(d) + 1.0 > self._half[i]:
                raise TrackError("E_GRID", "grid slot %d (d=%.1f) is not on the asphalt" % (k, d))
            if abs(self._k[i]) > 1.0 / 150.0:
                raise TrackError("E_GRID", "grid slot %d is on a curve (radius %.0f m)" % (k, 1.0 / abs(self._k[i])))
            self._grid.append((s, d))

    def _build_checkpoints(self, cps):
        rel = [(float(c) - self.start_s) % self.length for c in cps]
        for c in cps:
            if float(c) >= self.length:
                raise TrackError("E_CHECKPOINTS", "checkpoint beyond track length")
        prev = 0.0
        for r in rel:
            if r <= prev + 20.0:
                raise TrackError("E_CHECKPOINTS", "checkpoints must be in increasing order after the start line, "
                                 ">= 20 m apart")
            if r - prev >= 0.5 * self.length:
                raise TrackError("E_CHECKPOINTS", "gap between gates must be < half a lap")
            prev = r
        if self.length - prev >= 0.5 * self.length or self.length - prev <= 20.0:
            raise TrackError("E_CHECKPOINTS", "last checkpoint too close to / too far from the start line")
        self.checkpoints = [float(c) for c in cps]
        self.gates_rel = rel + [self.length]     # distances after the start line, last = finish

    def _build_cameras(self, cams):
        out = []
        length = self.length
        cover = 0.0
        for i, c in enumerate(cams):
            if max(c["s"], c["from"], c["to"]) >= length:
                raise TrackError("E_RANGE", "cameras[%d]: s beyond track length" % i)
            j = int(c["s"] / self.ds) % self.n
            wall = self._ewl[j] if c["d"] > 0 else self._ewr[j]
            if abs(c["d"]) < wall and c["h"] < 4.0:
                raise TrackError("E_CAMERA", "cameras[%d]: inside the walls at low height" % i)
            cover += (c["to"] - c["from"]) % length
            out.append(dict(c))
        if cams:
            ordered = sorted(out, key=lambda c: c["from"])
            for a, b in zip(ordered, ordered[1:] + ordered[:1]):
                if abs(((b["from"] - a["to"]) + 0.5 * length) % length - 0.5 * length) > 0.2:
                    raise TrackError("E_CAMERA", "camera ranges must tile the lap without gaps/overlaps "
                                     "(%.1f -> %.1f)" % (a["to"], b["from"]))
            if abs(cover - length) > 1.0:
                raise TrackError("E_CAMERA", "camera ranges cover %.1f m of %.1f m" % (cover, length))
        return out

    def _build_scenery(self, items):
        out = []
        for i, c in enumerate(items):
            if c["s"] >= self.length:
                raise TrackError("E_RANGE", "scenery[%d]: s beyond track length" % i)
            j = int(c["s"] / self.ds) % self.n
            wall = self._ewl[j] if c["d"] > 0 else self._ewr[j]
            if not c.get("overhead", False) and abs(c["d"]) < wall + 0.5:
                raise TrackError("E_SCENERY", "scenery[%d] (%s) is inside the walls (|d|=%.1f < %.1f)"
                                 % (i, c["kind"], abs(c["d"]), wall + 0.5))
            out.append(dict(c))
        return out

    # -- geometric validation ------------------------------------------------
    def _check_local_geometry(self):
        n = self.n
        if abs(abs(self.turning) - 2.0 * math.pi) > 0.01:
            raise TrackError("E_WINDING", "total turning %.3f rad is not +-2*pi (figure-8 or loop?)" % self.turning)
        for i in range(n):
            k = self._k[i]
            if abs(k) > 1.0 / MIN_RADIUS:
                raise TrackError("E_MIN_RADIUS", "radius %.1f m at s=%.0f (< %.1f)" % (1.0 / abs(k), i * self.ds, MIN_RADIUS))
            if abs(self._grade[i]) > MAX_GRADE:
                raise TrackError("E_GRADE", "grade %.3f at s=%.0f" % (self._grade[i], i * self.ds))
        for i in range(n):
            k = self._k[i]
            inner = self._ewl[i] if k > 0 else self._ewr[i]
            if 1.0 - abs(k) * inner < FOLD_MARGIN:
                raise TrackError("E_FOLD", "inner wall offset %.1f m too large for radius %.1f m at s=%.0f"
                                 % (inner, 1.0 / abs(k), i * self.ds))

    def _edge_polyline(self, which):
        """which: 'C' centerline, 'L' left wall, 'R' right wall -> list of (x, z)."""
        n = self.n
        if which == "C":
            return [(self._x[i], self._z[i]) for i in range(n)]
        e = self._ewl if which == "L" else self._ewr
        sg = 1.0 if which == "L" else -1.0
        return [(self._x[i] - sg * e[i] * self._tz[i], self._z[i] + sg * e[i] * self._tx[i]) for i in range(n)]

    def _check_intersections(self):
        """Centerline and both wall polylines must not intersect themselves or each other."""
        cell = 8.0
        grid = {}
        segs = []
        for which in ("C", "L", "R"):
            pts = self._edge_polyline(which)
            n = len(pts)
            for i in range(n):
                a = pts[i]
                b = pts[(i + 1) % n]
                sid = len(segs)
                segs.append((which, i, a[0], a[1], b[0], b[1]))
                cx0 = int(math.floor(min(a[0], b[0]) / cell))
                cx1 = int(math.floor(max(a[0], b[0]) / cell))
                cz0 = int(math.floor(min(a[1], b[1]) / cell))
                cz1 = int(math.floor(max(a[1], b[1]) / cell))
                for cx in range(cx0, cx1 + 1):
                    for cz in range(cz0, cz1 + 1):
                        grid.setdefault((cx, cz), []).append(sid)
        n = self.n
        self.intersection_tests = 0
        overlap = None
        for ids in grid.values():
            m = len(ids)
            for p in range(m):
                wa, ia, ax, az, bx, bz = segs[ids[p]]
                for q in range(p + 1, m):
                    wb, ib, cx, cz, dx, dz = segs[ids[q]]
                    if wa == wb:
                        gap = abs(ia - ib)
                        if gap <= 1 or gap >= n - 1:
                            continue
                    self.intersection_tests += 1
                    d1 = (bx - ax) * (cz - az) - (bz - az) * (cx - ax)
                    d2 = (bx - ax) * (dz - az) - (bz - az) * (dx - ax)
                    if (d1 > 0.0) == (d2 > 0.0):
                        continue
                    d3 = (dx - cx) * (az - cz) - (dz - cz) * (ax - cx)
                    d4 = (dx - cx) * (bz - cz) - (dz - cz) * (bx - cx)
                    if (d3 > 0.0) == (d4 > 0.0):
                        continue
                    if wa == "C" and wb == "C":
                        raise TrackError("E_SELF_INTERSECTION", "centerline crosses itself near s=%.0f and s=%.0f"
                                         % (ia * self.ds, ib * self.ds))
                    if overlap is None:
                        overlap = (wa, ia * self.ds, wb, ib * self.ds)
        if overlap is not None:
            raise TrackError("E_CORRIDOR_OVERLAP", "%s(s=%.0f) crosses %s(s=%.0f): run-off areas overlap" % overlap)

    # -- ideal line ------------------------------------------------------------
    def _build_ideal(self, ideal):
        n = self.n
        self.has_baked_ideal = ideal is not None
        if ideal is None:
            self._ideal_d = [0.0] * n
        else:
            if abs(float(ideal["baked_length"]) - self.length) > 0.5:
                raise TrackError("E_IDEAL_STALE", "ideal line was baked for length %.2f, track is %.2f; re-bake"
                                 % (ideal["baked_length"], self.length))
            src = [float(v) for v in ideal["d"]]
            m = len(src)
            out = [0.0] * n
            for i in range(n):
                f = i * m / float(n)
                j = int(f)
                u = f - j
                out[i] = src[j % m] + u * (src[(j + 1) % m] - src[j % m])
                if abs(out[i]) > self._half[i]:
                    raise TrackError("E_IDEAL_OFF_ROAD", "ideal line leaves the asphalt at s=%.0f" % (i * self.ds))
            self._ideal_d = out
        self._ideal_v = speed_profile(self, self._ideal_d)["v"]

    # ------------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------------
    def nearest_index(self, x, z):
        """Global search (O(n)): index of the nearest centerline sample."""
        xs = self._x
        zs = self._z
        best = 0
        bd = 1e30
        for i in range(self.n):
            dx = xs[i] - x
            dz = zs[i] - z
            d2 = dx * dx + dz * dz
            if d2 < bd:
                bd = d2
                best = i
        return best

    def query(self, x, z, hint=None, max_walk=16):
        """Locate (x, z) on the course. hint = previous index -> strictly local search
        (the result index never moves more than max_walk samples from hint)."""
        n = self.n
        xs = self._x
        zs = self._z
        tx = self._tx
        tz = self._tz
        if hint is None:
            i = self.nearest_index(x, z)
            if i > 0:
                i -= 1
            else:
                i = n - 1
            steps = n
        else:
            i = hint % n
            steps = max_walk
        a0 = (x - xs[i]) * tx[i] + (z - zs[i]) * tz[i]
        ok = False
        while steps > 0:
            if a0 < 0.0:
                j = i
                i = i - 1 if i > 0 else n - 1
                a1 = a0
                a0 = (x - xs[i]) * tx[i] + (z - zs[i]) * tz[i]
                if a0 >= 0.0:
                    ok = True
                    break
                steps -= 1
                continue
            j = i + 1 if i + 1 < n else 0
            a1 = (x - xs[j]) * tx[j] + (z - zs[j]) * tz[j]
            if a1 < 0.0:
                ok = True
                break
            i = j
            a0 = a1
            steps -= 1
        if ok:
            den = a0 - a1
            t = a0 / den if den > 1e-12 else 0.0
            qa = self._qa[i]
            if qa > 1e-9 or qa < -1e-9:
                # one Newton step on f(t) = a0 + t*(a1 - a0 - qa) + qa*t^2
                b = a1 - a0 - qa
                f = a0 + t * b + qa * t * t
                fp = b + 2.0 * qa * t
                if fp < -1e-12:
                    t -= f / fp
                    if t < 0.0:
                        t = 0.0
                    elif t > 1.0:
                        t = 1.0
        else:
            # outside the valid corridor (beyond a centre of curvature): clamp, stay local
            j = i + 1 if i + 1 < n else 0
            t = 0.0 if a0 < 0.0 else 1.0
        px = xs[i] + t * self._dxs[i]
        pz = zs[i] + t * self._dzs[i]
        nx = -(tz[i] + t * (tz[j] - tz[i]))
        nz = tx[i] + t * (tx[j] - tx[i])
        d = ((x - px) * nx + (z - pz) * nz) / math.sqrt(nx * nx + nz * nz)
        q = TrackQuery()
        q.index = i
        q.s = (i + t) * self.ds
        q.d = d
        q.converged = ok
        h = self._h[i] + t * self._dh[i]
        if h > math.pi:
            h -= 2.0 * math.pi
        elif h <= -math.pi:
            h += 2.0 * math.pi
        q.heading = h
        q.curvature = self._k[i] + t * self._dk[i]
        bank = self._bank[i] + t * (self._bank[j] - self._bank[i])
        q.bank_slope = bank
        q.bank_rate = (self._bank[j] - self._bank[i]) / self.ds
        q.grade = self._grade[i] + t * (self._grade[j] - self._grade[i])
        q.y = self._y[i] + t * self._dy[i] + d * bank
        half = self._half[i] + t * (self._half[j] - self._half[i])
        q.half_left = half
        q.half_right = half
        wl = self._ewl[i] + t * (self._ewl[j] - self._ewl[i])
        wr = self._ewr[i] + t * (self._ewr[j] - self._ewr[i])
        q.wall_left = wl
        q.wall_right = wr
        q.to_wall_left = wl - d
        q.to_wall_right = wr + d
        if d >= 0.0:
            ad = d
            if ad <= half:
                q.surface = "asphalt"
            elif ad <= self._ekl[i] + t * (self._ekl[j] - self._ekl[i]):
                q.surface = "kerb"
            elif ad <= self._egl[i] + t * (self._egl[j] - self._egl[i]):
                q.surface = "grass"
            else:
                q.surface = "gravel" if wl - (self._egl[i] + t * (self._egl[j] - self._egl[i])) > 0.05 else "grass"
        else:
            ad = -d
            if ad <= half:
                q.surface = "asphalt"
            elif ad <= self._ekr[i] + t * (self._ekr[j] - self._ekr[i]):
                q.surface = "kerb"
            elif ad <= self._egr[i] + t * (self._egr[j] - self._egr[i]):
                q.surface = "grass"
            else:
                q.surface = "gravel" if wr - (self._egr[i] + t * (self._egr[j] - self._egr[i])) > 0.05 else "grass"
        return q

    def surface_at(self, s, d):
        """Surface name at track coordinates (cheap; for per-wheel lookups)."""
        f = (s % self.length) / self.ds
        i = int(f)
        if i >= self.n:
            i = self.n - 1
        t = f - i
        j = i + 1 if i + 1 < self.n else 0
        ad = d if d >= 0.0 else -d
        if ad <= self._half[i] + t * (self._half[j] - self._half[i]):
            return "asphalt"
        ek, eg, ew = self._band["L"] if d >= 0.0 else self._band["R"]
        if ad <= ek[i] + t * (ek[j] - ek[i]):
            return "kerb"
        g = eg[i] + t * (eg[j] - eg[i])
        if ad <= g:
            return "grass"
        return "gravel" if ew[i] + t * (ew[j] - ew[i]) - g > 0.05 else "grass"

    def pose_at(self, s, d=0.0):
        """(x, z, heading, y) at distance s along the centerline and lateral offset d."""
        n = self.n
        f = (s % self.length) / self.ds
        i = int(f)
        if i >= n:
            i = n - 1
        t = f - i
        j = i + 1 if i + 1 < n else 0
        nx = -(self._tz[i] + t * (self._tz[j] - self._tz[i]))
        nz = self._tx[i] + t * (self._tx[j] - self._tx[i])
        ln = math.sqrt(nx * nx + nz * nz)
        x = self._x[i] + t * self._dxs[i] + d * nx / ln
        z = self._z[i] + t * self._dzs[i] + d * nz / ln
        h = self._h[i] + t * self._dh[i]
        if h > math.pi:
            h -= 2.0 * math.pi
        elif h <= -math.pi:
            h += 2.0 * math.pi
        y = self._y[i] + t * self._dy[i] + d * (self._bank[i] + t * (self._bank[j] - self._bank[i]))
        return (x, z, h, y)

    def ideal(self, s):
        """(lateral offset of the ideal line, target speed m/s) at s."""
        n = self.n
        f = (s % self.length) / self.ds
        i = int(f)
        if i >= n:
            i = n - 1
        t = f - i
        j = i + 1 if i + 1 < n else 0
        return (self._ideal_d[i] + t * (self._ideal_d[j] - self._ideal_d[i]),
                self._ideal_v[i] + t * (self._ideal_v[j] - self._ideal_v[i]))

    def ideal_points(self):
        """AI point list: [(s, x, z, d, v)] one per table sample."""
        out = []
        for i in range(self.n):
            s = i * self.ds
            x, z, _, _ = self.pose_at(s, self._ideal_d[i])
            out.append((s, x, z, self._ideal_d[i], self._ideal_v[i]))
        return out

    def start_pose(self, grid_index):
        """(x, z, heading, y) of grid slot grid_index (0 = pole)."""
        s, d = self.start_sd(grid_index)
        return self.pose_at(s, d)

    def start_sd(self, grid_index):
        if not 0 <= grid_index < len(self._grid):
            raise IndexError("grid_index %r out of range 0..%d" % (grid_index, len(self._grid) - 1))
        return self._grid[grid_index]

    def camera_for(self, s):
        """Index of the fixed TV camera whose range contains s."""
        s %= self.length
        for i, c in enumerate(self.cameras):
            a = c["from"]
            b = c["to"]
            if (a <= s < b) if a < b else (s >= a or s < b):
                return i
        return -1

    def stats(self):
        ks = [abs(k) for k in self._k]
        kmax = max(ks)
        return {"length": self.length, "n": self.n, "ds": self.ds,
                "min_radius": 1.0 / kmax, "min_radius_s": ks.index(kmax) * self.ds,
                "y_min": min(self._y), "y_max": max(self._y),
                "max_grade": max(abs(g) for g in self._grade),
                "width_min": min(self._w), "width_max": max(self._w),
                "turning_deg": math.degrees(self.turning)}


# ---------------------------------------------------------------------------
# lap counting with sub-tick timing
# ---------------------------------------------------------------------------

class LapTracker(object):
    """Counts laps from the s coordinate of one car.

    progress is the unwrapped distance after the start line. Gates (checkpoints, then the
    finish line) must be crossed forward and in order; reversing or re-crossing a gate
    never counts twice because the next gate is a single increasing position in progress.
    Crossing time is interpolated inside the tick: t = (tick - 1 + f) * DT.
    """

    def __init__(self, track, s, tick=0):
        self.length = track.length
        self.line = track.start_s
        self.gates_rel = track.gates_rel
        rel = (s - self.line) % self.length
        self._rel = rel
        # a car placed behind the line (grid) starts with negative progress
        self.progress = rel - self.length if rel > 0.5 * self.length else rel
        self.lap = 0                  # completed laps
        self._gate = -1               # -1: waiting for the first crossing of the start line
        self._lap_base = 0.0
        self.lap_start_time = None
        self.lap_times = []
        self.sector_times = []
        self._last_gate_time = None
        self.events = []
        self.max_step = 40.0          # m per tick; larger changes of s are treated as a jump
        self.lap_valid = True
        if self.progress >= 0.0:      # started on / after the line (rolling start not timed)
            self._gate = 0

    def _next_pos(self):
        if self._gate < 0:
            return 0.0
        return self._lap_base + self.gates_rel[self._gate]

    def update(self, s, tick):
        """Call once per tick after the physics step. tick = number of completed ticks."""
        rel = (s - self.line) % self.length
        dp = rel - self._rel
        half = 0.5 * self.length
        if dp > half:
            dp -= self.length
        elif dp <= -half:
            dp += self.length
        p0 = self.progress
        p1 = p0 + dp
        out = []
        if dp > self.max_step or dp < -self.max_step:
            # s jumped (reset / teleport): never count gates across a jump, void the lap
            self.lap_valid = False
            out.append(("jump", 0, tick * DT))
            dp = 0.0
        while dp > 0.0:
            target = self._next_pos()
            if not (p0 < target <= p1):
                break
            t = (tick - 1 + (target - p0) / (p1 - p0)) * DT
            if self._gate < 0:
                self.lap_start_time = t
                self._last_gate_time = t
                self._gate = 0
                out.append(("start", 0, t))
            else:
                if self._last_gate_time is not None:
                    self.sector_times.append(t - self._last_gate_time)
                self._last_gate_time = t
                if self._gate == len(self.gates_rel) - 1:
                    if self.lap_start_time is not None and self.lap_valid:
                        self.lap_times.append(t - self.lap_start_time)
                        out.append(("lap", self.lap + 1, t - self.lap_start_time))
                    else:
                        out.append(("lap_untimed", self.lap + 1, t))
                    self.lap_valid = True
                    self.lap += 1
                    self.lap_start_time = t
                    self._lap_base += self.length
                    self._gate = 0
                else:
                    out.append(("gate", self._gate, t))
                    self._gate += 1
        self.progress = p1
        self._rel = rel
        self.events.extend(out)
        return out


# ---------------------------------------------------------------------------
# collisions
# ---------------------------------------------------------------------------

def car_wall_contact(q, yaw, half_len, half_wid):
    """Rectangle vs. corridor walls using the centre's track frame.
    Returns (penetration m, side) with side +1 = left wall, -1 = right wall, 0 = none."""
    a = yaw - q.heading
    ext = abs(math.sin(a)) * half_len + abs(math.cos(a)) * half_wid
    # (curvature of the wall over the car length is ignored: l^2 / (2R) = 0.15 m at R = 15 m)
    pen_l = q.d + ext - q.wall_left
    pen_r = ext - q.d - q.wall_right
    if pen_l > 0.0 and pen_l >= pen_r:
        return pen_l, 1
    if pen_r > 0.0:
        return pen_r, -1
    return 0.0, 0


def resolve_wall(q, x, z, vx, vz, yaw, half_len=2.1, half_wid=0.85, restitution=0.15, friction=0.35):
    """Push the car back inside the wall and remove speed.
    Returns (x, z, vx, vz, hit, impact_speed). PROVISIONAL constants."""
    pen, side = car_wall_contact(q, yaw, half_len, half_wid)
    if side == 0:
        return x, z, vx, vz, False, 0.0
    ch = math.cos(q.heading)
    sh = math.sin(q.heading)
    nx = -sh * side          # outward normal (towards the wall)
    nz = ch * side
    x -= nx * pen
    z -= nz * pen
    vn = vx * nx + vz * nz
    impact = 0.0
    if vn > 0.0:
        impact = vn
        vt = vx * ch + vz * sh
        loss = friction * (1.0 + restitution) * vn
        if vt > loss:
            vt -= loss
        elif vt < -loss:
            vt += loss
        else:
            vt = 0.0
        vn2 = -restitution * vn
        vx = vt * ch + vn2 * nx
        vz = vt * sh + vn2 * nz
    return x, z, vx, vz, True, impact


def obb_overlap(ax, az, ayaw, bx, bz, byaw, half_len=2.1, half_wid=0.85):
    """Oriented rectangles (SAT). Returns (depth, nx, nz): minimum translation to move A
    away from B is depth along (nx, nz); depth <= 0 means no overlap."""
    ca = math.cos(ayaw)
    sa = math.sin(ayaw)
    cb = math.cos(byaw)
    sb = math.sin(byaw)
    dx = ax - bx
    dz = az - bz
    best = 1e30
    bnx = bnz = 0.0
    for ux, uz, own_a in ((ca, sa, 0), (-sa, ca, 1), (cb, sb, 2), (-sb, cb, 3)):
        ra = half_len * abs(ux * ca + uz * sa) + half_wid * abs(-ux * sa + uz * ca)
        rb = half_len * abs(ux * cb + uz * sb) + half_wid * abs(-ux * sb + uz * cb)
        dist = dx * ux + dz * uz
        depth = ra + rb - abs(dist)
        if depth <= 0.0:
            return depth, 0.0, 0.0
        if depth < best:
            best = depth
            if dist >= 0.0:
                bnx, bnz = ux, uz
            else:
                bnx, bnz = -ux, -uz
    return best, bnx, bnz


def circles_overlap(ax, az, ayaw, bx, bz, byaw, half_len=2.1, half_wid=0.85):
    """Two circles per car (front / rear). Returns (depth, nx, nz) like obb_overlap."""
    r = half_wid * 1.1
    off = half_len - r
    best = 0.0
    bnx = bnz = 0.0
    ca = math.cos(ayaw) * off
    sa = math.sin(ayaw) * off
    cb = math.cos(byaw) * off
    sb = math.sin(byaw) * off
    for sa_ in (1.0, -1.0):
        px = ax + sa_ * ca
        pz = az + sa_ * sa
        for sb_ in (1.0, -1.0):
            dx = px - (bx + sb_ * cb)
            dz = pz - (bz + sb_ * sb)
            d2 = dx * dx + dz * dz
            if d2 < 4.0 * r * r:
                dist = math.sqrt(d2)
                depth = 2.0 * r - dist
                if depth > best:
                    best = depth
                    if dist > 1e-9:
                        bnx = dx / dist
                        bnz = dz / dist
                    else:
                        bnx, bnz = 1.0, 0.0
    return best, bnx, bnz


def resolve_car_pair(a, b, depth, nx, nz, restitution=0.2):
    """a, b: dicts with x, z, vx, vz, mass. Separates and exchanges normal momentum."""
    ma = a["mass"]
    mb = b["mass"]
    wa = mb / (ma + mb)
    wb = ma / (ma + mb)
    a["x"] += nx * depth * wa
    a["z"] += nz * depth * wa
    b["x"] -= nx * depth * wb
    b["z"] -= nz * depth * wb
    rel = (a["vx"] - b["vx"]) * nx + (a["vz"] - b["vz"]) * nz
    if rel < 0.0:      # approaching
        jimp = -(1.0 + restitution) * rel / (1.0 / ma + 1.0 / mb)
        a["vx"] += jimp / ma * nx
        a["vz"] += jimp / ma * nz
        b["vx"] -= jimp / mb * nx
        b["vz"] -= jimp / mb * nz
        return -rel
    return 0.0


# ---------------------------------------------------------------------------
# ideal line and speed profile
# ---------------------------------------------------------------------------

def relax_racing_line(track, margin=1.3, steps=(64, 32, 16, 8, 4, 2, 1), iters_base=100):
    """Racing line by curvature equalisation (K1999-style, coarse to fine).

    Each point is moved along its track normal so that the curvature there becomes the
    length-weighted mean of the curvature just before and just after it; the offset is
    clamped to |d| <= half_width - margin. Returns lateral offsets, one per table sample.
    Offline tool (about 1 s native); the result is baked into the track JSON."""
    n = track.n
    cx = track._x
    cz = track._z
    nx = [-t for t in track._tz]
    nz = list(track._tx)
    lim = [max(0.0, track._half[i] - margin) for i in range(n)]
    d = [0.0] * n
    px = list(cx)
    pz = list(cz)
    sqrt = math.sqrt

    def rinv(a, b, c):
        x1 = px[b] - px[a]
        z1 = pz[b] - pz[a]
        x2 = px[c] - px[b]
        z2 = pz[c] - pz[b]
        x3 = px[c] - px[a]
        z3 = pz[c] - pz[a]
        den = sqrt((x1 * x1 + z1 * z1) * (x2 * x2 + z2 * z2) * (x3 * x3 + z3 * z3))
        return 2.0 * (x1 * z2 - z1 * x2) / den if den > 1e-12 else 0.0

    def adjust(p, i, q, target):
        vx = px[q] - px[p]
        vz = pz[q] - pz[p]
        den = vx * nz[i] - vz * nx[i]
        if den < 1e-9 and den > -1e-9:
            return
        # offset that puts point i on the chord p-q (zero curvature there)
        d0 = -(vx * (cz[i] - pz[p]) - vz * (cx[i] - px[p])) / den
        delta = 0.1
        px[i] = cx[i] + (d0 + delta) * nx[i]
        pz[i] = cz[i] + (d0 + delta) * nz[i]
        dr = rinv(p, i, q)
        if dr > 1e-12 or dr < -1e-12:
            d0 += delta * target / dr
        if d0 > lim[i]:
            d0 = lim[i]
        elif d0 < -lim[i]:
            d0 = -lim[i]
        d[i] = d0
        px[i] = cx[i] + d0 * nx[i]
        pz[i] = cz[i] + d0 * nz[i]

    for step in steps:
        idx = list(range(0, n - (n % step), step))
        m = len(idx)
        if m < 5:
            continue
        for _ in range(iters_base * int(sqrt(step))):
            for k in range(m):
                i = idx[k]
                p = idx[k - 1]
                pp = idx[k - 2]
                q = idx[(k + 1) % m]
                qq = idx[(k + 2) % m]
                r0 = rinv(pp, p, i)
                r1 = rinv(i, q, qq)
                lp = sqrt((px[i] - px[p]) ** 2 + (pz[i] - pz[p]) ** 2)
                lq = sqrt((px[q] - px[i]) ** 2 + (pz[q] - pz[i]) ** 2)
                adjust(p, i, q, (lq * r0 + lp * r1) / (lp + lq))
        if step > 1:    # interpolate the samples between stations
            for k in range(m):
                i = idx[k]
                q = idx[(k + 1) % m]
                r0 = rinv(idx[k - 1], i, q)
                r1 = rinv(i, q, idx[(k + 2) % m])
                span = (q - i) % n
                for o in range(1, span):
                    u = o / float(span)
                    adjust(i, (i + o) % n, q, (1.0 - u) * r0 + u * r1)
    return d


def line_geometry(track, d_line, base=2):
    """Points, segment lengths and curvature of a line given by lateral offsets."""
    n = track.n
    px = [0.0] * n
    pz = [0.0] * n
    for i in range(n):
        px[i] = track._x[i] - d_line[i] * track._tz[i]
        pz[i] = track._z[i] + d_line[i] * track._tx[i]
    seg = [math.hypot(px[(i + 1) % n] - px[i], pz[(i + 1) % n] - pz[i]) for i in range(n)]
    kap = [0.0] * n
    for i in range(n):
        a = (i - base) % n
        b = (i + base) % n
        x1 = px[i] - px[a]
        z1 = pz[i] - pz[a]
        x2 = px[b] - px[i]
        z2 = pz[b] - pz[i]
        x3 = px[b] - px[a]
        z3 = pz[b] - pz[a]
        den = math.hypot(x1, z1) * math.hypot(x2, z2) * math.hypot(x3, z3)
        kap[i] = 2.0 * (x1 * z2 - z1 * x2) / den if den > 1e-12 else 0.0   # Menger curvature
    return px, pz, seg, kap


# PROVISIONAL reference car (class A, FR 280 ps, 1340 kg + driver)
REF_CAR = {"a_lat": 1.05 * G, "a_brake": 1.05 * G, "a_trac": 0.60 * G,
           "power_w": 280 * 735.5 * 0.85 * 0.92, "mass": 1340.0 + 70.0,
           "cda": 0.62, "crr": 0.015, "v_cap": 70.0}


def speed_profile(track, d_line, car=None):
    """Target speed along a line: v <= sqrt(a_lat/|kappa|), then forward (traction/power)
    and backward (braking) passes with a friction-circle share. Returns dict(v, lap_time, ...)."""
    c = dict(REF_CAR)
    if car:
        c.update(car)
    n = track.n
    _, _, seg, kap = line_geometry(track, d_line)
    a_lat = c["a_lat"]
    v_cap = c["v_cap"]
    vmax = [min(v_cap, math.sqrt(a_lat / abs(k))) if abs(k) > 1e-9 else v_cap for k in kap]
    v = list(vmax)
    mass = c["mass"]
    drag_k = 0.5 * 1.2 * c["cda"] / mass
    roll = c["crr"] * G
    start = v.index(min(v))
    for _ in range(2):          # two laps so the periodic profile settles
        for q in range(n):      # forward: acceleration limit
            i = (start + q) % n
            j = (i + 1) % n
            vi = v[i]
            use = vi * vi * abs(kap[i]) / a_lat
            rem = math.sqrt(1.0 - use * use) if use < 1.0 else 0.0
            a = min(c["power_w"] / (mass * max(vi, 3.0)), c["a_trac"] * rem) - drag_k * vi * vi - roll
            vj = math.sqrt(max(0.0, vi * vi + 2.0 * a * seg[i]))
            if vj < v[j]:
                v[j] = vj
        for q in range(n):      # backward: braking limit
            j = (start - q) % n
            i = (j - 1) % n
            vj = v[j]
            use = vj * vj * abs(kap[j]) / a_lat
            rem = math.sqrt(1.0 - use * use) if use < 1.0 else 0.0
            a = c["a_brake"] * rem + drag_k * vj * vj + roll
            vi = math.sqrt(vj * vj + 2.0 * a * seg[i])
            if vi < v[i]:
                v[i] = vi
    lap = 0.0
    for i in range(n):
        lap += seg[i] / max(0.5, 0.5 * (v[i] + v[(i + 1) % n]))
    return {"v": v, "lap_time": lap, "line_length": sum(seg), "v_min": min(v), "v_max": max(v),
            "kappa": kap, "vmax_corner": vmax}


# ---------------------------------------------------------------------------
# render mesh (flat lists; turning them into pyxel Primitives is the display side's job)
# ---------------------------------------------------------------------------

MESH_PARTS = ("road", "kerb", "grass", "gravel", "wall")


def mesh_stations(track, max_len=12.0, angle_tol_deg=3.0, chunk_len=60.0, y_tol=0.05):
    """Adaptive station indices (sample numbers, ends at n). Straights get long quads."""
    n = track.n
    max_steps = max(1, int(max_len / track.ds + 1e-6))
    chunk_steps = max(1, int(round(chunk_len / track.ds)))
    tol = math.radians(angle_tol_deg)
    bands = (track._ekl, track._egl, track._ewl, track._ekr, track._egr, track._ewr, track._half)
    out = [0]
    i = 0
    while i < n:
        j = i + 1
        limit = min(n, i + max_steps, (i // chunk_steps + 1) * chunk_steps)
        while j < limit:
            jn = j % n
            if abs(track._h[jn] - track._h[i] if jn else track.turning + track._h[0] - track._h[i]) > tol:
                break
            # band offsets must stay linear between i and candidate end j+1
            k = j + 1
            kn = k % n
            lin_ok = True
            for arr in bands:
                for m in range(i + 1, k):
                    u = (m - i) / float(k - i)
                    if abs(arr[m % n] - (arr[i] + u * (arr[kn] - arr[i]))) > 0.05:
                        lin_ok = False
                        break
                if not lin_ok:
                    break
            if not lin_ok:
                break
            ymid = track._y[i] + (track._y[kn] - track._y[i]) * (j - i) / float(k - i)
            if abs(track._y[jn] - ymid) > y_tol:
                break
            j += 1
        out.append(j)
        i = j
    return out


def build_mesh(track, max_len=12.0, angle_tol_deg=3.0, chunk_len=60.0, wall_height=1.0,
               tile_len=8.0, flip_z=False):
    """Returns a list of chunks. Each chunk:
       {"s0", "s1", "center": (x, y, z), "radius", "parts": {name: {"positions": [x,y,z,...],
        "indices": [...], "uvs": [u,v,...]}}, "triangles"}.
    Quads own their 4 vertices. u runs across the band (0..1), v along the track in tiles
    (s / tile_len, continuous inside a quad). Triangles are counter-clockwise seen from above
    in a right-handed y-up frame; with flip_z=True z is negated and the winding swapped."""
    n = track.n
    st = mesh_stations(track, max_len, angle_tol_deg, chunk_len)
    chunk_steps = max(1, int(round(chunk_len / track.ds)))
    zs = -1.0 if flip_z else 1.0
    chunks = {}

    def section(i):
        i %= n
        x = track._x[i]
        z = track._z[i]
        y = track._y[i]
        nx = -track._tz[i]
        nz = track._tx[i]
        b = track._bank[i]
        offs = (-track._ewr[i], -track._egr[i], -track._ekr[i], -track._half[i],
                track._half[i], track._ekl[i], track._egl[i], track._ewl[i])
        return [(x + o * nx, y + o * b, (z + o * nz) * zs) for o in offs], offs

    names = ("gravel", "grass", "kerb", "road", "kerb", "grass", "gravel")
    for a, b in zip(st[:-1], st[1:]):
        key = a // chunk_steps
        ch = chunks.get(key)
        if ch is None:
            ch = {"s0": a * track.ds, "s1": 0.0, "parts": dict((p, {"positions": [], "indices": [], "uvs": []})
                                                               for p in MESH_PARTS), "triangles": 0}
            chunks[key] = ch
        ch["s1"] = b * track.ds
        pa, oa = section(a)
        pb, ob = section(b)
        v0 = (a * track.ds) / tile_len
        v1 = (b * track.ds) / tile_len
        vb = math.floor(v0)
        v0 -= vb
        v1 -= vb

        def quad(part, p0, p1, p2, p3, wa, wb):
            # p0 = right@a, p1 = left@a, p2 = left@b, p3 = right@b
            if wa < 0.02 and wb < 0.02:
                return
            pr = ch["parts"][part]
            base = len(pr["positions"]) // 3
            for p in (p0, p1, p2, p3):
                pr["positions"].extend(p)
            pr["uvs"].extend((0.0, v0, 1.0, v0, 1.0, v1, 0.0, v1))
            tris = []
            # seen from above (y up, right-handed, x east, z south when not flipped) the order
            # right@a -> right@b -> left@b is counter-clockwise only after the z flip, so pick per flag
            if wb >= 0.02:
                tris.append((0, 3, 2) if flip_z else (0, 2, 3))
            if wa >= 0.02:
                tris.append((0, 2, 1) if flip_z else (0, 1, 2))
            for t in tris:
                pr["indices"].extend((base + t[0], base + t[1], base + t[2]))
            ch["triangles"] += len(tris)

        for k in range(7):
            quad(names[k], pa[k], pa[k + 1], pb[k + 1], pb[k], oa[k + 1] - oa[k], ob[k + 1] - ob[k])
        # walls: vertical quads facing the track
        for k, facing_left in ((0, True), (7, False)):
            lo_a = pa[k]
            lo_b = pb[k]
            hi_a = (lo_a[0], lo_a[1] + wall_height, lo_a[2])
            hi_b = (lo_b[0], lo_b[1] + wall_height, lo_b[2])
            pr = ch["parts"]["wall"]
            base = len(pr["positions"]) // 3
            for p in (lo_a, hi_a, hi_b, lo_b):
                pr["positions"].extend(p)
            pr["uvs"].extend((v0, 1.0, v0, 0.0, v1, 0.0, v1, 1.0))
            order = ((0, 2, 1), (0, 3, 2)) if (facing_left != flip_z) else ((0, 1, 2), (0, 2, 3))
            for t in order:
                pr["indices"].extend((base + t[0], base + t[1], base + t[2]))
            ch["triangles"] += 2
    out = []
    for key in sorted(chunks):
        ch = chunks[key]
        xs = []
        ys = []
        zz = []
        for pr in ch["parts"].values():
            xs.extend(pr["positions"][0::3])
            ys.extend(pr["positions"][1::3])
            zz.extend(pr["positions"][2::3])
        cx = 0.5 * (min(xs) + max(xs))
        cy = 0.5 * (min(ys) + max(ys))
        cz = 0.5 * (min(zz) + max(zz))
        ch["center"] = (cx, cy, cz)
        ch["radius"] = max(math.sqrt((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) for x, y, z in zip(xs, ys, zz))
        out.append(ch)
    return out
