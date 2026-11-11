"""Top-level game state driven once per 60 Hz tick (pure Python): which screen, and the world."""
from .datadefs import GameData
from .world import World

SCREEN_ORDER = ("menu", "hud", "settings", "theater")
AXIS_MAX = 32767

# (tick, control, value): the fixed input of the headless smoke run, replayed here without Pyxel
SMOKE_SCRIPT = (
    (10, "start", True), (11, "start", False),  # menu -> hud
    (12, "throttle_axis", 32767), (30, "steer_axis", -16000), (60, "steer_axis", 9000),
    (80, "start", True), (81, "start", False),  # hud -> settings
    (95, "start", True), (96, "start", False),  # settings -> theater
    (110, "start", True), (110, "start", False),  # theater -> menu (press+release in one tick)
)


class Session:
    def __init__(self, data: GameData, seed: int = 7) -> None:
        self.data = data
        self.world = World(seed, sorted(data.table("cars")))
        self.screen_index = 0
        self.ticks = 0
        self.visited = [SCREEN_ORDER[0]]

    @property
    def screen(self) -> str:
        return SCREEN_ORDER[self.screen_index]

    def tick(self, start_pressed: bool, throttle_axis: int, steer_axis: int) -> None:
        if start_pressed:
            self.screen_index = (self.screen_index + 1) % len(SCREEN_ORDER)
            self.visited.append(self.screen)
        if self.screen == "hud":
            self.world.step(max(0.0, min(1.0, throttle_axis / AXIS_MAX)), max(-1.0, min(1.0, steer_axis / AXIS_MAX)))
        self.ticks += 1

    def fingerprint(self) -> str:
        return f"{self.world.fingerprint_exact()}-{self.ticks}-{self.screen}"


def script_events(tick: int) -> list:
    return [(c, v) for t, c, v in SMOKE_SCRIPT if t == tick]


def reference_session(data: GameData, ticks: int) -> Session:
    """What the app must end up with after `ticks` ticks of SMOKE_SCRIPT (btnp = pressed this tick)."""
    s = Session(data)
    axes = {"throttle_axis": 0, "steer_axis": 0}
    for t in range(ticks):
        pressed = False
        for control, value in script_events(t):
            if control == "start":
                pressed = pressed or value
            else:
                axes[control] = value
        s.tick(pressed, axes["throttle_axis"], axes["steer_axis"])
    return s
