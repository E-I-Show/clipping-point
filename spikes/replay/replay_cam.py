"""replay_cam.py -- replay cameras computed from the recorded pose only (pure Python spike).

TV: table of fixed trackside cameras, each owning a stretch [s_from, s_to) of the lap.
Chase / on-board / heli: functions of the interpolated pose.
"""
import bisect
import math


class TrackIndex:
    """closed centre line polyline -> distance along the lap for a world position."""

    def __init__(self, px, pz):
        self.px = px
        self.pz = pz
        self.n = len(px)
        cum = [0.0]
        for i in range(self.n):
            j = (i + 1) % self.n
            cum.append(cum[-1] + math.hypot(px[j] - px[i], pz[j] - pz[i]))
        self.cum = cum
        self.length = cum[-1]

    def locate(self, x, z, hint=None, window=40.0):
        """s of the nearest centre line point. With hint (previous s) only +-window m is searched."""
        px, pz, n = self.px, self.pz, self.n
        if hint is None:
            rng = range(n)
        else:
            i0 = bisect.bisect_right(self.cum, hint % self.length) - 1
            w = int(window / (self.length / n)) + 1
            rng = range(i0 - w, i0 + w + 1)
        best = 1e30
        bi = 0
        for i in rng:
            k = i % n
            dx = px[k] - x
            dz = pz[k] - z
            d = dx * dx + dz * dz
            if d < best:
                best = d
                bi = k
        # refine on the two segments around the nearest vertex
        bs = self.cum[bi]
        bd = best
        for a in ((bi - 1) % n, bi):
            b = (a + 1) % n
            ex = px[b] - px[a]
            ez = pz[b] - pz[a]
            ll = ex * ex + ez * ez
            if ll <= 0.0:
                continue
            t = ((x - px[a]) * ex + (z - pz[a]) * ez) / ll
            if t < 0.0: t = 0.0
            elif t > 1.0: t = 1.0
            qx = px[a] + ex * t - x
            qz = pz[a] + ez * t - z
            d = qx * qx + qz * qz
            if d <= bd:
                bd = d
                bs = self.cum[a] + t * math.sqrt(ll)
        return bs % self.length


def in_arc(s, a, b, length):
    """is s inside [a, b) going forward on a closed lap of the given length?"""
    return ((s - a) % length) < ((b - a) % length or length)


class TvDirector:
    """Chooses the trackside camera for the focus car.

    cams: list of dicts {"pos": (x, y, z), "s_from": m, "s_to": m, optional "fov_min", "fov_max"}.
    The stretches must tile the lap. Rules:
      1. stateless pick = the camera whose stretch contains s (used on seek / focus change / first frame)
      2. keep the current camera while s is inside its stretch widened by `hyst` metres on both sides
      3. after a cut, no new cut for `min_hold` seconds unless s is more than `hard` metres outside
    dt passed to update() is replay time (so slow motion slows the camera work too).
    """

    def __init__(self, cams, length, hyst=10.0, min_hold=1.0, hard=40.0, view_width=16.0,
                 fov_min=5.0, fov_max=55.0, zoom_tau=0.35, aspect=320.0 / 240.0):
        self.cams = sorted(cams, key=lambda c: c["s_from"])
        self.starts = [c["s_from"] for c in self.cams]
        self.length = length
        self.hyst, self.min_hold, self.hard = hyst, min_hold, hard
        self.view_width = view_width
        self.fov_min, self.fov_max = fov_min, fov_max
        self.zoom_tau = zoom_tau
        self.aspect = aspect
        self.reset()

    def reset(self):
        self.cur = None
        self.held = 0.0
        self.fov = None

    def pick(self, s):
        i = bisect.bisect_right(self.starts, s % self.length) - 1
        return i if i >= 0 else len(self.cams) - 1

    def update(self, s, dt):
        """returns (camera index, cut?)"""
        if self.cur is None:
            self.cur = self.pick(s)
            self.held = 0.0
            return self.cur, True
        self.held += abs(dt)
        c = self.cams[self.cur]
        L = self.length
        if in_arc(s, c["s_from"] - self.hyst, c["s_to"] + self.hyst, L):
            return self.cur, False
        if self.held < self.min_hold and in_arc(s, c["s_from"] - self.hard, c["s_to"] + self.hard, L):
            return self.cur, False
        new = self.pick(s)
        if new == self.cur:
            return self.cur, False
        self.cur = new
        self.held = 0.0
        return new, True

    def target_fov(self, cam_index, car_pos):
        """vertical fov (degrees) that makes `view_width` metres span the screen width at the car."""
        c = self.cams[cam_index]
        p = c["pos"]
        d = math.sqrt((car_pos[0] - p[0]) ** 2 + (car_pos[1] - p[1]) ** 2 + (car_pos[2] - p[2]) ** 2)
        half_h = math.atan((self.view_width / self.aspect) / (2.0 * max(d, 0.5)))
        f = math.degrees(2.0 * half_h)
        lo = c.get("fov_min", self.fov_min)
        hi = c.get("fov_max", self.fov_max)
        return lo if f < lo else (hi if f > hi else f), d

    def zoom(self, cam_index, car_pos, dt, cut):
        """smoothed fov: snaps on a cut, otherwise first order lag with zoom_tau seconds."""
        f, d = self.target_fov(cam_index, car_pos)
        if cut or self.fov is None:
            self.fov = f
        else:
            self.fov += (f - self.fov) * (1.0 - math.exp(-abs(dt) / self.zoom_tau))
        return self.fov, d


def auto_cameras(track_px, track_pz, length, n=10, side_offset=14.0, height=4.5):
    """evenly spaced demo table: camera i owns [i*L/n, (i+1)*L/n) and stands beside its middle."""
    cams = []
    m = len(track_px)
    for i in range(n):
        s0 = length * i / n
        s1 = length * (i + 1) / n
        k = int((s0 + s1) / 2.0 / length * m) % m
        kn = (k + 1) % m
        tx = track_px[kn] - track_px[k]
        tz = track_pz[kn] - track_pz[k]
        ll = math.hypot(tx, tz) or 1.0
        side = 1.0 if i % 2 else -1.0
        cams.append({"id": i, "pos": (track_px[k] - tz / ll * side_offset * side, height,
                                      track_pz[k] + tx / ll * side_offset * side),
                     "s_from": s0, "s_to": s1})
    return cams


# ---- cameras that only need the pose (x, y, z, yaw, pitch, roll, ...) ----
def chase_camera(pose, dist=6.0, height=2.0, look_ahead=2.0):
    x, y, z, yaw = pose[0], pose[1], pose[2], pose[3]
    fx, fz = math.cos(yaw), math.sin(yaw)
    return (x - fx * dist, y + height, z - fz * dist), (x + fx * look_ahead, y + 0.6, z + fz * look_ahead)


def onboard_camera(pose, offset=(0.2, 1.05, 0.0)):
    """eye at a body-fixed offset (forward, up, right); returns eye, forward, up (unit vectors)."""
    x, y, z, yaw, pitch, roll = pose[:6]
    cy, sy, cp, sp, cr, sr = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch), math.cos(roll), math.sin(roll)
    fwd = (cy * cp, sp, sy * cp)
    right0 = (-sy, 0.0, cy)
    up0 = (-cy * sp, cp, -sy * sp)
    up = tuple(up0[i] * cr + right0[i] * sr for i in range(3))
    right = tuple(right0[i] * cr - up0[i] * sr for i in range(3))
    eye = tuple((x, y, z)[i] + fwd[i] * offset[0] + up[i] * offset[1] + right[i] * offset[2] for i in range(3))
    return eye, fwd, up


def heli_camera(pose, height=45.0, back=18.0):
    x, y, z, yaw = pose[0], pose[1], pose[2], pose[3]
    return (x - math.cos(yaw) * back, y + height, z - math.sin(yaw) * back), (x, y, z)
