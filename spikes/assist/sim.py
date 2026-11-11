"""Shared harness for the input-assist spike: car + course + driver models (pure Python)."""
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKES = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(SPIKES, "vehicle"))
sys.path.insert(0, os.path.join(SPIKES, "track"))
sys.path.insert(0, HERE)

from vehicle import make_car, G, DT          # noqa: E402
import track as trk                          # noqa: E402
from input_assist import InputAssist, PassThrough   # noqa: E402

KMH = 3.6
CARS = ("tsubame", "kazane", "shirogane", "arashi")
TRACK = trk.load_track(os.path.join(SPIKES, "track", "akane_short.json"))

# PROVISIONAL surface table (the vehicle model takes one mu for all four wheels)
SURF_MU = {"asphalt": 1.0, "kerb": 0.92, "grass": 0.55, "gravel": 0.45}
SURF_BUMP = {"asphalt": 0.0, "kerb": 0.5, "grass": 0.3, "gravel": 0.5}
# measured by the vehicle spike (steady circle, R30): maximum lateral g
CAR_LAT = {"tsubame": 0.89, "kazane": 0.91, "shirogane": 0.955, "arashi": 0.94}
CAR_TRAC = {"tsubame": 0.45, "kazane": 0.50, "shirogane": 0.55, "arashi": 0.80}


def wrap(a):
    while a > math.pi:
        a -= 2.0 * math.pi
    while a < -math.pi:
        a += 2.0 * math.pi
    return a


def make_profile(car_id, skill):
    """Target speed table along the baked ideal line for a driver using `skill` of the car."""
    car = make_car(car_id)
    sp = car.spec
    prof = trk.speed_profile(TRACK, TRACK._ideal_d, car={
        "a_lat": skill * CAR_LAT[car_id] * G, "a_brake": skill * 0.92 * G,
        "a_trac": CAR_TRAC[car_id] * G, "power_w": sp["power_ps"] * 735.5 * sp["drive_eff"] * 0.92,
        "mass": sp["mass"], "cda": sp["cda"], "crr": 0.014, "v_cap": 75.0})
    return prof["v"], prof["lap_time"]


class Driver(object):
    """Follows the ideal line.  analog: stick proportional to the angle to a look-ahead point,
    with a reaction delay and a slowly wandering error.  digital: left / right / none and
    pedal on / off only, decided every `period` ticks."""

    def __init__(self, car_id, analog, skill=0.80, kp=6.0, delay=6, noise=0.03, period=7,
                 seed=1, look_t=0.9, feather=True, dig_th=0.15, gate=0.80, us_gain=0.03):
        self.car_id = car_id
        self.analog = analog
        self.vprof, self.est_lap = make_profile(car_id, skill)
        self.kp = kp
        self.delay = delay
        self.noise = noise
        self.period = period
        self.look_t = look_t
        self.feather = feather
        self.dig_th = dig_th
        self.gate = gate
        self.us_gain = us_gain
        self.assist_ref = None
        self.lat_cap = CAR_LAT[car_id] * G
        self.a_brake = skill * 0.92 * G
        self.brake_g = make_car(car_id).spec["brake_g"]
        self.rng = random.Random(seed)
        self.queue = []
        self.wander = 0.0
        self.key = (0.0, 0.0, 0.0)
        self.phase = self.rng.randrange(period)

    def v_target(self, s):
        tr = TRACK
        f = (s % tr.length) / tr.ds
        i = int(f) % tr.n
        return self.vprof[i]

    def decide(self, car, q, tick):
        v = car.speed
        ld = self.look_t * v
        ld = 6.0 if ld < 6.0 else (30.0 if ld > 30.0 else ld)
        s_t = q.s + ld
        d_t, _ = TRACK.ideal(s_t)
        tx, tz, _, _ = TRACK.pose_at(s_t, d_t)
        eta = wrap(math.atan2(tz - car.z, tx - car.x) - car.heading)
        lat = abs(car.ay) / self.lat_cap
        # speed: deceleration needed to meet the profile at several distances ahead
        a_req = 0.0
        v2 = v * v
        for dist in (4.0, 10.0, 20.0, 35.0, 55.0):
            vt = self.v_target(q.s + dist)
            a = (v2 - vt * vt) / (2.0 * dist)
            if a > a_req:
                a_req = a
        v_t = self.v_target(q.s + v * 0.10)
        err = v_t - v
        if self.analog:
            # slowly wandering hand error (first-order noise, sigma = noise)
            self.wander += (-self.wander) * DT / 0.4 + self.rng.gauss(0.0, 1.0) * self.noise * math.sqrt(2.0 * DT / 0.4)
            st = self.kp * eta + self.wander
            st = -1.0 if st < -1.0 else (1.0 if st > 1.0 else st)
            if a_req > 1.0:
                th = 0.0
                bk = min(1.0, a_req / (self.brake_g * G))
            elif err > 0.0:
                th = 0.25 + 0.4 * err
                if self.feather:
                    th = min(th, max(0.15, 1.6 * (1.05 - lat)))
                th = 1.0 if th > 1.0 else th
                bk = 0.0
            else:
                th = 0.1
                bk = 0.0
            out = (st, th, bk)
        else:
            if (tick + self.phase) % self.period == 0:
                # "how much wheel does this bend need" (learned feel): kinematic angle for the
                # look-ahead arc + a little for the slip angles; press towards it, release near it
                kd = 2.0 * math.sin(eta) / ld
                want = car.L * kd + self.us_gain * kd * v * v / G
                if abs(car.body_slip) > 0.09 and v > 5.0:
                    want = eta          # sliding: point the front wheels where the car should go
                lim = getattr(self.assist_ref, "limit", 0.0) or car.max_steer
                e = (want - car.steer) / lim
                if v < 3.0:
                    e = eta * 2.0
                st = 1.0 if e > self.dig_th else (-1.0 if e < -self.dig_th else 0.0)
                on = self.key[2] > 0.5
                if a_req > (0.30 if on else 0.75) * self.a_brake:
                    th, bk = 0.0, 1.0
                elif err > 0.3 and a_req < 1.0 and (not self.feather or lat < self.gate):
                    th, bk = 1.0, 0.0
                else:
                    th, bk = 0.0, 0.0
                self.key = (st, th, bk)
            out = self.key
        self.queue.append(out)
        if len(self.queue) > self.delay:
            return self.queue.pop(0)
        return (0.0, 1.0 if not self.analog else 0.6, 0.0)


class World(object):
    """One car on the course: surface mu, wall push-back, lap counting, incident counting."""

    def __init__(self, car_id, assist, setup=None, grid=0, cs_car_rate=False):
        self.car = make_car(car_id, setup)
        self.cs_car_rate = cs_car_rate
        self.base_steer_rate = self.car.steer_rate
        self.assist = assist
        x, z, h, _ = TRACK.start_pose(grid)
        self.car.reset(x, z, h, 0.0)
        self.q = TRACK.query(x, z)
        self.laps = trk.LapTracker(TRACK, self.q.s, 0)
        self.tick = 0
        self.off2 = 0          # centre beyond the asphalt edge (2 wheels or more off)
        self.off4 = 0          # centre beyond edge + half width (all four off)
        self.spins = 0
        self.walls = 0
        self.resets = 0
        self._off2 = False
        self._off4 = False
        self._spin_t = -999
        self._wall_t = -999
        self._slow = 0
        self._wrong = 0
        self.max_out = 0.0
        self.max_beta = 0.0
        self.lap_incident = {}   # lap number -> incidents during that lap
        self.fly = {"spins": 0, "off2": 0, "off4": 0, "walls": 0, "resets": 0}   # laps >= 1 only
        self._prev_counts = (0, 0, 0, 0, 0)
        self.mu = 1.0

    def step(self, steer, throttle, brake, steer_analog=True, pedal_analog=True):
        car = self.car
        q = self.q
        mu = SURF_MU[q.surface]
        self.mu = mu
        cmd, th, bk = self.assist.step(steer, throttle, brake, car, steer_analog, pedal_analog,
                                       pedal_analog, mu)
        if self.cs_car_rate:
            # experiment: let the car-side steering rate follow the countersteer relaxation
            car.steer_rate = self.base_steer_rate * getattr(self.assist, "steer_rate_scale", 1.0)
        car.step(cmd, th, bk, mu, DT, SURF_BUMP[q.surface])
        self.tick += 1
        q = TRACK.query(car.x, car.z, q.index)
        if not q.converged:
            q = TRACK.query(car.x, car.z)
        x, z, vx, vz, hit, impact = trk.resolve_wall(q, car.x, car.z, car.wvx, car.wvz, car.heading)
        inc = 0
        if hit:
            car.x, car.z, car.wvx, car.wvz = x, z, vx, vz
            c = math.cos(car.heading)
            s = math.sin(car.heading)
            car.vx = vx * c + vz * s
            car.vy = vz * c - vx * s
            car.yaw_rate *= 0.7
            if impact > 1.0 and self.tick - self._wall_t > 60:
                self.walls += 1
                inc += 1
            self._wall_t = self.tick
            q = TRACK.query(car.x, car.z, q.index)
        self.q = q
        self.laps.update(q.s, self.tick)
        out = abs(q.d) - q.half_left
        if out > self.max_out:
            self.max_out = out
        o2 = out > 0.0
        o4 = out > 0.85
        if o2 and not self._off2:
            self.off2 += 1
            inc += 1
        if o4 and not self._off4:
            self.off4 += 1
        if o2:
            self._off2 = True
        elif out < -0.3:
            self._off2 = False
        self._off4 = o4
        ab = abs(car.body_slip)
        if car.speed > 4.0:
            if ab > self.max_beta:
                self.max_beta = ab
            if ab > 0.7 and self.tick - self._spin_t > 120:
                self.spins += 1
                inc += 1
                self._spin_t = self.tick
        # stuck / wrong way -> put the car back on the centre line (counts as a reset)
        self._slow = self._slow + 1 if car.speed < 1.5 and self.tick > 300 else 0
        self._wrong = self._wrong + 1 if abs(wrap(car.heading - q.heading)) > 1.9 else 0
        if self._slow > 240 or self._wrong > 150:
            x, z, h, _ = TRACK.pose_at(q.s, 0.0)
            car.reset(x, z, h, 0.0)
            self.q = TRACK.query(x, z, q.index)
            self.resets += 1
            inc += 1
            self._slow = 0
            self._wrong = 0
            if hasattr(self.assist, "reset"):
                self.assist.reset()
        cur = (self.spins, self.off2, self.off4, self.walls, self.resets)
        if cur != self._prev_counts:
            if self.laps.lap >= 1:
                for k, a, b in zip(("spins", "off2", "off4", "walls", "resets"), cur, self._prev_counts):
                    self.fly[k] += a - b
            self._prev_counts = cur
        if inc:
            lap = self.laps.lap
            self.lap_incident[lap] = self.lap_incident.get(lap, 0) + inc


def run_laps(car_id, analog, mode, laps=3, levels=None, seed=1, setup=None, driver_kw=None,
             tweak=None, max_seconds=420.0, cs_car_rate=False):
    """mode: "full" (compensation + ABS/TCS), "steer" (compensation, assists off), "raw" (nothing).
    Lap 0 is the standing-start lap; timed flying laps follow.  Returns a result dict."""
    if mode == "raw":
        assist = PassThrough()
    else:
        assist = InputAssist(levels, preset="analog" if analog else "digital", assist_on=(mode == "full"))
        if tweak:
            for k, v in tweak.items():
                if not hasattr(assist, k):
                    raise AttributeError(k)
                setattr(assist, k, v)
    kw = dict(driver_kw or {})
    drv = Driver(car_id, analog, seed=seed, **kw)
    drv.assist_ref = assist
    w = World(car_id, assist, setup, cs_car_rate=cs_car_rate)
    n = int(max_seconds * 60)
    vmax = 0.0
    for _ in range(n):
        st, th, bk = drv.decide(w.car, w.q, w.tick)
        w.step(st, th, bk, analog, analog)
        if w.car.speed > vmax:
            vmax = w.car.speed
        if w.laps.lap >= laps + 1:
            break
    lt = w.laps.lap_times
    flying = lt[1:laps + 1]
    clean = [t for i, t in enumerate(lt) if 1 <= i <= laps and not w.lap_incident.get(i, 0)]
    return {"car": car_id, "input": "analog" if analog else "digital", "mode": mode,
            "laps_done": w.laps.lap, "lap0": round(lt[0], 2) if lt else None,
            "flying": [round(t, 2) for t in flying],
            "best": round(min(flying), 2) if flying else None,
            "mean": round(sum(flying) / len(flying), 2) if flying else None,
            "clean_laps": len(clean), "best_clean": round(min(clean), 2) if clean else None, "off2": w.off2, "off4": w.off4, "spins": w.spins,
            "walls": w.walls, "resets": w.resets, "fly": dict(w.fly), "max_out_m": round(w.max_out, 2),
            "max_beta_deg": round(math.degrees(w.max_beta), 1), "vmax_kmh": round(vmax * KMH, 1),
            "driver_est_lap": round(drv.est_lap, 2), "sim_seconds": round(w.tick * DT, 1)}
