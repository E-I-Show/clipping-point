"""Reads Pyxel input into a RawInput, and injects scripted input through Pyxel's own setters."""

import pyxel

from cp_core.controls import RawInput

# logical control -> Pyxel key. Axis keys must be read with btnv, button keys with btn/btnp:
# btn() on an axis key (or btnv() on a button key) panics inside Pyxel (PanicException).
AXIS_KEYS = {
    "steer_axis": pyxel.GAMEPAD1_AXIS_LEFTX,
    "throttle_axis": pyxel.GAMEPAD1_AXIS_TRIGGERRIGHT,
    "brake_axis": pyxel.GAMEPAD1_AXIS_TRIGGERLEFT,
}
BUTTON_KEYS = {
    "left": (pyxel.KEY_LEFT, pyxel.GAMEPAD1_BUTTON_DPAD_LEFT),
    "right": (pyxel.KEY_RIGHT, pyxel.GAMEPAD1_BUTTON_DPAD_RIGHT),
    "accel": (pyxel.KEY_UP, pyxel.GAMEPAD1_BUTTON_A),
    "brake": (pyxel.KEY_DOWN, pyxel.GAMEPAD1_BUTTON_B),
    "shift_up": (pyxel.KEY_X, pyxel.GAMEPAD1_BUTTON_RIGHTSHOULDER),
    "start": (pyxel.KEY_RETURN, pyxel.GAMEPAD1_BUTTON_START),
}


def _down(name: str) -> bool:
    return any(pyxel.btn(k) for k in BUTTON_KEYS[name])


def _pressed(name: str) -> bool:
    return any(pyxel.btnp(k) for k in BUTTON_KEYS[name])


def read_raw_input() -> RawInput:
    """Call once per update() (= once per 60 Hz tick)."""
    return RawInput(
        steer_axis=pyxel.btnv(AXIS_KEYS["steer_axis"]),
        throttle_axis=pyxel.btnv(AXIS_KEYS["throttle_axis"]),
        brake_axis=pyxel.btnv(AXIS_KEYS["brake_axis"]),
        left=_down("left"),
        right=_down("right"),
        accel=_down("accel"),
        brake=_down("brake"),
        shift_up_pressed=_pressed("shift_up"),
        start_pressed=_pressed("start"),
    )


def inject(control: str, value) -> None:
    """Scripted input: goes through the same btn/btnp/btnv path the game reads."""
    if control in AXIS_KEYS:
        pyxel.set_btnv(AXIS_KEYS[control], int(value))
    elif control in BUTTON_KEYS:
        pyxel.set_btn(BUTTON_KEYS[control][0], bool(value))
    else:
        raise KeyError(f"unknown control {control!r}")
