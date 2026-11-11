"""Summarise results/web_imports.json: per module ok / ms / number of server probes the runtime made."""
import json
import sys

src = sys.argv[1]
run = json.load(open(src))
cur = None
fetches = {}
for c in run["console"]:
    t = c["text"]
    if t.startswith("IMPORT_BEGIN "):
        cur = t.split(" ", 1)[1]
        fetches[cur] = []
    elif t.startswith("IMPORT_END "):
        cur = None
    elif t.startswith("Attempting to fetch") and cur:
        fetches[cur].append(t.split("'")[1])
    elif t.startswith("INFO"):
        print(t[:300])
ext = json.load(open(src[:-5] + ".extracted.json"))
print("%-18s %-5s %7s  %s" % ("module", "ok", "ms", "server probes / error"))
for r in ext["imports"]:
    f = fetches.get(r["module"], [])
    print("%-18s %-5s %7.1f  %s %s" % (r["module"], r["ok"], r["ms"], ("probes=%d %s" % (len(f), f[:6])) if f else "", r["error"] or ""))
print("late_missing_module probes:", fetches.get("late_missing_module"))
print("zlib:", ext.get("zlib"))
total = sum(len(v) for v in fetches.values())
print("total server probes:", total)
json.dump({"imports": ext["imports"], "server_probes": fetches, "zlib": ext.get("zlib")}, open(src[:-5] + ".summary.json", "w"), indent=1)
