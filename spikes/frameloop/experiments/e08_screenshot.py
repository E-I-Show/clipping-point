"""E8: PNG screenshots in headless mode; cwd change done by pyxel.init."""
import os
import sys
import time

cwd_before = os.getcwd()
import pyxel

pyxel.init(320, 240, fps=60, headless=True)
cwd_after = os.getcwd()
print("cwd before init:", cwd_before)
print("cwd after  init:", cwd_after, "(script dir:", os.path.dirname(os.path.abspath(__file__)) + ")")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
pyxel.colors[:] = [0x000000, 0xFF0000, 0x00FF00, 0x0000FF, 0x123456] + [0x808080] * 27  # 32 colours
pyxel.cls(4)
pyxel.rect(0, 0, 10, 10, 1)
pyxel.rect(310, 230, 10, 10, 2)
pyxel.text(100, 100, "CLIPPING POINT 0123", 3)

t0 = time.perf_counter()
pyxel.screen.save(os.path.join(out, "e08_screen_save_x1"), 1)       # no extension given
t1 = time.perf_counter()
pyxel.screen.save(os.path.join(out, "e08_screen_save_x2.png"), 2)
pyxel.screenshot(os.path.join(out, "e08_screenshot_default"))        # scale=None -> capture_scale (2)
pyxel.screenshot(os.path.join(out, "e08_screenshot_x1.png"), 1)
pyxel.screen.save("e08_rel.png", 1)                                  # relative path -> where?
try:
    pyxel.screen.save(os.path.join(out, "no_such_dir", "x.png"), 1)
    print("save into missing dir: no error (!)")
except Exception as e:
    print("save into missing dir ->", type(e).__name__, e)
print(f"screen.save 320x240 x1 took {(t1 - t0) * 1000:.2f} ms")

from PIL import Image

for name in sorted(os.listdir(out)):
    if name.startswith("e08_"):
        im = Image.open(os.path.join(out, name))
        rgb = im.convert("RGB")
        s = im.size[0] // 320
        print(
            f"{name}: size={im.size} mode={im.mode} px(0,0)={rgb.getpixel((0, 0))} "
            f"px(bottom-right)={rgb.getpixel((im.size[0] - 1, im.size[1] - 1))} px(center bg)={rgb.getpixel((160 * s, 20 * s))}"
        )
print("relative save landed at:", [p for p in (os.path.join(cwd_after, "e08_rel.png"), os.path.join(cwd_before, "e08_rel.png")) if os.path.exists(p)])
# Image without init screen: offscreen image save + pixel readback
img = pyxel.Image(320, 240)
img.cls(2)
img.save(os.path.join(out, "e08_offscreen.png"), 1)
print("offscreen saved:", Image.open(os.path.join(out, "e08_offscreen.png")).convert("RGB").getpixel((5, 5)))
