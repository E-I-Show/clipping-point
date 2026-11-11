"""Game-level state driven once per 60 Hz tick (pure Python, no pyxel)."""

from .controls import RawInput, resolve
from .sim import Sim


class Game:
    def __init__(self) -> None:
        self.sim = Sim()
        self.paused = False
        self.ticks = 0  # ticks seen, including paused ones

    def tick(self, raw: RawInput) -> None:
        if raw.start_pressed:
            self.paused = not self.paused
        if not self.paused:
            self.sim.step(resolve(raw))
        self.ticks += 1

    def fingerprint(self) -> str:
        return f"{self.sim.fingerprint()}-{self.ticks}-{int(self.paused)}"
