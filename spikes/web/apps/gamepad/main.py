"""What does Pyxel report for a browser gamepad (analog sticks, analog triggers, buttons)?

Driven by tools/fake_gamepad.js (a synthetic W3C "standard" mapping pad). For each step the
driver sets known values; this app reports pyxel.btnv / pyxel.btn and, for comparison, the raw
values read straight from navigator.getGamepads() through `import js`.
"""

import json
import time

import js
import pyxel

AXES = ["LEFTX", "LEFTY", "RIGHTX", "RIGHTY", "TRIGGERLEFT", "TRIGGERRIGHT"]
BUTTONS = ["A", "B", "X", "Y", "BACK", "GUIDE", "START", "LEFTSTICK", "RIGHTSTICK", "LEFTSHOULDER",
           "RIGHTSHOULDER", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]  # fmt: skip

frame = 0
seen_step = 0
step_frame = 0
ffi_ms = None


def sample():
    out = {"btnv": {}, "btn_pressed": []}
    for a in AXES:
        out["btnv"][a] = pyxel.btnv(getattr(pyxel, "GAMEPAD1_AXIS_" + a))
    for b in BUTTONS:
        if pyxel.btn(getattr(pyxel, "GAMEPAD1_BUTTON_" + b)):
            out["btn_pressed"].append(b)
    return out


def raw_pad():
    """Direct read through the JS bridge: analog values of every button (triggers are 6 and 7)."""
    pads = js.navigator.getGamepads()
    pad = pads[0]
    if pad is None or not isinstance(pad.connected, bool):
        return None
    return {
        "mapping": str(pad.mapping),
        "axes": [float(pad.axes[i]) for i in range(int(pad.axes.length))],
        "lt": float(pad.buttons[6].value),
        "rt": float(pad.buttons[7].value),
    }


def update():
    global frame, seen_step, step_frame, ffi_ms
    frame += 1
    if frame == 5:
        print("STAGE pad_connect")
    step = int(js.window.__padStep)
    if step != seen_step:
        seen_step = step
        step_frame = frame
    # report 6 frames after the driver changed the pad
    if seen_step and frame == step_frame + 6:
        if ffi_ms is None:
            t0 = time.perf_counter()
            for _ in range(200):
                raw_pad()
            ffi_ms = (time.perf_counter() - t0) / 200 * 1000
        print("RESULT_JSON pad_step%d %s" % (seen_step, json.dumps({"pyxel": sample(), "raw": raw_pad(), "raw_read_ms": round(ffi_ms, 4)})))
        print("STAGE pad_step%d_done" % seen_step)
        if seen_step == 6:
            print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "GAMEPAD STEP %d FRAME %d" % (seen_step, frame), 7)
    s = sample()
    y = 16
    for a in AXES:
        pyxel.text(4, y, "%-13s %6d" % (a, s["btnv"][a]), 10)
        y += 8
    pyxel.text(4, y + 4, " ".join(s["btn_pressed"])[:38], 11)


pyxel.init(160, 120, title="gamepad", fps=60)
pyxel.run(update, draw)
