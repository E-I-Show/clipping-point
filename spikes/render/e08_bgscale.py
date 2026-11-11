import json, time, math
import pyxel
import common as C
pyxel.init(320, 240, headless=True)
C.apply_palette("evening")
bg = C.make_background("evening")
buf = pyxel.Image(320, 240)
out = {}
# scaled blt of a 160x80 window of the panorama around the horizon -> 2x zoom (scale is about the blt center)
def zoom(scale):
    buf.cls(C.SKY0)
    sw, sh = int(320 / scale), int(240 / scale)
    # source window centered on the horizon row 150; destination center = screen center
    buf.blt(160 - sw / 2, 120 - sh / 2, bg, 100, 150 - sh // 2, sw, sh, None, 0.0, scale)
for s in (1.0, 2.0, 4.0):
    ts = []
    for _ in range(100):
        t0 = time.perf_counter(); zoom(s); ts.append((time.perf_counter() - t0) * 1000)
    ts.sort(); out[f"scaled_blt_x{s}_median_ms"] = round(ts[50], 4)
    pyxel.blt(0, 0, buf, 0, 0, 320, 240); pyxel.screen.save(f"out/e08_bg_zoom_{s}.png", 1)
    out[f"x{s}_horizon_row_color_at_(160,119),(160,121)"] = [buf.pget(160, 118), buf.pget(160, 122)]
json.dump(out, open("out/e08_bgscale.json", "w"), indent=1); print(out)
