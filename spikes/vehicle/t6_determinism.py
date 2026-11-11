"""Q6: determinism.  Same input sequence twice (and in a fresh process) -> identical state hashes."""
import hashlib, json, struct, subprocess, sys
from common import *

def run(seed=12345, ticks=60*120):
    """6 cars, pseudo-random inputs from an integer LCG (no float RNG), hash every state every tick."""
    cars = [make_car(c, {"gear": (i % 5) - 2, "traction": ((i*2) % 5) - 2, "suspension": ((i*3) % 5) - 2})
            for i, c in enumerate(("tsubame", "kazane", "shirogane", "arashi", "shirogane", "arashi"))]
    for i, car in enumerate(cars): car.reset(i*8.0, 0.0, 0.3*i, 5.0*i)
    h = hashlib.sha256(); s = seed
    steer = [0.0]*6; thr = [0.0]*6; brk = [0.0]*6; mu = [1.0]*6
    moved = 0.0; limit_ticks = 0
    for n in range(ticks):
        for i, car in enumerate(cars):
            if n % 20 == (i*3) % 20:           # change inputs 3 times a second
                s = (s*1103515245 + 12345) & 0x7fffffff; steer[i] = ((s >> 8) % 2001 - 1000)/1000.0*0.35
                s = (s*1103515245 + 12345) & 0x7fffffff; k = (s >> 8) % 100
                thr[i] = 1.0 if k < 55 else (0.5 if k < 70 else 0.0)
                brk[i] = 0.0 if k < 70 else (1.0 if k < 85 else 0.4)
                s = (s*1103515245 + 12345) & 0x7fffffff; mu[i] = (1.0, 1.0, 1.0, 0.9, 0.55, 0.4)[(s >> 8) % 6]
            car.step(steer[i], thr[i], brk[i], mu[i])
            h.update(struct.pack("<13d", *car.state_tuple()))
            moved += car.speed; limit_ticks += 1 if car.on_limit else 0
    return h.hexdigest(), moved/ticks/6, limit_ticks/(ticks*6)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        print(run()[0]); sys.exit(0)
    a = run(); b = run()
    child = subprocess.run([sys.executable, __file__, "child"], capture_output=True, text=True).stdout.strip()
    c = run(seed=12346)
    res = {"ticks_per_run": 60*120, "cars": 6, "hash_run1": a[0], "hash_run2": b[0], "hash_fresh_process": child,
           "identical_in_process": a[0] == b[0], "identical_across_process": a[0] == child,
           "different_seed_hash_differs": c[0] != a[0], "mean_speed_ms": a[1], "share_of_ticks_on_limit": a[2]}
    print(json.dumps(res, indent=1))
    json.dump(res, open("result_t6.json", "w"), indent=1)
