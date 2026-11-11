"""CLIPPING POINT vehicle model spike (pure Python, standard library only, no pyxel).

Conventions (shared with the course / input-assist spikes)
  plane (x, z), height y up.  heading 0 = +x, +pi/2 = +z  (heading = atan2(dz, dx)).
  "left" = the side heading turns to when it increases: left unit vector = (-sin h, cos h).
  units m, s, rad, kg, N.  fixed step dt = 1/60.
  steer > 0 = left, vy > 0 = moving left, yaw_rate > 0 = turning left.

Formulation (see the spike report for the reasons)
  * 3 DOF body (world velocity vX, vZ and yaw rate), 4 tyres, NO wheel-rotation DOF.
  * Drive / brake force is a *demand* per wheel; the tyre clips it at mu*Fz (quasi-static).
    u = demand / (mu*Fz) is the "slip-ratio equivalent": |u| < 1 grip, u > 1 wheelspin, u < -1 lock.
  * Lateral force = mu*Fz * ky(u) * sin(C*atan(B*sy)),  sy = tan(alpha)/tan(alpha_peak)
    (peak at sy = 1, falls to ~0.81 beyond the limit).  ky(u) = friction-ellipse factor.
  * Low speed: slip uses max(|v_long|, v_reg) and every tyre force is clamped to the force that
    would stop that contact patch within one substep (semi-implicit "stopping force" clamp).
  * Load transfer from low-pass filtered body accelerations (time constant = suspension).
  * Semi-implicit Euler in world frame, `substeps` inner steps per tick.

ALL NUMBERS IN THIS FILE ARE PROVISIONAL ("kari no atai").
"""
from math import sin, cos, atan, atan2, sqrt, tan, pi, hypot

G = 9.81
RHO = 1.2
PS_TO_W = 735.5
DT = 1.0 / 60.0

# ---- tyre curve constants (provisional) --------------------------------------------------
MF_C = 1.40                         # shape; sin(C*pi/2) = 0.81 = force far beyond the limit
MF_B = tan(pi / (2.0 * MF_C))       # puts the peak at sy = 1
CU2 = 0.94                          # ellipse: ky = sqrt(1 - CU2*u^2)  (ky = 0.245 at |u| = 1)
KY1 = sqrt(1.0 - CU2)
K_SPIN = 4.0                        # ky beyond |u| = 1: KY1 / (1 + K_SPIN*(|u|-1))
G_SLIDE = 0.85                      # longitudinal force of a spinning / locked wheel (x mu*Fz)
E_FULL_INV = 2.0                    # ... reached when demand exceeds the limit by 50 %
K_LOAD = 0.15                       # load sensitivity: mu *= 1 - K_LOAD*(Fz/Fz0 - 1)
C_RR = 0.014                        # rolling resistance coefficient

# ---- setup stages: signed offset from the centre (0 = standard) ---------------------------
SETUP_RANGE = {"gear": 2, "wing": 2, "suspension": 2, "brake_bias": 2, "traction": 2, "steering": 1}
GEAR_FINAL_SCALE = (1.12, 1.06, 1.00, 0.94, 0.88)      # -2 accel ... +2 top speed
LSD_LOCK = (0.10, 0.25, 0.40, 0.60, 0.80)              # -2 rotation ... +2 traction
STEER_RATE = (0.7, 1.0, 1.4)                           # rad/s at the road wheel, mild..quick
BRAKE_BIAS_STEP = 0.03                                 # front share: -2 -> +0.06, +2 -> -0.06
SUS_TAU = (0.20, 0.17, 0.14, 0.11, 0.08)               # load-transfer time constant, soft..hard
SUS_ALPHA_SCALE = (1.12, 1.06, 1.00, 0.94, 0.88)       # peak slip angle scale, soft..hard
SUS_GRIP = (0.98, 0.99, 1.00, 1.01, 1.02)              # smooth-road grip, soft..hard
SUS_BUMP_LOSS = (0.10, 0.15, 0.20, 0.25, 0.30)         # grip loss at bump = 1, soft..hard
WING_CDA_STEP = 0.02                                   # CdA per wing stage
WING_BALANCE_STEP = 0.04                               # aero front share moves rearward per stage

ALPHA_PEAK_DEG = 7.5
MAX_STEER = 0.55                    # rad at the road wheel (about 31.5 deg)

# ---- provisional car table ----------------------------------------------------------------
CAR_SPECS = {
    "tsubame": {   # FF 165 ps 1,040 kg  class B  (stable / understeer)
        "name": "TSUBAME 1600", "drive": "FF", "front_drive": 1.0,
        "mass": 1040.0, "power_ps": 165.0, "wheelbase": 2.57, "track": 1.47,
        "front_weight": 0.62, "cg_height": 0.50, "yaw_k": 1.00, "wheel_radius": 0.298,
        "gears": (3.230, 2.105, 1.458, 1.107, 0.930), "reverse": 3.0, "final": 4.40,
        "idle": 900.0, "redline": 8200.0, "shift_rpm": 8000.0, "launch_rpm": 5000.0,
        "torque_curve": ((1000, 0.70), (3000, 0.82), (5000, 0.90), (5800, 0.98), (7000, 1.00),
                         (7600, 0.97), (8200, 0.88)),
        "turbo": None, "drive_eff": 0.90,
        "cda": 0.60, "cla": 0.30, "wing_step": 0.15, "aero_front": 0.42,
        "mu": 1.00, "grip_front": 1.00, "grip_rear": 1.00, "roll_front": 0.66, "brake_g": 1.25,
    },
    "kazane": {    # FR 145 ps 960 kg  class B  (light / honest)
        "name": "KAZANE RS", "drive": "FR", "front_drive": 0.0,
        "mass": 960.0, "power_ps": 145.0, "wheelbase": 2.27, "track": 1.42,
        "front_weight": 0.51, "cg_height": 0.46, "yaw_k": 0.95, "wheel_radius": 0.290,
        "gears": (3.136, 1.888, 1.330, 1.000, 0.860), "reverse": 3.0, "final": 4.30,
        "idle": 850.0, "redline": 7200.0, "shift_rpm": 7000.0, "launch_rpm": 4500.0,
        "torque_curve": ((1000, 0.72), (2500, 0.88), (4500, 1.00), (5500, 0.98), (6500, 0.90),
                         (7200, 0.78)),
        "turbo": None, "drive_eff": 0.90,
        "cda": 0.62, "cla": 0.30, "wing_step": 0.15, "aero_front": 0.42,
        "mu": 1.00, "grip_front": 1.00, "grip_rear": 1.00, "roll_front": 0.53, "brake_g": 1.25,
    },
    "shirogane": {  # FR 280 ps 1,340 kg  class A  (turbo, rear steps out on exit)
        "name": "SHIROGANE GT-T", "drive": "FR", "front_drive": 0.0,
        "mass": 1340.0, "power_ps": 280.0, "wheelbase": 2.67, "track": 1.49,
        "front_weight": 0.54, "cg_height": 0.50, "yaw_k": 1.00, "wheel_radius": 0.317,
        "gears": (3.214, 1.925, 1.302, 1.000, 0.817), "reverse": 3.0, "final": 4.111,
        "idle": 850.0, "redline": 7200.0, "shift_rpm": 6900.0, "launch_rpm": 4500.0,
        "torque_curve": ((1000, 0.45), (2000, 0.70), (3200, 1.00), (4800, 1.00), (6400, 0.86),
                         (7200, 0.72)),
        "turbo": {"base": 0.55, "lag_up": 0.55, "lag_down": 0.30, "spool": (2200.0, 3800.0)},
        "drive_eff": 0.89,
        "cda": 0.68, "cla": 0.45, "wing_step": 0.20, "aero_front": 0.42,
        "mu": 1.05, "grip_front": 1.00, "grip_rear": 1.02, "roll_front": 0.57, "brake_g": 1.30,
    },
    "arashi": {    # 4WD 280 ps 1,390 kg  class A  (turbo, best traction, heavy)
        "name": "ARASHI 4T", "drive": "4WD", "front_drive": 0.40,
        "mass": 1390.0, "power_ps": 280.0, "wheelbase": 2.51, "track": 1.51,
        "front_weight": 0.59, "cg_height": 0.52, "yaw_k": 1.00, "wheel_radius": 0.315,
        "gears": (2.785, 1.950, 1.407, 1.031, 0.761), "reverse": 3.0, "final": 4.529,
        "idle": 900.0, "redline": 7200.0, "shift_rpm": 6900.0, "launch_rpm": 5500.0,
        "torque_curve": ((1000, 0.40), (2000, 0.62), (3000, 1.00), (5000, 0.97), (6500, 0.82),
                         (7200, 0.68)),
        "turbo": {"base": 0.50, "lag_up": 0.65, "lag_down": 0.30, "spool": (2500.0, 4000.0)},
        "drive_eff": 0.86,
        "cda": 0.74, "cla": 0.45, "wing_step": 0.20, "aero_front": 0.42,
        "mu": 1.05, "grip_front": 1.00, "grip_rear": 1.00, "roll_front": 0.62, "brake_g": 1.30,
    },
    # Not part of the first release: only here to show that MR is the same formula.
    "mikazuki": {  # MR 240 ps 1,180 kg
        "name": "MIKAZUKI", "drive": "MR", "front_drive": 0.0,
        "mass": 1180.0, "power_ps": 240.0, "wheelbase": 2.45, "track": 1.50,
        "front_weight": 0.43, "cg_height": 0.45, "yaw_k": 0.85, "wheel_radius": 0.310,
        "gears": (3.166, 1.904, 1.392, 1.031, 0.815), "reverse": 3.0, "final": 4.20,
        "idle": 900.0, "redline": 7800.0, "shift_rpm": 7600.0, "launch_rpm": 5000.0,
        "torque_curve": ((1000, 0.70), (3000, 0.86), (5000, 0.98), (6000, 1.00), (7200, 0.95),
                         (7800, 0.85)),
        "turbo": None, "drive_eff": 0.90,
        "cda": 0.62, "cla": 0.45, "wing_step": 0.20, "aero_front": 0.40,
        "mu": 1.05, "grip_front": 1.00, "grip_rear": 1.04, "roll_front": 0.50, "brake_g": 1.30,
    },
}

RPM_STEP = 25.0


def _curve(points, rpm):
    if rpm <= points[0][0]:
        return points[0][1]
    for i in range(1, len(points)):
        r1, t1 = points[i]
        if rpm <= r1:
            r0, t0 = points[i - 1]
            return t0 + (t1 - t0) * (rpm - r0) / (r1 - r0)
    return points[-1][1]


def _tire(vlong, vlat, fmax, fdrv, fbrk, mh, tap_inv, v_reg):
    """One tyre in its own frame.  Returns (fx, fy, sy, u).

    vlong / vlat : contact patch velocity along / across the wheel plane (m/s)
    fmax         : mu * Fz (N)
    fdrv         : signed drive demand (N), fbrk: brake demand (N >= 0, opposes rolling)
    mh           : (mass carried by this wheel) / substep  -> stopping-force clamp
    tap_inv      : 1 / tan(alpha_peak)
    """
    if fmax < 1.0:
        return 0.0, 0.0, 0.0, 0.0
    av = vlong if vlong >= 0.0 else -vlong
    if fbrk > 0.0:
        lim = mh * av                      # a brake cannot reverse the wheel within the step
        if fbrk > lim:
            fbrk = lim
        fxc = fdrv - fbrk if vlong > 0.0 else fdrv + fbrk
    else:
        fxc = fdrv
    u = fxc / fmax
    au = u if u >= 0.0 else -u
    if au <= 1.0:
        fx = fxc
        ky = sqrt(1.0 - CU2 * au * au)
    else:
        e = au - 1.0
        drop = e * E_FULL_INV
        if drop > 1.0:
            drop = 1.0
        fx = fmax * (1.0 - (1.0 - G_SLIDE) * drop)
        if u < 0.0:
            fx = -fx
        ky = KY1 / (1.0 + K_SPIN * e)
    sy = vlat / (av if av > v_reg else v_reg) * tap_inv
    asy = sy if sy >= 0.0 else -sy
    fy = fmax * ky * sin(MF_C * atan(MF_B * asy))
    lim = mh * (vlat if vlat >= 0.0 else -vlat)   # cannot reverse the lateral slip within the step
    if fy > lim:
        fy = lim
    if vlat > 0.0:
        fy = -fy
    return fx, fy, sy, u


class Car:
    """4-wheel car (lite=False) or 2-wheel "bicycle" car for AI (lite=True)."""

    def __init__(self, car_id, setup=None, lite=False, substeps=2):
        if car_id not in CAR_SPECS:
            raise ValueError("unknown car_id: %r" % (car_id,))
        s = CAR_SPECS[car_id]
        st = {k: 0 for k in SETUP_RANGE}
        if setup:
            for k, v in setup.items():
                if k not in SETUP_RANGE:
                    raise ValueError("unknown setup item: %r" % (k,))
                if not isinstance(v, int) or abs(v) > SETUP_RANGE[k]:
                    raise ValueError("setup %s out of range: %r" % (k, v))
                st[k] = v
        self.car_id = car_id
        self.spec = s
        self.setup = st
        self.lite = lite
        self.substeps = substeps
        self.v_reg = 0.5            # low-speed regularisation of the slip angle (m/s)
        self.stop_clamp = 1.0       # 1.0 = stopping-force clamp on, 0 = off (experiments)
        self.auto = True            # AT; set False for MT and call shift()

        m = s["mass"]
        L = s["wheelbase"]
        self.m = m
        self.L = L
        self.a = L * (1.0 - s["front_weight"])      # CG -> front axle
        self.b = L * s["front_weight"]              # CG -> rear axle
        self.tw = s["track"]
        self.h = s["cg_height"]
        self.iz = m * self.a * self.b * s["yaw_k"]
        self.wf = m * G * self.b / L * 0.5          # static load per front wheel
        self.wr = m * G * self.a / L * 0.5
        self.front_drive = s["front_drive"]
        self.mu_tire = s["mu"]
        self.grip_f = s["grip_front"]
        self.grip_r = s["grip_rear"]
        self.rsf = s["roll_front"]
        self.max_steer = MAX_STEER

        # --- setup mapping ---------------------------------------------------------------
        gi = st["gear"] + 2
        self.final = s["final"] * GEAR_FINAL_SCALE[gi]
        wi = st["wing"]
        self.cla = max(0.0, s["cla"] + wi * s["wing_step"])
        self.cda = s["cda"] + wi * WING_CDA_STEP
        self.aero_front = s["aero_front"] - wi * WING_BALANCE_STEP
        si = st["suspension"] + 2
        self.tau_load = SUS_TAU[si]
        self.tap_inv = 1.0 / tan(ALPHA_PEAK_DEG * pi / 180.0 * SUS_ALPHA_SCALE[si])
        self.sus_grip = SUS_GRIP[si]
        self.bump_loss = SUS_BUMP_LOSS[si]
        # brake: centre = ideal distribution at 1.0 g + 0.02 (fronts lock first on asphalt)
        self.brake_front = min(0.95, max(0.3, s["front_weight"] + self.h / L + 0.02
                                         - st["brake_bias"] * BRAKE_BIAS_STEP))
        self.brake_force = s["brake_g"] * m * G     # total brake demand at pedal = 1 (N)
        self.lsd_lock = LSD_LOCK[st["traction"] + 2]
        self.lsd_kc = 4000.0        # N per (m/s) of left/right wheel speed difference
        self.lsd_pre = 300.0        # N preload
        self.lsd_ramp = 0.25        # coupling limit grows with |axle drive force|
        self.steer_rate = STEER_RATE[st["steering"] + 1]

        # --- engine / driveline ----------------------------------------------------------
        self.idle = s["idle"]
        self.redline = s["redline"]
        self.shift_rpm = s["shift_rpm"]
        # AT downshift when the rpm in the lower gear would be below this (2nd -> 1st much later:
        # with 0.90 the AT sat in 1st at 53 km/h and every FR car spun on full throttle)
        self.down_rpm = s["shift_rpm"] * 0.75
        self.down_rpm_first = s["shift_rpm"] * 0.55
        self.launch_rpm = s["launch_rpm"]
        self.shift_time = 0.20
        self.n_gears = len(s["gears"])
        # total ratio by gear index: [unused, 1st..nth, reverse]  (gear -1 -> last entry)
        self.gear_total = [0.0] + [g * self.final for g in s["gears"]] + [-s["reverse"] * self.final]
        self.rw = s["wheel_radius"]
        self.rpm_per_ms = 30.0 / pi / self.rw
        self.eff = s["drive_eff"]
        pts = s["torque_curve"]
        n = int((self.redline + 1000.0) / RPM_STEP) + 2
        shape = [_curve(pts, i * RPM_STEP) for i in range(n)]
        pmax = max(shape[i] * i * RPM_STEP for i in range(int(self.redline / RPM_STEP) + 1))
        scale = s["power_ps"] * PS_TO_W / (pmax * 2.0 * pi / 60.0)
        self.torque_table = [scale * v for v in shape]
        self.torque_peak = max(self.torque_table)
        self.eb_k = 0.18 * self.torque_peak / self.redline   # engine braking Nm per rpm
        self.turbo = s["turbo"]

        self.reset(0.0, 0.0, 0.0, 0.0)

    # ------------------------------------------------------------------------------------
    def reset(self, x, z, heading, speed=0.0):
        self.x = float(x)
        self.z = float(z)
        self.heading = float(heading)
        self.wvx = speed * cos(heading)     # world velocity
        self.wvz = speed * sin(heading)
        self.vx = float(speed)
        self.vy = 0.0
        self.yaw_rate = 0.0
        self.speed = abs(float(speed))
        self.steer = 0.0
        self.axf = 0.0                      # filtered body accelerations (load transfer)
        self.ayf = 0.0
        self.ax = 0.0
        self.ay = 0.0
        self.boost = 0.0
        self.shift_t = 0.0
        self.gear = 1
        if self.auto and speed > 0.0:
            g = 1
            while g < self.n_gears and speed * self.rpm_per_ms * self.gear_total[g] > (
                    self.down_rpm if g > 1 else self.down_rpm_first):
                g += 1
            self.gear = g
        self.rpm = max(self.idle, abs(speed) * self.rpm_per_ms * self.gear_total[self.gear])
        self.slip_front = 0.0
        self.slip_rear = 0.0
        self.body_slip = 0.0
        self.wheel_load = [self.wf, self.wf, self.wr, self.wr]     # FL, FR, RL, RR
        self.wheel_util = [0.0, 0.0, 0.0, 0.0]   # u per wheel: >1 wheelspin, <-1 lock
        self.wheel_sy = [0.0, 0.0, 0.0, 0.0]     # normalised lateral slip per wheel (|sy|>1 past peak)
        self.on_limit = False
        self.drive_util = 0.0       # max u over driven wheels (first wheel to spin, usually the inner one)
        self.drive_util_axle = 0.0  # max over driven axles of (axle demand / axle mu*Fz): traction-control quantity
        self.brake_util = 0.0       # max -u over all wheels (ABS quantity)
        self.yaw_ref = 0.0          # neutral-steer yaw rate for the current steer and speed
        self.yaw_err = 0.0          # yaw_rate - yaw_ref  (>0 while steering left = oversteer)
        self.drive_force = 0.0

    def shift(self, d):
        """MT shift request: +1 up, -1 down.  1st -> reverse only when almost stopped."""
        g = self.gear
        if d > 0:
            if g == -1:
                ng = 1
            elif g < self.n_gears:
                ng = g + 1
            else:
                return False
        else:
            if g == -1:
                return False
            if g > 1:
                ng = g - 1
            elif abs(self.vx) < 1.0:
                ng = -1
            else:
                return False
        self.gear = ng
        self.shift_t = self.shift_time
        return True

    # ------------------------------------------------------------------------------------
    def step(self, steer_rad, throttle, brake, mu=1.0, dt=DT, bump=0.0):
        if throttle < 0.0:
            throttle = 0.0
        elif throttle > 1.0:
            throttle = 1.0
        if brake < 0.0:
            brake = 0.0
        elif brake > 1.0:
            brake = 1.0

        # ---- steering actuator: lock + rate limit (car-side "steering" setup) -------------
        ms = self.max_steer
        if steer_rad > ms:
            steer_rad = ms
        elif steer_rad < -ms:
            steer_rad = -ms
        d = steer_rad - self.steer
        lim = self.steer_rate * dt
        if d > lim:
            d = lim
        elif d < -lim:
            d = -lim
        steer = self.steer + d
        self.steer = steer
        cd = cos(steer)
        sd = sin(steer)

        # ---- driveline, once per tick ----------------------------------------------------
        gear = self.gear
        gt = self.gear_total
        ratio = gt[gear]
        avx = self.vx if self.vx >= 0.0 else -self.vx
        rpm_w = avx * self.rpm_per_ms * (ratio if ratio >= 0.0 else -ratio)
        engaged = True
        if self.shift_t > 0.0:
            self.shift_t -= dt
            engaged = False
        elif self.auto and gear >= 1:
            if rpm_w > self.shift_rpm and gear < self.n_gears:
                gear += 1
                self.gear = gear
                self.shift_t = self.shift_time
                engaged = False
            elif gear > 1 and rpm_w * gt[gear - 1] / ratio < (self.down_rpm if gear > 2 else self.down_rpm_first):
                gear -= 1
                self.gear = gear
                self.shift_t = self.shift_time
                engaged = False
            if not engaged:
                ratio = gt[gear]
                rpm_w = avx * self.rpm_per_ms * ratio
        clutch_rpm = self.idle + throttle * (self.launch_rpm - self.idle)
        if rpm_w < clutch_rpm:          # slipping clutch (launch / too low rpm)
            rpm_e = clutch_rpm
            slipping = True
        else:
            rpm_e = rpm_w
            slipping = False
        tq = self.torque_table[int(rpm_e / RPM_STEP)] if rpm_e < self.redline else 0.0
        tb = self.turbo
        if tb is not None:
            lo, hi = tb["spool"]
            sp = (rpm_e - lo) / (hi - lo)
            if sp < 0.0:
                sp = 0.0
            elif sp > 1.0:
                sp = 1.0
            target = throttle * sp if engaged else 0.0
            bo = self.boost
            bo += (target - bo) * dt / (tb["lag_up"] if target > bo else tb["lag_down"])
            self.boost = bo
            tq *= tb["base"] + (1.0 - tb["base"]) * bo
        tq *= throttle
        if not slipping:
            tq -= (1.0 - throttle) * self.eb_k * rpm_e      # engine braking
        fdrive = tq * ratio * self.eff / self.rw if engaged else 0.0
        self.drive_force = fdrive
        self.rpm += (rpm_e - self.rpm) * (dt / 0.06 if dt < 0.06 else 1.0)

        # ---- locals ----------------------------------------------------------------------
        m = self.m
        a = self.a
        b = self.b
        htw = self.tw * 0.5
        iz = self.iz
        wf = self.wf
        wr = self.wr
        v_reg = self.v_reg
        tap_inv = self.tap_inv
        nsub = self.substeps
        h = dt / nsub
        kf = self.tau_load
        kf = h / kf if h < kf else 1.0
        mu_base = mu * self.mu_tire * self.sus_grip * (1.0 - bump * self.bump_loss)
        mu_f = mu_base * self.grip_f
        mu_r = mu_base * self.grip_r
        fb_f = brake * self.brake_force * self.brake_front * 0.5     # per wheel
        fb_r = brake * self.brake_force * (1.0 - self.brake_front) * 0.5
        fd_f = fdrive * self.front_drive                            # per axle
        fd_r = fdrive - fd_f
        lock = self.lsd_lock
        lock2 = 2.0 * lock - 1.0
        kc = self.lsd_kc
        lsd_pre = self.lsd_pre
        lsd_ramp = self.lsd_ramp
        clamp = self.stop_clamp
        big = 1e30
        mh_f = (m * b / self.L * 0.5 / h) * clamp if clamp > 0.0 else big
        mh_r = (m * a / self.L * 0.5 / h) * clamp if clamp > 0.0 else big
        mh_all = m / h
        qd = 0.5 * RHO * self.cda
        ql = 0.5 * RHO * self.cla
        af = self.aero_front
        k_long = m * self.h / self.L * 0.5         # per wheel, per (m/s^2)
        k_latf = m * self.h / self.tw * self.rsf
        k_latr = m * self.h / self.tw * (1.0 - self.rsf)
        f_roll = C_RR * m * G

        x = self.x
        z = self.z
        hd = self.heading
        wvx = self.wvx
        wvz = self.wvz
        r = self.yaw_rate
        axf = self.axf
        ayf = self.ayf
        lite = self.lite

        for _ in range(nsub):
            c = cos(hd)
            s = sin(hd)
            vx = wvx * c + wvz * s
            vy = wvz * c - wvx * s
            v2 = vx * vx + vy * vy
            dfl = ql * v2                      # downforce
            fzf = wf + dfl * af * 0.5
            fzr = wr + dfl * (1.0 - af) * 0.5
            dx = k_long * axf
            # contact patch velocities (body frame)
            vyf = vy + r * a
            vyr = vy - r * b
            if lite:
                # ---- 2-wheel model: one tyre per axle, no lateral load transfer, no diff ----
                f0 = 2.0 * (fzf - dx)
                f1 = 2.0 * (fzr + dx)
                if f0 < 0.0:
                    f0 = 0.0
                if f1 < 0.0:
                    f1 = 0.0
                m0 = mu_f * (1.0 + K_LOAD - K_LOAD * f0 / (2.0 * wf))
                m1 = mu_r * (1.0 + K_LOAD - K_LOAD * f1 / (2.0 * wr))
                fx0, fy0, sy0, u0 = _tire(vx * cd + vyf * sd, vyf * cd - vx * sd, m0 * f0,
                                          fd_f, 2.0 * fb_f, 2.0 * mh_f, tap_inv, v_reg)
                fx2, fy2, sy2, u2 = _tire(vx, vyr, m1 * f1, fd_r, 2.0 * fb_r, 2.0 * mh_r,
                                          tap_inv, v_reg)
                bx0 = fx0 * cd - fy0 * sd
                by0 = fx0 * sd + fy0 * cd
                fxs = bx0 + fx2
                fys = by0 + fy2
                mz = a * by0 - b * fy2
                f1 = f0 = f0 * 0.5
                f3 = f2 = (2.0 * (fzr + dx)) * 0.5 if fzr + dx > 0.0 else 0.0
                sy1 = sy0
                sy3 = sy2
                u1 = u0
                u3 = u2
            else:
                dyf = k_latf * ayf
                dyr = k_latr * ayf
                f0 = fzf - dx - dyf                # FL
                f1 = fzf - dx + dyf                # FR
                f2 = fzr + dx - dyr                # RL
                f3 = fzr + dx + dyr                # RR
                if f0 < 0.0:
                    f0 = 0.0
                if f1 < 0.0:
                    f1 = 0.0
                if f2 < 0.0:
                    f2 = 0.0
                if f3 < 0.0:
                    f3 = 0.0
                kl = K_LOAD / wf
                m0 = mu_f * (1.0 + K_LOAD - kl * f0) * f0
                m1 = mu_f * (1.0 + K_LOAD - kl * f1) * f1
                kl = K_LOAD / wr
                m2 = mu_r * (1.0 + K_LOAD - kl * f2) * f2
                m3 = mu_r * (1.0 + K_LOAD - kl * f3) * f3
                vxl = vx - r * htw
                vxr = vx + r * htw
                dv = r * htw * 2.0                 # right wheel speed - left wheel speed
                # ---- differential: split the axle demand left / right ------------------
                if fd_f != 0.0:
                    # (1) coupling: the faster wheel hands torque to the slower one
                    fc = lock * kc * dv
                    lim = lock * (lsd_pre + lsd_ramp * (fd_f if fd_f > 0.0 else -fd_f))
                    if fc > lim:
                        fc = lim
                    elif fc < -lim:
                        fc = -lim
                    c0 = 0.5 * fd_f + fc
                    c1 = 0.5 * fd_f - fc
                    # (2) a wheel asked for more than mu*Fz spins: open diff -> the other wheel
                    #     drops to the same torque, locked diff -> the other wheel takes the excess
                    e0 = c0 - m0
                    e1 = c1 - m1
                    if e0 > 0.0 and e0 >= e1:
                        c0 = m0 + (1.0 - lock) * e0
                        c1 += lock2 * e0
                    elif e1 > 0.0:
                        c1 = m1 + (1.0 - lock) * e1
                        c0 += lock2 * e1
                else:
                    c0 = c1 = 0.0
                if fd_r != 0.0:
                    fc = lock * kc * dv
                    lim = lock * (lsd_pre + lsd_ramp * (fd_r if fd_r > 0.0 else -fd_r))
                    if fc > lim:
                        fc = lim
                    elif fc < -lim:
                        fc = -lim
                    c2 = 0.5 * fd_r + fc
                    c3 = 0.5 * fd_r - fc
                    e0 = c2 - m2
                    e1 = c3 - m3
                    if e0 > 0.0 and e0 >= e1:
                        c2 = m2 + (1.0 - lock) * e0
                        c3 += lock2 * e0
                    elif e1 > 0.0:
                        c3 = m3 + (1.0 - lock) * e1
                        c2 += lock2 * e1
                else:
                    c2 = c3 = 0.0
                # ---- tyres ---------------------------------------------------------------
                fx0, fy0, sy0, u0 = _tire(vxl * cd + vyf * sd, vyf * cd - vxl * sd, m0, c0, fb_f,
                                          mh_f, tap_inv, v_reg)
                fx1, fy1, sy1, u1 = _tire(vxr * cd + vyf * sd, vyf * cd - vxr * sd, m1, c1, fb_f,
                                          mh_f, tap_inv, v_reg)
                fx2, fy2, sy2, u2 = _tire(vxl, vyr, m2, c2, fb_r, mh_r, tap_inv, v_reg)
                fx3, fy3, sy3, u3 = _tire(vxr, vyr, m3, c3, fb_r, mh_r, tap_inv, v_reg)
                bx0 = fx0 * cd - fy0 * sd
                by0 = fx0 * sd + fy0 * cd
                bx1 = fx1 * cd - fy1 * sd
                by1 = fx1 * sd + fy1 * cd
                fxs = bx0 + bx1 + fx2 + fx3
                fys = by0 + by1 + fy2 + fy3
                mz = a * (by0 + by1) - b * (fy2 + fy3) + htw * (bx1 - bx0 + fx3 - fx2)
            # ---- body resistances: aero drag + rolling (cannot reverse the car) ----------
            avx = vx if vx >= 0.0 else -vx
            fr = f_roll
            lim = mh_all * avx
            if fr > lim:
                fr = lim
            fr += qd * vx * vx
            if vx > 0.0:
                fxs -= fr
            else:
                fxs += fr
            ax = fxs / m                       # body-frame specific force
            ay = fys / m
            axf += (ax - axf) * kf
            ayf += (ay - ayf) * kf
            # ---- semi-implicit Euler in the world frame ----------------------------------
            wvx += (ax * c - ay * s) * h
            wvz += (ax * s + ay * c) * h
            r += mz / iz * h
            hd += r * h
            x += wvx * h
            z += wvz * h

        # ---- rest: snap to an exact standstill -------------------------------------------
        if throttle == 0.0 and wvx * wvx + wvz * wvz < 1e-4 and -0.01 < r < 0.01:
            wvx = 0.0
            wvz = 0.0
            r = 0.0
        if hd > pi:
            hd -= 2.0 * pi
        elif hd < -pi:
            hd += 2.0 * pi

        # ---- store state and derived outputs ---------------------------------------------
        self.x = x
        self.z = z
        self.heading = hd
        self.wvx = wvx
        self.wvz = wvz
        self.yaw_rate = r
        self.axf = axf
        self.ayf = ayf
        self.ax = ax
        self.ay = ay
        c = cos(hd)
        s = sin(hd)
        vx = wvx * c + wvz * s
        vy = wvz * c - wvx * s
        self.vx = vx
        self.vy = vy
        sp = sqrt(wvx * wvx + wvz * wvz)
        self.speed = sp
        avx = vx if vx >= 0.0 else -vx
        den = avx if avx > 1.0 else 1.0
        self.body_slip = atan2(vy, den) if sp > 0.3 else 0.0
        # axle slip angles (rad): >0 = contact patch moving to the left of the wheel plane
        self.slip_front = atan2((vy + r * a) * cd - vx * sd, max(1.0, abs(vx * cd + (vy + r * a) * sd))) if sp > 0.3 else 0.0
        self.slip_rear = atan2(vy - r * b, den) if sp > 0.3 else 0.0
        wl = self.wheel_load
        wl[0] = f0
        wl[1] = f1
        wl[2] = f2
        wl[3] = f3
        wu = self.wheel_util
        wu[0] = u0
        wu[1] = u1
        wu[2] = u2
        wu[3] = u3
        ws = self.wheel_sy
        ws[0] = sy0
        ws[1] = sy1
        ws[2] = sy2
        ws[3] = sy3
        fdv = self.front_drive
        du = 0.0
        if fdv > 0.0:
            du = u0 if u0 > u1 else u1
        if fdv < 1.0:
            t = u2 if u2 > u3 else u3
            if t > du:
                du = t
        self.drive_util = du if du > 0.0 else 0.0
        da = 0.0
        if not lite:
            if fd_f > 0.0 and m0 + m1 > 1.0:
                da = fd_f / (m0 + m1)
            if fd_r > 0.0 and m2 + m3 > 1.0:
                t = fd_r / (m2 + m3)
                if t > da:
                    da = t
        else:
            da = self.drive_util
        self.drive_util_axle = da
        bu = -min(u0, u1, u2, u3)
        self.brake_util = bu if bu > 0.0 else 0.0
        self.on_limit = sp > 1.0 and (
            u0 > 1.0 or u0 < -1.0 or u1 > 1.0 or u1 < -1.0 or u2 > 1.0 or u2 < -1.0
            or u3 > 1.0 or u3 < -1.0
            or sy0 > 1.0 or sy0 < -1.0 or sy1 > 1.0 or sy1 < -1.0
            or sy2 > 1.0 or sy2 < -1.0 or sy3 > 1.0 or sy3 < -1.0)
        # neutral-steer reference yaw rate, limited by what the surface can hold
        yr = vx * steer / self.L
        if sp > 3.0:
            lim = mu * self.mu_tire * G / sp
            if yr > lim:
                yr = lim
            elif yr < -lim:
                yr = -lim
        self.yaw_ref = yr
        self.yaw_err = r - yr

    # ------------------------------------------------------------------------------------
    def state_tuple(self):
        """Everything that defines the future (for determinism hashes / snapshots)."""
        return (self.x, self.z, self.heading, self.wvx, self.wvz, self.yaw_rate, self.steer,
                self.axf, self.ayf, self.boost, self.shift_t, float(self.gear), self.rpm)

    def speed_kmh(self):
        return self.speed * 3.6


def make_car(car_id, setup=None, lite=False, substeps=2):
    """car_id: "tsubame" / "kazane" / "shirogane" / "arashi" (+ "mikazuki" as an MR check).

    setup: dict of signed stages, 0 = centre.  Missing items = centre.
      gear       -2 (acceleration) .. +2 (top speed)
      wing       -2 (low downforce) .. +2 (high)
      suspension -2 (soft) .. +2 (hard)
      brake_bias -2 (front) .. +2 (rear)
      traction   -2 (rotation, weak LSD) .. +2 (traction, strong LSD)
      steering   -1 (mild) .. +1 (quick)
    """
    return Car(car_id, setup, lite=lite, substeps=substeps)
