"""E10: approach (b): fps=30 and two 60 Hz ticks inside one update().
What do the two sub-ticks see from btn/btnp/btnv?"""
import pyxel

pyxel.init(64, 64, fps=1000, capture_sec=0, headless=True)  # fps value irrelevant to the semantics
K = pyxel.KEY_SPACE
LX = pyxel.GAMEPAD1_AXIS_LEFTX
print("frame subtick | btn btnp btnr | LX")
for frame in range(6):
    if frame == 2:
        pyxel.set_btn(K, True)
        pyxel.set_btnv(LX, 20000)
    if frame == 4:
        pyxel.set_btn(K, False)
    for sub in range(2):
        print(f"{frame:>5} {sub:>7} | {int(pyxel.btn(K))} {int(pyxel.btnp(K))} {int(pyxel.btnr(K))} | {pyxel.btnv(LX)}")
    pyxel.flip()
