"""Toy deterministic simulation (pure Python, no pyxel). Stands in for the vehicle model."""

import hashlib
import math
import struct

from .controls import Controls
from .fixed_loop import TICK_DT


class Sim:
    def __init__(self, max_speed: float = 50.0) -> None:
        self.tick = 0
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self.speed = 0.0
        self.gear = 1
        self.shift_count = 0
        self.max_speed = max_speed

    def step(self, c: Controls, dt: float = TICK_DT) -> None:
        if c.shift_up:
            self.gear = self.gear % 5 + 1
            self.shift_count += 1
        accel = 8.0 * c.throttle - 14.0 * c.brake - 0.02 * self.speed
        self.speed = max(0.0, min(self.max_speed, self.speed + accel * dt))
        self.heading += 1.2 * c.steer * dt * min(1.0, self.speed / 5.0)
        self.x += math.cos(self.heading) * self.speed * dt
        self.y += math.sin(self.heading) * self.speed * dt
        self.tick += 1

    def fingerprint(self) -> str:
        blob = struct.pack(
            "<I4dII", self.tick, self.x, self.y, self.heading, self.speed, self.gear, self.shift_count
        )
        return hashlib.sha256(blob).hexdigest()[:16]
