"""Browser (Pyodide) check of the replay library: read native files, write in the browser,
compare CRCs with the native run. Prints one JSON line starting with RESULT and then SPIKE_DONE."""
import json
import sys
import time
import zlib
from pathlib import Path

import pyxel

import mkreplay
import posehash
import replay as R
import synth

HERE = Path(__file__).parent
state = {"done": False, "frame": 0}


def best(f, n=3):
    b = 1e9
    r = None
    for _ in range(n):
        t = time.perf_counter()
        r = f()
        b = min(b, time.perf_counter() - t)
    return b * 1e3, r


def work():
    res = {"python": sys.version.split()[0], "platform": sys.platform, "byteorder": sys.byteorder,
           "zlib": zlib.ZLIB_RUNTIME_VERSION}
    exp = json.loads((HERE / "expected.json").read_text())
    # 1. files written by native CPython
    small = (HERE / "golden_v1_0.cpr").read_bytes()
    big = (HERE / "big_native.cpr").read_bytes()
    rs = R.load_cpr(small, mkreplay.CATALOG)
    t_load, rb = best(lambda: R.load_cpr(big, mkreplay.CATALOG))
    res["read_native_small_content_crc"] = rs.content_crc()
    res["read_native_big_content_crc"] = rb.content_crc()
    res["read_native_ok"] = (rs.content_crc() == exp["small_content_crc"] and rb.content_crc() == exp["big_content_crc"]
                             and rs.header == exp["small_header"])
    # 2. playback floats (interpolated poses) of the same file
    crc, n = posehash.pose_crc(rs)
    res["pose_crc_small"] = crc
    res["pose_values"] = n
    res["pose_crc_equal_native"] = crc == exp["small_pose_crc"] and n == exp["small_pose_values"]
    crc_b, n_b = posehash.pose_crc(rb, step=997)
    res["pose_crc_big_equal_native"] = crc_b == exp["big_pose_crc"] and n_b == exp["big_pose_values"]
    # 3. write in the browser, read back in the browser
    t_dump, big2 = best(lambda: R.dump_cpr(rb))
    rb2 = R.load_cpr(big2, mkreplay.CATALOG)
    res["write_read_exact"] = bytes(rb2.samples) == bytes(rb.samples) and rb2.events == rb.events and rb2.header == rb.header
    res["rewritten_big_bytes_identical_to_native_file"] = big2 == big
    res["rewritten_big_len"] = len(big2)
    small2 = R.dump_cpr(rs)
    res["rewritten_small_bytes_identical_to_native_file"] = small2 == small
    # 4. damaged / cut files are rejected here too
    d = bytearray(small)
    d[len(d) // 2] ^= 0x10
    codes = []
    for blob in (bytes(d), small[:len(small) // 2], b"", small + b"x"):
        try:
            R.load_cpr(blob)
            codes.append("OK")
        except R.ReplayError as e:
            codes.append(e.code)
    res["reject_codes"] = codes
    # 5. a replay recorded in the browser from the synthetic drive (floats computed here)
    rp_w, _ = mkreplay.build(1, 20.0, 3, seed=2)
    res["browser_recorded_content_crc"] = rp_w.content_crc()
    res["browser_recorded_equals_native_recording"] = rp_w.content_crc() == exp["small_content_crc"]
    nd = sum(1 for a, b in zip(bytes(rp_w.samples), bytes(rs.samples)) if a != b)
    res["browser_recorded_differing_bytes"] = nd
    res["browser_recorded_total_bytes"] = len(rp_w.samples)
    data_w = R.dump_cpr(rp_w)
    res["browser_file_b64"] = R.to_base64(data_w)
    res["browser_file_crc32"] = zlib.crc32(data_w) & 0xFFFFFFFF
    # 6. timings in the browser
    res["t_load_big_ms"] = t_load
    res["t_dump_big_ms"] = t_dump
    res["t_dump_big_level6_ms"] = best(lambda: R.dump_cpr(rb, level=6))[0]
    res["t_peek_big_ms"] = best(lambda: R.peek_cpr(big))[0]
    b64 = R.to_base64(big2)
    res["t_b64_big_ms"] = best(lambda: R.to_base64(big2))[0]
    res["t_unb64_big_ms"] = best(lambda: R.from_base64(b64))[0]
    sim = synth.simulate(6, 20.0, 3)
    rec = R.Recorder(6, mkreplay.quant_for(sim["track"]), 3)
    frames = [[sim["ticks"][c][t][:15] for c in range(6)] for t in range(sim["n_ticks"])]
    a = time.perf_counter()
    for f in frames:
        rec.tick(f)
    res["recorder_tick_us_avg_6cars"] = (time.perf_counter() - a) / len(frames) * 1e6
    rec1 = R.Recorder(6, mkreplay.quant_for(sim["track"]), 1)       # every tick is a sample tick
    a = time.perf_counter()
    for f in frames:
        rec1.tick(f)
    res["recorder_sample_tick_us_6cars"] = (time.perf_counter() - a) / len(frames) * 1e6
    pl = R.Player(rb)
    for interp in ("lerp", "hermite"):
        pl.seek_q(0)
        a = time.perf_counter()
        k = 0
        while k < 3000 and not pl.advance(8):
            for c in range(6):
                pl.pose(c, interp)
            k += 1
        res["pose_6cars_us_" + interp] = (time.perf_counter() - a) / k * 1e6
    # 7. localStorage (browser only)
    try:
        import js
        ls = js.localStorage
        ls.setItem("cpr_test", b64)
        back = ls.getItem("cpr_test")
        res["localstorage_roundtrip"] = bool(back == b64)
        res["localstorage_len"] = len(b64)
        rb3 = R.load_cpr(R.from_base64(str(back)), mkreplay.CATALOG)
        res["localstorage_reload_exact"] = bytes(rb3.samples) == bytes(rb.samples)
        ls.removeItem("cpr_test")
        chunk = "A" * 500000
        n_ok = 0
        err = ""
        for i in range(40):
            try:
                ls.setItem("cpr_quota_%d" % i, chunk)
                n_ok += 1
            except Exception as e:
                err = type(e).__name__ + ": " + str(e)[:120]
                break
        for i in range(n_ok):
            ls.removeItem("cpr_quota_%d" % i)
        res["localstorage_quota_chars_at_least"] = n_ok * 500000
        res["localstorage_quota_error"] = err
        res["location"] = str(js.location.protocol)
    except Exception as e:
        res["localstorage_error"] = type(e).__name__ + ": " + str(e)[:200]
    return res


def update():
    state["frame"] += 1
    if state["frame"] == 2 and not state["done"]:
        state["done"] = True
        res = work()
        print("RESULT " + json.dumps(res))
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(8, 8, "CPR REPLAY SPIKE", 7)
    pyxel.text(8, 20, "DONE" if state["done"] else "WORKING", 10)


pyxel.init(160, 120, title="cpr spike", fps=30)
pyxel.run(update, draw)
