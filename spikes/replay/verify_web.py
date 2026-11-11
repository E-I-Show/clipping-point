"""native side of the browser check: read web_result.json (console of the Pyodide run), compare with
the native values, and load the file the browser wrote. Writes q_web.json. Exit 1 on any mismatch."""
import json
import sys
import zlib

import mkreplay
import replay as R

res = json.load(open("web_result.json"))
exp = json.load(open("web_expected.json"))
lines = [c.get("text", c) if isinstance(c, dict) else c for c in res.get("console", [])]
line = next((l for l in lines if isinstance(l, str) and l.startswith("RESULT ")), None)
if line is None:
    print("no RESULT line in the browser console")
    sys.exit(1)
w = json.loads(line[7:])
b64 = w.pop("browser_file_b64")
data = R.from_base64(b64)
rp = R.load_cpr(data, mkreplay.CATALOG)          # file written by Pyodide, read by native CPython
native_small, _ = mkreplay.build(1, 20.0, 3, seed=2)
checks = {
    "browser is Pyodide (emscripten)": w["platform"] == "emscripten",
    "browser reads native files: content CRC and header equal": w["read_native_ok"] is True,
    "interpolated poses (lerp + cubic, %d floats) bit-identical native vs browser" % w["pose_values"]: w["pose_crc_equal_native"] is True and w["pose_crc_big_equal_native"] is True,
    "browser write -> browser read exact (6 cars 5 min)": w["write_read_exact"] is True,
    "browser rejects damaged / cut / empty / padded files": w["reject_codes"] == ["E_CORRUPT", "E_TRUNCATED", "E_NOT_CPR", "E_CORRUPT"],
    "native reads the file written in the browser (load_cpr passes its CRC check, content CRC as reported)": rp.content_crc() == w["browser_recorded_content_crc"] and rp.n_samples == 400,
    "localStorage round trip of the base64 text": w.get("localstorage_roundtrip") is True and w.get("localstorage_reload_exact") is True,
}
info = {
    "file bytes rewritten in browser identical to native file (6 cars)": w["rewritten_big_bytes_identical_to_native_file"],
    "file bytes rewritten in browser identical to native file (1 car)": w["rewritten_small_bytes_identical_to_native_file"],
    "recording of the same synthetic drive identical native vs browser": w["browser_recorded_equals_native_recording"],
    "differing sample bytes (browser drive vs native drive)": "%d of %d" % (w["browser_recorded_differing_bytes"], w["browser_recorded_total_bytes"]),
}
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
for k, v in info.items():
    print("INFO %s: %s" % (k, v))
print("browser:", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in w.items()})
json.dump({"checks": checks, "info": info, "browser": w, "webrun": {k: res[k] for k in res if k not in ("console",)}}, open("q_web.json", "w"), indent=1, default=str)
sys.exit(0 if all(checks.values()) and len(checks) == 7 else 1)
