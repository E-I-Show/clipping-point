"""Toy race world standing in for the real simulation (pure Python).

It has what the determinism harness needs: fixed 60 Hz ticks, float maths with libm calls,
a sequential stream (grid order, AI pace) and a hash draw (per car / lap / corner error).
"""
import hashlib
import math
import struct

from .rng import RngSet, hash_unit

TICK_HZ = 60
TICK_DT = 1.0 / TICK_HZ
LAP_M = 1800.0
CORNERS = (150.0, 420.0, 610.0, 880.0, 1010.0, 1230.0, 1400.0, 1580.0, 1720.0)


class Car:
    __slots__ = ("car_id", "s", "v", "lap", "pace", "lateral", "best_lap_ticks", "lap_start_tick")

    def __init__(self, car_id: str, s: float, pace: float) -> None:
        self.car_id = car_id
        self.s = s
        self.v = 0.0
        self.lap = 0
        self.pace = pace
        self.lateral = 0.0
        self.best_lap_ticks = 0
        self.lap_start_tick = 0


class World:
    def __init__(self, seed: int, car_ids: list, player_index: int = 0) -> None:
        self.seed = seed
        self.rng = RngSet(seed)
        self.tick = 0
        order = list(car_ids)
        self.rng.stream("grid").shuffle(order)
        ai = self.rng.stream("ai")
        self.cars = [Car(cid, -8.0 * i, ai.uniform(0.94, 1.0)) for i, cid in enumerate(order)]
        self.player_id = car_ids[player_index]

    def _target_speed(self, car: Car) -> float:
        base = 50.0 * car.pace
        nxt = min(CORNERS, key=lambda c: (c - car.s) % LAP_M)
        dist = (nxt - car.s) % LAP_M
        if dist < 60.0:
            # stateless draw: same answer for the same (car, lap, corner) however often it is asked
            err = hash_unit(self.seed, "brake", car.car_id, car.lap, CORNERS.index(nxt))
            base *= 0.45 + 0.1 * err
        return base

    def step(self, throttle: float = 1.0, steer: float = 0.0) -> None:
        for car in self.cars:
            target = self._target_speed(car)
            if car.car_id == self.player_id:
                target *= 0.5 + 0.5 * throttle
                car.lateral += steer * TICK_DT * 2.0
            car.v += (target - car.v) * 1.8 * TICK_DT
            car.lateral += math.sin(car.s * 0.013) * 0.004 - car.lateral * 0.02
            car.s += car.v * math.cos(car.lateral * 0.1) * TICK_DT
            if car.s >= LAP_M:
                car.s -= LAP_M
                car.lap += 1
                lap_ticks = self.tick + 1 - car.lap_start_tick
                if car.best_lap_ticks == 0 or lap_ticks < car.best_lap_ticks:
                    car.best_lap_ticks = lap_ticks
                car.lap_start_tick = self.tick + 1
        self.tick += 1

    def player(self) -> Car:
        return next(c for c in self.cars if c.car_id == self.player_id)

    def standings(self) -> list:
        return sorted(self.cars, key=lambda c: (-c.lap, -c.s, c.car_id))

    # --- fingerprints --------------------------------------------------------------------
    def fingerprint_exact(self) -> str:
        """Every bit of the state. Stable inside one environment; differs across libm builds."""
        h = hashlib.sha256(struct.pack("<qq", self.seed, self.tick))
        for name, state in sorted(self.rng.state().items()):
            h.update(name.encode() + struct.pack("<Q", state))
        for c in self.cars:
            h.update(c.car_id.encode())
            h.update(struct.pack("<4dqqq", c.s, c.v, c.pace, c.lateral, c.lap, c.best_lap_ticks, c.lap_start_tick))
        return h.hexdigest()[:16]

    def summary(self) -> dict:
        """Readable snapshot: when the fingerprint moves, the diff says which car / field moved.
        Floats are stored as repr() (round-trip exact) so the JSON compares bit for bit."""
        return {
            "tick": self.tick,
            "grid": [c.car_id for c in self.cars],
            "order": [c.car_id for c in self.standings()],
            "rng": {k: f"{v:016x}" for k, v in sorted(self.rng.state().items())},
            "cars": {
                c.car_id: {"lap": c.lap, "best": c.best_lap_ticks, "s": repr(c.s), "v": repr(c.v), "lat": repr(c.lateral)}
                for c in self.cars
            },
            "exact": self.fingerprint_exact(),
        }

    def summary_portable(self, digits: int = 3) -> dict:
        """Coarse snapshot for comparing native against the browser build (libm differs by 1 ulp)."""
        return {
            "tick": self.tick,
            "grid": [c.car_id for c in self.cars],
            "rng": {k: f"{v:016x}" for k, v in sorted(self.rng.state().items())},
            "cars": {c.car_id: {"lap": c.lap, "s": round(c.s, digits), "v": round(c.v, digits)} for c in self.cars},
        }


def run_scenario(name: str) -> World:
    """Fixed-input scenarios used by the snapshot test, the headless smoke run and the web smoke run."""
    spec = SCENARIOS[name]
    world = World(spec["seed"], list(spec["cars"]))
    for t in range(spec["ticks"]):
        world.step(throttle=1.0 if (t // 90) % 4 else 0.3, steer=math.sin(t * 0.05) * 0.5)
    return world


CAR_IDS = ("tsubame_1600", "kazane_rs", "shirogane_gtt", "arashi_4t")
SCENARIOS = {
    "ta_600": {"seed": 1, "cars": CAR_IDS[:1], "ticks": 600},
    "race_3600": {"seed": 20261111, "cars": CAR_IDS + ("tsubame_1600#2", "kazane_rs#2"), "ticks": 3600},
}
