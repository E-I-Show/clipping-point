"""Q5 / Q8: .cpr file format checks. Every check asserts; results go to q58.json."""
import json
import random
import struct
import sys
import time
import zlib

import mkreplay
import replay as R
import synth

checks = []
out = {}


def check(name, cond, detail=""):
    checks.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + str(detail)) if detail else ""))


def err_code(data, catalog=None):
    try:
        R.load_cpr(data, catalog)
    except R.ReplayError as e:
        return e.code
    except Exception as e:                       # anything else is a bug in the loader
        return "UNCAUGHT:" + type(e).__name__
    return "OK"


def reseal(data, major=None, minor=None, header=None, body=None):
    """rebuild a file with a valid CRC after tampering (what a newer / buggy writer would produce)."""
    _, mj, mn, hl, bl = R.PREAMBLE.unpack_from(data, 0)
    h = data[20:20 + hl] if header is None else (header if isinstance(header, bytes) else
                                                 json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    b = data[20 + hl:20 + hl + bl] if body is None else body
    d = R.PREAMBLE.pack(R.MAGIC, mj if major is None else major, mn if minor is None else minor, len(h), len(b)) + h + b
    return d + struct.pack("<I", zlib.crc32(d) & 0xFFFFFFFF)


def header_of(data):
    hl = R.PREAMBLE.unpack_from(data, 0)[3]
    return json.loads(data[20:20 + hl])


track = synth.Track()
small_rp, _ = mkreplay.build(1, 20.0, 3, seed=2, track=track)
big_rp, _ = mkreplay.build(6, 300.0, 3, seed=3, track=track)
small = R.dump_cpr(small_rp)
big = R.dump_cpr(big_rp)
out["small_file_bytes"] = len(small)
out["big_file_bytes"] = len(big)

# ---- 1. write -> read is exact, writer is deterministic
for name, rp, data in (("1 car 20 s", small_rp, small), ("6 cars 5 min", big_rp, big)):
    rp2 = R.load_cpr(data, mkreplay.CATALOG)
    exp_h = dict(rp.header, content_crc=rp.content_crc(), n_samples=rp.n_samples)
    check("round trip exact: %s (samples, events, header)" % name,
          bytes(rp2.samples) == bytes(rp.samples) and rp2.events == rp.events and rp2.header == exp_h
          and rp2.n_samples == rp.n_samples and len(rp2.samples) > 0,
          "%d samples x %d cars, %d events, %d bytes" % (rp2.n_samples, rp2.n_cars, len(rp2.events), len(data)))
    check("re-saving the loaded replay gives byte-identical file: %s" % name, R.dump_cpr(rp2) == data)
    b64 = R.to_base64(data)
    check("base64 round trip: %s" % name, R.from_base64(b64) == data and len(b64) == 4 * ((len(data) + 2) // 3),
          "%d chars for %d bytes (x%.3f)" % (len(b64), len(data), len(b64) / len(data)))

# ---- 2. every single-byte corruption of the small file is rejected
codes = {}
accepted = []
t0 = time.perf_counter()
for i in range(len(small)):
    for mask in (0x01, 0x80, 0xFF):
        d = bytearray(small)
        d[i] ^= mask
        c = err_code(bytes(d))
        codes[c] = codes.get(c, 0) + 1
        if c == "OK" or c.startswith("UNCAUGHT"):
            accepted.append((i, mask, c))
n_trials = len(small) * 3
check("1 byte corrupted anywhere -> rejected (all %d positions x 3 masks of the small file)" % len(small),
      not accepted and sum(codes.values()) == n_trials and n_trials > 3000, codes)
out["corrupt_small"] = {"trials": n_trials, "codes": codes, "ms_per_load": (time.perf_counter() - t0) / n_trials * 1e3}
rng = random.Random(9)
codes_b = {}
acc_b = 0
for _ in range(1500):
    i = rng.randrange(len(big))
    d = bytearray(big)
    d[i] ^= 1 << rng.randrange(8)
    c = err_code(bytes(d))
    codes_b[c] = codes_b.get(c, 0) + 1
    acc_b += c == "OK" or c.startswith("UNCAUGHT")
check("1 bit flipped at 1500 random positions of the 6-car file -> rejected", acc_b == 0, codes_b)
out["corrupt_big"] = codes_b
# two bytes swapped (same CRC is impossible for a single transposition, but check anyway)
sw = 0
for _ in range(500):
    i = rng.randrange(len(small) - 1)
    if small[i] != small[i + 1]:
        d = bytearray(small)
        d[i], d[i + 1] = d[i + 1], d[i]
        sw += err_code(bytes(d)) in ("OK",)
check("adjacent bytes swapped (500 tries) -> rejected", sw == 0)

# ---- 3. truncation at every length is rejected, and reported as truncated
codes_t = {}
for n in range(len(small)):
    c = err_code(small[:n])
    codes_t[c] = codes_t.get(c, 0) + 1
check("cut at every length 0..%d -> rejected; E_TRUNCATED except the empty file" % (len(small) - 1),
      codes_t.get("E_TRUNCATED", 0) == len(small) - 1 and codes_t.get("E_NOT_CPR", 0) == 1 and len(codes_t) == 2, codes_t)
out["truncate_small"] = codes_t
codes_tb = {}
for _ in range(300):
    c = err_code(big[:rng.randrange(1, len(big))])
    codes_tb[c] = codes_tb.get(c, 0) + 1
check("6-car file cut at 300 random lengths -> E_TRUNCATED", codes_tb == {"E_TRUNCATED": 300}, codes_tb)
check("extra bytes after the checksum -> E_CORRUPT", err_code(small + b"\x00") == "E_CORRUPT")

# ---- 4. not a replay / damaged signature
check("empty, text, PNG, zip -> E_NOT_CPR",
      [err_code(b""), err_code(b"hello world, not a replay"), err_code(b"\x89PNG\r\n\x1a\n" + b"\0" * 64),
       err_code(b"PK\x03\x04" + b"\0" * 64)] == ["E_NOT_CPR"] * 4)
check("CRLF -> LF text-mode damage -> E_CORRUPT (signature damaged)", err_code(small.replace(b"\r\n", b"\n")) == "E_CORRUPT")

# ---- 5. versions
check("major version newer than this build -> E_TOO_NEW (checked before length and CRC)",
      err_code(reseal(small, major=R.VER_MAJOR + 1)) == "E_TOO_NEW"
      and err_code(reseal(small, major=R.VER_MAJOR + 1)[:40]) == "E_TOO_NEW")
h = header_of(small)
h2 = dict(h, future_key={"anything": [1, 2, 3]})
hl, bl = R.PREAMBLE.unpack_from(small, 0)[3:5]
body = small[20 + hl:20 + hl + bl]
newer = reseal(small, minor=R.VER_MINOR + 3, header=h2, body=body + b"XTRA" + struct.pack("<I", 5) + b"hello")
rpn = None
try:
    rpn = R.load_cpr(newer, mkreplay.CATALOG)
except R.ReplayError as e:
    print("   ", e.code, e)
check("same major, newer minor with an unknown header key and an unknown chunk -> loads, extras ignored",
      rpn is not None and bytes(rpn.samples) == bytes(small_rp.samples) and rpn.version == (1, R.VER_MINOR + 3)
      and rpn.header["future_key"] == {"anything": [1, 2, 3]})
# unknown sample codec id
p = body.index(b"SMPL")
b2 = bytearray(body)
b2[p + 8] = 99
check("unknown sample codec id -> E_TOO_NEW", err_code(reseal(small, body=bytes(b2))) == "E_TOO_NEW")
# older major goes through the upgrade chain (simulated: pretend this build is major 2)
calls = []


def up1(header, chunks):
    calls.append(1)
    header = dict(header, added_in_v2=1)
    return header, chunks


R._UPGRADERS[1] = up1
R.VER_MAJOR = 2
try:
    rpo = R.load_cpr(small, mkreplay.CATALOG)
    ok = calls == [1] and rpo.header["added_in_v2"] == 1 and rpo.version == (1, 0) and bytes(rpo.samples) == bytes(small_rp.samples)
except Exception as e:
    ok = False
    print("   ", type(e).__name__, e)
finally:
    R.VER_MAJOR = 1
    del R._UPGRADERS[1]
check("a major-1 file read by a (simulated) major-2 build goes through the upgrade function", ok)

# ---- 6. header validation (CRC is valid, content is wrong)
def bad_header(mut):
    hh = json.loads(json.dumps(h))
    mut(hh)
    return err_code(reseal(small, header=hh), mkreplay.CATALOG)


cases = {
    "missing course": lambda x: x.pop("course"),
    "n_cars 0": lambda x: x.update(n_cars=0),
    "n_cars 2 but 1 car listed": lambda x: x.update(n_cars=2),
    "sample_div 0": lambda x: x.update(sample_div=0),
    "tick_hz 50": lambda x: x.update(tick_hz=50),
    "float in header": lambda x: x.update(laps=5.5),
    "quant step 0": lambda x: x["quant"].update(step_um=[0, 1, 1]),
    "quant origin not 3 ints": lambda x: x["quant"].update(origin_mm=[1, 2]),
    "title not ASCII": lambda x: x.update(title="テスト"),
    "title too long": lambda x: x.update(title="A" * 33),
    "cars[0] without setup": lambda x: x["cars"][0].pop("setup"),
    "n_samples huge": lambda x: x.update(n_samples=10 ** 9),
    "n_samples is a string": lambda x: x.update(n_samples="400"),
}
res = {k: bad_header(m) for k, m in cases.items()}
check("13 kinds of invalid header -> E_BAD_HEADER", all(v == "E_BAD_HEADER" for v in res.values()), res)
check("header that is not JSON -> E_BAD_HEADER", err_code(reseal(small, header=b"{not json")) == "E_BAD_HEADER")
check("n_samples not matching the body -> E_CORRUPT", bad_header(lambda x: x.update(n_samples=x["n_samples"] + 1)) == "E_CORRUPT")
check("body without sample chunk -> E_CORRUPT", err_code(reseal(small, body=b"")) == "E_CORRUPT")
bomb = b"SMPL" + struct.pack("<I", 0)
zb = bytes([1]) + zlib.compress(b"\0" * (50 * 1024 * 1024), 9)
t0 = time.perf_counter()
cb = err_code(reseal(small, body=b"SMPL" + struct.pack("<I", len(zb)) + zb))
tb = time.perf_counter() - t0
check("sample chunk inflating to 50 MB instead of %d bytes -> E_CORRUPT without inflating it all" % len(small_rp.samples),
      cb == "E_CORRUPT" and tb < 0.05, "%.1f ms" % (tb * 1e3))

# ---- 7. unknown content
def content(mut):
    hh = json.loads(json.dumps(h))
    mut(hh)
    d = reseal(small, header=hh)
    try:
        R.load_cpr(d, mkreplay.CATALOG)
        return "OK", [c[1] for c in R.check_content(R.peek_cpr(d)[1], mkreplay.CATALOG)]
    except R.ReplayError as e:
        return e.code, [c[1] for c in R.check_content(R.peek_cpr(d)[1], mkreplay.CATALOG)]


r7 = {
    "unknown course": content(lambda x: x["course"].update(id="kasumi_hills")),
    "unknown layout": content(lambda x: x["course"].update(layout="reverse")),
    "course data newer": content(lambda x: x["course"].update(data_ver=2)),
    "unknown car": content(lambda x: x["cars"][0].update(car="mikazuki_mr")),
    "unknown mode": content(lambda x: x.update(mode="drift_trial")),
}
check("unknown course / layout / newer course data / unknown car / unknown mode -> E_UNKNOWN_CONTENT with a specific code",
      r7 == {"unknown course": ("E_UNKNOWN_CONTENT", ["E_UNKNOWN_COURSE"]),
             "unknown layout": ("E_UNKNOWN_CONTENT", ["E_UNKNOWN_LAYOUT"]),
             "course data newer": ("E_UNKNOWN_CONTENT", ["E_COURSE_TOO_NEW"]),
             "unknown car": ("E_UNKNOWN_CONTENT", ["E_UNKNOWN_CAR"]),
             "unknown mode": ("E_UNKNOWN_CONTENT", ["E_UNKNOWN_MODE"])}, r7)
cat2 = {"courses": {"akane_short": {"layouts": ["normal"], "data_ver": 3}}, "cars": mkreplay.CATALOG["cars"]}
warn = R.check_content(R.peek_cpr(small)[1], cat2)
check("course data older than the build -> plays, with warning W_COURSE_OLDER",
      err_code(small, cat2) == "OK" and warn == [("warn", "W_COURSE_OLDER", "akane_short v1 < v3")], warn)
check("without a catalog the file still loads (theatre list can show it greyed out)", err_code(reseal(small, header=dict(h, mode="drift_trial"))) == "OK")
try:
    R.from_base64("@@@not base64@@@")
    b64_ok = False
except R.CorruptError:
    b64_ok = True
check("invalid base64 text -> E_CORRUPT", b64_ok)

# ---- 7b. does the corruption test have teeth? Re-seal the file-level CRC after the damage (= a file
# format without the trailing CRC32) and count what the remaining checks let through.
passed = 0
silently_changed = 0
ref_header = R.load_cpr(small).header
for i in range(len(small) - 4):
    d = bytearray(small[:-4])
    d[i] ^= 0x01
    d += struct.pack("<I", zlib.crc32(bytes(d)) & 0xFFFFFFFF)
    try:
        r_ = R.load_cpr(bytes(d))
        passed += 1
        if bytes(r_.samples) != bytes(small_rp.samples) or r_.header != ref_header:
            silently_changed += 1
    except R.ReplayError:
        pass
check("mutation check: without the file CRC32, single-bit damage gets through with changed content (so the CRC is what catches it)",
      passed > 50 and silently_changed > 50, "%d of %d damaged files accepted, %d with changed content" % (passed, len(small) - 4, silently_changed))
out["without_crc"] = {"accepted": passed, "changed_content": silently_changed, "trials": len(small) - 4}

# ---- 8. peek (list screen) and golden file
t0 = time.perf_counter()
for _ in range(200):
    ver, hh = R.peek_cpr(big)
t_peek = (time.perf_counter() - t0) / 200
check("peek_cpr returns version + validated header without inflating", ver == (1, 0) and hh["n_cars"] == 6, "%.3f ms for a %d byte file" % (t_peek * 1e3, len(big)))
out["peek_ms_big"] = t_peek * 1e3
out["header_json_small"] = json.loads(json.dumps(h))
out["header_bytes_small"] = R.PREAMBLE.unpack_from(small, 0)[3]
out["header_bytes_big"] = R.PREAMBLE.unpack_from(big, 0)[3]
open("golden_v1_0.cpr", "wb").write(small)
out["golden"] = {"file": "golden_v1_0.cpr", "bytes": len(small), "file_crc32": zlib.crc32(small) & 0xFFFFFFFF,
                 "content_crc": small_rp.content_crc(), "n_samples": small_rp.n_samples}
out["checks"] = [{"name": n, "ok": ok, "detail": str(d)} for n, ok, d in checks]
json.dump(out, open("q58.json", "w"), indent=1)
bad = [c for c in checks if not c[1]]
print("%d checks, %d failed" % (len(checks), len(bad)))
sys.exit(1 if bad or len(checks) < 25 else 0)
