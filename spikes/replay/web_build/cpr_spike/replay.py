"""replay.py -- CLIPPING POINT replay: record / codec / .cpr file / playback (spike).

Pure Python. Imports only struct, zlib, base64, json, bisect, itertools, operator, math.floor.
No pyxel. Stored data is integers only (quantized), so libm last-bit differences between
native CPython and Pyodide never reach the file.

Sample record (14 bytes, little endian, struct "<HHHHbbbBBB"), one per car per sample:
  off size field  meaning
  0   2    x      u16  (x - origin_x) / step_x
  2   2    y      u16  height
  4   2    z      u16
  6   2    yaw    u16  yaw / (2*pi) * 65536 (wraps)
  8   1    pitch  i8   pitch / pitch_step
  9   1    roll   i8   roll / roll_step
  10  1    steer  i8   front wheel angle / steer_step
  11  1    rpm    u8   rpm / rpm_step
  12  1    gf     u8   bit0-2 gear code (0=R 1=N 2..7=1st..6th), bit3 brake lamp,
                       bit4-5 surface (0 asphalt 1 curb 2 grass 3 gravel),
                       bit6 contact latched since previous sample,
                       bit7 cut (do not interpolate from previous sample into this one)
  13  1    aux    u8   bit0-3 tyre slip level 0..15 (squeal / smoke), bit4-7 throttle 0..15
"""
import base64
import bisect
import json
import struct
import zlib
from itertools import accumulate
from math import floor, sqrt
from operator import sub

MAGIC = b"\x89CPR\r\n\x1a\n"
VER_MAJOR = 1
VER_MINOR = 0
PREAMBLE = struct.Struct("<8sHHII")  # magic, major, minor, header_len, body_len  (20 bytes)
REC_FMT = "HHHHbbbBBB"
REC = struct.Struct("<" + REC_FMT)
REC_SIZE = REC.size  # 14
NF = 10  # fields per record
# (name, byte offset, byte size)
FIELDS = (("x", 0, 2), ("y", 2, 2), ("z", 4, 2), ("yaw", 6, 2), ("pitch", 8, 1), ("roll", 9, 1),
          ("steer", 10, 1), ("rpm", 11, 1), ("gf", 12, 1), ("aux", 13, 1))
EV = struct.Struct("<IBBHI")  # tick, type, car, a, b   (12 bytes)
EV_START, EV_LAP, EV_SECTOR, EV_POS, EV_CONTACT, EV_OFFTRACK, EV_FINISH = 1, 2, 3, 4, 5, 6, 7
TICK_HZ = 60
Q_PER_TICK = 4            # playback position unit = 1/240 s
TWO_PI = 6.283185307179586
YAW_K = 65536.0 / TWO_PI
MAX_CARS = 16
MAX_RAW_BYTES = 32 * 1024 * 1024
MODES = ("race", "time_attack", "ghost")

# codec id -> per field transform. "d1"/"d2" = 1st/2nd order time delta + zigzag, "x" = xor with
# previous, "r" = raw.  16 bit fields are split into a low byte plane and a high byte plane.
CODECS = {
    0: None,  # interleaved records, zlib only
    1: {"x": "d2", "y": "d2", "z": "d2", "yaw": "d2", "pitch": "d1", "roll": "d1",
        "steer": "d1", "rpm": "d1", "gf": "x", "aux": "r"},
    2: {"x": "d1", "y": "d1", "z": "d1", "yaw": "d1", "pitch": "d1", "roll": "d1",
        "steer": "d1", "rpm": "d1", "gf": "x", "aux": "r"},
    3: {"x": "d2", "y": "d2", "z": "d2", "yaw": "d2", "pitch": "d1", "roll": "d1",
        "steer": "d1", "rpm": "d1", "gf": "r", "aux": "r"},
    4: {"x": "d2", "y": "d1", "z": "d2", "yaw": "d1", "pitch": "d1", "roll": "d1",
        "steer": "d1", "rpm": "d1", "gf": "x", "aux": "r"},
    5: {"x": "d2", "y": "d2", "z": "d2", "yaw": "d2", "pitch": "r", "roll": "r",
        "steer": "r", "rpm": "r", "gf": "r", "aux": "r"},
}
DEFAULT_CODEC = 1


# ----------------------------------------------------------------------------- errors
class ReplayError(Exception):
    code = "E_REPLAY"


class NotCprError(ReplayError):
    code = "E_NOT_CPR"          # not a .cpr file at all


class TruncatedError(ReplayError):
    code = "E_TRUNCATED"        # shorter than its own declared length


class TooNewError(ReplayError):
    code = "E_TOO_NEW"          # written by a newer major format / unknown codec


class CorruptError(ReplayError):
    code = "E_CORRUPT"          # checksum mismatch or inconsistent body


class InvalidHeaderError(ReplayError):
    code = "E_BAD_HEADER"       # checksum fine but header fields missing / out of range


class UnknownContentError(ReplayError):
    code = "E_UNKNOWN_CONTENT"  # course / car / mode not known to this build


# ----------------------------------------------------------------------------- quantization
class Quant:
    """Quantization ranges. All parameters are integers so the header holds no floats."""
    __slots__ = ("origin_mm", "step_um", "pitch_step_urad", "roll_step_urad", "steer_step_urad",
                 "rpm_step", "_o", "_s", "_ps", "_rs", "_ss")

    def __init__(self, origin_mm, step_um, pitch_step_urad=2500, roll_step_urad=2500,
                 steer_step_urad=5000, rpm_step=40):
        self.origin_mm = [int(v) for v in origin_mm]
        self.step_um = [int(v) for v in step_um]
        self.pitch_step_urad = int(pitch_step_urad)
        self.roll_step_urad = int(roll_step_urad)
        self.steer_step_urad = int(steer_step_urad)
        self.rpm_step = int(rpm_step)
        self._o = [v / 1000.0 for v in self.origin_mm]
        self._s = [v / 1e6 for v in self.step_um]
        self._ps = self.pitch_step_urad / 1e6
        self._rs = self.roll_step_urad / 1e6
        self._ss = self.steer_step_urad / 1e6

    @classmethod
    def for_bbox(cls, mins, maxs, margin=(25.0, 5.0, 25.0), **kw):
        origin_mm = [int(floor((mins[i] - margin[i]) * 1000.0)) for i in range(3)]
        step_um = []
        for i in range(3):
            span_um = int((maxs[i] + margin[i]) * 1e6) - origin_mm[i] * 1000
            step_um.append(max(1, -(-span_um // 65535)))  # ceil
        return cls(origin_mm, step_um, **kw)

    def to_json(self):
        return {"origin_mm": self.origin_mm, "step_um": self.step_um,
                "pitch_step_urad": self.pitch_step_urad, "roll_step_urad": self.roll_step_urad,
                "steer_step_urad": self.steer_step_urad, "rpm_step": self.rpm_step}

    @classmethod
    def from_json(cls, d):
        return cls(d["origin_mm"], d["step_um"], d["pitch_step_urad"], d["roll_step_urad"],
                   d["steer_step_urad"], d["rpm_step"])

    def quantize(self, x, y, z, yaw, pitch, roll, steer, rpm, gear, brake, surface, contact, cut,
                 slip, throttle):
        """floats -> the 10 integers of one record. gear: -1=R 0=N 1..6. slip/throttle 0..1."""
        o = self._o
        s = self._s
        qx = int((x - o[0]) / s[0] + 0.5)
        qy = int((y - o[1]) / s[1] + 0.5)
        qz = int((z - o[2]) / s[2] + 0.5)
        if qx < 0: qx = 0
        elif qx > 65535: qx = 65535
        if qy < 0: qy = 0
        elif qy > 65535: qy = 65535
        if qz < 0: qz = 0
        elif qz > 65535: qz = 65535
        qyaw = int(floor(yaw * YAW_K + 0.5)) & 0xFFFF
        qp = int(floor(pitch / self._ps + 0.5))
        qr = int(floor(roll / self._rs + 0.5))
        qs = int(floor(steer / self._ss + 0.5))
        if qp < -127: qp = -127
        elif qp > 127: qp = 127
        if qr < -127: qr = -127
        elif qr > 127: qr = 127
        if qs < -127: qs = -127
        elif qs > 127: qs = 127
        qrpm = int(rpm / self.rpm_step + 0.5)
        if qrpm < 0: qrpm = 0
        elif qrpm > 255: qrpm = 255
        g = gear + 1
        if g < 0: g = 0
        elif g > 7: g = 7
        gf = g | (8 if brake else 0) | ((surface & 3) << 4) | (64 if contact else 0) | (128 if cut else 0)
        sl = int(slip * 15.0 + 0.5)
        th = int(throttle * 15.0 + 0.5)
        if sl < 0: sl = 0
        elif sl > 15: sl = 15
        if th < 0: th = 0
        elif th > 15: th = 15
        return qx, qy, qz, qyaw, qp, qr, qs, qrpm, gf, sl | (th << 4)


# ----------------------------------------------------------------------------- sample codec
def _zz16(d):
    return [(((u & 0xFFFF) << 1) ^ -((u >> 15) & 1)) & 0xFFFF for u in d]


def _zz8(d):
    return bytes([(((u & 0xFF) << 1) ^ -((u >> 7) & 1)) & 0xFF for u in d])


def _delta(v, order):
    d = [v[0]]
    d.extend(map(sub, v[1:], v))
    if order == 2:
        e = [d[0]]
        e.extend(map(sub, d[1:], d))
        return e
    return d


def transform_samples(raw, n_cars, codec=DEFAULT_CODEC):
    """interleaved records -> column ordered, delta coded bytes (same length)."""
    cfg = CODECS[codec]
    if cfg is None:
        return bytes(raw)
    stride = REC_SIZE * n_cars
    n = len(raw) // stride
    if n == 0:
        return b""
    out = []
    fmt16 = "<%dH" % n
    for name, off, size in FIELDS:
        mode = cfg[name]
        for c in range(n_cars):
            base = c * REC_SIZE + off
            if size == 2:
                ba = bytearray(2 * n)
                ba[0::2] = raw[base::stride]
                ba[1::2] = raw[base + 1::stride]
                if mode != "r":
                    v = struct.unpack(fmt16, ba)
                    ba = struct.pack(fmt16, *_zz16(_delta(v, 2 if mode == "d2" else 1)))
                out.append(ba[0::2])
                out.append(ba[1::2])
            else:
                col = raw[base::stride]
                if mode == "r":
                    out.append(bytes(col))
                elif mode == "x":
                    b = bytearray(n)
                    b[0] = col[0]
                    b[1:] = bytes(map(int.__xor__, col[1:], col))
                    out.append(bytes(b))
                else:
                    out.append(_zz8(_delta(col, 2 if mode == "d2" else 1)))
    return b"".join(out)


def inverse_transform_samples(data, n_cars, codec=DEFAULT_CODEC):
    cfg = CODECS[codec]
    if cfg is None:
        return bytearray(data)
    stride = REC_SIZE * n_cars
    n = len(data) // stride
    out = bytearray(len(data))
    if n == 0:
        return out
    fmt16 = "<%dH" % n
    p = 0
    for name, off, size in FIELDS:
        mode = cfg[name]
        for c in range(n_cars):
            base = c * REC_SIZE + off
            if size == 2:
                lo = data[p:p + n]
                hi = data[p + n:p + 2 * n]
                p += 2 * n
                if mode != "r":
                    ba = bytearray(2 * n)
                    ba[0::2] = lo
                    ba[1::2] = hi
                    zz = struct.unpack(fmt16, ba)
                    d = [(z >> 1) ^ -(z & 1) for z in zz]
                    v = accumulate(d)
                    if mode == "d2":
                        v = accumulate(v)
                    ba = struct.pack(fmt16, *[u & 0xFFFF for u in v])
                    lo = ba[0::2]
                    hi = ba[1::2]
                out[base::stride] = lo
                out[base + 1::stride] = hi
            else:
                col = data[p:p + n]
                p += n
                if mode == "x":
                    col = bytes(accumulate(col, int.__xor__))
                elif mode != "r":
                    d = [(z >> 1) ^ -(z & 1) for z in col]
                    v = accumulate(d)
                    if mode == "d2":
                        v = accumulate(v)
                    col = bytes([u & 0xFF for u in v])
                out[base::stride] = col
    return out


def encode_samples(raw, n_cars, codec=DEFAULT_CODEC, level=9):
    return bytes([codec]) + zlib.compress(transform_samples(raw, n_cars, codec), level)


def decode_samples(payload, n_cars, expected_len):
    if len(payload) < 1:
        raise CorruptError("empty sample chunk")
    codec = payload[0]
    if codec not in CODECS:
        raise TooNewError("unknown sample codec %d" % codec)
    d = zlib.decompressobj()
    try:
        data = d.decompress(payload[1:], expected_len + 1)
    except zlib.error as e:
        raise CorruptError("sample chunk does not inflate: %s" % e)
    if len(data) != expected_len or not d.eof or d.unused_data:
        raise CorruptError("sample chunk size mismatch (got %d, header says %d)" % (len(data), expected_len))
    return inverse_transform_samples(data, n_cars, codec)


def encode_events(events, level=9):
    return b"\x00" + zlib.compress(b"".join([EV.pack(*e) for e in events]), level)


def decode_events(payload, n_cars, max_events=200000):
    if len(payload) < 1 or payload[0] != 0:
        raise TooNewError("unknown event codec")
    d = zlib.decompressobj()
    try:
        data = d.decompress(payload[1:], max_events * EV.size + 1)
    except zlib.error as e:
        raise CorruptError("event chunk does not inflate: %s" % e)
    if not d.eof or d.unused_data or len(data) % EV.size:
        raise CorruptError("event chunk size mismatch")
    ev = [e for e in EV.iter_unpack(data)]
    last = 0
    for e in ev:
        if e[0] < last:
            raise CorruptError("events not sorted by tick")
        last = e[0]
        if e[2] != 255 and e[2] >= n_cars:
            raise CorruptError("event refers to car %d of %d" % (e[2], n_cars))
    return ev


# ----------------------------------------------------------------------------- replay object
class Replay:
    """Decoded replay: header (dict, ints/strings only), raw interleaved samples, event tuples."""

    def __init__(self, header, samples, events=()):
        self.header = header
        self.samples = samples
        self.events = list(events)
        self.n_cars = header["n_cars"]
        self.sample_div = header["sample_div"]
        self.n_samples = len(samples) // (REC_SIZE * self.n_cars)
        self.quant = Quant.from_json(header["quant"])
        self.version = (VER_MAJOR, VER_MINOR)
        self._laps = None
        self._ranks = None

    # --- indexes built on demand (bisect tables) ---
    def lap_table(self, car):
        """[(end_tick, lap_no, lap_ms)] for one car, sorted by tick."""
        if self._laps is None:
            t = [[] for _ in range(self.n_cars)]
            for e in self.events:
                if e[1] == EV_LAP:
                    t[e[2]].append((e[0], e[3], e[4]))
            self._laps = t
        return self._laps[car]

    def lap_start_ticks(self, car):
        """tick where each lap begins: lap 1 at header start_tick, lap k+1 at end of lap k."""
        return [self.header.get("start_tick", 0)] + [e[0] for e in self.lap_table(car)]

    def lap_at(self, car, tick):
        """1-based number of the lap the car is driving at tick."""
        return bisect.bisect_right([e[0] for e in self.lap_table(car)], tick) + 1

    def rank_at(self, car, tick):
        if self._ranks is None:
            t = [([], []) for _ in range(self.n_cars)]
            for e in self.events:
                if e[1] == EV_POS:
                    t[e[2]][0].append(e[0])
                    t[e[2]][1].append(e[3])
            self._ranks = t
        ticks, ranks = self._ranks[car]
        i = bisect.bisect_right(ticks, tick) - 1
        if i < 0:
            return self.header["cars"][car].get("grid", car + 1)
        return ranks[i]

    def events_between(self, tick_a, tick_b):
        """events with tick_a < tick <= tick_b (for triggering sounds while playing forward)."""
        keys = self._ev_ticks()
        return self.events[bisect.bisect_right(keys, tick_a):bisect.bisect_right(keys, tick_b)]

    def _ev_ticks(self):
        k = getattr(self, "_evk", None)
        if k is None or len(k) != len(self.events):
            k = self._evk = [e[0] for e in self.events]
        return k

    def content_crc(self):
        """identity of the replay content, independent of zlib output bytes."""
        c = zlib.crc32(bytes(self.samples))
        c = zlib.crc32(b"".join([EV.pack(*e) for e in self.events]), c)
        return c & 0xFFFFFFFF


class Recorder:
    """Appends raw records while driving. Call tick() once per physics tick with all cars."""

    def __init__(self, n_cars, quant, sample_div=3):
        self.n_cars = n_cars
        self.quant = quant
        self.sample_div = sample_div
        self.buf = bytearray()
        self.events = []
        self._S = struct.Struct("<" + REC_FMT * n_cars)
        self._latch = [0] * n_cars  # contact / cut bits latched between samples
        self.ticks = 0

    def tick(self, states):
        """states: per car (x,y,z,yaw,pitch,roll,steer,rpm,gear,brake,surface,contact,cut,slip,throttle)."""
        latch = self._latch
        if self.ticks % self.sample_div:
            for c in range(self.n_cars):
                st = states[c]
                if st[11]: latch[c] |= 64
                if st[12]: latch[c] |= 128
        else:
            q = self.quant.quantize
            vals = []
            for c in range(self.n_cars):
                r = q(*states[c])
                if latch[c]:
                    r = r[:8] + (r[8] | latch[c],) + r[9:]
                    latch[c] = 0
                vals.extend(r)
            self.buf += self._S.pack(*vals)
        self.ticks += 1

    def add_event(self, tick, etype, car=255, a=0, b=0):
        self.events.append((tick, etype, car, a, b))

    def finish(self, header):
        h = dict(header)
        h["n_cars"] = self.n_cars
        h["sample_div"] = self.sample_div
        h["tick_hz"] = TICK_HZ
        h["quant"] = self.quant.to_json()
        h["n_samples"] = len(self.buf) // (REC_SIZE * self.n_cars)
        self.events.sort(key=lambda e: e[0])
        return Replay(h, self.buf, self.events)


# ----------------------------------------------------------------------------- .cpr file
def _has_float(o):
    if isinstance(o, float):
        return True
    if isinstance(o, dict):
        return any(_has_float(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return any(_has_float(v) for v in o)
    return False


def _req(h, key, typ, where="header"):
    if key not in h:
        raise InvalidHeaderError("%s: missing '%s'" % (where, key))
    v = h[key]
    if isinstance(v, bool) and typ is int:
        raise InvalidHeaderError("%s: '%s' must be int" % (where, key))
    if not isinstance(v, typ):
        raise InvalidHeaderError("%s: '%s' has wrong type" % (where, key))
    return v


def validate_header(h):
    if not isinstance(h, dict):
        raise InvalidHeaderError("header is not an object")
    if _has_float(h):
        raise InvalidHeaderError("header must not contain floats")
    if _req(h, "tick_hz", int) != TICK_HZ:
        raise InvalidHeaderError("tick_hz must be %d" % TICK_HZ)
    if not 1 <= _req(h, "sample_div", int) <= 6:
        raise InvalidHeaderError("sample_div out of range")
    n_cars = _req(h, "n_cars", int)
    if not 1 <= n_cars <= MAX_CARS:
        raise InvalidHeaderError("n_cars out of range")
    n = _req(h, "n_samples", int)
    if n < 1 or n * n_cars * REC_SIZE > MAX_RAW_BYTES:
        raise InvalidHeaderError("n_samples out of range")
    _req(h, "mode", str)
    course = _req(h, "course", dict)
    _req(course, "id", str, "course")
    _req(course, "layout", str, "course")
    _req(course, "data_ver", int, "course")
    q = _req(h, "quant", dict)
    for k in ("origin_mm", "step_um"):
        v = _req(q, k, list, "quant")
        if len(v) != 3 or not all(isinstance(i, int) and not isinstance(i, bool) for i in v):
            raise InvalidHeaderError("quant.%s must be 3 ints" % k)
    if min(q["step_um"]) < 1:
        raise InvalidHeaderError("quant.step_um must be positive")
    for k in ("pitch_step_urad", "roll_step_urad", "steer_step_urad", "rpm_step"):
        if _req(q, k, int, "quant") < 1:
            raise InvalidHeaderError("quant.%s must be positive" % k)
    cars = _req(h, "cars", list)
    if len(cars) != n_cars:
        raise InvalidHeaderError("cars has %d entries, n_cars is %d" % (len(cars), n_cars))
    for i, c in enumerate(cars):
        if not isinstance(c, dict):
            raise InvalidHeaderError("cars[%d] is not an object" % i)
        _req(c, "car", str, "cars[%d]" % i)
        _req(c, "color", int, "cars[%d]" % i)
        _req(c, "setup", dict, "cars[%d]" % i)
    _req(h, "saved_at", str)
    title = _req(h, "title", str)
    if len(title) > 32 or any(not (32 <= ord(ch) < 127) for ch in title):
        raise InvalidHeaderError("title must be <= 32 printable ASCII characters")
    return h


def check_content(header, catalog):
    """Compare a valid header with what this build knows.
    catalog = {"courses": {id: {"layouts": [...], "data_ver": int}}, "cars": [ids]}
    Returns a list of (severity, code, detail); severity "error" means it cannot be played."""
    out = []
    if header["mode"] not in MODES:
        out.append(("error", "E_UNKNOWN_MODE", header["mode"]))
    c = header["course"]
    known = catalog["courses"].get(c["id"])
    if known is None:
        out.append(("error", "E_UNKNOWN_COURSE", c["id"]))
    else:
        if c["layout"] not in known["layouts"]:
            out.append(("error", "E_UNKNOWN_LAYOUT", "%s/%s" % (c["id"], c["layout"])))
        if c["data_ver"] > known["data_ver"]:
            out.append(("error", "E_COURSE_TOO_NEW", "%s v%d > v%d" % (c["id"], c["data_ver"], known["data_ver"])))
        elif c["data_ver"] < known["data_ver"]:
            out.append(("warn", "W_COURSE_OLDER", "%s v%d < v%d" % (c["id"], c["data_ver"], known["data_ver"])))
    for i, car in enumerate(header["cars"]):
        if car["car"] not in catalog["cars"]:
            out.append(("error", "E_UNKNOWN_CAR", "cars[%d]=%s" % (i, car["car"])))
    return out


def require_content(header, catalog):
    problems = check_content(header, catalog)
    errs = [p for p in problems if p[0] == "error"]
    if errs:
        raise UnknownContentError("; ".join("%s %s" % (p[1], p[2]) for p in errs))
    return problems


def _chunk(tag, payload):
    return tag + struct.pack("<I", len(payload)) + payload


def dump_cpr(rp, level=9, codec=DEFAULT_CODEC, extra_chunks=()):
    header = dict(rp.header)
    header["n_samples"] = rp.n_samples
    header["content_crc"] = rp.content_crc()
    validate_header(header)
    hj = json.dumps(header, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    body = _chunk(b"SMPL", encode_samples(rp.samples, rp.n_cars, codec, level))
    body += _chunk(b"EVNT", encode_events(rp.events, level))
    for tag, payload in extra_chunks:
        body += _chunk(tag, payload)
    pre = PREAMBLE.pack(MAGIC, VER_MAJOR, VER_MINOR, len(hj), len(body))
    data = pre + hj + body
    return data + struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)


def _check_envelope(data):
    """magic / version / length / CRC. Returns (major, minor, header_bytes, body_bytes)."""
    n = len(data)
    if n < 8:
        if n and MAGIC.startswith(bytes(data)):
            raise TruncatedError("file ends inside the signature")
        raise NotCprError("not a CLIPPING POINT replay")
    if data[:8] != MAGIC:
        if data[:4] == MAGIC[:4]:
            raise CorruptError("signature damaged (text-mode transfer?)")
        raise NotCprError("not a CLIPPING POINT replay")
    if n < PREAMBLE.size:
        raise TruncatedError("file ends inside the preamble")
    _, major, minor, hlen, blen = PREAMBLE.unpack_from(data, 0)
    if major > VER_MAJOR:
        raise TooNewError("format %d.%d is newer than this build (%d.%d)" % (major, minor, VER_MAJOR, VER_MINOR))
    if major < 1:
        raise CorruptError("format version 0")
    total = PREAMBLE.size + hlen + blen + 4
    if n < total:
        raise TruncatedError("file has %d bytes, should have %d" % (n, total))
    if n > total:
        raise CorruptError("file has %d extra bytes" % (n - total))
    (crc,) = struct.unpack_from("<I", data, total - 4)
    if zlib.crc32(data[:total - 4]) & 0xFFFFFFFF != crc:
        raise CorruptError("checksum mismatch")
    h0 = PREAMBLE.size
    return major, minor, data[h0:h0 + hlen], data[h0 + hlen:h0 + hlen + blen]


def _parse_header(hbytes):
    try:
        h = json.loads(hbytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise InvalidHeaderError("header is not JSON: %s" % e)
    return h


# upgrade functions for older major versions: major -> f(header, chunks) -> (header, chunks)
_UPGRADERS = {}


def peek_cpr(data):
    """Integrity check + header only (for the theatre list). No inflate."""
    major, minor, hbytes, _ = _check_envelope(data)
    h = validate_header(_parse_header(hbytes))
    return (major, minor), h


def load_cpr(data, catalog=None):
    major, minor, hbytes, body = _check_envelope(data)
    header = _parse_header(hbytes)
    chunks = {}
    p = 0
    nb = len(body)
    while p < nb:
        if p + 8 > nb:
            raise CorruptError("chunk header overruns body")
        tag = bytes(body[p:p + 4])
        (ln,) = struct.unpack_from("<I", body, p + 4)
        p += 8
        if p + ln > nb:
            raise CorruptError("chunk %r overruns body" % tag)
        if tag in chunks:
            raise CorruptError("duplicate chunk %r" % tag)
        chunks[tag] = body[p:p + ln]   # unknown tags are kept but ignored (minor additions)
        p += ln
    m = major
    while m < VER_MAJOR:
        header, chunks = _UPGRADERS[m](header, chunks)
        m += 1
    validate_header(header)
    if catalog is not None:
        require_content(header, catalog)
    if b"SMPL" not in chunks:
        raise CorruptError("no sample chunk")
    n_cars = header["n_cars"]
    samples = decode_samples(chunks[b"SMPL"], n_cars, header["n_samples"] * n_cars * REC_SIZE)
    events = decode_events(chunks[b"EVNT"], n_cars) if b"EVNT" in chunks else []
    rp = Replay(header, samples, events)
    rp.version = (major, minor)
    if "content_crc" in header and header["content_crc"] != rp.content_crc():
        raise CorruptError("content_crc mismatch")
    return rp


def to_base64(data):
    return base64.b64encode(data).decode("ascii")


def from_base64(text):
    try:
        return base64.b64decode(text, validate=True)
    except Exception as e:  # binascii.Error
        raise CorruptError("not base64: %s" % e)


# ----------------------------------------------------------------------------- playback
SPEEDS = {"x1": 8, "x1/2": 4, "x1/4": 2, "x2": 16, "x4": 32,
          "rew": -8, "rew2": -16, "rew4": -32, "pause": 0}  # q-units per 1/30 s frame


class Player:
    """Random access playback. Position is an integer in 1/240 s units (4 per physics tick)."""

    def __init__(self, rp):
        self.rp = rp
        self.n = rp.n_samples
        self.unit = rp.sample_div * Q_PER_TICK
        self.end = (self.n - 1) * self.unit
        self.pos = 0
        self._S = struct.Struct("<" + REC_FMT * rp.n_cars)
        self._fs = REC_SIZE * rp.n_cars
        self._rows = {}
        q = rp.quant
        self._o = q._o
        self._s = q._s
        self._ps, self._rs, self._ss, self._rpm = q._ps, q._rs, q._ss, q.rpm_step
        self._dt = rp.sample_div / TICK_HZ

    # --- transport: all index arithmetic, no scanning ---
    def seek_q(self, pos):
        self.pos = 0 if pos < 0 else (self.end if pos > self.end else pos)
        return self.pos

    def seek_tick(self, tick):
        return self.seek_q(tick * Q_PER_TICK)

    def seek_seconds(self, sec):
        return self.seek_q(int(sec * TICK_HZ * Q_PER_TICK + 0.5))

    def advance(self, dq):
        """dq = SPEEDS[...] per rendered frame. Returns True when an end was hit."""
        p = self.pos + dq
        self.seek_q(p)
        return p != self.pos

    def tick(self):
        return self.pos / Q_PER_TICK

    def seek_lap(self, car, lap_no):
        """jump to the start of lap lap_no (1-based) of a car; returns False if no such lap."""
        starts = self.rp.lap_start_ticks(car)
        if not 1 <= lap_no <= len(starts):
            return False
        self.seek_tick(starts[lap_no - 1])
        return True

    def next_lap(self, car, direction=1):
        starts = self.rp.lap_start_ticks(car)
        t = self.pos // Q_PER_TICK
        if direction > 0:
            i = bisect.bisect_right(starts, t)
            if i >= len(starts):
                return False
        else:
            i = bisect.bisect_left(starts, t - 30) - 1   # within 0.5 s of a start: go to previous
            if i < 0:
                i = 0
        self.seek_tick(starts[i])
        return True

    # --- samples ---
    def row(self, i):
        if i < 0: i = 0
        elif i >= self.n: i = self.n - 1
        r = self._rows.get(i)
        if r is None:
            if len(self._rows) > 16:
                self._rows.clear()
            r = self._rows[i] = self._S.unpack_from(self.rp.samples, i * self._fs)
        return r

    def pose(self, car, interp="lerp"):
        """(x,y,z,yaw,pitch,roll,steer,rpm,gear,brake,surface,contact,slip,throttle,speed_mps)."""
        i, f = divmod(self.pos, self.unit)
        if i >= self.n - 1:
            i, f = self.n - 1, 0
        a = f / self.unit
        o = car * NF
        r0 = self.row(i)
        r1 = self.row(i + 1)
        gf = r0[o + 8]
        aux = r0[o + 9]
        cut = r1[o + 8] & 128
        dx = r1[o] - r0[o]
        dy = r1[o + 1] - r0[o + 1]
        dz = r1[o + 2] - r0[o + 2]
        dyaw = ((r1[o + 3] - r0[o + 3] + 32768) & 0xFFFF) - 32768
        s = self._s
        if cut:
            a = 0.0
            speed = 0.0
        else:
            ax, ay, az = dx * s[0], dy * s[1], dz * s[2]
            speed = sqrt(ax * ax + ay * ay + az * az) / self._dt   # sqrt is correctly rounded everywhere
        if interp == "hermite" and not cut and a:
            rm = self.row(i - 1)
            r2 = self.row(i + 2)
            if not ((r0[o + 8] | r2[o + 8]) & 128):
                a2 = a * a
                a3 = a2 * a
                h10 = a3 - 2.0 * a2 + a
                h01 = 3.0 * a2 - 2.0 * a3
                h11 = a3 - a2
                # tangents = central differences; one-sided at the two ends of the record
                h10 *= 1.0 if i == 0 else 0.5
                h11 *= 1.0 if i + 2 >= self.n else 0.5
                qx = r0[o] + h10 * (r1[o] - rm[o]) + h01 * dx + h11 * (r2[o] - r0[o])
                qy = r0[o + 1] + h10 * (r1[o + 1] - rm[o + 1]) + h01 * dy + h11 * (r2[o + 1] - r0[o + 1])
                qz = r0[o + 2] + h10 * (r1[o + 2] - rm[o + 2]) + h01 * dz + h11 * (r2[o + 2] - r0[o + 2])
                dm = ((r0[o + 3] - rm[o + 3] + 32768) & 0xFFFF) - 32768
                d2 = ((r2[o + 3] - r1[o + 3] + 32768) & 0xFFFF) - 32768
                qyaw = r0[o + 3] + h10 * (dm + dyaw) + h01 * dyaw + h11 * (dyaw + d2)
            else:
                interp = "lerp"
        else:
            interp = "lerp"
        if interp == "lerp":
            qx = r0[o] + dx * a
            qy = r0[o + 1] + dy * a
            qz = r0[o + 2] + dz * a
            qyaw = r0[o + 3] + dyaw * a
        oo = self._o
        return (oo[0] + qx * s[0], oo[1] + qy * s[1], oo[2] + qz * s[2],
                qyaw * (TWO_PI / 65536.0),
                (r0[o + 4] + (r1[o + 4] - r0[o + 4]) * a) * self._ps,
                (r0[o + 5] + (r1[o + 5] - r0[o + 5]) * a) * self._rs,
                (r0[o + 6] + (r1[o + 6] - r0[o + 6]) * a) * self._ss,
                (r0[o + 7] + (r1[o + 7] - r0[o + 7]) * a) * self._rpm,
                (gf & 7) - 1, (gf >> 3) & 1, (gf >> 4) & 3, (gf >> 6) & 1,
                (aux & 15) / 15.0, (aux >> 4) / 15.0, speed)


# ----------------------------------------------------------------------------- time attack ring + ghost
def cut_car_samples(samples, n_cars, car, i0, i1):
    """records i0..i1-1 of one car out of an interleaved multi-car buffer (C-speed slices)."""
    fs = REC_SIZE * n_cars
    n = i1 - i0
    out = bytearray(n * REC_SIZE)
    base = i0 * fs + car * REC_SIZE
    end = i1 * fs
    for b in range(REC_SIZE):
        out[b::REC_SIZE] = samples[base + b:end:fs]
    return out


def make_ghost(src_header, samples, n_cars, car, sample_div, start_tick, end_tick, lap_ms,
               first_sample=0, saved_at="", title="GHOST"):
    """Cut one lap of one car into a 1-car replay. first_sample = global index of samples[0]."""
    i0 = start_tick // sample_div
    i1 = -(-end_tick // sample_div) + 2            # one extra sample past the line for interpolation
    n_avail = len(samples) // (REC_SIZE * n_cars) + first_sample
    if i1 > n_avail:
        i1 = n_avail
    cut = cut_car_samples(samples, n_cars, car, i0 - first_sample, i1 - first_sample)
    h = {"mode": "ghost", "course": src_header["course"], "tick_hz": TICK_HZ,
         "sample_div": sample_div, "n_cars": 1, "n_samples": i1 - i0, "quant": src_header["quant"],
         "cars": [src_header["cars"][car]], "saved_at": saved_at or src_header.get("saved_at", ""),
         "title": title, "start_tick": start_tick - i0 * sample_div,
         "ghost": {"t0_tick": start_tick - i0 * sample_div, "lap_ticks": end_tick - start_tick,
                   "lap_ms": lap_ms}}
    t0 = h["start_tick"]
    return Replay(h, cut, [(t0, EV_START, 0, 0, 0), (t0 + end_tick - start_tick, EV_LAP, 0, 1, lap_ms)])


class GhostPlayer:
    """Ghost = ordinary Player on a 1-car replay, addressed by 'ticks since crossing the line'."""

    def __init__(self, ghost):
        self.player = Player(ghost)
        self.t0 = ghost.header["ghost"]["t0_tick"]
        self.lap_ticks = ghost.header["ghost"]["lap_ticks"]

    def pose_at(self, lap_tick, interp="lerp"):
        if lap_tick < 0 or lap_tick > self.lap_ticks + 2:
            return None                              # ghost finished: hide it
        self.player.seek_q(int((self.t0 + lap_tick) * Q_PER_TICK))
        return self.player.pose(0, interp)


class LapRing:
    """Time attack recorder: keeps the last n_keep completed laps (+ the lap in progress) and the
    best lap. One bytearray; old laps are dropped from the front when a lap completes."""

    def __init__(self, quant, n_keep=5, sample_div=3):
        self.quant = quant
        self.n_keep = n_keep
        self.sample_div = sample_div
        self.buf = bytearray()
        self.first_sample = 0        # global sample index of buf[0]
        self.laps = []               # (start_tick, end_tick, lap_ms, lap_no) of kept laps
        self.lap_start = None        # tick where the lap in progress began
        self.lap_no = 0
        self.best = None             # (lap_ms, lap_no, start_tick, end_tick, bytes of that lap)
        self.ticks = 0
        self._latch = 0
        self._pending = None

    def tick(self, state):
        if self.ticks % self.sample_div:
            if state[11]: self._latch |= 64
            if state[12]: self._latch |= 128
        else:
            r = self.quant.quantize(*state)
            if self._latch:
                r = r[:8] + (r[8] | self._latch,) + r[9:]
                self._latch = 0
            self.buf += REC.pack(*r)
            if self._pending is not None:
                need = -(-self._pending[3] // self.sample_div) + 2
                if len(self.buf) // REC_SIZE + self.first_sample >= need:
                    self._take_best()
        self.ticks += 1

    def _take_best(self):
        lap_ms, lap_no, s, e = self._pending
        i0 = s // self.sample_div - self.first_sample
        self.best = (lap_ms, lap_no, s, e, bytes(self.buf[i0 * REC_SIZE:]), s // self.sample_div)
        self._pending = None

    def cross_line(self, tick, lap_ms=0):
        """call when the car crosses the start/finish line at `tick` (before tick() of that tick+1)."""
        if self.lap_start is not None:
            self.lap_no += 1
            lap = (self.lap_start, tick, lap_ms, self.lap_no)
            self.laps.append(lap)
            if self.best is None or lap_ms < self.best[0]:
                # the copy is taken two samples later (see tick): the ghost needs samples past the line
                self._pending = (lap_ms, self.lap_no, self.lap_start, tick)
                self.best = (lap_ms, self.lap_no, self.lap_start, tick, None, 0)
            if len(self.laps) > self.n_keep:
                self.laps.pop(0)
                new_first = self.laps[0][0] // self.sample_div
                del self.buf[:(new_first - self.first_sample) * REC_SIZE]
                self.first_sample = new_first
        else:
            # out lap is not kept: drop everything before the first crossing
            new_first = tick // self.sample_div
            del self.buf[:(new_first - self.first_sample) * REC_SIZE]
            self.first_sample = new_first
        self.lap_start = tick

    def build_replay(self, header):
        """Replay of the kept laps (time axis re-based so sample 0 is tick 0)."""
        h = dict(header)
        base = self.first_sample * self.sample_div
        h.update(mode="time_attack", n_cars=1, sample_div=self.sample_div, tick_hz=TICK_HZ,
                 quant=self.quant.to_json(), n_samples=len(self.buf) // REC_SIZE)
        ev = []
        if self.laps:
            h["start_tick"] = self.laps[0][0] - base
            ev.append((h["start_tick"], EV_START, 0, 0, 0))
            for (s, e, ms, no) in self.laps:
                ev.append((e - base, EV_LAP, 0, no, ms))
        return Replay(h, bytearray(self.buf), ev)

    def best_ghost(self, header, title="BEST"):
        if self.best is None:
            return None
        if self._pending is not None:
            self._take_best()
        lap_ms, lap_no, s, e, data, first = self.best
        h = dict(header)
        h.update(n_cars=1, quant=self.quant.to_json())
        return make_ghost(h, data, 1, 0, self.sample_div, s, e, lap_ms, first_sample=first, title=title)
