"""Timing core shared by the native benchmark and the browser app (no pyxel import here)."""
import math, time
from vehicle import make_car

CAR_IDS = ("tsubame", "kazane", "shirogane", "arashi", "shirogane", "arashi")

def make_field(lite, substeps):
    cars = []
    for i, cid in enumerate(CAR_IDS):
        car = make_car(cid, lite=lite, substeps=substeps)
        car.reset(i*10.0, 0.0, 0.0, 25.0)
        cars.append(car)
    return cars

def one_second(cars, t0):
    """6 cars x 60 ticks of mixed driving (cornering near the limit, throttle, a braking phase)."""
    for k in range(60):
        n = t0 + k
        st = 0.09*math.sin(n*0.035)
        th = 0.9 if (n % 240) < 170 else 0.0
        br = 0.0 if (n % 240) < 170 else 0.7
        for car in cars:
            car.step(st, th, br)

def bench(lite, substeps, reps=300, warm=20):
    cars = make_field(lite, substeps)
    t = 0
    for _ in range(warm):
        one_second(cars, t); t += 60
    samples = []
    pc = time.perf_counter
    for _ in range(reps):
        a = pc(); one_second(cars, t); b = pc(); t += 60
        samples.append((b - a)*1000.0)
    samples.sort()
    med = samples[len(samples)//2]
    return {"lite": lite, "substeps": substeps, "reps": reps,
            "ms_per_game_second_6cars_median": round(med, 4), "ms_min": round(samples[0], 4),
            "ms_p95": round(samples[int(len(samples)*0.95)], 4),
            "us_per_car_tick_median": round(med*1000.0/360.0, 3),
            "ms_per_tick_6cars_median": round(med/60.0, 5),
            "pct_of_16_7ms_tick": round(med/60.0/16.6667*100.0, 3),
            "finite": all(math.isfinite(c.x + c.z + c.heading) for c in cars),
            "checksum": repr(sum(c.x + c.z + c.heading for c in cars))}

def run_all(reps=300):
    out = []
    for lite, n in ((False, 1), (False, 2), (False, 4), (True, 1), (True, 2)):
        out.append(bench(lite, n, reps))
    return out


def fingerprint(seed=12345, ticks=60 * 120):
    """Same run as t6_determinism.run(): 6 cars, integer-LCG inputs, sha256 over every state every tick."""
    import hashlib, struct
    cars = [make_car(c, {"gear": (i % 5) - 2, "traction": ((i * 2) % 5) - 2, "suspension": ((i * 3) % 5) - 2})
            for i, c in enumerate(("tsubame", "kazane", "shirogane", "arashi", "shirogane", "arashi"))]
    for i, car in enumerate(cars):
        car.reset(i * 8.0, 0.0, 0.3 * i, 5.0 * i)
    h = hashlib.sha256()
    s = seed
    steer = [0.0] * 6
    thr = [0.0] * 6
    brk = [0.0] * 6
    mu = [1.0] * 6
    first_diff_probe = []
    for n in range(ticks):
        for i, car in enumerate(cars):
            if n % 20 == (i * 3) % 20:
                s = (s * 1103515245 + 12345) & 0x7fffffff
                steer[i] = ((s >> 8) % 2001 - 1000) / 1000.0 * 0.35
                s = (s * 1103515245 + 12345) & 0x7fffffff
                k = (s >> 8) % 100
                thr[i] = 1.0 if k < 55 else (0.5 if k < 70 else 0.0)
                brk[i] = 0.0 if k < 70 else (1.0 if k < 85 else 0.4)
                s = (s * 1103515245 + 12345) & 0x7fffffff
                mu[i] = (1.0, 1.0, 1.0, 0.9, 0.55, 0.4)[(s >> 8) % 6]
            car.step(steer[i], thr[i], brk[i], mu[i])
            h.update(struct.pack("<13d", *car.state_tuple()))
        if n in (0, 9, 59, 599, 3599, 7199):
            # per-checkpoint digest + a readable sample, to see WHEN two environments diverge
            first_diff_probe.append([n + 1, hashlib.sha256(struct.pack("<78d", *[v for c in cars for v in c.state_tuple()])).hexdigest()[:16],
                                     repr(cars[2].x), repr(cars[2].heading)])
    return {"hash": h.hexdigest(), "checkpoints": first_diff_probe}


def timer_res_ms(samples=200):
    """Smallest non-zero step of time.perf_counter() seen (ms)."""
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
    return round(best * 1000.0, 6)
