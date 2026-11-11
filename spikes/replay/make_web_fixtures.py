"""native side: write the files the browser app reads + the values it must reproduce."""
import json
import sys
import zlib

import mkreplay
import posehash
import replay as R

dst = sys.argv[1]
small_rp, _ = mkreplay.build(1, 20.0, 3, seed=2)
big_rp, _ = mkreplay.build(6, 300.0, 3, seed=3)
small = R.dump_cpr(small_rp)
big = R.dump_cpr(big_rp)
open(dst + "/golden_v1_0.cpr", "wb").write(small)
open(dst + "/big_native.cpr", "wb").write(big)
rs = R.load_cpr(small)
rb = R.load_cpr(big)
pc, pn = posehash.pose_crc(rs)
pcb, pnb = posehash.pose_crc(rb, step=997)
exp = {"small_content_crc": rs.content_crc(), "big_content_crc": rb.content_crc(), "small_header": rs.header,
       "small_pose_crc": pc, "small_pose_values": pn, "big_pose_crc": pcb, "big_pose_values": pnb,
       "small_file_crc32": zlib.crc32(small) & 0xFFFFFFFF, "big_file_crc32": zlib.crc32(big) & 0xFFFFFFFF,
       "small_len": len(small), "big_len": len(big)}
json.dump(exp, open(dst + "/expected.json", "w"))
json.dump(exp, open("web_expected.json", "w"), indent=1)
print("fixtures:", {k: v for k, v in exp.items() if k != "small_header"})
