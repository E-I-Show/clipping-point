import math, json, sys
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Quat, Mesh

pyxel.init(320, 240, headless=True)
out = {}
def v(a): return [round(a.x, 4), round(a.y, 4), round(a.z, 4)]
def m(a): return [[round(a[r, c], 4) for c in range(4)] for r in range(4)]
out["FORWARD"] = v(Vec3.FORWARD); out["BACK"] = v(Vec3.BACK)
out["RIGHT"] = v(Vec3.RIGHT); out["LEFT"] = v(Vec3.LEFT)
out["UP"] = v(Vec3.UP); out["DOWN"] = v(Vec3.DOWN)
# euler rotations (degrees?)
for name, e in [("ex90", Vec3(90, 0, 0)), ("ey90", Vec3(0, 90, 0)), ("ez90", Vec3(0, 0, 90))]:
    M = Mat4.from_euler(e)
    out[name] = {"mat": m(M), "X->": v(M * Vec3(1, 0, 0)), "Y->": v(M * Vec3(0, 1, 0)), "Z->": v(M * Vec3(0, 0, 1)),
                 "FORWARD->": v(Vec3.FORWARD.to_world_dir(M))}
# euler composition order
M = Mat4.from_euler(Vec3(30, 40, 50))
Rx = Mat4.IDENTITY.rotate_x(30); Ry = Mat4.IDENTITY.rotate_y(40); Rz = Mat4.IDENTITY.rotate_z(50)
import itertools
cands = {"Rx*Ry*Rz": Rx * Ry * Rz, "Rz*Ry*Rx": Rz * Ry * Rx, "Ry*Rx*Rz": Ry * Rx * Rz, "Rz*Rx*Ry": Rz * Rx * Ry, "Ry*Rz*Rx": Ry * Rz * Rx, "Rx*Rz*Ry": Rx * Rz * Ry}
def close(a, b): return all(abs(a[r, c] - b[r, c]) < 1e-4 for r in range(4) for c in range(4))
out["euler_order"] = [k for k, c in cands.items() if close(M, c)]
# axis-angle variants
A = Mat4.from_axis_angle(Vec3(1,0,0), 30); out["rotate_x==from_axis_angle(X)"] = close(A, Rx)
# translate / rotate method = post or pre multiply?
T = Mat4.from_translation(Vec3(1, 2, 3))
R = Mat4.from_euler(Vec3(0, 90, 0))
out["T.rotate_y(90)==T*R"] = close(T.rotate_y(90), T * R)
out["T.rotate_y(90)==R*T"] = close(T.rotate_y(90), R * T)
out["R.translate(v)==R*T"] = close(R.translate(Vec3(1, 2, 3)), R * T)
out["R.translate(v)==T*R"] = close(R.translate(Vec3(1, 2, 3)), T * R)
out["T_mat"] = m(T)
# look_at
L = Mat4.look_at(Vec3(0, 0, 0), Vec3(10, 0, 0))
out["look_at(+x)"] = {"mat": m(L), "FORWARD->": v(Vec3.FORWARD.to_world_dir(L)), "RIGHT->": v(Vec3.RIGHT.to_world_dir(L)), "UP->": v(Vec3.UP.to_world_dir(L)), "-Zcol": [round(-L[0,2],4), round(-L[1,2],4), round(-L[2,2],4)]}
L2 = Mat4.look_at(Vec3(5, 2, 5), Vec3(5, 0, 15))
out["look_at(eye(5,2,5)->(5,0,15))"] = {"pos": v(L2.pos), "FORWARD->": v(Vec3.FORWARD.to_world_dir(L2)), "RIGHT->": v(Vec3.RIGHT.to_world_dir(L2)), "UP->": v(Vec3.UP.to_world_dir(L2))}
# node forward/right/up
n = Node(); n.transform = Mat4.from_euler(Vec3(0, 90, 0))
out["node(ey90)"] = {"forward": v(n.forward), "right": v(n.right), "up": v(n.up)}
n.transform = Mat4.IDENTITY
out["node(identity)"] = {"forward": v(n.forward), "right": v(n.right), "up": v(n.up)}
# Quat
q = Quat.from_euler(Vec3(0, 90, 0)); out["quat_ey90*X"] = v(q * Vec3(1, 0, 0))
q2 = Quat.from_direction(Vec3(1, 0, 0)); out["Quat.from_direction(+x)*FORWARD"] = v(q2 * Vec3.FORWARD)
out["Quat.from_direction(+x).to_euler"] = v(q2.to_euler())
# projection check: where does a point at camera-right appear on screen
scene = Node(); scene.camera = Camera(); scene.camera.clear_color = 0
scene.camera.transform = Mat4.look_at(Vec3(0, 0, 0), Vec3(0, 0, -10))
class P(Node):
    def on_draw(self):
        self.shaded(False)
        self.box(Mat4.from_translation(Vec3(3, 0, -10)), Vec3(1, 1, 1), 8)   # +x  red
        self.box(Mat4.from_translation(Vec3(0, 3, -10)), Vec3(1, 1, 1), 11)  # +y green
scene.add_child(P())
scene.draw(0, 0, 320, 240)
def find(col):
    xs = [(x, y) for y in range(240) for x in range(320) if pyxel.pget(x, y) == col]
    if not xs: return None
    return [sum(p[0] for p in xs) / len(xs), sum(p[1] for p in xs) / len(xs)]
out["cam_look_-z: +x box screen"] = find(8); out["cam_look_-z: +y box screen"] = find(11)
out["default_cam"] = {"fov": scene.camera.fov, "near": scene.camera.near, "far": scene.camera.far, "ortho": scene.camera.ortho_size, "clear": scene.camera.clear_color}
# fov vertical or horizontal? box at distance 10 with half-height tan(fov/2)*10
cam = scene.camera; cam.fov = 60
class Q(Node):
    def on_draw(self):
        self.shaded(False)
        h = math.tan(math.radians(30)) * 10
        self.box(Mat4.from_translation(Vec3(0, h, -10)), Vec3(0.2, 0.2, 0.2), 9)
        self.box(Mat4.from_translation(Vec3(h, 0, -10)), Vec3(0.2, 0.2, 0.2), 10)
scene2 = Node(); scene2.camera = cam; scene2.add_child(Q()); scene2.draw(0, 0, 320, 240)
out["fov60: point at y=tan(30)*10 screen"] = find(9); out["fov60: point at x=tan(30)*10 screen"] = find(10)
json.dump(out, open("out/e01_coords.json", "w"), indent=1)
print(json.dumps(out, indent=1))
