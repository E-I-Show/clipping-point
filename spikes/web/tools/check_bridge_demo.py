"""Assert the facts the bridge demo must have produced. usage: check_bridge_demo.py results/<run>.json downloads_dir"""
import hashlib
import json
import os
import sys

run = json.load(open(sys.argv[1]))
dl_dir = sys.argv[2]
res = {}
for c in run["console"]:
    if c["text"].startswith("RESULT_JSON "):
        _, name, payload = c["text"].split(" ", 2)
        res.setdefault(name, []).append(json.loads(payload))


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


checks = []


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))


check("run passed", run["passed"], str(run["failures"])[:300])
check("two visits", [v["visit"] for v in res.get("visit", [])] == [1, 2], str(res.get("visit")))
st = res.get("stored", [{}])[0]
check("12 replays stored, 3.0 MB, identical on read-back", st.get("count") == 12 and st.get("bytes") == 3_000_000 and st.get("roundtrip_ok"), str(st))
q = res.get("quota", [{}])[0]
check("quota overflow raises StorageFull and keeps data", q.get("storage_full_raised") and q.get("replays_still_ok"), str(q))
exp = res.get("export", [{}])[0]
dl = os.path.join(dl_dir, "demo_export.cpr")
check("export downloaded with identical bytes", os.path.exists(dl) and sha_file(dl) == exp.get("sha256"), dl)
pk = res.get("picked", [{}])[0]
check("file dialog delivers identical bytes", pk.get("sha256") == sha_file("fixtures/sample upload (1).cpr") and pk.get("name") == "sample upload (1).cpr", str(pk))
dr = res.get("dropped", [{}])[0]
check("drag and drop delivers identical bytes", dr.get("sha256") == sha_file("fixtures/drop me.cpr"), str(dr))
tr = res.get("triggers", [{}])[0]
check("analog trigger read through JS", abs(tr.get("right", 0) - 0.37) < 1e-9 and abs(tr.get("left", 1) - 0.0) < 1e-9, str(tr))
ps = res.get("persisted", [{}])[0]
check("all 12 replays identical after reload", ps.get("all_12_identical") is True, str(ps))
check("cleanup leaves no keys", res.get("cleanup", [{}])[0].get("keys_after_delete") == [], str(res.get("cleanup")))
bad = 0
for name, ok, detail in checks:
    print("%-55s %s %s" % (name, "OK  " if ok else "FAIL", "" if ok else detail))
    bad += not ok
print("used_chars after 12 x 250 kB:", st.get("used_chars"), "| extra 250 kB slots that still fit:", q.get("extra_250kB_slots_that_fit"), "| pyxel trigger value:", tr.get("pyxel_trigger_right"))
sys.exit(1 if bad else 0)
