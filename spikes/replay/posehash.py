"""posehash.py -- CRC of interpolated poses, to compare playback results between platforms."""
import struct
import zlib

import replay as R


def pose_crc(rp, interps=("lerp", "hermite"), step=7):
    pl = R.Player(rp)
    vals = []
    for interp in interps:
        pos = 0
        while pos <= pl.end:
            pl.seek_q(pos)
            for car in range(rp.n_cars):
                vals.extend(pl.pose(car, interp))
            pos += step
    return zlib.crc32(struct.pack("<%dd" % len(vals), *vals)) & 0xFFFFFFFF, len(vals)
