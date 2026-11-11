import json, math, sys, time
import pyxel
from pyxel.cube import Vec3
import common as C
from world import World, W, H

tod = sys.argv[1] if len(sys.argv) > 1 else "evening"
pyxel.init(W, H, headless=True)
w = World(tod)
out = {"tris": w.tri, "sections": len(w.sec_info), "track_segments": len(w.frames)}
# track length
L = sum(math.hypot(w.frames[i][0] - w.frames[i - 1][0], w.frames[i][1] - w.frames[i - 1][1]) for i in range(len(w.frames)))
out["track_length_m"] = round(L, 1); out["segment_len_m"] = round(L / len(w.frames), 2)
x, z, h = w.place_cars(8.0)
shots = {
    "chase": w.cam_chase(x, z, h),
    "bumper": w.cam_bumper(x, z, h),
    "tv": w.cam_tv(*w.track_pose(w.car_s[2], 0.0), post_s=27.5, side=-1),
    "tv_wide": w.cam_tv(*w.track_pose(w.car_s[2], 0.0), post_s=13.0, side=-1, height=6.0, frame_m=16.0),
}
for name, (eye, tgt, fov) in shots.items():
    w.cars[0].visible = name != "bumper"
    w.set_camera(eye, tgt, fov)
    w.draw_scene()
    w.draw_hud(name.upper())
    pyxel.blt(0, 0, w.buf, 0, 0, W, H)
    pyxel.screen.save(f"out/proto_{tod}_{name}.png", 2)
    out[name] = {"fov": round(fov, 1), "visible_sections": w.visible_sections, "sprites_drawn": w.sprites.drawn}
json.dump(out, open(f"out/e10_proto_{tod}.json", "w"), indent=1); print(out)
