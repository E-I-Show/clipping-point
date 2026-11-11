import sys
import pyxel
pyxel.init(64, 64, headless=True)
which = sys.argv[1]
try:
    if which == "btn_on_axis":
        print("btn(axis) ->", pyxel.btn(pyxel.GAMEPAD1_AXIS_LEFTX))
    elif which == "btnv_on_button":
        print("btnv(button) ->", pyxel.btnv(pyxel.GAMEPAD1_BUTTON_A))
    elif which == "set_btn_on_axis":
        pyxel.set_btn(pyxel.GAMEPAD1_AXIS_LEFTX, True); print("set_btn(axis) ok")
        print("btnv(axis) after ->", pyxel.btnv(pyxel.GAMEPAD1_AXIS_LEFTX))
    elif which == "set_btnv_on_button":
        pyxel.set_btnv(pyxel.GAMEPAD1_BUTTON_A, 1); print("set_btnv(button) ok")
        print("btn(button) after ->", pyxel.btn(pyxel.GAMEPAD1_BUTTON_A))
except BaseException as e:
    print("caught:", type(e).__mro__[:3], str(e)[:120])
    sys.stdout.flush()
    sys.exit(7)
