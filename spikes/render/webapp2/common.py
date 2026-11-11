# Shared helpers for the render spike: palette, textures, procedural car, flat circuit.
# Logic convention: plane (x, z), height y, heading 0 = +x, +pi/2 = +z.
import math
import random

import pyxel
from pyxel.cube import Mat4, Mesh, Node, Primitive, Shading, Vec3

# ---------------------------------------------------------------- palette (32 colors)
(BLACK, NAVY, ASPH_D, ASPH_M, ASPH_L, WHITE, GRASS_D, GRASS_M, GRASS_L, SAND_D, SAND_L,
 RED_D, RED, ORANGE, YELLOW, CREAM, SKY0, SKY1, SKY2, SKY3, MOUNT_D, MOUNT_L, BLUE_D, BLUE,
 CYAN, GLASS, TRUNK, LEAF_D, SILVER, GRAY_D, BRAKE, PINK) = range(32)

BASE_NOON = [
    0x101018, 0x1C2038, 0x3A3D46, 0x55585F, 0x7A7D82, 0xF0F0E8, 0x2F5A2A, 0x4A8034,
    0x74A848, 0x9A7A4A, 0xC8A870, 0x7A1C24, 0xD03030, 0xE87830, 0xF0C830, 0xF8ECA0,
    0x2A6AD0, 0x4A90E0, 0x80B8F0, 0xC0E0F8, 0x3C4868, 0x62709A, 0x1C3478, 0x3060C8,
    0x60B0E0, 0x24404C, 0x5A3C28, 0x1E4028, 0xB4B8C0, 0x26282E, 0xFF4050, 0xE070A0,
]
SKY = {
    "noon": [0x2A6AD0, 0x4A90E0, 0x80B8F0, 0xC0E0F8],
    "evening": [0x3A2A68, 0x8A3A78, 0xE06A48, 0xF8C060],
    "overcast": [0x7C848E, 0x969EA6, 0xB0B6BC, 0xC8CDD0],
}
MOUNT = {
    "noon": [0x3C4868, 0x62709A],
    "evening": [0x2A2044, 0x503060],
    "overcast": [0x4A505A, 0x6C727A],
}
KEEP = (BRAKE,)  # emissive colors are not tinted


def _rgb(c):
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def _pack(r, g, b):
    cl = lambda v: max(0, min(255, int(round(v))))
    return (cl(r) << 16) | (cl(g) << 8) | cl(b)


def make_palette(tod="evening"):
    out = []
    for i, c in enumerate(BASE_NOON):
        r, g, b = _rgb(c)
        if i in KEEP or tod == "noon":
            pass
        elif tod == "evening":
            # warm, slightly dim light
            r, g, b = r * 0.98 + 6, g * 0.87 + 3, b * 0.78 + 10
        elif tod == "overcast":
            y = 0.30 * r + 0.59 * g + 0.11 * b
            r, g, b = (r * 0.55 + y * 0.45) * 0.92, (g * 0.55 + y * 0.45) * 0.92, (b * 0.55 + y * 0.45) * 0.95
        out.append(_pack(r, g, b))
    out[SKY0:SKY3 + 1] = SKY[tod]
    out[MOUNT_D:MOUNT_L + 1] = MOUNT[tod]
    return out


def apply_palette(tod, shading=None):
    """Replace pyxel.colors and rebuild the shading table. Returns the Shading."""
    pal = make_palette(tod)
    pyxel.colors[:] = pal
    if shading is None:
        shading = Shading(pyxel.colors)
    else:
        shading.build(pyxel.colors)
    fix_shading(shading)
    return shading


def fix_shading(shading):
    """Hand edits after build(): emissive colors never darken."""
    for lv in range(Shading.LEVEL_COUNT):
        shading[BRAKE, lv] = (BRAKE, BRAKE)
        shading[CREAM, lv] = (CREAM, CREAM)


# ---------------------------------------------------------------- textures (one atlas)
ATLAS_W = ATLAS_H = 256
# name -> (x, y, w, h) in atlas pixels
RECT = {
    "road": (0, 0, 64, 32),
    "road_start": (64, 0, 64, 32),
    "curb": (128, 0, 16, 16),
    "grass": (144, 0, 32, 32),
    "sand": (176, 0, 32, 32),
    "rail": (208, 0, 32, 8),
    "wall": (208, 8, 32, 8),
    "sign0": (0, 32, 64, 16),
    "sign1": (64, 32, 64, 16),
    "sign2": (128, 32, 64, 16),
    "crowd": (0, 48, 64, 24),
    "tree": (0, 80, 32, 48),
    "tree2": (32, 80, 32, 48),
    "pole": (64, 80, 8, 48),
    "stand": (72, 80, 64, 32),
}


def uv_rect(name, inset=0.0):
    x, y, w, h = RECT[name]
    return ((x + inset) / ATLAS_W, (y + inset) / ATLAS_H, (x + w - inset) / ATLAS_W, (y + h - inset) / ATLAS_H)


def sprite_uvs(name):
    u0, v0, u1, v1 = uv_rect(name)
    return ((u0, v0), (u1, v0), (u0, v1), (u1, v1))


def make_atlas(seed=7):
    rnd = random.Random(seed)
    img = pyxel.Image(ATLAS_W, ATLAS_H)
    img.cls(0)

    def fill(name, fn):
        x0, y0, w, h = RECT[name]
        for y in range(h):
            for x in range(w):
                img.pset(x0 + x, y0 + y, fn(x, y, w, h))

    def asphalt(x, y, w, h):
        # u across the road (64 texels / 12 m), v along the road.
        r = rnd.random()
        c = ASPH_M if r > 0.10 else (ASPH_D if r > 0.03 else ASPH_L)
        if 22 <= x < 42 and (x + y * 3) % 5 == 0:
            c = ASPH_D  # darker racing line band (regular pattern, low contrast)
        if x in (2, 3) or x in (60, 61):
            c = WHITE  # edge lines
        return c

    fill("road", asphalt)

    def start(x, y, w, h):
        c = asphalt(x, y, w, h)
        if 12 <= y < 20 and 2 <= x < 62:
            c = WHITE if ((x // 4) + (y // 4)) % 2 == 0 else BLACK
        return c

    fill("road_start", start)
    fill("curb", lambda x, y, w, h: RED if y < 8 else WHITE)
    fill("grass", lambda x, y, w, h: GRASS_M if rnd.random() > 0.3 else (GRASS_D if rnd.random() > 0.4 else GRASS_L))
    fill("sand", lambda x, y, w, h: SAND_L if rnd.random() > 0.3 else SAND_D)
    fill("rail", lambda x, y, w, h: (ASPH_L if y in (0, 3, 4, 7) else SILVER) if x % 16 else ASPH_D)
    fill("wall", lambda x, y, w, h: (WHITE if (x // 8) % 2 == 0 else RED) if y < 6 else ASPH_D)

    def sign(bg, fg, text):
        def f(name):
            x0, y0, w, h = RECT[name]
            img.rect(x0, y0, w, h, bg)
            img.rectb(x0, y0, w, h, fg)
            img.text(x0 + (w - len(text) * 4) // 2, y0 + 5, text, fg)
        return f

    sign(BLUE_D, WHITE, "CLIPPING POINT")("sign0")
    sign(YELLOW, BLACK, "AKANE SHORT")("sign1")
    sign(RED, WHITE, "TSUBAME 1600")("sign2")

    x0, y0, w, h = RECT["crowd"]
    img.rect(x0, y0, w, h, ASPH_D)
    for y in range(2, h - 4, 5):
        for x in range(1, w - 2, 3):
            c = rnd.choice([RED, BLUE, YELLOW, WHITE, PINK, CYAN, ORANGE, SAND_L])
            img.rect(x0 + x + (y // 5) % 2, y0 + y, 2, 3, c)
            img.pset(x0 + x + (y // 5) % 2, y0 + y - 1, SAND_L)

    for name, leaf_a, leaf_b in (("tree", GRASS_D, LEAF_D), ("tree2", LEAF_D, GRASS_D)):
        x0, y0, w, h = RECT[name]
        img.rect(x0 + 14, y0 + 30, 4, 18, TRUNK)
        for cx, cy, r in ((16, 14, 12), (9, 22, 8), (23, 22, 8), (16, 26, 9)):
            img.circ(x0 + cx, y0 + cy, r, leaf_a)
        for _ in range(110):
            px, py = rnd.randrange(w), rnd.randrange(34)
            if img.pget(x0 + px, y0 + py) == leaf_a:
                img.pset(x0 + px, y0 + py, leaf_b if rnd.random() > 0.35 else GRASS_M)

    x0, y0, w, h = RECT["pole"]
    img.rect(x0 + 3, y0, 2, h, ASPH_L)
    img.rect(x0, y0, 8, 3, CREAM)

    x0, y0, w, h = RECT["stand"]
    img.rect(x0, y0, w, h, ASPH_L)
    img.rect(x0, y0, w, 6, BLUE_D)
    for y in range(8, h - 2, 4):
        for x in range(1, w - 2, 3):
            img.rect(x0 + x, y0 + y, 2, 2, rnd.choice([RED, BLUE, YELLOW, WHITE, PINK, CYAN, ORANGE]))
    return img


# ---------------------------------------------------------------- mesh builder
class Builder:
    """Collects unshared-vertex triangles with UVs; fixes winding from an outward hint."""

    def __init__(self):
        self.pos = []
        self.uv = []
        self.idx = []

    @property
    def tri_count(self):
        return len(self.idx) // 3

    def tri(self, a, b, c, uva, uvb, uvc, outward=None):
        if outward is not None:
            n = _cross(_sub(b, a), _sub(c, a))
            if n[0] * outward[0] + n[1] * outward[1] + n[2] * outward[2] < 0:
                b, c, uvb, uvc = c, b, uvc, uvb
        base = len(self.pos) // 3
        for p in (a, b, c):
            self.pos += [p[0], p[1], p[2]]
        for t in (uva, uvb, uvc):
            self.uv += [t[0], t[1]]
        self.idx += [base, base + 1, base + 2]

    def quad(self, p0, p1, p2, p3, uvs, outward=None):
        """p0..p3 in ring order; uvs: 4 (u, v) pairs in the same order."""
        self.tri(p0, p1, p2, uvs[0], uvs[1], uvs[2], outward)
        self.tri(p0, p2, p3, uvs[0], uvs[2], uvs[3], outward)

    def quad_rect(self, p0, p1, p2, p3, rect, outward=None):
        """Map a (u0, v0, u1, v1) rect: p0=(u0,v0) p1=(u1,v0) p2=(u1,v1) p3=(u0,v1)."""
        u0, v0, u1, v1 = rect
        self.quad(p0, p1, p2, p3, ((u0, v0), (u1, v0), (u1, v1), (u0, v1)), outward)

    def quad_col(self, p0, p1, p2, p3, uvc, outward=None):
        self.quad(p0, p1, p2, p3, (uvc, uvc, uvc, uvc), outward)

    def tri_col(self, a, b, c, uvc, outward=None):
        self.tri(a, b, c, uvc, uvc, uvc, outward)

    def box_col(self, cx, cy, cz, sx, sy, sz, uvc, skip=()):
        x0, x1, y0, y1, z0, z1 = cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, cz - sz / 2, cz + sz / 2
        faces = {
            "+x": ((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (1, 0, 0)),
            "-x": ((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (-1, 0, 0)),
            "+y": ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1), (0, 1, 0)),
            "-y": ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0, -1, 0)),
            "+z": ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0, 0, 1)),
            "-z": ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (0, 0, -1)),
        }
        for k, (a, b, c, d, n) in faces.items():
            if k not in skip:
                self.quad_col(a, b, c, d, uvc, n)

    def primitive(self, cull=None):
        p = Primitive(Primitive.MODE_TRIANGLES, self.pos, self.idx, uvs=self.uv,
                      cull=Primitive.CULL_BACK if cull is None else cull)
        p.compute_normals()
        return p


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


# ---------------------------------------------------------------- car (procedural)
CAR_TEX = 32  # 32x32: 8x4 swatches of 4x4 px (top 16 rows), wheel face 16x16 at (0,16)
SW = {"body": 0, "body2": 1, "glass": 2, "tire": 3, "bumper": 4, "head": 5, "tail": 6, "under": 7,
      "silver": 8, "black": 9, "stripe": 10}


def swatch_uv(name):
    i = SW[name]
    return (((i % 8) * 4 + 2) / CAR_TEX, ((i // 8) * 4 + 2) / CAR_TEX)


def make_car_texture(body, body2=None, stripe=WHITE):
    img = pyxel.Image(CAR_TEX, CAR_TEX)
    img.cls(0)
    cols = {"body": body, "body2": body if body2 is None else body2, "glass": GLASS, "tire": GRAY_D,
            "bumper": ASPH_D, "head": CREAM, "tail": BRAKE, "under": BLACK, "silver": SILVER,
            "black": BLACK, "stripe": stripe}
    for name, i in SW.items():
        img.rect((i % 8) * 4, (i // 8) * 4, 4, 4, cols[name])
    # wheel face 16x16 at (0, 16): tire ring + 5-spoke-ish hub
    img.rect(0, 16, 16, 16, GRAY_D)
    img.circ(7, 23, 5, SILVER)
    img.circ(8, 24, 5, SILVER)
    img.circ(7, 23, 1, ASPH_D)
    for dx, dy in ((0, -3), (3, -1), (2, 3), (-2, 3), (-3, -1)):
        img.pset(7 + dx, 23 + dy, ASPH_D)
        img.pset(8 + dx, 24 + dy, ASPH_D)
    return img


# stations along +x (rear -> nose): x, half width at sill, belt y, half width at belt, top y, half width at top
COUPE = [
    (-2.10, 0.70, 0.60, 0.70, 0.70, 0.58),
    (-1.95, 0.84, 0.70, 0.84, 0.82, 0.66),
    (-1.30, 0.86, 0.76, 0.86, 0.86, 0.68),
    (-0.70, 0.86, 0.78, 0.86, 1.22, 0.56),
    (0.05, 0.86, 0.78, 0.86, 1.24, 0.57),
    (0.80, 0.86, 0.76, 0.86, 0.80, 0.70),
    (1.65, 0.84, 0.68, 0.84, 0.70, 0.68),
    (2.00, 0.80, 0.58, 0.80, 0.62, 0.62),
    (2.10, 0.70, 0.50, 0.70, 0.52, 0.56),
]
Y_BOT, Y_MID = 0.17, 0.40
WHEEL_R, WHEEL_W = 0.31, 0.22
AXLE_F, AXLE_R, TRACK_HALF = 1.28, -1.27, 0.76


def build_car_body(stations=COUPE, wing=True):
    b = Builder()
    uv = swatch_uv

    def ring(s):
        x, ws, yb, wb, yt, wt = s
        # 8 points, left (-z) bottom -> over the top -> right (+z) bottom
        return [(x, Y_BOT, -ws * 0.94), (x, Y_MID, -ws), (x, yb, -wb), (x, yt, -wt),
                (x, yt, wt), (x, yb, wb), (x, Y_MID, ws), (x, Y_BOT, ws * 0.94)]

    rings = [ring(s) for s in stations]
    n = len(rings)
    # color per (segment, strip). strips: 0 skirtL 1 sideL 2 upperL 3 top 4 upperR 5 sideR 6 skirtR
    for i in range(n - 1):
        a, c = rings[i], rings[i + 1]
        xm = (stations[i][0] + stations[i + 1][0]) / 2
        for k in range(7):
            col = "body"
            if k in (0, 6):
                col = "bumper"
            if k == 3:
                col = "glass" if i in (2, 4) else ("body" if i != 3 else "body2")
            if k in (2, 4):
                col = "glass" if i in (2, 3, 4) else "body"
                if i == n - 2:
                    col = "head"
                if i == 0:
                    col = "tail"
            if k in (1, 5) and i in (0, n - 2):
                col = "bumper"
            mid = [(a[k][j] + a[k + 1][j] + c[k][j] + c[k + 1][j]) / 4 for j in range(3)]
            outward = (0.0, mid[1] - 0.55 if k == 3 else 0.0, mid[2]) if k != 3 else (0, 1, 0)
            b.quad_col(a[k], a[k + 1], c[k + 1], c[k], uv(col), outward)
    # end caps as fans
    # end caps: skirt band, lower panel, and an upper band split into lamp / center / lamp
    for r, nx, lamp, center in ((rings[0], -1, "tail", "body"), (rings[-1], 1, "head", "black")):
        out = (nx, 0, 0)
        b.quad_col(r[0], r[7], r[6], r[1], uv("bumper"), out)
        b.quad_col(r[1], r[6], r[5], r[2], uv("body"), out)
        lo = [tuple(r[2][j] + (r[5][j] - r[2][j]) * t for j in range(3)) for t in (0, 0.3, 0.7, 1)]
        hi = [tuple(r[3][j] + (r[4][j] - r[3][j]) * t for j in range(3)) for t in (0, 0.3, 0.7, 1)]
        for k, col in enumerate((lamp, center, lamp)):
            b.quad_col(lo[k], lo[k + 1], hi[k + 1], hi[k], uv(col), out)
    # floor (one quad, dark) so the car is closed when seen from a low TV camera
    b.quad_col((-2.0, Y_BOT, -0.8), (2.0, Y_BOT, -0.8), (2.0, Y_BOT, 0.8), (-2.0, Y_BOT, 0.8), uv("under"), (0, -1, 0))
    if wing:
        b.box_col(-1.90, 1.02, 0.0, 0.30, 0.04, 1.50, uv("body"))
        b.box_col(-1.88, 0.92, -0.55, 0.10, 0.18, 0.05, uv("black"), skip=("+y", "-y"))
        b.box_col(-1.88, 0.92, 0.55, 0.10, 0.18, 0.05, uv("black"), skip=("+y", "-y"))
    # door mirrors
    b.box_col(0.62, 0.84, -0.93, 0.10, 0.09, 0.14, uv("body"), skip=("+z",))
    b.box_col(0.62, 0.84, 0.93, 0.10, 0.09, 0.14, uv("body"), skip=("-z",))
    return b


def build_wheel(sides=8):
    """Wheel centered at origin, axis along z, outer face at +z."""
    b = Builder()
    uvt = swatch_uv("tire")
    pts = [(WHEEL_R * math.cos(2 * math.pi * k / sides), WHEEL_R * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    zo, zi = WHEEL_W / 2, -WHEEL_W / 2
    for k in range(sides):
        (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % sides]
        b.quad_col((x0, y0, zi), (x1, y1, zi), (x1, y1, zo), (x0, y0, zo), uvt, ((x0 + x1) / 2, (y0 + y1) / 2, 0))
    # outer cap textured with the wheel face (16x16 at (0,16) in the 32x32 car texture)
    def wuv(x, y):
        return ((8 + 7.5 * x / WHEEL_R) / CAR_TEX, (24 - 7.5 * y / WHEEL_R) / CAR_TEX)
    for k in range(1, sides - 1):
        a, c, d = pts[0], pts[k], pts[k + 1]
        b.tri((a[0], a[1], zo), (c[0], c[1], zo), (d[0], d[1], zo), wuv(*a), wuv(*c), wuv(*d), (0, 0, 1))
    return b


WHEEL_NAMES = ("wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr")
WHEEL_POS = {
    "wheel_fl": (AXLE_F, WHEEL_R, -TRACK_HALF),
    "wheel_fr": (AXLE_F, WHEEL_R, TRACK_HALF),
    "wheel_rl": (AXLE_R, WHEEL_R, -TRACK_HALF),
    "wheel_rr": (AXLE_R, WHEEL_R, TRACK_HALF),
}


def wheel_transform(name, steer_deg=0.0, spin_deg=0.0):
    """Local transform of a wheel node. steer_deg > 0 = steer right (toward +z)."""
    x, y, z = WHEEL_POS[name]
    m = Mat4.from_translation(Vec3(x, y, z))
    if name in ("wheel_fl", "wheel_fr"):
        m = m.rotate_y(-steer_deg)
    if z < 0:
        m = m.rotate_y(180.0)  # left wheels: flip so the textured cap faces outward
        spin_deg = -spin_deg
    return m.rotate_z(-spin_deg)


_CAR_PRIMS = {}


def car_prims():
    if not _CAR_PRIMS:
        body = build_car_body()
        wheel = build_wheel()
        _CAR_PRIMS["body"] = body.primitive()
        _CAR_PRIMS["wheel"] = wheel.primitive()
        _CAR_PRIMS["tris"] = body.tri_count + 4 * wheel.tri_count
        _CAR_PRIMS["body_tris"] = body.tri_count
        _CAR_PRIMS["wheel_tris"] = wheel.tri_count
    return _CAR_PRIMS


def make_car_mesh(tex):
    p = car_prims()
    prims = [p["body"]] + [p["wheel"]] * 4
    transforms = [Mat4.IDENTITY] + [wheel_transform(n) for n in WHEEL_NAMES]
    return Mesh(prims, transforms, [-1, 0, 0, 0, 0], ["body", *WHEEL_NAMES], tex)


def car_transform(x, y, z, heading, pitch=0.0, roll=0.0):
    """Logic pose -> Cube matrix for a model whose nose is +x, right is +z, up is +y.
    heading [rad]: 0 = +x, +pi/2 = +z. pitch [rad] > 0 = nose up. roll [rad] > 0 = right side down."""
    return (Mat4.from_translation(Vec3(x, y, z))
            .rotate_y(-math.degrees(heading))
            .rotate_z(math.degrees(pitch))
            .rotate_x(math.degrees(roll)))


class Car(Node):
    """Retained-mode car: child node tree from a Mesh + immediate shadow decal."""

    def __init__(self, tex, shadow=True):
        super().__init__()
        self.model = Node.from_mesh(make_car_mesh(tex))
        self.add_child(self.model)
        self.wheels = {n: self.model.find_by_name(n)[0] for n in WHEEL_NAMES}
        self.shadow = shadow
        self.steer = 0.0
        self.spin = 0.0
        self.brake = False

    def set_pose(self, x, y, z, heading, pitch=0.0, roll=0.0, steer_deg=0.0, spin_deg=0.0):
        self.transform = car_transform(x, y, z, heading, pitch, roll)
        for n, node in self.wheels.items():
            node.transform = wheel_transform(n, steer_deg, spin_deg)

    def on_draw(self):
        if self.shadow:
            self.shaded(False)
            self.decal(1.0)
            self.dither(0.5)
            self.elli(Mat4.from_translation(Vec3(0, 0.3, 0)).rotate_x(-90.0), 4.4, 2.0, BLACK)
            self.dither(1.0)
            self.decal()


# ---------------------------------------------------------------- flat circuit
def centerline(n=220):
    """Closed loop on the (x, z) plane, roughly 1.1 km, with a hairpin-ish end."""
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = 150 + 38 * math.sin(2 * t) + 22 * math.sin(3 * t + 0.7) + 12 * math.cos(5 * t)
        pts.append((r * math.cos(t) * 1.25, r * math.sin(t) * 0.8))
    return pts


def track_frames(pts):
    """Per point: (x, z, heading, nx, nz) with n = right-hand normal (heading + 90 deg)."""
    n = len(pts)
    out = []
    for i in range(n):
        x0, z0 = pts[i - 1]
        x1, z1 = pts[(i + 1) % n]
        h = math.atan2(z1 - z0, x1 - x0)
        out.append((pts[i][0], pts[i][1], h, -math.sin(h), math.cos(h)))
    return out


ROAD_HALF = 6.0
CURB_W = 1.0
VERGE_W = 6.0
RAIL_OFF = ROAD_HALF + CURB_W + VERGE_W


def curvature(frames, i):
    n = len(frames)
    d = frames[(i + 1) % n][2] - frames[i - 1][2]
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def build_track_section(frames, i0, i1, across=2, ground_y=0.0):
    """Builder for segments i0..i1-1 (road, curbs, verges, rails)."""
    b = Builder()
    n = len(frames)
    up = (0, 1, 0)
    road, curb, grass, sand, rail = (uv_rect(k, 0.5) for k in ("road", "curb", "grass", "sand", "rail"))
    road_start = uv_rect("road_start", 0.5)
    for i in range(i0, i1):
        a, c = frames[i % n], frames[(i + 1) % n]

        def P(f, off, y=ground_y):
            return (f[0] + f[3] * off, y, f[1] + f[4] * off)

        r = road_start if i % n == 0 else road
        # road: `across` quads from left (-ROAD_HALF) to right (+ROAD_HALF)
        for k in range(across):
            o0 = -ROAD_HALF + 2 * ROAD_HALF * k / across
            o1 = -ROAD_HALF + 2 * ROAD_HALF * (k + 1) / across
            u0 = r[0] + (r[2] - r[0]) * k / across
            u1 = r[0] + (r[2] - r[0]) * (k + 1) / across
            b.quad_rect(P(a, o0), P(a, o1), P(c, o1), P(c, o0), (u0, r[1], u1, r[3]), up)
        kappa = curvature(frames, i % n)
        for side in (-1, 1):
            e0, e1 = side * ROAD_HALF, side * (ROAD_HALF + CURB_W)
            # curbs only where the track bends (both sides), alternating red/white per segment
            if abs(kappa) > 0.035:
                cr = (curb[0], curb[1], curb[2], (curb[1] + curb[3]) / 2) if i % 2 == 0 else (curb[0], (curb[1] + curb[3]) / 2, curb[2], curb[3])
                b.quad_rect(P(a, e0), P(a, e1), P(c, e1), P(c, e0), cr, up)
            else:
                b.quad_rect(P(a, e0), P(a, e1), P(c, e1), P(c, e0), grass, up)
            # verge: sand on the outside of bends, else grass
            g0, g1 = e1, side * RAIL_OFF
            outside = (kappa * side) < -0.035
            b.quad_rect(P(a, g0), P(a, g1), P(c, g1), P(c, g0), sand if outside else grass, up)
            # guardrail (two-sided so it is visible from behind too)
            b.quad_rect(P(a, g1, 0.9), P(c, g1, 0.9), P(c, g1, 0.0), P(a, g1, 0.0), rail, (-side * a[3], 0, -side * a[4]))
    return b


def build_ground(size=1400.0, tile=50.0, y=-0.05):
    """Big grass plane under everything, in tiles."""
    b = Builder()
    g = uv_rect("grass", 0.5)
    n = int(size / tile)
    h = size / 2
    for iz in range(n):
        for ix in range(n):
            x0, z0 = -h + ix * tile, -h + iz * tile
            b.quad_rect((x0, y, z0), (x0 + tile, y, z0), (x0 + tile, y, z0 + tile), (x0, y, z0 + tile), g, (0, 1, 0))
    return b


def build_props(frames, seed=3):
    """Signboards, stands (textured quads) + list of sprite props (trees, poles)."""
    rnd = random.Random(seed)
    b = Builder()
    n = len(frames)
    sprites = []
    for i in range(0, n, 11):
        f = frames[i]
        side = 1 if (i // 11) % 2 == 0 else -1
        off = side * (RAIL_OFF + 1.5)
        name = ("sign0", "sign1", "sign2")[(i // 11) % 3]
        r = uv_rect(name)
        w = 8.0
        f2 = frames[(i + 1) % n]
        dx, dz = math.cos(f[2]), math.sin(f[2])
        bx, bz = f[0] + f[3] * off, f[1] + f[4] * off
        p_lo0 = (bx - dx * w / 2, 1.2, bz - dz * w / 2)
        p_lo1 = (bx + dx * w / 2, 1.2, bz + dz * w / 2)
        p_hi0 = (p_lo0[0], 3.2, p_lo0[2])
        p_hi1 = (p_lo1[0], 3.2, p_lo1[2])
        face = (-side * f[3], 0, -side * f[4])
        # viewed from the track: the left end of the text is the +d end on the right side, the -d end on the left side
        back = (-face[0], 0, -face[2])
        dark = uv_rect("rail", 2.0)
        dk = (dark[0], dark[1], dark[0], dark[1])
        if side > 0:
            b.quad_rect(p_hi1, p_hi0, p_lo0, p_lo1, r, face)
        else:
            b.quad_rect(p_hi0, p_hi1, p_lo1, p_lo0, r, face)
        b.quad_rect(p_hi0, p_hi1, p_lo1, p_lo0, dk, back)
    # one grandstand near the start line (left side)
    f = frames[2]
    st = uv_rect("stand")
    dx, dz = math.cos(f[2]), math.sin(f[2])
    off = -(RAIL_OFF + 6.0)
    bx, bz = f[0] + f[3] * off, f[1] + f[4] * off
    wlen = 40.0
    a0 = (bx - dx * wlen / 2, 0.0, bz - dz * wlen / 2)
    a1 = (bx + dx * wlen / 2, 0.0, bz + dz * wlen / 2)
    b0 = (a0[0] - f[3] * 6, 9.0, a0[2] - f[4] * 6)
    b1 = (a1[0] - f[3] * 6, 9.0, a1[2] - f[4] * 6)
    b.quad_rect(b0, b1, a1, a0, st, (f[3], 0.5, f[4]))
    for i in range(0, n, 3):
        f = frames[i]
        for side in (-1, 1):
            if rnd.random() < 0.55:
                off = side * (RAIL_OFF + 4.0 + rnd.random() * 14.0)
                hgt = 6.0 + rnd.random() * 4.0
                sprites.append(("tree" if rnd.random() > 0.4 else "tree2", f[0] + f[3] * off, f[1] + f[4] * off, hgt * 0.66, hgt))
    return b, sprites


class SpriteProps(Node):
    """Immediate-mode camera-facing sprites (trees). Culls by distance on the Python side."""

    def __init__(self, atlas, sprites, max_dist=300.0):
        super().__init__()
        self.atlas = atlas
        self.sprites = sprites
        self.max_d2 = max_dist * max_dist
        self.cam_pos = (0.0, 0.0, 0.0)
        self.cam_fwd = (1.0, 0.0)
        self.uvs = {k: sprite_uvs(k) for k in ("tree", "tree2", "pole")}
        self.drawn = 0

    def on_draw(self):
        cx, _, cz = self.cam_pos
        fx, fz = self.cam_fwd
        atlas, uvs, max_d2 = self.atlas, self.uvs, self.max_d2
        self.shaded(False)
        cnt = 0
        for name, x, z, w, h in self.sprites:
            dx, dz = x - cx, z - cz
            if dx * dx + dz * dz > max_d2 or dx * fx + dz * fz < -5.0:
                continue
            self.sprite(Vec3(x, h / 2, z), atlas, uvs[name], w, h, colkey=0)
            cnt += 1
        self.drawn = cnt


def make_background(tod="evening", width=640, height=240, horizon=150, seed=5):
    """Sky + mountain strip. Image is `width` wide and loops horizontally; horizon at row `horizon`."""
    rnd = random.Random(seed)
    img = pyxel.Image(width, height)
    bands = [SKY0, SKY1, SKY2, SKY3]
    top = horizon - 132
    for y in range(height):
        t = (y - top) / 132.0 * 3.0
        t = max(0.0, min(2.999, t))
        i, fr = int(t), t - int(t)
        for x in range(width):
            # ordered 4x4 dither between neighboring bands
            thr = ((x & 3) * 5 + (y & 3) * 7 + ((x ^ y) & 1) * 8) % 16 / 16.0
            img.pset(x, y, bands[i + 1] if fr > thr else bands[i])
    if tod != "overcast":
        img.circ(width // 3, horizon - 14, 9, CREAM if tod == "evening" else WHITE)
    # mountains: far ridge then near ridge
    for col, amp, base, k in ((MOUNT_L, 26, 20, 3), (MOUNT_D, 16, 9, 7)):
        ph = [rnd.random() * 6.28 for _ in range(4)]
        for x in range(width):
            a = 2 * math.pi * x / width
            hgt = base + amp * (0.5 + 0.3 * math.sin(k * a + ph[0]) + 0.15 * math.sin(2 * k * a + ph[1]) + 0.08 * math.sin(5 * k * a + ph[2]))
            img.line(x, horizon - int(hgt), x, horizon, col)
    img.rect(0, horizon, width, height - horizon, GRASS_D)
    return img


def draw_background(target, bg, cam_heading, cam_pitch_up, fov_deg, w=320, h=240, bg_horizon=150, loop_deg=120.0):
    """Blit the panorama so its horizon row lands on the camera's horizon. cam_heading [rad] logic convention."""
    f = (h / 2) / math.tan(math.radians(fov_deg) / 2)
    y_h = h / 2 + f * math.tan(cam_pitch_up)
    # at fov 60 the strip is drawn 1:1; keep it 1:1 for other fovs too (cheap, no scaling)
    px_per_deg = bg.width / loop_deg
    ox = int(math.degrees(cam_heading) * px_per_deg) % bg.width
    oy = int(round(y_h)) - bg_horizon
    target.cls(SKY0 if oy > 0 else GRASS_D)
    if oy > 0:
        target.rect(0, 0, w, oy, SKY0)
    if oy + bg.height < h:
        target.rect(0, oy + bg.height, w, h - oy - bg.height, GRASS_D)
    target.blt(-ox, oy, bg, 0, 0, bg.width, bg.height)
    if bg.width - ox < w:
        target.blt(bg.width - ox, oy, bg, 0, 0, bg.width, bg.height)
