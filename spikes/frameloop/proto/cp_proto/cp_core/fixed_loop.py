"""Fixed-step loop bookkeeping (pure Python, no pyxel).

Simulation and input run at TICK_HZ (one tick per Pyxel update() call, pyxel.init(fps=60)).
The expensive scene render runs at RENDER_HZ (30 fps): at most every RENDER_DIVISOR ticks.
"""

TICK_HZ = 60
RENDER_HZ = 30
TICK_DT = 1.0 / TICK_HZ
RENDER_DIVISOR = TICK_HZ // RENDER_HZ  # 2
# Wall-clock fallback: a little under one render period (33.3 ms) but above the longest gap
# between two consecutive 60 Hz frames on odd displays (26.7 ms on a 75 Hz monitor).
RENDER_MIN_INTERVAL_MS = 30.0


class RenderGate:
    """Decides, at each draw() call, whether the expensive scene render should run.

    Rule: render when
      (1) at least `divisor` ticks have elapsed since the last render, or
      (2) `min_interval_ms` of wall-clock time has passed since the last render started.

    Why not `pyxel.frame_count % 2`: when Pyxel catches up it calls update twice per draw, so
    the parity seen by draw() is constant and the scene is rendered never or always (e03).

    Why rule (2): the browser build reports a late frame one callback later than the native
    build (platform_sdl2.rs advance_frame_schedule and its unit test
    `reports_missed_frames_in_delta`). With rule (1) alone the desk model e12 settles at
    20 renders/s in a case where 30 fits. Rendering never feeds back into the simulation, so
    using the wall clock here does not affect determinism.
    """

    def __init__(self, divisor: int = RENDER_DIVISOR, min_interval_ms: float | None = RENDER_MIN_INTERVAL_MS) -> None:
        if divisor < 1:
            raise ValueError("divisor must be >= 1")
        self.divisor = divisor
        self.min_interval_ms = min_interval_ms
        self._ticks_since_render = divisor  # the very first draw renders
        self._last_render_ms: float | None = None

    def on_tick(self) -> None:
        self._ticks_since_render += 1

    def should_render(self, now_ms: float | None = None) -> bool:
        due = self._ticks_since_render >= self.divisor
        if (
            not due
            and now_ms is not None
            and self.min_interval_ms is not None
            and self._last_render_ms is not None
            and self._ticks_since_render >= 1  # never re-render an unchanged state
        ):
            due = now_ms - self._last_render_ms >= self.min_interval_ms
        if due:
            self._ticks_since_render = 0
            self._last_render_ms = now_ms
        return due
