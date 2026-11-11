import sys, math
sys.path.insert(0, ".")
from vehicle import make_car, CAR_SPECS, G
for cid in ("tsubame", "kazane", "shirogane", "arashi", "mikazuki"):
    car = make_car(cid)
    t = 0.0; t100 = None; t400 = None
    for i in range(60*60):
        car.step(0.0, 1.0, 0.0)
        t += 1/60
        if t100 is None and car.speed*3.6 >= 100: t100 = t
        if t400 is None and car.x >= 402.3: t400 = t
    vmax = car.speed*3.6
    # brake 100-0
    car.reset(0,0,0,100/3.6)
    x0 = car.x; n=0
    while car.speed > 0.01 and n < 2000:
        car.step(0.0, 0.0, 1.0); n+=1
    d_full = car.x - x0
    print(cid, "0-100 %.2fs" % t100, "0-400m %.2fs" % t400, "vmax %.1f km/h gear %d rpm %.0f" % (vmax, car.gear, car.rpm), "100-0 full pedal %.1f m (%.2fs)" % (d_full, n/60), "peakTq %.0f Nm" % car.torque_peak)
