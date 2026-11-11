import json, sys, platform
from common import *
import bench_core
res = bench_core.run_all(300)
for r in res: print(r)
json.dump({"python": sys.version, "platform": platform.platform(), "results": res}, open("result_t2_native.json", "w"), indent=1)
