import json, random, sys, time
sys.path.insert(0, sys.argv[1])
from cp_core.rng import RngStream, hash_unit, hash_u64
def bench(fn, n=200_000):
    best = 1e9
    for _ in range(5):
        t = time.perf_counter()
        for i in range(n): fn(i)
        best = min(best, time.perf_counter() - t)
    return round(best / n * 1e9, 1)
s = RngStream(1); r = random.Random(1)
out = {"splitmix_unit_ns": bench(lambda i: s.unit()), "stdlib_random_ns": bench(lambda i: r.random()),
       "hash_unit_int_keys_ns": bench(lambda i: hash_unit(7, 3, i)), "hash_unit_str_key_ns": bench(lambda i: hash_unit(7, "brake", "kazane_rs", 3, i)),
       "lambda_overhead_ns": bench(lambda i: None), "python": sys.version.split()[0]}
json.dump(out, open(sys.argv[2], "w"), indent=1); print(out)
