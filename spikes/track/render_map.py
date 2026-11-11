"""Top-down picture of a track (spike tool). Uses Pillow only for drawing; track.py stays pure.
x to the right, z up (so a left turn = counter-clockwise on the picture)."""
import math
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import track as T  # noqa: E402

COL = {"bg": (40, 60, 40), "grass": (70, 120, 60), "gravel": (200, 180, 120), "kerb": (220, 60, 50),
       "road": (70, 70, 78), "wall": (240, 240, 240), "center": (150, 150, 160), "ideal": (255, 220, 0),
       "text": (255, 255, 255), "cam": (80, 200, 255), "scn": (30, 90, 30)}


def render(tr, path, scale=2.2, with_ideal=True, pad=40.0):
    n = tr.n
    xs = tr._x
    zs = tr._z
    x0 = min(xs) - pad
    x1 = max(xs) + pad
    z0 = min(zs) - pad
    z1 = max(zs) + pad
    w = int((x1 - x0) * scale)
    h = int((z1 - z0) * scale)
    img = Image.new("RGB", (w, h), COL["bg"])
    dr = ImageDraw.Draw(img)

    def P(x, z):
        return ((x - x0) * scale, (z1 - z) * scale)

    def off(i, o):
        i %= n
        return P(xs[i] - o * tr._tz[i], zs[i] + o * tr._tx[i])

    bands = [("gravel", lambda i: -tr._ewr[i], lambda i: -tr._egr[i]),
             ("grass", lambda i: -tr._egr[i], lambda i: -tr._ekr[i]),
             ("kerb", lambda i: -tr._ekr[i], lambda i: -tr._half[i]),
             ("road", lambda i: -tr._half[i], lambda i: tr._half[i]),
             ("kerb", lambda i: tr._half[i], lambda i: tr._ekl[i]),
             ("grass", lambda i: tr._ekl[i], lambda i: tr._egl[i]),
             ("gravel", lambda i: tr._egl[i], lambda i: tr._ewl[i])]
    for name, fa, fb in bands:
        for i in range(n):
            j = i + 1
            a0 = fa(i)
            b0 = fb(i)
            a1 = fa(j % n)
            b1 = fb(j % n)
            if b0 - a0 < 0.02 and b1 - a1 < 0.02:
                continue
            dr.polygon([off(i, a0), off(i, b0), off(j, b1), off(j, a1)], fill=COL[name])
    for e in (tr._ewl, [-v for v in tr._ewr]):
        pts = [off(i, e[i]) for i in range(n)]
        dr.line(pts + [pts[0]], fill=COL["wall"], width=1)
    pts = [P(xs[i], zs[i]) for i in range(n)]
    dr.line(pts + [pts[0]], fill=COL["center"], width=1)
    if with_ideal and tr.has_baked_ideal:
        pts = [off(i, tr._ideal_d[i]) for i in range(n)]
        dr.line(pts + [pts[0]], fill=COL["ideal"], width=2)
    # start line and grid
    i0 = int(tr.start_s / tr.ds) % n
    dr.line([off(i0, -tr._half[i0]), off(i0, tr._half[i0])], fill=(255, 255, 255), width=3)
    for g in range(tr.grid_slots):
        x, z, hd, _ = tr.start_pose(g)
        px, pz = P(x, z)
        dr.rectangle([px - 3, pz - 3, px + 3, pz + 3], outline=(255, 255, 0))
    # direction arrow after the start line
    x, z, hd, _ = tr.pose_at(tr.start_s + 30.0, 0.0)
    ax, az = P(x, z)
    bx, bz = P(x + 14 * math.cos(hd), z + 14 * math.sin(hd))
    dr.line([ax, az, bx, bz], fill=(255, 255, 255), width=3)
    for sgn in (1, -1):
        cx, cz = P(x + 8 * math.cos(hd) - sgn * 4 * math.sin(hd), z + 8 * math.sin(hd) + sgn * 4 * math.cos(hd))
        dr.line([bx, bz, cx, cz], fill=(255, 255, 255), width=3)
    for c in tr.corners:
        sm = 0.5 * (c["s0"] + c["s1"])
        side = -1.0 if c["angle_deg"] > 0 else 1.0     # label on the outside
        x, z, _, _ = tr.pose_at(sm, side * 30.0)
        dr.text(P(x, z), "%s R%d" % (c["name"], c["radius"]), fill=COL["text"])
    for c in tr.cameras:
        x, z, _, _ = tr.pose_at(c["s"], c["d"])
        px, pz = P(x, z)
        dr.ellipse([px - 3, pz - 3, px + 3, pz + 3], fill=COL["cam"])
    for c in tr.scenery:
        x, z, _, _ = tr.pose_at(c["s"], c["d"])
        px, pz = P(x, z)
        dr.rectangle([px - 2, pz - 2, px + 2, pz + 2], fill=COL["scn"], outline=(0, 0, 0))
    for cp in tr.checkpoints:
        i = int(cp / tr.ds) % n
        dr.line([off(i, -tr._half[i] - 2), off(i, tr._half[i] + 2)], fill=(255, 0, 255), width=2)
    # scale bar 100 m and labels
    dr.line([20, h - 20, 20 + 100 * scale, h - 20], fill=COL["text"], width=3)
    dr.text((20, h - 36), "100 m", fill=COL["text"])
    dr.text((20, 10), "%s  length %.1f m  (x right, z up; white bar = start line, magenta = checkpoints, "
            "yellow = ideal line, cyan = cameras)" % (tr.name, tr.length), fill=COL["text"])
    img.save(path)
    return w, h


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "akane_short.json")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "akane_short_map.png")
    tr = T.load_track(src, validate="--novalidate" not in sys.argv)
    print(render(tr, dst), dst)
