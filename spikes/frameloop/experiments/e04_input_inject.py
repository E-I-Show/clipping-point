"""E4: set_btn / set_btnv -> btn / btnp / btnr / btnv, inside pyxel.run (headless)."""
import sys

import pyxel

K = pyxel.KEY_SPACE
A = pyxel.GAMEPAD1_BUTTON_A
LX = pyxel.GAMEPAD1_AXIS_LEFTX
RT = pyxel.GAMEPAD1_AXIS_TRIGGERRIGHT
LT = pyxel.GAMEPAD1_AXIS_TRIGGERLEFT

rows = []
draw_rows = {}
frame = 0

# script: frame -> list of actions applied at the START of update
script = {
    2: [("btn", K, True), ("btn", A, True), ("btnv", LX, -32768), ("btnv", RT, 32767)],
    5: [("btn", K, False), ("btn", A, False), ("btnv", LX, 12345), ("btnv", RT, 0)],
    7: [("btn", K, True), ("btn", K, False)],  # press+release in the same frame
    9: [("btnv", LX, 100000), ("btnv", LT, -5)],  # out-of-range values: are they clamped?
}


def update():
    global frame
    for kind, key, val in script.get(frame, []):
        if kind == "btn":
            pyxel.set_btn(key, val)
        else:
            pyxel.set_btnv(key, val)
    rows.append(
        (
            frame,
            pyxel.frame_count,
            pyxel.btn(K), pyxel.btnp(K), pyxel.btnr(K),
            pyxel.btn(A), pyxel.btnp(A), pyxel.btnr(A),
            pyxel.btnv(LX), pyxel.btnv(RT), pyxel.btnv(LT),
            list(pyxel.input_keys),
        )
    )
    frame += 1
    if frame >= 12:
        print("frame fc | SPACE btn btnp btnr | PAD_A btn btnp btnr | LX RT LT | input_keys | btnp(SPACE) seen in draw")
        for r in rows:
            f, fc, kb, kp, kr, ab, ap, ar, lx, rt, lt, ik = r
            print(
                f"{f:>5} {fc:>2} | {int(kb)} {int(kp)} {int(kr)} | {int(ab)} {int(ap)} {int(ar)} | {lx:>6} {rt:>6} {lt:>3} | {ik} | {draw_rows.get(f)}"
            )
        sys.stdout.flush()
        sys.exit(0)


def draw():
    # frame was already incremented by update
    draw_rows[frame - 1] = int(pyxel.btnp(K))


pyxel.init(64, 64, fps=1000, headless=True)
print("key codes: KEY_SPACE=%d GAMEPAD1_AXIS_LEFTX=0x%x GAMEPAD1_AXIS_TRIGGERRIGHT=0x%x GAMEPAD1_BUTTON_A=0x%x" % (K, LX, RT, A))
pyxel.run(update, draw)
