"""Logic-side audio interface (pure Python, no pyxel import).

The simulation only *describes* what should be heard. The Pyxel adapter (pyxel_audio.py) decides how.
"""
from dataclasses import dataclass, field
from enum import IntEnum
from math import log2


class Scene(IntEnum):
    MENU = 0
    RACE = 1
    REPLAY = 2
    RESULT = 3
    SILENT = 4


class Ev(IntEnum):
    CONTACT = 0  # strength = closing speed normalized 0..1
    SHIFT = 1
    COUNT_BEEP = 2  # 3, 2, 1
    COUNT_GO = 3


@dataclass(slots=True)
class CarAudio:
    engine: int = 0  # engine timbre id (index into sound_data.ENGINES)
    rpm: float = 900.0
    throttle: float = 0.0  # 0..1
    slip: float = 0.0  # 0..1, 0 = gripping, 1 = fully sliding (already thresholded by the logic)
    on_curb: bool = False
    off_road: bool = False  # grass / gravel
    speed: float = 0.0  # m/s
    dist: float = 0.0  # distance to the listener in metres (0 for the listener's own car)


@dataclass(slots=True)
class AudioFrame:
    scene: Scene = Scene.SILENT
    paused: bool = False
    player: CarAudio | None = None
    others: list[CarAudio] = field(default_factory=list)
    events: list[tuple[Ev, float]] = field(default_factory=list)  # (event, strength)


# ---- pure mapping functions (unit-testable without pyxel) ----

def rpm_to_detune(rpm: float, ref_rpm: float) -> int:
    """Cents relative to the base note that sounds right at ref_rpm. Channel.detune must be an int."""
    return round(1200.0 * log2(max(rpm, 1.0) / ref_rpm))


def engine_gain(throttle: float, rpm: float, idle_rpm: float, max_rpm: float, g_off: float, g_on: float) -> float:
    r = min(max((rpm - idle_rpm) / (max_rpm - idle_rpm), 0.0), 1.0)
    return (g_off + (g_on - g_off) * throttle) * (0.75 + 0.25 * r)


def squeal_gain(slip: float, g_max: float, knee: float = 0.15) -> float:
    if slip <= knee:
        return 0.0
    return g_max * min((slip - knee) / (1.0 - knee), 1.0)


def distance_gain(dist: float, d_ref: float = 6.0, d_max: float = 60.0) -> float:
    """1 at d_ref or closer, falls with 1/d, 0 at d_max."""
    if dist >= d_max:
        return 0.0
    g = d_ref / max(dist, d_ref)
    return g * (1.0 - dist / d_max)


class NearestPicker:
    """Pick the nearest other car with hysteresis so the channel does not flap between two cars."""

    def __init__(self, switch_ratio: float = 0.8, min_hold_ticks: int = 20):
        self.current = -1
        self.hold = 0
        self.switch_ratio = switch_ratio
        self.min_hold_ticks = min_hold_ticks

    def pick(self, dists: list[float]) -> int:
        if not dists:
            self.current = -1
            return -1
        best = min(range(len(dists)), key=dists.__getitem__)
        self.hold += 1
        if self.current < 0 or self.current >= len(dists):
            self.current, self.hold = best, 0
        elif best != self.current and self.hold >= self.min_hold_ticks \
                and dists[best] < dists[self.current] * self.switch_ratio:
            self.current, self.hold = best, 0
        return self.current
