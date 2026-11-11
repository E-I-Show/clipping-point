"""synth.py -- synthetic driving data for the replay spike (pure Python, deterministic).

A closed ~1.8 km circuit (Catmull-Rom through hand placed points), cars follow it with a
curvature-limited speed profile, braking / accelerating, gear shifts, body roll / pitch,
steering corrections, suspension noise, contacts (velocity jumps), off-track excursions and spins.
This is NOT the game's vehicle model; it only produces plausible 60 Hz signals to test the recorder.
"""
import math
import random

DT = 1.0 / 60.0
CTRL = [(0, 0), (130, 0), (260, 0), (330, 18), (352, 78), (305, 128), (228, 122), (182, 160),
        (228, 218), (322, 226), (362, 272), (322, 318), (205, 300), (102, 330), (22, 300),
        (-38, 242), (0, 182), (62, 152), (42, 100), (-58, 108), (-108, 62), (-82, 10)]
HALF_WIDTH = 6.0


class Track:
    def __init__(self, length=1800.0, ds=1.0):
        pts = CTRL
        n = len(pts)
        dense = []
        for i in range(n):
            p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
            for k in range(40):
                t = k / 40.0
                t2, t3 = t * t, t * t * t
                dense.append(tuple(
                    0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                           + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in (0, 1)))
        # arc length, scale to requested length
        cum = [0.0]
        for i in range(len(dense)):
            a, b = dense[i], dense[(i + 1) % len(dense)]
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        scale = length / cum[-1]
        dense = [(p[0] * scale, p[1] * scale) for p in dense]
        cum = [c * scale for c in cum]
        self.length = length
        self.ds = ds
        m = int(round(length / ds))
        self.n = m
        self.px, self.pz = [], []
        j = 0
        nd = len(dense)
        for i in range(m):
            s = i * ds
            while cum[j + 1] < s:
                j += 1
            f = (s - cum[j]) / (cum[j + 1] - cum[j])
            a, b = dense[j], dense[(j + 1) % nd]
            self.px.append(a[0] + (b[0] - a[0]) * f)
            self.pz.append(a[1] + (b[1] - a[1]) * f)
        # heading and curvature (smoothed)
        self.hd = []
        for i in range(m):
            self.hd.append(math.atan2(self.pz[(i + 1) % m] - self.pz[i - 1], self.px[(i + 1) % m] - self.px[i - 1]))
        k = []
        for i in range(m):
            d = self.hd[(i + 1) % m] - self.hd[i - 1]
            d = (d + math.pi) % (2 * math.pi) - math.pi
            k.append(d / (2 * ds))
        for _ in range(3):
            k = [(k[i - 2] + k[i - 1] + k[i] + k[(i + 1) % m] + k[(i + 2) % m]) / 5.0 for i in range(m)]
        self.k = k

    def at(self, s):
        """(x, z, heading, curvature, y, slope) at arc length s (wrapped, linear interpolation)."""
        m = self.n
        u = (s % self.length) / self.ds
        i = int(u)
        f = u - i
        i %= m
        j = (i + 1) % m
        x = self.px[i] + (self.px[j] - self.px[i]) * f
        z = self.pz[i] + (self.pz[j] - self.pz[i]) * f
        dh = (self.hd[j] - self.hd[i] + math.pi) % (2 * math.pi) - math.pi
        h = self.hd[i] + dh * f
        k = self.k[i] + (self.k[j] - self.k[i]) * f
        w = 2 * math.pi / self.length
        y = 3.0 * math.sin(w * s) + 1.5 * math.sin(2 * w * s + 1.0)
        slope = 3.0 * w * math.cos(w * s) + 3.0 * w * math.cos(2 * w * s + 1.0)
        return x, z, h, k, y, slope

    def bbox(self):
        return (min(self.px), -5.0, min(self.pz)), (max(self.px), 5.0, max(self.pz))

    def corners(self, thresh=1.0 / 80.0):
        """count of separate stretches where |curvature| > thresh (radius < 80 m)."""
        c = 0
        prev = abs(self.k[-1]) > thresh
        for v in self.k:
            cur = abs(v) > thresh
            if cur and not prev:
                c += 1
            prev = cur
        return c

    def speed_profile(self, a_lat, a_brake, a_acc0, v_top):
        m = self.n
        v = [min(v_top, math.sqrt(a_lat / max(abs(k), 1e-4))) for k in self.k]
        for _ in range(2):
            for i in range(2 * m):                      # forward: acceleration limit
                j, jn = i % m, (i + 1) % m
                acc = a_acc0 * max(0.08, 1.0 - v[j] / (v_top * 1.05))
                v[jn] = min(v[jn], math.sqrt(v[j] * v[j] + 2 * acc * self.ds))
            for i in range(2 * m, 0, -1):               # backward: braking limit
                j, jp = i % m, (i - 1) % m
                v[jp] = min(v[jp], math.sqrt(v[j] * v[j] + 2 * a_brake * self.ds))
        return v


CAR_PARAMS = [  # a_lat, a_brake, a_acc0, v_top, gear ratios*final, redline
    dict(a_lat=14.5, a_brake=13.0, a_acc0=7.6, v_top=64.0),
    dict(a_lat=15.0, a_brake=13.5, a_acc0=7.9, v_top=66.0),
    dict(a_lat=13.6, a_brake=12.2, a_acc0=6.0, v_top=57.0),
    dict(a_lat=13.9, a_brake=12.5, a_acc0=5.8, v_top=56.0),
    dict(a_lat=13.2, a_brake=11.8, a_acc0=6.6, v_top=60.0),
    dict(a_lat=13.5, a_brake=12.0, a_acc0=7.2, v_top=62.0),
]
GEARS = [13.2, 8.4, 6.0, 4.7, 3.9, 3.3]   # overall ratio per gear
WHEEL_R = 0.31


def simulate(n_cars=6, seconds=300.0, seed=1, track=None, events_rate=1.0, start_gap=9.0):
    """Returns dict(track, ticks=[per car list of state tuples], events=[(tick,type,car,a,b)], marks).
    state = (x,y,z,yaw,pitch,roll,steer,rpm,gear,brake,surface,contact,cut,slip,throttle, s_total, v)"""
    track = track or Track()
    rng = random.Random(seed)
    n_ticks = int(round(seconds / DT))
    L = track.length
    out = []
    events = [(0, 1, 255, 0, 0)]
    marks = {"contact": [], "spin": [], "offtrack": []}
    progress = []
    for c in range(n_cars):
        P = CAR_PARAMS[c % len(CAR_PARAMS)]
        prof = track.speed_profile(P["a_lat"], P["a_brake"], P["a_acc0"], P["v_top"])
        r = random.Random(seed * 1000 + c)
        s = -start_gap * c - 5.0 + L          # grid behind the line (s measured so the line is at k*L)
        s0 = s
        v = 0.0
        gear = 1
        shift_t = 0.0
        # lateral line: slow sines + noise
        ph = [r.uniform(0, 6.28) for _ in range(3)]
        amp = [r.uniform(0.6, 1.6), r.uniform(0.3, 0.9), r.uniform(0.2, 0.5)]
        lat_noise = 0.0
        ex_off, ex_vel = 0.0, 0.0             # excursion offset (contact shove / off-track)
        beta_kick = 0.0
        spin_t, spin_total = -1.0, 0.0
        spin_base = 0.0
        off_t = -1.0
        off_side = 1.0
        off_prev = None
        ln_v = 0.0
        roll_f = 0.0
        pitch_f = 0.0
        hd_f = 0.0
        kick_w = 0.0
        pn, rn, yn, sn = 0.0, 0.0, 0.0, 0.0   # suspension / steering noise states
        grid_side = 1.8 if c % 2 else -1.8
        prev = None
        hd_prev = None
        v_prev = 0.0
        yaw_unwrapped = None
        states = []
        prog = []
        lap = 0
        lap_start_ms = 0.0
        # scheduled incidents
        n_inc = int(seconds / 60.0 * events_rate * 1.2) + (1 if seconds >= 60 else 0)
        inc = sorted((r.uniform(12.0, max(13.0, seconds - 5.0)), r.choice(["contact", "contact", "off", "spin"]))
                     for _ in range(n_inc))
        inc_i = 0
        for t in range(n_ticks):
            time = t * DT
            contact = 0
            push = 0.0
            # incidents
            if inc_i < len(inc) and time >= inc[inc_i][0] and v > 12.0 and spin_t < 0 and off_t < 0:
                kind = inc[inc_i][1]
                inc_i += 1
                if kind == "contact":
                    contact = 1
                    dv = r.uniform(2.0, 6.0)
                    v = max(3.0, v - dv)
                    side = r.choice([-1, 1])
                    ex_vel += side * r.uniform(1.0, 2.5)
                    push = side * r.uniform(0.05, 0.25)         # push-back: position step in one tick
                    ex_off += push
                    kick_w += r.choice([-1, 1]) * r.uniform(0.5, 1.5)   # yaw rate impulse rad/s
                    marks["contact"].append((t, c))
                    events.append((t, 5, c, 0xFFFF, int(dv * 100)))
                elif kind == "off":
                    off_t = 0.0
                    off_side = 1.0 if track.at(s)[3] <= 0 else -1.0
                    marks["offtrack"].append((t, c))
                    events.append((t, 6, c, 1, 0))
                else:
                    spin_t = 0.0
                    spin_total = r.choice([-1, 1]) * (2 * math.pi if r.random() < 0.5 else math.pi * 2)
                    marks["spin"].append((t, c))
            x0, z0, h, k, y0, slope = track.at(s)
            target = prof[int((s % L) / track.ds) % track.n]
            grip = 1.0
            # off-track excursion: push the car wide for ~3.5 s
            if off_t >= 0:
                off_t += DT
                ex_target = 9.5 * math.sin(math.pi * min(1.0, off_t / 3.5)) ** 2 * off_side
                ex_new = ex_off + (ex_target - ex_off) * min(1.0, DT / 0.25)
                ex_vel = (ex_new - ex_off) / DT
                ex_off = ex_new
                grip = 0.55
                if off_t >= 3.5:
                    off_t = -1.0
            else:
                ex_vel -= ex_vel * DT / 0.35
                ex_off += ex_vel * DT
                ex_off -= ex_off * DT / 1.5
            spinning = spin_t >= 0
            if spinning:
                spin_t += DT
                grip = 0.35
                u = min(1.0, spin_t / 1.6)
                spin_beta = spin_total * (u * u * (3 - 2 * u))
                if spin_t >= 1.6:
                    spin_t = -1.0
                    spin_beta = 0.0          # a full turn: same orientation again
            else:
                spin_beta = 0.0
            # longitudinal
            if time < 3.0:
                target = 0.0                 # waiting on the grid
            vt = target * grip
            acc_max = P["a_acc0"] * max(0.08, 1.0 - v / (P["v_top"] * 1.05)) * (0.6 if shift_t > 0 else 1.0)
            dv = vt - v
            if dv > acc_max * DT:
                dv = acc_max * DT
            elif dv < -P["a_brake"] * DT:
                dv = -P["a_brake"] * DT
            v += dv + r.gauss(0.0, 0.004)
            if v < 0.0:
                v = 0.0
            a_long = (v - v_prev) / DT if not contact else 0.0
            v_prev = v
            s += v * DT
            a_lat = v * v * k
            # lateral line
            ln_v += (-ln_v / 0.5) * DT + r.gauss(0.0, 0.07) * math.sqrt(DT) * min(1.0, v / 15.0)
            lat_noise += ln_v * DT - lat_noise * DT / 3.0
            w = 2 * math.pi / L
            line = amp[0] * math.sin(w * s + ph[0]) + amp[1] * math.sin(3 * w * s + ph[1]) + amp[2] * math.sin(7 * w * s + ph[2])
            launch = max(0.0, 1.0 - (s - s0) / 120.0)
            off = line * (1.0 - launch) + grid_side * launch + lat_noise + ex_off
            x = x0 - math.sin(h) * off
            z = z0 + math.cos(h) * off
            # noise states (Ornstein-Uhlenbeck)
            vs = min(1.0, v / 15.0)
            pn += (-pn / 0.08) * DT + r.gauss(0.0, 0.010) * math.sqrt(DT) * vs
            rn += (-rn / 0.08) * DT + r.gauss(0.0, 0.012) * math.sqrt(DT) * vs
            yn += (-yn / 0.05) * DT + r.gauss(0.0, 0.012) * math.sqrt(DT) * vs
            sn += (-sn / 0.15) * DT + r.gauss(0.0, 0.03) * math.sqrt(DT) * vs
            y = y0 + 0.35 + yn
            # heading from actual motion
            off_rate = 0.0 if off_prev is None else (off - off_prev - push) / DT
            off_prev = off
            hd_f += (math.atan(off_rate / max(v, 4.0)) - hd_f) * min(1.0, DT / 0.06)
            hd = h + hd_f
            kick_w -= kick_w * DT / 0.15
            beta_kick += kick_w * DT - beta_kick * DT / 0.4
            beta = -0.0035 * a_lat + beta_kick + spin_beta
            yaw = hd + beta
            if yaw_unwrapped is None:
                yaw_unwrapped = yaw
            else:
                d = (yaw - yaw_unwrapped + math.pi) % (2 * math.pi) - math.pi
                yaw_unwrapped += d
            # body attitude follows the load transfer through a spring/damper lag (tau 0.1 s)
            roll_f += (0.004 * a_lat - roll_f) * (DT / 0.10)
            pitch_f += (-0.003 * a_long - pitch_f) * (DT / 0.10)
            roll = roll_f + rn
            pitch = pitch_f + math.atan(slope) + pn
            steer = math.atan(2.55 * k) * (1.0 + 0.0009 * v * v) + sn - 0.6 * beta_kick
            if spinning:
                steer = max(-0.6, min(0.6, -0.8 * math.sin(spin_beta)))
            steer = max(-0.62, min(0.62, steer))
            # gearbox
            if shift_t > 0:
                shift_t -= DT
            rpm_g = v / (2 * math.pi * WHEEL_R) * 60.0 * GEARS[gear - 1]
            if shift_t <= 0:
                if rpm_g > 7300 and gear < 6:
                    gear += 1
                    shift_t = 0.18
                elif rpm_g < 3900 and gear > 1:
                    gear -= 1
                    shift_t = 0.12
                rpm_g = v / (2 * math.pi * WHEEL_R) * 60.0 * GEARS[gear - 1]
            rpm = max(900.0, rpm_g) + r.gauss(0.0, 12.0)
            if time < 3.0:
                rpm = 2500.0 + 1500.0 * math.sin(time * 5.0) ** 2   # revving on the grid
            brake = 1 if (a_long < -1.0 or (time < 3.0)) else 0
            throttle = 0.0 if brake else max(0.0, min(1.0, 0.25 + a_long / max(0.5, acc_max)))
            lim = abs(a_lat) / P["a_lat"]
            slip = max(0.0, (lim - 0.8) / 0.25) + max(0.0, (-a_long - 8.0) / 4.0)
            if spinning:
                slip = 1.0
            slip = min(1.0, slip)
            ao = abs(off)
            surface = 0 if ao < 5.2 else (1 if ao < HALF_WIDTH else (2 if ao < 8.5 else 3))
            states.append((x, y, z, yaw_unwrapped, pitch, roll, steer, rpm, gear, brake, surface, contact, 0,
                           slip, throttle, s, v))
            prog.append(s)
            # lap counting: the line is at s = k*L
            new_lap = int(s // L) - 1
            if new_lap > lap:
                now_ms = time * 1000.0
                if lap >= 1 or True:
                    events.append((t, 2, c, new_lap, int(now_ms - lap_start_ms)))
                lap_start_ms = now_ms
                lap = new_lap
        out.append(states)
        progress.append(prog)
    # rank changes (checked every tick)
    order_prev = None
    for t in range(n_ticks):
        order = sorted(range(n_cars), key=lambda c: -progress[c][t])
        if order != order_prev:
            for rank, c in enumerate(order):
                if order_prev is None or order_prev[rank] != c:
                    events.append((t, 4, c, rank + 1, 0))
            order_prev = order
    events.sort(key=lambda e: e[0])
    return {"track": track, "ticks": out, "events": events, "marks": marks, "n_ticks": n_ticks}
