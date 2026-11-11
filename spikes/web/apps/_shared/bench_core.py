"""Pure-Python benchmarks and determinism probes shared by native CPython and Pyodide.

No pyxel import. Every function returns plain data (dict / list / str).
"""

import hashlib
import math
import struct
import sys
import time

# ---------------------------------------------------------------- timing helpers


def timer_resolution(samples=2000):
    """Smallest non-zero step of time.perf_counter() observed (seconds)."""
    best = None
    last = time.perf_counter()
    n = 0
    while n < samples:
        now = time.perf_counter()
        if now != last:
            d = now - last
            if best is None or d < best:
                best = d
            last = now
            n += 1
    return best


def _repeat(fn, repeats):
    """Run fn() repeats times. Return list of seconds per run and last return value."""
    times = []
    value = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        value = fn()
        times.append(time.perf_counter() - t0)
    return times, value


# ---------------------------------------------------------------- micro benchmarks


def float_loop(n):
    """Float arithmetic and math functions in a tight loop. ~14 float ops + 4 libm calls per iteration."""
    sin = math.sin
    cos = math.cos
    atan2 = math.atan2
    sqrt = math.sqrt
    x = 0.1
    y = 0.2
    acc = 0.0
    for i in range(n):
        a = x * 1.0001 + y * 0.5
        b = (a - y) / (1.0 + x * x)
        s = sin(a)
        c = cos(b)
        r = sqrt(s * s + c * c + 1.0)
        t = atan2(s, c)
        x = (x + t * 0.001) % 6.283185307179586
        y = y * 0.999 + r * 0.001
        acc += a * b - t
    return acc


class Body:
    __slots__ = ("x", "y", "vx", "vy", "yaw", "yaw_rate", "steer", "throttle")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 10.0
        self.vy = 0.0
        self.yaw = 0.0
        self.yaw_rate = 0.0
        self.steer = 0.05
        self.throttle = 0.5


class BodyDict:
    """Same as Body but without __slots__ (instance dict)."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 10.0
        self.vy = 0.0
        self.yaw = 0.0
        self.yaw_rate = 0.0
        self.steer = 0.05
        self.throttle = 0.5


def attr_loop(n, cls=Body):
    """Attribute reads/writes on an object. ~16 attribute reads and 6 writes per iteration."""
    b = cls()
    dt = 1.0 / 60.0
    for i in range(n):
        b.vx += (b.throttle * 3.0 - b.vx * 0.01) * dt
        b.vy += (-b.vy * 2.0 + b.steer * b.vx * 0.5) * dt
        b.yaw_rate += (b.steer * b.vx * 0.3 - b.yaw_rate * 1.5) * dt
        b.yaw += b.yaw_rate * dt
        b.x += (b.vx - b.vy * b.yaw) * dt
        b.y += (b.vy + b.vx * b.yaw) * dt
    return b.x + b.y + b.yaw


def call_loop(n):
    """Function-call overhead: a small helper called 3 times per iteration."""

    def clamp(v, lo, hi):
        return lo if v < lo else hi if v > hi else v

    acc = 0.0
    for i in range(n):
        acc += clamp(i * 0.001 - 50.0, -1.0, 1.0)
        acc += clamp(acc, -10.0, 10.0) * 0.5
        acc = clamp(acc, -100.0, 100.0)
    return acc


# ---------------------------------------------------------------- representative vehicle tick

# A deliberately "realistic-sized" 3-DOF car with 4 wheels: per wheel slip angle (atan2),
# slip ratio, combined-slip friction circle (sqrt), load transfer, simple engine/turbo/aero.
# It is NOT the game's model. It exists to estimate the cost of one car-tick in pure Python.


class Wheel:
    __slots__ = ("px", "py", "omega", "load", "fx", "fy", "steered", "driven", "slip_ratio", "slip_angle")

    def __init__(self, px, py, steered, driven):
        self.px = px
        self.py = py
        self.omega = 30.0
        self.load = 3000.0
        self.fx = 0.0
        self.fy = 0.0
        self.steered = steered
        self.driven = driven
        self.slip_ratio = 0.0
        self.slip_angle = 0.0


class Car:
    __slots__ = (
        "x", "y", "yaw", "vx", "vy", "yaw_rate", "steer", "throttle", "brake",
        "mass", "inertia", "cg_h", "wheelbase", "track", "wheels", "rpm", "boost", "gear_ratio",
        "ax", "ay", "roll", "pitch",
    )  # fmt: skip

    def __init__(self, seed):
        self.x = seed * 3.0
        self.y = 0.0
        self.yaw = 0.01 * seed
        self.vx = 20.0 + seed
        self.vy = 0.0
        self.yaw_rate = 0.0
        self.steer = 0.0
        self.throttle = 0.6
        self.brake = 0.0
        self.mass = 1040.0 + 60.0 * seed
        self.inertia = 1500.0 + 80.0 * seed
        self.cg_h = 0.5
        self.wheelbase = 2.5
        self.track = 1.5
        a = 1.1
        b = 1.4
        t = 0.75
        self.wheels = [
            Wheel(a, t, True, False),
            Wheel(a, -t, True, False),
            Wheel(-b, t, False, True),
            Wheel(-b, -t, False, True),
        ]
        self.rpm = 3000.0
        self.boost = 0.0
        self.gear_ratio = 8.0
        self.ax = 0.0
        self.ay = 0.0
        self.roll = 0.0
        self.pitch = 0.0


def car_tick(car, dt, tick):
    sin = math.sin
    cos = math.cos
    atan2 = math.atan2
    sqrt = math.sqrt
    g = 9.81
    mass = car.mass
    vx = car.vx
    vy = car.vy
    yaw_rate = car.yaw_rate

    # scripted driver input (deterministic)
    phase = tick * dt
    car.steer = 0.12 * sin(phase * 0.9 + car.mass * 0.001) + 0.05 * sin(phase * 2.3)
    car.throttle = 0.55 + 0.45 * sin(phase * 0.37)
    if car.throttle < 0.0:
        car.brake = -car.throttle
        car.throttle = 0.0
    else:
        car.brake = 0.0

    # load transfer from last tick's accelerations
    w_static = mass * g * 0.25
    d_long = mass * car.ax * car.cg_h / car.wheelbase * 0.5
    d_lat = mass * car.ay * car.cg_h / car.track * 0.5

    # engine / turbo
    target_boost = car.throttle * (1.0 if car.rpm > 2500.0 else car.rpm / 2500.0)
    car.boost += (target_boost - car.boost) * (dt / 0.4)
    torque = (120.0 + 80.0 * car.boost) * car.throttle * (1.0 - ((car.rpm - 5200.0) / 5200.0) ** 2 * 0.35)
    drive_torque = torque * car.gear_ratio * 0.5

    fx_total = 0.0
    fy_total = 0.0
    mz_total = 0.0
    steer = car.steer
    cs = cos(steer)
    sn = sin(steer)
    omega_sum = 0.0
    for i, w in enumerate(car.wheels):
        load = w_static - (d_long if w.px > 0.0 else -d_long) + (d_lat if w.py > 0.0 else -d_lat)
        if load < 50.0:
            load = 50.0
        w.load = load
        # contact patch velocity in car frame
        wvx = vx - yaw_rate * w.py
        wvy = vy + yaw_rate * w.px
        if w.steered:
            lx = wvx * cs + wvy * sn
            ly = -wvx * sn + wvy * cs
        else:
            lx = wvx
            ly = wvy
        alx = lx if lx > 0.0 else -lx
        slip_angle = atan2(ly, alx + 0.5)
        wheel_speed = w.omega * 0.3
        slip_ratio = (wheel_speed - lx) / (alx + 1.0)
        w.slip_angle = slip_angle
        w.slip_ratio = slip_ratio
        # combined slip, friction circle with fall-off past the peak
        sa = slip_angle / 0.14
        sr = slip_ratio / 0.10
        k = sqrt(sa * sa + sr * sr)
        mu = 1.05 * (1.0 - 0.00004 * (load - 3000.0))
        if k < 1.0:
            f = k * (1.5 - 0.5 * k * k)
        else:
            f = 1.0 - 0.18 * (1.0 - 1.0 / (1.0 + (k - 1.0) * 2.0))
        fmag = mu * load * f
        if k > 1e-9:
            fxl = fmag * sr / k
            fyl = -fmag * sa / k
        else:
            fxl = 0.0
            fyl = 0.0
        # wheel spin dynamics
        tq = (drive_torque if w.driven else 0.0) - car.brake * 1500.0 * (1.0 if w.omega > 0.0 else -1.0)
        w.omega += (tq - fxl * 0.3) / 1.2 * dt
        if w.omega < 0.0:
            w.omega = 0.0
        omega_sum += w.omega
        if w.steered:
            fx = fxl * cs - fyl * sn
            fy = fxl * sn + fyl * cs
        else:
            fx = fxl
            fy = fyl
        w.fx = fx
        w.fy = fy
        fx_total += fx
        fy_total += fy
        mz_total += w.px * fy - w.py * fx

    # aero
    speed2 = vx * vx + vy * vy
    drag = 0.42 * speed2
    fx_total -= drag if vx > 0.0 else -drag

    ax = fx_total / mass
    ay = fy_total / mass
    car.ax = ax
    car.ay = ay
    car.vx = vx + (ax + vy * yaw_rate) * dt
    car.vy = vy + (ay - vx * yaw_rate) * dt
    car.yaw_rate = yaw_rate + mz_total / car.inertia * dt
    car.yaw += car.yaw_rate * dt
    cy = cos(car.yaw)
    sy = sin(car.yaw)
    car.x += (car.vx * cy - car.vy * sy) * dt
    car.y += (car.vx * sy + car.vy * cy) * dt
    car.rpm = omega_sum * 0.25 * car.gear_ratio * 9.549
    if car.rpm < 900.0:
        car.rpm = 900.0
    car.roll += (ay * 0.004 - car.roll) * dt * 8.0
    car.pitch += (-ax * 0.003 - car.pitch) * dt * 8.0


def vehicle_sim(ticks, cars=6, dt=1.0 / 60.0):
    fleet = [Car(i) for i in range(cars)]
    for t in range(ticks):
        for c in fleet:
            car_tick(c, dt, t)
    return fleet


def car_state(c):
    out = [c.x, c.y, c.yaw, c.vx, c.vy, c.yaw_rate, c.rpm, c.boost, c.roll, c.pitch]
    for w in c.wheels:
        out += [w.omega, w.load, w.fx, w.fy]
    return out


def state_hash(values):
    return hashlib.sha256(struct.pack("<%dd" % len(values), *values)).hexdigest()[:16]


# ---------------------------------------------------------------- determinism probes


def libm_probe(n=20000):
    """Hash of raw outputs of each math function over a fixed input sweep.

    A differing hash for a function means native libm and Emscripten libm round differently.
    """
    funcs1 = {
        "sqrt": (math.sqrt, lambda i: 0.001 + i * 0.37),
        "sin": (math.sin, lambda i: -50.0 + i * 0.005),
        "cos": (math.cos, lambda i: -50.0 + i * 0.005),
        "tan": (math.tan, lambda i: -1.5 + i * 0.00015),
        "atan": (math.atan, lambda i: -100.0 + i * 0.01),
        "asin": (math.asin, lambda i: -1.0 + i * 0.0001),
        "acos": (math.acos, lambda i: -1.0 + i * 0.0001),
        "exp": (math.exp, lambda i: -20.0 + i * 0.002),
        "log": (math.log, lambda i: 0.001 + i * 0.05),
        "tanh": (math.tanh, lambda i: -5.0 + i * 0.0005),
        "floor": (math.floor, lambda i: -100.0 + i * 0.01),
    }
    out = {}
    for name, (fn, gen) in funcs1.items():
        vals = [float(fn(gen(i))) for i in range(n)]
        out[name] = state_hash(vals)
    vals = [math.atan2(-3.0 + i * 0.0003, 1.0 + (i % 97) * 0.11 - 5.0) for i in range(n)]
    out["atan2"] = state_hash(vals)
    vals = [math.hypot(-3.0 + i * 0.0003, (i % 97) * 0.11) for i in range(n)]
    out["hypot"] = state_hash(vals)
    vals = [math.pow(0.5 + (i % 300) * 0.01, -2.0 + i * 0.0002) for i in range(n)]
    out["pow"] = state_hash(vals)
    vals = [(0.5 + (i % 300) * 0.01) ** 0.5 for i in range(n)]
    out["**0.5"] = state_hash(vals)
    vals = [math.fmod(-50.0 + i * 0.37, 6.283185307179586) for i in range(n)]
    out["fmod"] = state_hash(vals)
    vals = [(-50.0 + i * 0.37) % 6.283185307179586 for i in range(n)]
    out["%"] = state_hash(vals)
    vals = [math.radians(i * 0.1) + math.degrees(i * 0.001) for i in range(n)]
    out["radians/degrees"] = state_hash(vals)
    # pure IEEE arithmetic only
    x = 0.1
    vals = []
    for i in range(n):
        x = (x * 1.000001 + 0.3) / 1.0000003 - 0.29999
        vals.append(x)
    out["arith(+-*/)"] = state_hash(vals)
    return out


def libm_first_diffs(n=20000):
    """Raw bit patterns for the first few inputs of sin/cos/atan2, to compare by eye."""
    out = {}
    for name, fn in (("sin", math.sin), ("cos", math.cos)):
        out[name] = [struct.pack("<d", fn(-50.0 + i * 0.005)).hex() for i in range(8)]
    return out


def determinism_run(ticks=36000, cars=6, checkpoint=600):
    """Vehicle sim for `ticks` ticks. Returns hashes at checkpoints to locate first divergence."""
    fleet = [Car(i) for i in range(cars)]
    dt = 1.0 / 60.0
    hashes = []
    for t in range(ticks):
        for c in fleet:
            car_tick(c, dt, t)
        if (t + 1) % checkpoint == 0:
            vals = []
            for c in fleet:
                vals += car_state(c)
            hashes.append(state_hash(vals))
    vals = []
    for c in fleet:
        vals += car_state(c)
    return {
        "ticks": ticks,
        "cars": cars,
        "checkpoint": checkpoint,
        "final_hash": state_hash(vals),
        "final_car0": [repr(v) for v in car_state(fleet[0])[:6]],
        "checkpoints": hashes,
    }


def determinism_run_nolibm(ticks=36000):
    """Integration that uses only + - * / and sqrt (IEEE-754 exact operations)."""
    x = 0.3
    y = -0.2
    vx = 1.0
    vy = 0.5
    dt = 1.0 / 60.0
    for t in range(ticks):
        r = math.sqrt(x * x + y * y) + 0.05
        ax = -x / (r * r * r) - 0.01 * vx
        ay = -y / (r * r * r) - 0.01 * vy
        vx += ax * dt
        vy += ay * dt
        x += vx * dt
        y += vy * dt
    return {"final_hash": state_hash([x, y, vx, vy]), "final": [repr(x), repr(y), repr(vx), repr(vy)]}


# ---------------------------------------------------------------- suite


def run_speed_suite(scale=1.0, repeats=5):
    n_float = int(300000 * scale)
    n_attr = int(300000 * scale)
    n_call = int(300000 * scale)
    ticks = int(3600 * scale)  # 60 s of game time for 6 cars
    out = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "implementation": sys.implementation.name,
        "timer_resolution_us": timer_resolution() * 1e6,
        "repeats": repeats,
    }

    def record(name, fn, units, unit_name):
        times, _ = _repeat(fn, repeats)
        best = min(times)
        srt = sorted(times)
        med = srt[len(srt) // 2]
        out[name] = {
            "units": units,
            "unit": unit_name,
            "runs_ms": [round(t * 1000, 2) for t in times],
            "best_ns_per_unit": round(best / units * 1e9, 1),
            "median_ns_per_unit": round(med / units * 1e9, 1),
            "first_ns_per_unit": round(times[0] / units * 1e9, 1),
        }

    record("float_loop", lambda: float_loop(n_float), n_float, "iteration")
    record("attr_loop_slots", lambda: attr_loop(n_attr, Body), n_attr, "iteration")
    record("attr_loop_dict", lambda: attr_loop(n_attr, BodyDict), n_attr, "iteration")
    record("call_loop", lambda: call_loop(n_call), n_call, "iteration")
    record("vehicle_6cars", lambda: vehicle_sim(ticks, 6), ticks * 6, "car-tick")
    return out


def libm_dump(n=4000):
    """Raw IEEE-754 bit patterns (hex) of libm results, for an exact native-vs-web comparison."""
    out = {}
    out["sin"] = "".join(struct.pack("<d", math.sin(-50.0 + i * 0.025)).hex() for i in range(n))
    out["cos"] = "".join(struct.pack("<d", math.cos(-50.0 + i * 0.025)).hex() for i in range(n))
    out["tan"] = "".join(struct.pack("<d", math.tan(-1.5 + i * 0.00075)).hex() for i in range(n))
    out["atan2"] = "".join(struct.pack("<d", math.atan2(-3.0 + i * 0.0015, 1.0 + (i % 97) * 0.11 - 5.0)).hex() for i in range(n))
    out["exp"] = "".join(struct.pack("<d", math.exp(-20.0 + i * 0.01)).hex() for i in range(n))
    # the ranges a car model really uses: small angles
    out["sin_small"] = "".join(struct.pack("<d", math.sin(-0.7 + i * 0.00035)).hex() for i in range(n))
    out["cos_small"] = "".join(struct.pack("<d", math.cos(-0.7 + i * 0.00035)).hex() for i in range(n))
    out["atan2_small"] = "".join(struct.pack("<d", math.atan2(-2.0 + i * 0.001, 5.0 + (i % 50))).hex() for i in range(n))
    return out
