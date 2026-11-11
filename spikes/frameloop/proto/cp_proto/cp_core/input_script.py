"""Scripted logical input (pure Python, no pyxel): the basis for autopilot tests and screen tours.

A script is a list of (tick, control, value). The same script is
  * injected through pyxel.set_btn / pyxel.set_btnv by cp_app.smoke (real Pyxel input path), and
  * replayed by `reference_raw_inputs` with no Pyxel at all (the expected result).
If both give the same Sim fingerprint, the Pyxel input path behaves as modelled here.
"""

from .controls import RawInput

AXIS_CONTROLS = ("steer_axis", "throttle_axis", "brake_axis")
BUTTON_CONTROLS = ("left", "right", "accel", "brake", "shift_up", "start")
EDGE_CONTROLS = ("shift_up", "start")  # read with btnp

DEMO_SCRIPT = [
    (5, "throttle_axis", 32767),
    (20, "shift_up", True),
    (21, "shift_up", False),
    (30, "steer_axis", -16000),
    (45, "steer_axis", 0),
    (50, "shift_up", True),  # press and release inside one tick: must still count once
    (50, "shift_up", False),
    (55, "right", True),
    (70, "right", False),
    (80, "throttle_axis", 0),
    (80, "brake_axis", 20000),
    (95, "brake_axis", 0),
    (96, "accel", True),
    (100, "shift_up", True),
    (104, "shift_up", False),
]

# Screen tour: drive the app through its screens and name the ticks at which to save a PNG.
TOUR_SCRIPT = [
    (2, "accel", True),
    (12, "start", True),  # -> PAUSE
    (13, "start", False),
    (24, "start", True),  # -> back to RACE
    (25, "start", False),
]
TOUR_SHOTS = [(10, "race"), (20, "pause"), (40, "race_resumed")]
TOUR_TICKS = 41

SCRIPTS = {"demo": DEMO_SCRIPT, "tour": TOUR_SCRIPT}


def validate_script(script) -> None:
    last_tick = -1
    for tick, control, value in script:
        if tick < last_tick:
            raise ValueError(f"script not sorted by tick at {tick}")
        last_tick = tick
        if control in AXIS_CONTROLS:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"axis value must be int: {control}={value!r}")
        elif control in BUTTON_CONTROLS:
            if not isinstance(value, bool):
                raise ValueError(f"button value must be bool: {control}={value!r}")
        else:
            raise ValueError(f"unknown control {control!r}")


def events_by_tick(script) -> dict:
    validate_script(script)
    table: dict = {}
    for tick, control, value in script:
        table.setdefault(tick, []).append((control, value))
    return table


def reference_raw_inputs(script, n_ticks: int):
    """Yield the RawInput each tick would see, modelling Pyxel's btn / btnp semantics."""
    table = events_by_tick(script)
    axes = dict.fromkeys(AXIS_CONTROLS, 0)
    held = dict.fromkeys(BUTTON_CONTROLS, False)
    for tick in range(n_ticks):
        pressed = dict.fromkeys(EDGE_CONTROLS, False)
        for control, value in table.get(tick, []):
            if control in axes:
                axes[control] = value
            else:
                if control in pressed and value:
                    pressed[control] = True
                held[control] = value
        yield RawInput(
            steer_axis=axes["steer_axis"],
            throttle_axis=axes["throttle_axis"],
            brake_axis=axes["brake_axis"],
            left=held["left"],
            right=held["right"],
            accel=held["accel"],
            brake=held["brake"],
            shift_up_pressed=pressed["shift_up"],
            start_pressed=pressed["start"],
        )
