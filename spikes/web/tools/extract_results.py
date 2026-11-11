"""Pull 'RESULT_JSON <name> <json>' console lines out of a webrun.js result file.

usage: python tools/extract_results.py results/<run>.json  -> writes results/<run>.extracted.json and prints it
"""
import json
import sys

src = sys.argv[1]
run = json.load(open(src))
out = {}
for entry in run["console"]:
    text = entry["text"]
    if text.startswith("RESULT_JSON "):
        _, name, payload = text.split(" ", 2)
        out[name] = json.loads(payload)
dst = src[:-5] + ".extracted.json"
json.dump(out, open(dst, "w"), indent=1)
print(dst, "keys:", list(out))
if not out:
    sys.exit("no RESULT_JSON lines found")
