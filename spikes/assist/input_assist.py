"""CLIPPING POINT input assist spike (pure Python, standard library only, no pyxel).

Raw, already normalised input  ->  steering command (rad at the road wheel) and pedal amounts
for the vehicle model.

Conventions (shared with the vehicle / course spikes)
  steer > 0 = left.  raw steer -1 .. +1 (+1 = full left), throttle 0 .. 1, brake 0 .. 1.
  Every channel carries its own "analog or digital" flag: a digital channel only ever has the
  values -1 / 0 / +1 (steer) or 0 / 1 (pedals).  How the values were obtained (pyxel.btnv,
  js Gamepad API, keyboard, right stick as pedals ...) is the display-side adapter's business.
  units m, s, rad.  fixed step dt = 1/60, one call of InputAssist.step per tick, called just
  before car.step with the car state left by the previous tick.

Pipeline
  steer : dead zone -> response curve -> x speed-dependent limit -> countersteer relaxation
          -> slip-angle window clip -> rate limit (digital: progressive) -> command (rad)
  pedals: dead zone -> response curve -> rate limit (digital: rise / fall time)
          -> assist (brake: lock prevention, throttle: wheelspin / power-slide limiter)

ALL NUMBERS IN THIS FILE ARE PROVISIONAL ("kari no atai").
"""
from math import atan, atan2, log, tan
import json

G = 9.81
DT = 1.0 / 60.0

FORMAT = "clipping-point-assist"
VERSION = 1

# --------------------------------------------------------------------------------------------
# data: player-facing items (5 stages each) and fixed internal numbers.  Written to
# assist_config.json by `python input_assist.py --dump`; load_config() validates a file.
# stage index 0..4 is shown to the player as 1..5.
# --------------------------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "format": FORMAT,
    "version": VERSION,
    "items": {
        # y = x + k*(x^3 - x): slope at the centre = 1 - k
        "steer_curve": {"label": "STEER CURVE", "low": "LINEAR", "high": "SOFT",
                        "values": {"steer_k": [0.0, 0.2, 0.4, 0.6, 0.8]}},
        # digital: time from 0 to the full (speed-limited) angle while the key is held, and back;
        # analog : time for a full-range change (only removes spikes)
        "steer_speed": {"label": "STEER SPEED", "low": "SLOW", "high": "FAST",
                        "values": {"dig_t_full": [0.50, 0.40, 0.32, 0.25, 0.19],
                                   "dig_t_return": [0.32, 0.26, 0.21, 0.17, 0.13],
                                   "ana_t_full": [0.16, 0.12, 0.09, 0.07, 0.05]}},
        # speed-dependent lock: limit = ka * L*a/v^2 + km*alpha_peak (stage 1 = widest)
        "steer_limit": {"label": "SPEED LOCK", "low": "WIDE", "high": "TIGHT",
                        "values": {"limit_km": [0.50, 0.30, 0.20, 0.12, 0.08],
                                   "limit_ka": [1.25, 1.10, 1.00, 0.92, 0.85],
                                   "clip_k": [2.40, 1.90, 1.50, 1.25, 1.10]}},
        # countersteer: how much of the extra angle is released, and how much faster the wheel turns
        "counter": {"label": "COUNTER", "low": "OFF", "high": "STRONG",
                    "values": {"cs_gain": [0.0, 0.6, 1.0, 1.0, 1.0],
                               "cs_km": [0.0, 0.0, 0.15, 0.30, 0.50],
                               "cs_rate": [1.0, 1.5, 2.0, 2.5, 3.0]}},
        "throttle_curve": {"label": "THROTTLE CURVE", "low": "LINEAR", "high": "SOFT",
                           "values": {"throttle_k": [0.0, 0.2, 0.4, 0.6, 0.8]}},
        "brake_curve": {"label": "BRAKE CURVE", "low": "LINEAR", "high": "SOFT",
                        "values": {"brake_k": [0.0, 0.2, 0.4, 0.6, 0.8]}},
        # digital pedals: rise / fall time of the pedal amount
        "pedal_speed": {"label": "PEDAL SPEED", "low": "SLOW", "high": "FAST",
                        "values": {"thr_t_up": [0.50, 0.38, 0.28, 0.20, 0.12],
                                   "thr_t_down": [0.20, 0.16, 0.12, 0.09, 0.06],
                                   "brk_t_up": [0.32, 0.24, 0.18, 0.13, 0.08],
                                   "brk_t_down": [0.16, 0.13, 0.10, 0.08, 0.05]}},
        "deadzone": {"label": "DEAD ZONE", "low": "SMALL", "high": "LARGE",
                     "values": {"steer_dz": [0.03, 0.06, 0.10, 0.15, 0.20]}},
    },
    # default stage (0..4) per item for the two input styles
    "presets": {
        "analog": {"steer_curve": 2, "steer_speed": 2, "steer_limit": 2, "counter": 2,
                   "throttle_curve": 1, "brake_curve": 1, "pedal_speed": 2, "deadzone": 2},
        "digital": {"steer_curve": 0, "steer_speed": 2, "steer_limit": 3, "counter": 2,
                    "throttle_curve": 0, "brake_curve": 0, "pedal_speed": 2, "deadzone": 2},
    },
    "fixed": {
        "limit_mode": "physics",      # "physics" / "simple" / "none"
        "simple_v0": 11.0,            # simple: limit = max*(floor + (1-floor)/(1+(v/v0)^2))
        "simple_floor": 0.10,
        "limit_mu_min": 0.5,          # the kinematic part uses max(mu, this) * tyre mu
        "clip_on": False,             # slip-angle window clip (front slip <= clip_k * alpha_peak); tested, not adopted
        "clip_v0": 6.0,               # window fully open below this speed (m/s) ...
        "clip_v1": 12.0,              # ... fully active above this
        "steer_sat": 0.97,            # stick value treated as full
        "pedal_dz": 0.04,
        "pedal_sat": 0.97,
        "pedal_ana_t": 0.06,          # analog pedals: full-range time (spike filter only)
        "dig_rate_start": 0.35,       # digital steer: rate at the moment the key goes down ...
        "dig_ramp_t": 0.60,           # ... reaches the full rate after this fraction of dig_t_full
        "dig_limit_frac": 1.0,        # digital target = this fraction of the limit
        # countersteer detection
        "cs_slide0": 0.95,            # rear normalised slip where the relaxation starts ...
        "cs_slide1": 1.35,            # ... and is complete
        "cs_beta_min_deg": 3.0,       # and the body slip must exceed this
        "cs_v_min": 5.0,              # m/s
        "cs_hold_t": 0.30,            # relaxation decays with this time constant after the slide
        # brake lock prevention (assist ON)
        "abs_target": 0.97,           # keep max(-u) of all wheels below this ...
        "abs_target_turn": 0.80,      # ... or this when the front tyres are at their lateral peak
        "abs_u_lo_rear": 0.15,        # allowed brake u of a rear wheel when the rear axle slides sideways
        "abs_recover": 4.0,           # cap recovery per second
        "abs_min": 0.05,
        # engine-drag control (assist ON): keep a little throttle while the rear axle is near its
        # lateral peak and the brake is released, so that lifting off does not unsettle the car
        "coast_thr": 0.12,
        "coast_sy0": 0.60,
        "coast_sy1": 0.95,
        "coast_v_min": 8.0,
        # drive limiter (assist ON)
        "tcs_u_hi": 0.97,             # allowed u of a driven wheel while the axle slides little
        "tcs_u_lo_rear": 0.30,        # ... when the driven rear axle is at / past its lateral peak
        "tcs_u_lo_front": 0.55,       # ... same for a driven front axle
        "tcs_sy0": 0.55,              # normalised lateral slip where the target starts to fall
        "tcs_sy1": 1.05,              # ... and reaches the low value
        "tcs_recover": 1.6,           # cap recovery per second
        "tcs_min": 0.06,
    },
}

ITEM_ORDER = ("steer_curve", "steer_speed", "steer_limit", "counter",
              "throttle_curve", "brake_curve", "pedal_speed", "deadzone")
STAGES = 5


class AssistConfigError(ValueError):
    pass


def validate_config(cfg):
    """Load-time check: unknown / missing keys, stage counts, value ranges, monotonic tables."""
    if not isinstance(cfg, dict):
        raise AssistConfigError("config must be an object")
    for k in ("format", "version", "items", "presets", "fixed"):
        if k not in cfg:
            raise AssistConfigError("missing key: %s" % k)
    for k in cfg:
        if k not in ("format", "version", "items", "presets", "fixed", "notes"):
            raise AssistConfigError("unknown key: %s" % k)
    if cfg["format"] != FORMAT or cfg["version"] != VERSION:
        raise AssistConfigError("format / version mismatch")
    items = cfg["items"]
    if sorted(items) != sorted(ITEM_ORDER):
        raise AssistConfigError("items must be exactly %s" % (ITEM_ORDER,))
    ref = DEFAULT_CONFIG["items"]
    for name in ITEM_ORDER:
        it = items[name]
        for k in ("label", "low", "high", "values"):
            if k not in it:
                raise AssistConfigError("%s: missing %s" % (name, k))
        for s in (it["label"], it["low"], it["high"]):
            if not isinstance(s, str) or not s or any(ord(c) > 126 or ord(c) < 32 for c in s):
                raise AssistConfigError("%s: labels must be ASCII" % name)
        if sorted(it["values"]) != sorted(ref[name]["values"]):
            raise AssistConfigError("%s: value tables must be %s" % (name, sorted(ref[name]["values"])))
        for key, tab in it["values"].items():
            if not isinstance(tab, list) or len(tab) != STAGES:
                raise AssistConfigError("%s.%s: need %d stages" % (name, key, STAGES))
            for v in tab:
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0.0 or v > 10.0:
                    raise AssistConfigError("%s.%s: bad value %r" % (name, key, v))
            up = all(tab[i] <= tab[i + 1] for i in range(STAGES - 1))
            dn = all(tab[i] >= tab[i + 1] for i in range(STAGES - 1))
            if not (up or dn):
                raise AssistConfigError("%s.%s: stages must be monotonic" % (name, key))
            if key.endswith("_k") and name.endswith("curve") and max(tab) > 1.0:
                raise AssistConfigError("%s.%s: curve k must be <= 1" % (name, key))
            if key.startswith(("dig_t", "ana_t", "thr_t", "brk_t")) and min(tab) < 0.02:
                raise AssistConfigError("%s.%s: times must be >= 0.02 s" % (name, key))
            if key == "steer_dz" and max(tab) > 0.5:
                raise AssistConfigError("deadzone too large")
    for pname in ("analog", "digital"):
        if pname not in cfg["presets"]:
            raise AssistConfigError("missing preset %s" % pname)
        check_levels(cfg["presets"][pname], need_all=True)
    fx = cfg["fixed"]
    if sorted(fx) != sorted(DEFAULT_CONFIG["fixed"]):
        raise AssistConfigError("fixed keys differ from the known set")
    if fx["limit_mode"] not in ("physics", "simple", "none"):
        raise AssistConfigError("limit_mode")
    for k, v in fx.items():
        if k == "limit_mode":
            continue
        if k == "clip_on":
            if not isinstance(v, bool):
                raise AssistConfigError("clip_on must be a bool")
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0.0:
            raise AssistConfigError("fixed.%s: bad value %r" % (k, v))
    if not fx["cs_slide0"] < fx["cs_slide1"] or not fx["tcs_sy0"] < fx["tcs_sy1"] or not fx["clip_v0"] < fx["clip_v1"]:
        raise AssistConfigError("fixed: ordered pairs are reversed")
    return cfg


def check_levels(levels, need_all=False):
    if not isinstance(levels, dict):
        raise AssistConfigError("levels must be an object")
    for k, v in levels.items():
        if k not in ITEM_ORDER:
            raise AssistConfigError("unknown item: %r" % (k,))
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < STAGES:
            raise AssistConfigError("stage of %s out of range: %r" % (k, v))
    if need_all and sorted(levels) != sorted(ITEM_ORDER):
        raise AssistConfigError("preset must set every item")
    return levels


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise AssistConfigError("duplicate key in JSON: %s" % k)
        d[k] = v
    return d


def load_config(path):
    with open(path, "r") as f:
        cfg = json.load(f, object_pairs_hook=_no_dup)
    return validate_config(cfg)


# --------------------------------------------------------------------------------------------
# pure helper functions
# --------------------------------------------------------------------------------------------
def apply_deadzone(x, dz, sat=1.0):
    """Symmetric dead zone with rescale: |x| <= dz -> 0, |x| >= sat -> 1, linear between."""
    ax = x if x >= 0.0 else -x
    if ax <= dz:
        return 0.0
    y = (ax - dz) / (sat - dz)
    if y > 1.0:
        y = 1.0
    return y if x > 0.0 else -y


def curve_cubic(x, k):
    """y = x + k*(x^3 - x).  k = 0 linear, k -> 1 pure cubic.  Slope at the centre = 1 - k,
    end points fixed (0 -> 0, +-1 -> +-1), odd, monotonic for -0.5 <= k <= 1."""
    return x + k * (x * x * x - x)


def curve_power(x, p):
    """y = sign(x)*|x|^p.  Slope at the centre is 0 for every p > 1."""
    if x >= 0.0:
        return x ** p
    return -((-x) ** p)


def cubic_k_to_power(k):
    """Exponent of the power curve that gives the same output at half deflection."""
    return log(0.5 - 0.375 * k) / log(0.5)


def speed_limit_physics(v, wheelbase, alpha_peak, max_steer, km, ka=1.0, a_lat=G):
    """Largest useful steer angle at speed v: the angle the corner itself needs at the grip
    limit (L * a / v^2) plus a slip-angle allowance (km * alpha_peak)."""
    if v < 1.0:
        return max_steer
    lim = ka * wheelbase * a_lat / (v * v) + km * alpha_peak
    return lim if lim < max_steer else max_steer


def speed_limit_simple(v, max_steer, v0, floor):
    """Simple rational form: max_steer at 0, max_steer*floor at infinite speed."""
    r = v / v0
    return max_steer * (floor + (1.0 - floor) / (1.0 + r * r))


# ---- adapter-side helpers (pure; the pyxel / js side passes plain numbers) ------------------
def stick_from_device(value, full_scale=32767.0):
    """Device units (pyxel.btnv: -32768..32767) -> -1..1 (no dead zone here)."""
    v = value / full_scale
    return -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)


def digital_axis(neg_down, pos_down):
    """Two keys -> -1 / 0 / +1 (both down = 0)."""
    return (1.0 if pos_down else 0.0) - (1.0 if neg_down else 0.0)


def pedals_from_stick_y(y, up_is_negative=True):
    """Right stick up = throttle, down = brake.  Returns (throttle, brake), both 0..1 analog."""
    if up_is_negative:
        y = -y
    return (y if y > 0.0 else 0.0, -y if y < 0.0 else 0.0)


def is_two_valued(samples, eps=1e-3):
    """True when every sample of a trigger is 0 or 1 (a path that only delivers 2 values must
    be treated as digital)."""
    return all(s <= eps or s >= 1.0 - eps for s in samples)


class RawInput(object):
    """Normalised raw input for one tick (what the adapter hands over)."""
    __slots__ = ("steer", "throttle", "brake", "steer_analog", "throttle_analog", "brake_analog")

    def __init__(self, steer=0.0, throttle=0.0, brake=0.0,
                 steer_analog=True, throttle_analog=True, brake_analog=True):
        self.steer = steer
        self.throttle = throttle
        self.brake = brake
        self.steer_analog = steer_analog
        self.throttle_analog = throttle_analog
        self.brake_analog = brake_analog


# --------------------------------------------------------------------------------------------
class InputAssist(object):
    """One instance per human-driven car.

    levels : dict item -> stage 0..4 (missing items come from the preset)
    preset : "analog" / "digital"
    assist_on : brake lock prevention + drive limiter (the game's ASSIST ON/OFF)
    Every resolved number is a plain attribute, so experiments can overwrite them.
    """

    def __init__(self, levels=None, preset="analog", assist_on=True, config=None):
        cfg = validate_config(config if config is not None else DEFAULT_CONFIG)
        if preset not in cfg["presets"]:
            raise AssistConfigError("unknown preset: %r" % (preset,))
        lv = dict(cfg["presets"][preset])
        if levels:
            lv.update(check_levels(levels))
        self.levels = lv
        self.assist_on = bool(assist_on)
        for name in ITEM_ORDER:
            for key, tab in cfg["items"][name]["values"].items():
                setattr(self, key, float(tab[lv[name]]))
        for key, v in cfg["fixed"].items():
            setattr(self, key, v)
        self.reset()

    def reset(self):
        self.thr = 0.0            # shaped + rate limited pedal amounts (before the assists)
        self.brk = 0.0
        self.thr_out = 0.0        # what was sent to the car last tick
        self.brk_out = 0.0
        self.thr_cap = 1.0
        self.brk_cap = 1.0
        self.hold_dir = 0         # digital steer: direction currently held and for how long
        self.hold_t = 0.0
        self.slide = 0.0          # filtered countersteer relaxation 0..1
        self.steer_rate_scale = 1.0
        # debug / HUD outputs
        self.limit = 0.0          # current steer limit (rad) after the relaxation
        self.limit_base = 0.0     # speed-dependent limit before the relaxation
        self.counter = False
        self.clipped = False
        self.abs_active = False
        self.tcs_active = False
        self.target = 0.0

    # ------------------------------------------------------------------------------------
    def base_limit(self, car, mu=1.0):
        v = car.vx if car.vx >= 0.0 else -car.vx
        ms = car.max_steer
        mode = self.limit_mode
        if mode == "physics":
            m = mu if mu > self.limit_mu_min else self.limit_mu_min
            return speed_limit_physics(v, car.L, atan(1.0 / car.tap_inv), ms, self.limit_km,
                                       self.limit_ka, m * car.mu_tire * G)
        if mode == "simple":
            return speed_limit_simple(v, ms, self.simple_v0, self.simple_floor)
        return ms

    def step(self, steer, throttle, brake, car, steer_analog=True, throttle_analog=True,
             brake_analog=True, mu=1.0, dt=DT):
        """Returns (steer_cmd_rad, throttle, brake) for car.step()."""
        # ================= steering ======================================================
        if steer_analog:
            y = curve_cubic(apply_deadzone(steer, self.steer_dz, self.steer_sat), self.steer_k)
            d = 0
        else:
            d = 1 if steer > 0.5 else (-1 if steer < -0.5 else 0)
            y = d * self.dig_limit_frac
        ms = car.max_steer
        vx = car.vx
        v = vx if vx >= 0.0 else -vx
        ap = atan(1.0 / car.tap_inv)                 # slip angle of maximum grip (rad)
        lim = self.base_limit(car, mu)
        self.limit_base = lim

        # ---- countersteer: rear axle sliding and the input points the way the tail goes ----
        den = v if v > 1.0 else 1.0
        bf = atan2(car.vy + car.a * car.yaw_rate, den)      # travel direction of the front axle
        br = atan2(car.vy - car.b * car.yaw_rate, den)      # ... of the rear axle (<0: tail goes right)
        raw_slide = 0.0
        if v > self.cs_v_min and vx > 0.0 and self.cs_gain > 0.0:
            syr = tan(br if br >= 0.0 else -br) * car.tap_inv
            beta = car.body_slip
            if (beta if beta >= 0.0 else -beta) > self.cs_beta_min_deg * 0.017453292519943295 \
                    and beta * br > 0.0:
                raw_slide = (syr - self.cs_slide0) / (self.cs_slide1 - self.cs_slide0)
                if raw_slide < 0.0:
                    raw_slide = 0.0
                elif raw_slide > 1.0:
                    raw_slide = 1.0
        sl = self.slide
        if raw_slide >= sl:
            sl = raw_slide
        else:
            sl += (raw_slide - sl) * (dt / self.cs_hold_t if dt < self.cs_hold_t else 1.0)
        self.slide = sl
        counter = sl > 0.0 and y * br > 0.0
        self.counter = counter
        rate_mul = 1.0
        if counter:
            # angle that points the front wheels along their own travel direction + allowance
            abf = bf if bf >= 0.0 else -bf
            lim_cs = (abf if bf * br > 0.0 else 0.0) + self.cs_km * ap
            if lim_cs > ms:
                lim_cs = ms
            if lim_cs > lim:
                lim += self.cs_gain * sl * (lim_cs - lim)
            rate_mul = 1.0 + (self.cs_rate - 1.0) * sl
        self.limit = lim
        # how much faster than its normal rate the car's own steering actuator should be allowed
        # to move this tick (the vehicle model limits the rate itself; see the report)
        self.steer_rate_scale = rate_mul

        target = y * lim

        # ---- slip-angle window: never ask the front tyres for much more than their peak ----
        clipped = False
        if self.clip_on and v > self.clip_v0 and vx > 0.0:
            w = self.clip_k * ap
            if v < self.clip_v1:
                w += (ms - w) * (self.clip_v1 - v) / (self.clip_v1 - self.clip_v0)
            hi = bf + w
            lo = bf - w
            if target > 0.0:
                if hi < 0.0:
                    hi = 0.0
                if target > hi:
                    target = hi
                    clipped = True
            elif target < 0.0:
                if lo > 0.0:
                    lo = 0.0
                if target < lo:
                    target = lo
                    clipped = True
        self.clipped = clipped
        self.target = target

        # ---- rate limit, measured from the wheel's real position (no wind-up) --------------
        cur = car.steer
        acur = cur if cur >= 0.0 else -cur
        span = lim if lim > acur else acur          # rate is "fraction of the range per second"
        if steer_analog:
            rate = span / self.ana_t_full
        else:
            if d != self.hold_dir:
                self.hold_dir = d
                self.hold_t = 0.0
            else:
                self.hold_t += dt
            if d == 0 or cur * d < 0.0:
                rate = span / self.dig_t_return          # released, or still on the wrong side
            else:
                # progressive: slow at key-down (a tap gives a small angle), full rate later.
                # mean rate over dig_t_full is exactly 1/dig_t_full.
                r0 = self.dig_rate_start
                tr = self.dig_ramp_t * self.dig_t_full
                r1 = (1.0 - r0 * self.dig_ramp_t * 0.5) / (1.0 - self.dig_ramp_t * 0.5)
                f = self.hold_t / tr if self.hold_t < tr else 1.0
                rate = span / self.dig_t_full * (r0 + (r1 - r0) * f)
        rate *= rate_mul
        stepmax = rate * dt
        dlt = target - cur
        if dlt > stepmax:
            dlt = stepmax
        elif dlt < -stepmax:
            dlt = -stepmax
        cmd = cur + dlt

        # ================= pedals ========================================================
        fx_dz = self.pedal_dz
        if throttle_analog:
            t_in = curve_cubic(apply_deadzone(throttle, fx_dz, self.pedal_sat), self.throttle_k)
            up = dn = dt / self.pedal_ana_t
        else:
            t_in = 1.0 if throttle > 0.5 else 0.0
            up = dt / self.thr_t_up
            dn = dt / self.thr_t_down
        t = self.thr
        if t_in > t:
            t = t + up if t + up < t_in else t_in
        else:
            t = t - dn if t - dn > t_in else t_in
        self.thr = t

        if brake_analog:
            b_in = curve_cubic(apply_deadzone(brake, fx_dz, self.pedal_sat), self.brake_k)
            up = dn = dt / self.pedal_ana_t
        else:
            b_in = 1.0 if brake > 0.5 else 0.0
            up = dt / self.brk_t_up
            dn = dt / self.brk_t_down
        b = self.brk
        if b_in > b:
            b = b + up if b + up < b_in else b_in
        else:
            b = b - dn if b - dn > b_in else b_in
        self.brk = b

        t_out = t
        b_out = b
        self.abs_active = False
        self.tcs_active = False
        if self.assist_on:
            ws = car.wheel_sy
            wu = car.wheel_util
            syf = max(ws[0] if ws[0] >= 0.0 else -ws[0], ws[1] if ws[1] >= 0.0 else -ws[1])
            syr2 = max(ws[2] if ws[2] >= 0.0 else -ws[2], ws[3] if ws[3] >= 0.0 else -ws[3])
            # ---- brake: keep every wheel short of locking; a rear axle that is sliding sideways
            #      is allowed much less brake force (keeps the tail in on corner entry) ----------
            s0 = self.tcs_sy0
            s1 = self.tcs_sy1
            fr_ = (syr2 - s0) / (s1 - s0)
            fr_ = 0.0 if fr_ < 0.0 else (1.0 if fr_ > 1.0 else fr_)
            tgt_f = self.abs_target - (self.abs_target - self.abs_target_turn) * (syf if syf < 1.0 else 1.0)
            tgt_r = self.abs_target - (self.abs_target - self.abs_u_lo_rear) * fr_
            uf = -(wu[0] if wu[0] < wu[1] else wu[1])
            ur = -(wu[2] if wu[2] < wu[3] else wu[3])
            bratio = uf / tgt_f
            if ur / tgt_r > bratio:
                bratio = ur / tgt_r
            cap = self.brk_cap
            if bratio > 1.0 and self.brk_out > 0.0:
                cap = self.brk_out / bratio            # brake demand is proportional to the pedal
                if cap < self.abs_min:
                    cap = self.abs_min
            else:
                cap += self.abs_recover * dt
                if cap > 1.0:
                    cap = 1.0
            self.brk_cap = cap
            if b_out > cap:
                b_out = cap
                self.abs_active = True
            # ---- throttle: per driven axle, allowed u falls as the axle uses up its side grip --
            fd = car.front_drive
            ratio = 0.0
            hi = self.tcs_u_hi
            if fd > 0.0:
                f = (syf - s0) / (s1 - s0)
                f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
                ut = hi - (hi - self.tcs_u_lo_front) * f
                u = wu[0] if wu[0] > wu[1] else wu[1]
                if u / ut > ratio:
                    ratio = u / ut
            if fd < 1.0:
                f = (syr2 - s0) / (s1 - s0)
                f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
                ut = hi - (hi - self.tcs_u_lo_rear) * f
                u = wu[2] if wu[2] > wu[3] else wu[3]
                if u / ut > ratio:
                    ratio = u / ut
            cap = self.thr_cap
            if ratio > 1.0 and self.thr_out > 0.0:
                cap = self.thr_out / ratio
                if cap < self.tcs_min:
                    cap = self.tcs_min
            else:
                cap += self.tcs_recover * dt
                if cap > 1.0:
                    cap = 1.0
            self.thr_cap = cap
            if t_out > cap:
                t_out = cap
                self.tcs_active = True
            # ---- engine-drag control ----------------------------------------------------------
            if self.coast_thr > 0.0 and b_out < 0.02 and v > self.coast_v_min:
                f = (syr2 - self.coast_sy0) / (self.coast_sy1 - self.coast_sy0)
                f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
                if t_out < self.coast_thr * f:
                    t_out = self.coast_thr * f
        self.thr_out = t_out
        self.brk_out = b_out
        return cmd, t_out, b_out

    def step_raw(self, raw, car, mu=1.0, dt=DT):
        return self.step(raw.steer, raw.throttle, raw.brake, car, raw.steer_analog,
                         raw.throttle_analog, raw.brake_analog, mu, dt)


class PassThrough(object):
    """Baseline without any compensation: stick -> max_steer * stick, pedals untouched.
    (The car still applies its own steering rate and lock.)"""

    def __init__(self):
        self.limit = 0.0
        self.counter = False
        self.abs_active = False
        self.tcs_active = False
        self.slide = 0.0

    def reset(self):
        pass

    def step(self, steer, throttle, brake, car, steer_analog=True, throttle_analog=True,
             brake_analog=True, mu=1.0, dt=DT):
        self.limit = car.max_steer
        return steer * car.max_steer, throttle, brake


if __name__ == "__main__":
    import os
    import sys
    if "--dump" in sys.argv:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assist_config.json")
        with open(out, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=1)
        load_config(out)
        print("wrote", out)
