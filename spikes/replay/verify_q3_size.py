"""Q3: size / time / memory of delta + column + zlib. Writes q3_size.json."""
import json
import sys
import time
import tracemalloc
import zlib

import mkreplay
import replay as R
import synth


def best(f, n=3):
    b = 1e9
    r = None
    for _ in range(n):
        t = time.perf_counter()
        r = f()
        b = min(b, time.perf_counter() - t)
    return b, r


def peak(f):
    tracemalloc.start()
    tracemalloc.reset_peak()
    r = f()
    _, p = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return p, r


def main():
    quick = len(sys.argv) > 1
    out = {"zlib": zlib.ZLIB_RUNTIME_VERSION, "python": sys.version.split()[0], "sets": []}
    track = synth.Track()
    cases = [("1car_90s", 1, 90.0), ("6cars_5min", 6, 300.0), ("6cars_10min", 6, 600.0)]
    if quick:
        cases = cases[:2]
    for name, n_cars, seconds in cases:
        for label, rate in (("stress", 1.0), ("calm", 0.1)):
            sim = synth.simulate(n_cars, seconds, 7, track=track, events_rate=rate)
            for div in (3, 2):
                t0 = time.perf_counter()
                rp, _ = mkreplay.build(n_cars, 0, div, sim=sim)
                t_rec = time.perf_counter() - t0
                raw = bytes(rp.samples)
                row = {"case": name, "incidents": label, "n_inc": {k: len(v) for k, v in sim["marks"].items()},
                       "hz": 60 // div, "n_cars": n_cars, "seconds": seconds, "n_samples": rp.n_samples,
                       "raw_bytes": len(raw), "events": len(rp.events),
                       "record_us_per_tick_avg": t_rec / sim["n_ticks"] * 1e6, "codecs": {}}
                for codec in sorted(R.CODECS):
                    tr = R.transform_samples(raw, n_cars, codec)
                    z9 = len(zlib.compress(tr, 9))
                    z6 = len(zlib.compress(tr, 6))
                    z1 = len(zlib.compress(tr, 1))
                    row["codecs"][codec] = {"z9": z9, "z6": z6, "z1": z1, "ratio_z9": z9 / len(raw)}
                # default codec: full file, timing, memory
                t_tr, tr = best(lambda: R.transform_samples(raw, n_cars, R.DEFAULT_CODEC))
                t_z9, _ = best(lambda: zlib.compress(tr, 9))
                t_z6, _ = best(lambda: zlib.compress(tr, 6))
                t_dump, data = best(lambda: R.dump_cpr(rp))
                t_dump6, data6 = best(lambda: R.dump_cpr(rp, level=6))
                t_load, rp2 = best(lambda: R.load_cpr(data))
                t_peek, _ = best(lambda: R.peek_cpr(data))
                t_b64, b64 = best(lambda: R.to_base64(data))
                t_unb64, _ = best(lambda: R.from_base64(b64))
                assert bytes(rp2.samples) == raw and rp2.events == rp.events
                m_dump, _ = peak(lambda: R.dump_cpr(rp))
                m_load, _ = peak(lambda: R.load_cpr(data))
                ev_z = len(R.encode_events(rp.events))
                hdr = R.PREAMBLE.unpack_from(data, 0)[3]
                row.update(file_bytes=len(data), file_bytes_level6=len(data6), file_ratio=len(data) / len(raw),
                           header_bytes=hdr, events_chunk_bytes=ev_z, base64_chars=len(b64),
                           bytes_per_car_second=len(data) / n_cars / seconds,
                           t_transform_ms=t_tr * 1e3, t_zlib9_ms=t_z9 * 1e3, t_zlib6_ms=t_z6 * 1e3,
                           t_dump_ms=t_dump * 1e3, t_dump_level6_ms=t_dump6 * 1e3, t_load_ms=t_load * 1e3,
                           t_peek_ms=t_peek * 1e3, t_b64_ms=t_b64 * 1e3, t_unb64_ms=t_unb64 * 1e3,
                           peak_alloc_dump_bytes=m_dump, peak_alloc_load_bytes=m_load,
                           recorder_buf_bytes=len(rp.samples), recorder_buf_sizeof=sys.getsizeof(rp.samples))
                out["sets"].append(row)
                print("%-12s %-6s %2dHz raw %8d | " % (name, label, row["hz"], len(raw)) +
                      " ".join("c%d %.3f" % (c, v["ratio_z9"]) for c, v in row["codecs"].items()) +
                      " | file %7d (%.3f) b64 %7d | tr %.0f z9 %.0f z6 %.0f dump %.0f load %.0f ms | peak dump %.2f load %.2f MB" % (
                          len(data), row["file_ratio"], len(b64), t_tr * 1e3, t_z9 * 1e3, t_z6 * 1e3, t_dump * 1e3,
                          t_load * 1e3, m_dump / 1e6, m_load / 1e6))
    # cost of the recorder per tick (6 cars)
    sim = synth.simulate(6, 60.0, 3, track=track)
    q = mkreplay.quant_for(track)
    rec = R.Recorder(6, q, 3)
    frames = [[sim["ticks"][c][t][:15] for c in range(6)] for t in range(sim["n_ticks"])]
    ts, tn = [], []
    for t, f in enumerate(frames):
        a = time.perf_counter()
        rec.tick(f)
        b = time.perf_counter() - a
        (ts if t % 3 == 0 else tn).append(b)
    ts.sort()
    tn.sort()
    out["recorder_tick_us"] = {"sample_tick_median": ts[len(ts) // 2] * 1e6, "sample_tick_p99": ts[int(len(ts) * .99)] * 1e6,
                               "other_tick_median": tn[len(tn) // 2] * 1e6, "n_cars": 6}
    print("recorder.tick 6 cars:", out["recorder_tick_us"])
    json.dump(out, open("q3_size.json", "w"), indent=1)


if __name__ == "__main__":
    main()
