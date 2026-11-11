"""E12: DESK MODEL (not a browser measurement) of Pyxel Web's frame scheduling for approach (a).

Ports two pieces of Pyxel 3.0.1 source to Python:
  * platform_sdl2.rs advance_frame_schedule()  (emscripten: called from requestAnimationFrame)
  * system.rs Pyxel::run closure               (update_count / catch-up, MAX_FRAME_DELAY_MS = 100)
and drives them with an idealised requestAnimationFrame (callbacks on vsync boundaries; a callback
that overruns delays the next one to the following vsync). Costs are made-up parameters.
"""
import math
import sys

sys.path.insert(0, __file__.rsplit("/experiments/", 1)[0] + "/proto/cp_proto")
from cp_core.fixed_loop import RenderGate  # noqa: E402

import struct

FPS = 60
FRAME_MS = 1000.0 / FPS  # f64, as in platform_sdl2.rs (frame_ms: f64)
MAX_FRAME_DELAY_MS = 100


def f32(x: float) -> float:
    """Round to the nearest IEEE single, as Rust's `as f32` does."""
    return struct.unpack("f", struct.pack("f", x))[0]


FRAME_MS_F32 = f32(1000.0 / FPS)  # system.rs: frame_ms: 1000.0 / fps as f32


def update_count(delta_ms_f64: float) -> int:
    """system.rs: (delta_ms / frame_ms) as u32 with both operands f32; then at least one update."""
    delta = f32(delta_ms_f64)
    n = 1 if delta > MAX_FRAME_DELAY_MS else int(f32(delta / FRAME_MS_F32))
    return max(n, 1)


def advance_frame_schedule(now_ms, frame_ms, st):
    if now_ms < st["next"] - frame_ms / 2.0:
        return None
    delta = st["next"] - st["last"]
    st["last"] = st["next"]
    st["next"] += frame_ms
    while st["next"] <= now_ms:
        st["next"] += frame_ms
    return delta


def simulate(display_hz, tick_ms, render_ms, seconds=20.0, present_ms=0.3, callback_lag_ms=0.4, timed_gate=False):
    vsync = 1000.0 / display_hz
    st = {"last": 0.0, "next": 0.0}
    gate = RenderGate(2, 30.0 if timed_gate else None)
    now = 0.0
    ticks = renders = draws = 0
    upd_hist = {}
    render_times = []
    while now < seconds * 1000.0:
        cost = 0.0
        # emscripten_get_now() is read inside the callback, i.e. a little after the vsync
        delta = advance_frame_schedule(now + callback_lag_ms, FRAME_MS, st)
        if delta is not None:
            n = update_count(delta)
            for _ in range(n):
                gate.on_tick()
                ticks += 1
                cost += tick_ms
            upd_hist[n] = upd_hist.get(n, 0) + 1
            draws += 1
            if gate.should_render(now + cost):
                renders += 1
                cost += render_ms
                render_times.append(now + cost)
            cost += present_ms
        # next requestAnimationFrame callback: first vsync boundary after this callback finished
        now = (math.floor((now + cost) / vsync + 1e-9) + 1) * vsync
    gaps = [b - a for a, b in zip(render_times, render_times[1:])]
    return {
        "ticks/s": ticks / seconds,
        "draw_cb/s": draws / seconds,
        "renders/s": renders / seconds,
        "updates_per_draw": dict(sorted(upd_hist.items())),
        "render_gap_ms(min/avg/max)": (round(min(gaps), 1), round(sum(gaps) / len(gaps), 1), round(max(gaps), 1)),
    }


cases = [
    (60, 2, 8, "60 Hz display, light load"),
    (60, 4, 20, "60 Hz display, render frame overruns one vsync"),
    (60, 3, 14, "60 Hz display, tick+render just over one vsync"),
    (60, 6, 28, "60 Hz display, heavy render"),
    (60, 10, 20, "60 Hz display, heavy tick"),
    (60, 18, 20, "60 Hz display, tick alone exceeds 16.7 ms"),
    (120, 2, 8, "120 Hz display"),
    (144, 2, 8, "144 Hz display"),
    (75, 2, 8, "75 Hz display"),
    (50, 2, 8, "50 Hz display"),
    (30, 2, 8, "30 Hz callbacks (throttled tab / low-power mode)"),
]
print("update_count for 1..7 frame deltas (f32 emulation):", [update_count(k * FRAME_MS) for k in range(1, 8)])
print("fps=60 in pyxel.init, RenderGate(divisor=2). tick/render costs in ms are assumptions.")
for hz, tick, rend, label in cases:
    print(f"- {label}: tick={tick} render={rend}")
    for timed in (False, True):
        r = simulate(hz, tick, rend, timed_gate=timed)
        name = "gate=ticks+30ms" if timed else "gate=ticks only "
        print(f"    {name}: " + "  ".join(f"{k}={v if not isinstance(v, float) else round(v, 1)}" for k, v in r.items()))
