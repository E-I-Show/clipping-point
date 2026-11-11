"""Run the shared pure-Python benchmarks natively and write results/<tag>.json.

usage: python tools/bench_native.py <tag> [speed|determinism|all]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apps", "_shared"))
import bench_core  # noqa: E402

tag = sys.argv[1]
what = sys.argv[2] if len(sys.argv) > 2 else "all"
out = {"python": sys.version, "platform": sys.platform}
if what in ("speed", "all"):
    out["speed"] = bench_core.run_speed_suite(1.0, 5)
if what in ("determinism", "all"):
    out["libm"] = bench_core.libm_probe()
    out["libm_first"] = bench_core.libm_first_diffs()
    out["determinism"] = bench_core.determinism_run()
    out["determinism_nolibm"] = bench_core.determinism_run_nolibm()
path = os.path.join(HERE, "..", "results", tag + ".json")
with open(path, "w") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out.get("speed", {}), indent=1))
print("determinism final:", out.get("determinism", {}).get("final_hash"), "nolibm:", out.get("determinism_nolibm", {}).get("final_hash"))
