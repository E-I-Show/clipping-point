"""Pyxel adapter: 60 Hz update (input + sim), 30 fps scene render, every-frame present."""

import os
import time
from pathlib import Path

import pyxel

from cp_core.datafiles import load_cars, load_track
from cp_core.fixed_loop import RENDER_DIVISOR, TICK_HZ, RenderGate
from cp_core.game import Game

from .input_pyxel import read_raw_input
from .smoke import SmokeConfig, SmokeSession

W, H = 320, 240


class App:
    def __init__(self, smoke: SmokeConfig | None = None) -> None:
        self.cwd_before_init = os.getcwd()
        fast = smoke is not None and smoke.driver == "flip"
        pyxel.init(
            W,
            H,
            title="CLIPPING POINT PROTO",
            # One Pyxel frame = one simulation tick. The fast test driver raises fps only to
            # shorten Pyxel's real-time wait (min 1 ms per flip); game logic never reads fps.
            fps=1000 if fast else TICK_HZ,
            quit_key=pyxel.KEY_NONE,
            # The built-in GIF ring buffer keeps fps*capture_sec full screens: 0 for tests.
            capture_sec=0 if smoke is not None else 10,
            headless=smoke is not None,
        )
        # pyxel.init chdir()s to the directory of the file that called it (here: cp_app/).
        # Never rely on the working directory: build every path from __file__.
        self.cwd_after_init = os.getcwd()
        self.root = Path(__file__).resolve().parent.parent

        self.cars = load_cars(self.root / "data" / "cars.json")
        self.track = load_track(self.root / "data" / "track.bin")
        pyxel.load(str(self.root / "assets" / "proto.pyxres"))
        self.pyxres_pixel = pyxel.images[0].pget(3, 3)
        self.logo = pyxel.Image.from_image(str(self.root / "assets" / "logo.png"))

        self.game = Game()
        self.sim = self.game.sim
        self.gate = RenderGate(RENDER_DIVISOR)
        self.back = pyxel.Image(W, H)  # scene is rendered here at 30 fps
        self.ticks = 0
        self.draw_calls = 0
        self.renders = 0
        self.smoke = SmokeSession(smoke) if smoke is not None else None

    # --- 60 Hz -------------------------------------------------------------------------
    def update(self) -> None:
        if self.smoke:
            self.smoke.before_tick(self)
        self.game.tick(read_raw_input())
        self.gate.on_tick()
        self.ticks += 1
        if self.smoke:
            self.smoke.after_tick(self)

    # --- called by Pyxel up to 60 times per second; renders at 30 fps --------------------
    def draw(self) -> None:
        self.draw_calls += 1
        no_render = self.smoke is not None and self.smoke.cfg.fault == "no_render"
        self.present(force_render=False, allow_render=not no_render)

    def present(self, force_render: bool = False, allow_render: bool = True) -> None:
        if allow_render and (force_render or self.gate.should_render(time.perf_counter() * 1000.0)):
            self.render_scene(self.back)
            self.renders += 1
        # Repaint the whole screen every frame from the back buffer (cheap), so that Pyxel's
        # own overlays (perf monitor, mouse cursor), which are drawn INTO pyxel.screen after
        # draw(), never pile up on a stale image.
        pyxel.blt(0, 0, self.back, 0, 0, W, H)

    def render_scene(self, img) -> None:
        if self.smoke:
            self.smoke.on_scene_render(self)
        img.cls(1)
        cx, cy, s = W // 2, H // 2 + 20, 0.9
        pts = self.track
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            img.line(cx + x1 * s, cy + y1 * s, cx + x2 * s, cy + y2 * s, 13)
        img.blt(W - self.logo.width - 4, 4, self.logo, 0, 0, self.logo.width, self.logo.height, 0)
        img.blt(4, H - 20, pyxel.images[0], 0, 0, 16, 16)
        px = cx + (self.sim.x % 200 - 100) * s
        py = cy + (self.sim.y % 120 - 60) * s
        img.rect(px - 3, py - 2, 6, 4, 8)
        img.text(4, 4, f"TICK {self.sim.tick:5d}  GEAR {self.sim.gear}", 7)
        img.text(4, 12, f"SPEED {self.sim.speed * 3.6:6.1f} KM/H", 7)
        img.text(4, 20, self.cars[0]["name"], 10)
        if self.game.paused:
            img.rect(W // 2 - 40, H // 2 - 12, 80, 24, 0)
            img.rectb(W // 2 - 40, H // 2 - 12, 80, 24, 7)
            img.text(W // 2 - 10, H // 2 - 3, "PAUSE", 7)

    # --- drivers -----------------------------------------------------------------------
    def run(self) -> None:
        if self.smoke is not None and self.smoke.cfg.driver == "flip":
            # Own loop: one update + one draw per pyxel.flip(). Native only (flip panics on web).
            while not self.smoke.done:
                self.update()
                self.draw()
                pyxel.flip()
            return
        pyxel.run(self.update, self.draw)  # never returns


def main() -> None:
    App(SmokeConfig.from_env()).run()
