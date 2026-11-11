import json, math, sys, time
import pyxel
from pyxel.cube import Camera, Mat4, Node, Primitive, Shading, Vec3, Mesh
import common as C

pyxel.init(320, 240, headless=True)
sh = C.apply_palette("evening")
out = {}
p = C.car_prims()
out["car_tris"] = {"total": p["tris"], "body": p["body_tris"], "wheel_each": p["wheel_tris"]}
out["body_vertices"] = len(p["body"].positions) // 3
out["normals_len_body"] = len(p["body"].normals)

scene = Node(); scene.shading = sh; scene.camera = Camera(); scene.camera.clear_color = C.GRASS_D
cam = scene.camera; cam.fov = 40; cam.near = 0.2; cam.far = 300
class Ground(Node):
    def on_draw(self):
        self.rect(Mat4.from_translation(Vec3(0, 0, 0)).rotate_x(-90), 60, 60, C.ASPH_M)
scene.add_child(Ground())
bodies = [C.RED, C.BLUE, C.YELLOW, C.WHITE, C.GRASS_M, C.GRAY_D]
cars = []
for i, col in enumerate(bodies):
    car = C.Car(C.make_car_texture(col, stripe=C.WHITE))
    cars.append(car); scene.add_child(car)
# layout: 3x2 grid, each rotated differently
def layout(base_heading, steer=0.0, pitch=0.0, roll=0.0):
    for i, car in enumerate(cars):
        x = (i % 3 - 1) * 5.5; z = (i // 3 - 0.5) * 6.0
        car.set_pose(x, 0, z, base_heading + i * math.radians(60), pitch, roll, steer_deg=steer, spin_deg=i * 20)
views = [("front34", 0.0, Vec3(-11, 5.0, 13)), ("rear34", math.pi, Vec3(-11, 5.0, 13)), ("top", 0.5, Vec3(0.1, 22, 2.0)), ("low", 1.2, Vec3(-13, 1.0, 10))]
for name, hd, eye in views:
    layout(hd, steer=25.0)
    cam.transform = Mat4.look_at(eye, Vec3(0, 0.5, 0))
    scene.draw(0, 0, 320, 240)
    pyxel.text(4, 4, f"{name}  {p['tris']} tris/car", C.WHITE)
    pyxel.screen.save(f"out/e03_car_{name}.png", 2)
# close-up single car: heading check + roll/pitch + brake lamp
for c in cars[1:]: c.visible = False
car = cars[0]
cam.fov = 30
shots = [("h0_from_+z_side", 0.0, 0, 0, Vec3(0, 1.2, 9)),       # heading 0: nose should point to +x = screen right when camera is at +z looking toward -z
         ("h90_from_+z_side", math.pi / 2, 0, 0, Vec3(0, 1.2, 9)),  # heading +90deg: nose toward +z = toward camera
         ("rear_roll_right_5deg", 0.0, 0.0, math.radians(8), Vec3(-9, 1.2, 0)),
         ("side_pitch_up_5deg", 0.0, math.radians(8), 0.0, Vec3(0, 1.2, 9)),
         ("rear_close", 0.0, 0.0, 0.0, Vec3(-6.5, 1.6, 2.2))]
for name, hd, pitch, roll, eye in shots:
    car.set_pose(0, 0, 0, hd, pitch, roll, steer_deg=20.0)
    cam.transform = Mat4.look_at(eye, Vec3(0, 0.6, 0))
    scene.draw(0, 0, 320, 240)
    pyxel.text(4, 4, name, C.WHITE)
    pyxel.screen.save(f"out/e03_one_{name}.png", 2)
# verify nose direction numerically: where is the headlight (CREAM) centroid on screen for h0 from +z
car.set_pose(0, 0, 0, 0.0); cam.transform = Mat4.look_at(Vec3(0, 1.2, 9), Vec3(0, 0.6, 0)); scene.draw(0, 0, 320, 240)
def centroid(col):
    pts = [(x, y) for y in range(240) for x in range(320) if pyxel.pget(x, y) == col]
    return None if not pts else [round(sum(q[0] for q in pts) / len(pts), 1), round(sum(q[1] for q in pts) / len(pts), 1), len(pts)]
out["h0_cam_at_+z: headlight(CREAM) centroid"] = centroid(C.CREAM)
out["h0_cam_at_+z: taillight(BRAKE) centroid"] = centroid(C.BRAKE)
# top view to check right side: steer right 30deg front wheels + heading 0, camera above, up = -z? use look_at with up vector
car.set_pose(0, 0, 0, 0.0, steer_deg=30.0)
cam.transform = Mat4.look_at(Vec3(0, 14, 0.01), Vec3(0, 0, 0))
scene.draw(0, 0, 320, 240); pyxel.screen.save("out/e03_one_top_steer_right30.png", 2)
json.dump(out, open("out/e03_car.json", "w"), indent=1); print(out)
