"""Native (headless) run of the shared Pyxel Cube benchmark. usage: python tools/bench_cube_native.py <tag>"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apps", "_shared"))
import pyxel  # noqa: E402

pyxel.init(320, 240, headless=True)
import cube_bench  # noqa: E402

res = cube_bench.run_suite(120)
res["python"] = sys.version.split()[0]
json.dump(res, open(os.path.join(HERE, "..", "results", sys.argv[1] + ".json"), "w"), indent=1)
for r in res["rows"]:
    print(r)
print("distinct colors:", res["distinct_colors_on_screen"], "hud ms:", res["cls_plus_40_text_ms"])
