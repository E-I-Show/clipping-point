# Prototype scene for the render spike (flat circuit, 6 cars, evening palette, panorama background).
# Used by the native headless scripts and by the browser app (webapp/main.py).
import math

import pyxel
from pyxel.cube import Camera, Mat4, Mesh, Node, Vec3

import common as C

W, H = 320, 240
SEC_LEN = 10  # track segments per section node
FAR = 300.0


class ImmediateSections(Node):
    """Immediate-mode alternative: draw section primitives with prim() in on_draw."""

    def __init__(self, prims, atlas):
        super().__init__()
        self.prims = prims
        self.atlas = atlas
        self.mask = None

    def on_draw(self):
        ident = Mat4.IDENTITY
        atlas = self.atlas
        if self.mask is None:
            for p in self.prims:
                self.prim(ident, p, atlas)
        else:
            for p, on in zip(self.prims, self.mask):
                if on:
                    self.prim(ident, p, atlas)


class World:
    def __init__(self, tod="evening", mode="sections", ground_tile=50.0, across=2, n_cars=6):
        self.tod = tod
        self.mode = mode
        self.shading = C.apply_palette(tod)
        self.atlas = C.make_atlas()
        self.bg = C.make_background(tod)
        self.frames = C.track_frames(C.centerline())
        n = len(self.frames)
        self.buf = pyxel.Image(W, H)

        self.root = Node()
        self.root.shading = self.shading
        self.camera = Camera()
        self.camera.clear_color = None
        self.camera.near = 0.3
        self.camera.far = FAR
        self.root.camera = self.camera

        # ground
        gb = C.build_ground(tile=ground_tile)
        self.ground = Node.from_mesh(Mesh([gb.primitive()], [Mat4.IDENTITY], [-1], ["ground"], self.atlas))
        self.root.add_child(self.ground)
        self.tri = {"ground": gb.tri_count}

        # track sections
        self.sec_nodes = []
        self.sec_info = []  # (cx, cz, radius)
        self.sec_prims = []
        tri_track = 0
        merged = C.Builder()
        for i0 in range(0, n, SEC_LEN):
            i1 = min(n, i0 + SEC_LEN)
            b = C.build_track_section(self.frames, i0, i1, across=across)
            tri_track += b.tri_count
            xs = b.pos[0::3]
            zs = b.pos[2::3]
            cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
            rad = math.hypot(max(xs) - min(xs), max(zs) - min(zs)) / 2
            self.sec_info.append((cx, cz, rad))
            prim = b.primitive(cull=C.Primitive.CULL_NONE)
            self.sec_prims.append(prim)
            if mode == "merged":
                base = len(merged.pos) // 3
                merged.pos += b.pos
                merged.uv += b.uv
                merged.idx += [k + base for k in b.idx]
        self.tri["track"] = tri_track
        if mode == "sections":
            for prim in self.sec_prims:
                node = Node.from_mesh(Mesh([prim], [Mat4.IDENTITY], [-1], ["sec"], self.atlas))
                self.sec_nodes.append(node)
                self.root.add_child(node)
        elif mode == "merged":
            node = Node.from_mesh(Mesh([merged.primitive(cull=C.Primitive.CULL_NONE)], [Mat4.IDENTITY], [-1], ["track"], self.atlas))
            self.root.add_child(node)
        elif mode == "immediate":
            self.imm = ImmediateSections(self.sec_prims, self.atlas)
            self.root.add_child(self.imm)

        # props (signs, stand) + sprites (trees)
        pb, sprites = C.build_props(self.frames)
        self.props = Node.from_mesh(Mesh([pb.primitive()], [Mat4.IDENTITY], [-1], ["props"], self.atlas))
        self.root.add_child(self.props)
        self.tri["props"] = pb.tri_count
        self.sprites = C.SpriteProps(self.atlas, sprites, max_dist=FAR)
        self.root.add_child(self.sprites)
        self.tri["sprites_total"] = len(sprites) * 2

        # cars
        body_cols = [C.RED, C.BLUE, C.YELLOW, C.WHITE, C.GRASS_M, C.ORANGE]
        self.cars = []
        for k in range(n_cars):
            car = C.Car(C.make_car_texture(body_cols[k % len(body_cols)]))
            self.cars.append(car)
            self.root.add_child(car)
        self.tri["cars"] = n_cars * C.car_prims()["tris"]
        self.car_s = [0.0] * n_cars
        self.place_cars(6.0)
        self.culling = True
        self.visible_sections = len(self.sec_info)

    # -------------------------------------------------------------- cars
    def track_pose(self, s, lateral=0.0):
        """s in segment units (float). Returns x, z, heading."""
        n = len(self.frames)
        i = int(math.floor(s)) % n
        t = s - math.floor(s)
        a, b = self.frames[i], self.frames[(i + 1) % n]
        x = a[0] + (b[0] - a[0]) * t
        z = a[1] + (b[1] - a[1]) * t
        dh = b[2] - a[2]
        while dh > math.pi:
            dh -= 2 * math.pi
        while dh < -math.pi:
            dh += 2 * math.pi
        h = a[2] + dh * t
        nx, nz = -math.sin(h), math.cos(h)
        return x + nx * lateral, z + nz * lateral, h

    def place_cars(self, s0):
        gaps = [0.0, 2.2, 3.6, 5.5, 7.5, 10.5]
        lats = [1.2, -2.2, 2.6, -0.8, 1.8, -2.8]
        for k, car in enumerate(self.cars):
            s = s0 + gaps[k % 6]
            self.car_s[k] = s
            x, z, h = self.track_pose(s, lats[k % 6])
            steer = math.degrees(C.curvature(self.frames, int(s) % len(self.frames))) * 4.0
            car.set_pose(x, 0.0, z, h, roll=-math.radians(steer) * 0.15, steer_deg=steer, spin_deg=s * 400.0)
        return self.track_pose(s0, lats[0])

    # -------------------------------------------------------------- cameras
    def cam_chase(self, x, z, h, dist=6.2, height=2.1):
        fx, fz = math.cos(h), math.sin(h)
        eye = Vec3(x - fx * dist, height, z - fz * dist)
        tgt = Vec3(x + fx * 6.0, 0.9, z + fz * 6.0)
        return eye, tgt, 58.0

    def cam_bumper(self, x, z, h):
        fx, fz = math.cos(h), math.sin(h)
        eye = Vec3(x + fx * 1.6, 0.62, z + fz * 1.6)
        tgt = Vec3(x + fx * 30.0, 0.5, z + fz * 30.0)
        return eye, tgt, 62.0

    def cam_tv(self, x, z, h, post_s, side=1, height=3.5, frame_m=7.0):
        px, pz, ph = self.track_pose(post_s, side * (C.RAIL_OFF + 2.5))
        eye = Vec3(px, height, pz)
        tgt = Vec3(x, 0.6, z)
        dist = math.hypot(x - px, z - pz)
        fov = max(6.0, min(55.0, math.degrees(2 * math.atan(frame_m / max(dist, 1.0)))))
        return eye, tgt, fov

    def set_camera(self, eye, tgt, fov):
        cam = self.camera
        cam.transform = Mat4.look_at(eye, tgt)
        cam.fov = fov
        dx, dy, dz = tgt.x - eye.x, tgt.y - eye.y, tgt.z - eye.z
        ln = math.sqrt(dx * dx + dy * dy + dz * dz)
        self.cam_heading = math.atan2(dz, dx)
        self.cam_pitch_up = math.asin(dy / ln)
        self.cam_eye = (eye.x, eye.y, eye.z)
        hl = math.hypot(dx, dz) or 1.0
        self.cam_fwd = (dx / hl, dz / hl)
        self.sprites.cam_pos = self.cam_eye
        self.sprites.cam_fwd = self.cam_fwd
        self.update_visibility()

    def update_visibility(self):
        ex, _, ez = self.cam_eye
        fx, fz = self.cam_fwd
        cnt = 0
        mask = []
        for (cx, cz, rad) in self.sec_info:
            dx, dz = cx - ex, cz - ez
            on = True
            if self.culling:
                on = (dx * dx + dz * dz) < (FAR + rad) ** 2 and (dx * fx + dz * fz) > -rad
            mask.append(on)
            cnt += on
        self.visible_sections = cnt
        if self.mode == "sections":
            for node, on in zip(self.sec_nodes, mask):
                node.visible = on
        elif self.mode == "immediate":
            self.imm.mask = mask if self.culling else None

    # -------------------------------------------------------------- drawing
    def draw_scene(self, target=None):
        """Background (2D) -> 3D on top (camera.clear_color = None)."""
        tgt = self.buf if target is None else target
        C.draw_background(tgt, self.bg, self.cam_heading, self.cam_pitch_up, self.camera.fov, W, H)
        self.root.draw(0, 0, W, H, tgt)

    def draw_3d_only(self, target=None):
        self.root.draw(0, 0, W, H, self.buf if target is None else target)

    def draw_hud(self, label, target=None):
        t = self.buf if target is None else target
        t.rect(0, 0, W, 9, C.BLACK)
        t.text(3, 2, "LAP 1/3  0:42.318  BEST 1:01.204", C.WHITE)
        t.text(W - 4 * len(label) - 3, 2, label, C.YELLOW)
        t.rect(W - 62, H - 22, 58, 18, C.BLACK)
        t.text(W - 58, H - 19, "142 KM/H", C.WHITE)
        t.text(W - 58, H - 11, "GEAR 3  6200", C.CREAM)
