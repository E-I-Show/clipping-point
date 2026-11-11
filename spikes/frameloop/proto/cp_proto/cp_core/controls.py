"""Raw device values -> normalized controls (pure Python, no pyxel).

Pyxel passes SDL game-controller values through unchanged (poll_events.rs: caxis.value as i32):
sticks -32768..32767, triggers 0..32767. No dead zone is applied by Pyxel.
The curve / speed-sensitive assist layer would sit after `resolve` (not part of this spike).
"""

from dataclasses import dataclass

AXIS_MAX = 32767
STICK_DEADZONE = 0.12  # placeholder value for the spike only


@dataclass(frozen=True)
class RawInput:
    steer_axis: int = 0  # GAMEPAD1_AXIS_LEFTX
    throttle_axis: int = 0  # GAMEPAD1_AXIS_TRIGGERRIGHT
    brake_axis: int = 0  # GAMEPAD1_AXIS_TRIGGERLEFT
    left: bool = False
    right: bool = False
    accel: bool = False
    brake: bool = False
    shift_up_pressed: bool = False  # edge (btnp), true for exactly one tick per press
    start_pressed: bool = False  # edge (btnp)


@dataclass(frozen=True)
class Controls:
    steer: float  # -1 (left) .. +1 (right)
    throttle: float  # 0 .. 1
    brake: float  # 0 .. 1
    shift_up: bool


def axis_to_unit(value: int) -> float:
    return max(-1.0, min(1.0, value / AXIS_MAX))


def trigger_to_unit(value: int) -> float:
    return max(0.0, min(1.0, value / AXIS_MAX))


def resolve(raw: RawInput) -> Controls:
    steer = axis_to_unit(raw.steer_axis)
    if abs(steer) < STICK_DEADZONE:
        steer = float(raw.right) - float(raw.left)
    throttle = max(trigger_to_unit(raw.throttle_axis), float(raw.accel))
    brake = max(trigger_to_unit(raw.brake_axis), float(raw.brake))
    return Controls(steer=steer, throttle=throttle, brake=brake, shift_up=raw.shift_up_pressed)
