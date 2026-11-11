"""Shared helpers for the vehicle validation scripts (pure Python)."""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vehicle import make_car, CAR_SPECS, G, DT

CARS = ("tsubame", "kazane", "shirogane", "arashi")
KMH = 3.6

def wrap(a):
    while a > math.pi: a -= 2*math.pi
    while a < -math.pi: a += 2*math.pi
    return a

class TCS:
    """Ideal-driver throttle: keep a utilisation just under target (axle=True: car.drive_util_axle)."""
    def __init__(self, target=0.97, axle=False): self.t = 1.0; self.target = target; self.axle = axle
    def __call__(self, car, want=1.0):
        du = car.drive_util_axle if self.axle else car.drive_util
        if du > self.target: self.t = max(0.05, self.t * self.target / du)
        else: self.t = min(1.0, self.t + 0.04)
        return min(want, self.t)

class ABS:
    """Ideal-driver brake: keep brake_util just under 1 (uses only car.brake_util)."""
    def __init__(self, target=0.97): self.b = 1.0; self.target = target
    def __call__(self, car, want=1.0):
        bu = car.brake_util
        if bu > self.target: self.b = max(0.05, self.b * self.target / bu)
        else: self.b = min(1.0, self.b + 0.04)
        return min(want, self.b)

def accel_run(car, tcs=False, seconds=60.0, mu=1.0):
    car.reset(0, 0, 0, 0)
    ctl = TCS() if tcs else None
    t = 0.0; t100 = None; t400 = None; thr = 1.0
    for i in range(int(seconds*60)):
        car.step(0.0, thr, 0.0, mu)
        if ctl: thr = ctl(car)
        t += DT
        if t100 is None and car.speed*KMH >= 100: t100 = t
        if t400 is None and car.x >= 402.34: t400 = t
    return {"t0_100": t100, "t0_400m": t400, "vmax_kmh": car.speed*KMH, "top_gear": car.gear, "top_rpm": car.rpm}

def brake_run(car, v_kmh=100.0, abs_on=False, mu=1.0, pedal=1.0):
    car.reset(0, 0, 0, v_kmh/KMH)
    for _ in range(30): car.step(0.0, 0.3, 0.0, mu)   # settle
    car.wvx = v_kmh/KMH; car.wvz = 0.0; car.vx = v_kmh/KMH
    x0 = car.x; n = 0; ctl = ABS() if abs_on else None; b = pedal
    maxdev = 0.0; peak = 0.0
    while car.speed > 0.01 and n < 3000:
        car.step(0.0, 0.0, b, mu); n += 1
        if ctl: b = ctl(car, pedal)
        maxdev = max(maxdev, abs(car.z)); peak = max(peak, -car.ax)
    return {"dist_m": car.x - x0, "time_s": n*DT, "peak_decel_g": peak/G, "max_lateral_dev_m": maxdev}

class CircleDriver:
    """Keeps the car on a left-hand circle of radius R centred at (0, R); speed by PI throttle."""
    def __init__(self, car, R, v0):
        self.car = car; self.R = R; self.i = 0.0; self.si = 0.0
        car.reset(0.0, 0.0, 0.0, v0)
    def steer(self):
        car = self.car; R = self.R
        dx = car.x; dz = car.z - R
        rho = math.hypot(dx, dz)
        e = rho - R
        edot = (car.wvx*dx + car.wvz*dz)/rho
        v = max(car.speed, 5.0)
        w = 2.0; zeta = 0.9
        kp = w*w*car.L/(v*v); kd = 2*zeta*w*car.L/(v*v)
        self.si = max(-0.3, min(0.3, self.si + 0.8*kp*e*DT))   # integral: removes the steady radius error
        return car.L/R + kp*e + kd*edot + self.si, e
    def throttle(self, vt):
        car = self.car
        err = vt - car.speed
        self.i = max(-0.5, min(1.0, self.i + err*0.3*DT))
        return max(0.0, min(1.0, 0.6*err + self.i))

def circle_ramp(car, R, v0, v1, rate=0.25, mu=1.0, bump=0.0, tcs=True):
    """Ramp speed slowly on a circle.  Returns samples and the maximum held lateral g."""
    drv = CircleDriver(car, R, v0)
    vt = v0; rows = []; best = 0.0; fail = None; t = 0.0
    win = []
    lim = TCS()
    for n in range(int((v1 - v0)/rate*60) + 600):
        st, e = drv.steer()
        th = drv.throttle(vt)
        if tcs: th = lim(car, th)
        car.step(st, th, 0.0, mu, DT, bump)
        t += DT
        if n > 240: vt = min(v1, vt + rate*DT)
        rho = math.hypot(car.x, car.z - R)
        ay = car.speed**2/rho/G
        win.append(ay)
        if len(win) > 30: win.pop(0)
        if n % 6 == 0:
            rows.append((t, car.speed, ay, car.steer, car.body_slip, car.slip_front, car.slip_rear, e,
                         max(abs(car.wheel_sy[0]), abs(car.wheel_sy[1])), max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3]))))
        if abs(e) < 1.0 and len(win) == 30:
            best = max(best, sum(win)/30)
        if abs(e) > 2.5 or abs(car.body_slip) > 0.6:
            fail = {"t": t, "speed_kmh": car.speed*KMH, "radius_err_m": e, "body_slip_deg": math.degrees(car.body_slip),
                    "sy_front": max(abs(car.wheel_sy[0]), abs(car.wheel_sy[1])), "sy_rear": max(abs(car.wheel_sy[2]), abs(car.wheel_sy[3])),
                    "mode": "understeer(front washes out)" if e > 0 and abs(car.body_slip) < 0.35 else "oversteer(spin)"}
            break
    return rows, best, fail

def settle_on_circle(car, R, v, seconds=8.0, mu=1.0):
    """Drive steady on the circle at speed v; returns the driver (car left in steady state)."""
    drv = CircleDriver(car, R, v)
    for n in range(int(seconds*60)):
        st, e = drv.steer()
        car.step(st, drv.throttle(v), 0.0, mu)
    return drv
