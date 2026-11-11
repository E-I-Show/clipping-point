"""Headless smoke-test mode, switched on by environment variables (absent in the browser).

  CP_SMOKE=<abs path of result JSON>   enables smoke mode (headless, scripted input, N ticks, exit)
  CP_SMOKE_TICKS=<n>                   number of 60 Hz ticks to run (default 120)
  CP_SMOKE_DRIVER=flip|run             flip: own loop + pyxel.flip() (fast). run: pyxel.run (real time)
  CP_SMOKE_SHOT=<abs path .png>        save the final screen
  CP_SMOKE_SCRIPT=demo|tour            input script; tour also saves named PNGs (screen tour)
  CP_SMOKE_SHOT_DIR=<abs dir>          where the tour PNGs go;  CP_SMOKE_ONLY=<name> limits them
  CP_SMOKE_DRAW_SLEEP_MS=<ms>          make every scene render slow (exercises Pyxel's catch-up)
  CP_SMOKE_FAULT=update|draw|quit_early|no_render   break something on purpose

The result file is written only after every tick ran, so "exit code 0" alone is never accepted
as a pass by tools/run_smoke.py (pyxel.quit() exits with 0 from anywhere).
"""

import json
import os
import sys
import time
from dataclasses import dataclass

import pyxel

from cp_core.input_script import SCRIPTS, TOUR_SHOTS, TOUR_TICKS, events_by_tick

from .input_pyxel import inject


@dataclass
class SmokeConfig:
    result_path: str
    ticks: int = 120
    driver: str = "flip"
    shot_path: str = ""
    draw_sleep_ms: float = 0.0
    fault: str = ""
    script: str = "demo"
    shot_dir: str = ""
    only: str = ""

    @classmethod
    def from_env(cls, env=os.environ):
        result_path = env.get("CP_SMOKE", "")
        if not result_path:
            return None
        cfg = cls(
            result_path=result_path,
            ticks=int(env.get("CP_SMOKE_TICKS", "120")),
            driver=env.get("CP_SMOKE_DRIVER", "flip"),
            shot_path=env.get("CP_SMOKE_SHOT", ""),
            draw_sleep_ms=float(env.get("CP_SMOKE_DRAW_SLEEP_MS", "0")),
            fault=env.get("CP_SMOKE_FAULT", ""),
            script=env.get("CP_SMOKE_SCRIPT", "demo"),
            shot_dir=env.get("CP_SMOKE_SHOT_DIR", ""),
            only=env.get("CP_SMOKE_ONLY", ""),
        )
        if cfg.script not in SCRIPTS:
            raise ValueError(f"unknown CP_SMOKE_SCRIPT {cfg.script!r}")
        if cfg.script == "tour":
            cfg.ticks = TOUR_TICKS
            if not cfg.shot_dir:
                raise ValueError("CP_SMOKE_SCRIPT=tour needs CP_SMOKE_SHOT_DIR")
        if cfg.driver not in ("flip", "run"):
            raise ValueError(f"CP_SMOKE_DRIVER must be flip or run, got {cfg.driver!r}")
        if cfg.fault not in ("", "update", "draw", "quit_early", "no_render"):
            raise ValueError(f"unknown CP_SMOKE_FAULT {cfg.fault!r}")
        if cfg.ticks < 1:
            raise ValueError("CP_SMOKE_TICKS must be >= 1")
        return cfg


class SmokeSession:
    def __init__(self, cfg: SmokeConfig) -> None:
        self.cfg = cfg
        self.events = events_by_tick(SCRIPTS[cfg.script])
        self.shots = dict(TOUR_SHOTS) if cfg.script == "tour" else {}
        self.shots_saved = []
        self.t0 = time.perf_counter()
        self.done = False

    def before_tick(self, app) -> None:
        tick = app.ticks
        if self.cfg.fault == "update" and tick == 5:
            raise RuntimeError("injected fault in update")
        if self.cfg.fault == "quit_early" and tick == 5:
            pyxel.quit()  # process ends here with exit code 0 and no result file
        for control, value in self.events.get(tick, []):
            inject(control, value)

    def on_scene_render(self, app) -> None:
        if self.cfg.fault == "draw" and app.renders == 3:
            raise RuntimeError("injected fault in draw")
        if self.cfg.draw_sleep_ms:
            time.sleep(self.cfg.draw_sleep_ms / 1000.0)

    def after_tick(self, app) -> None:
        name = self.shots.get(app.ticks - 1)  # the tick that just ran
        if name and self.cfg.only in ("", name):
            app.present(force_render=True)
            pyxel.screen.save(os.path.join(self.cfg.shot_dir, f"{name}.png"), 2)
            self.shots_saved.append(name)
        if app.ticks < self.cfg.ticks:
            return
        wall = time.perf_counter() - self.t0
        no_render = self.cfg.fault == "no_render"
        app.present(force_render=not no_render, allow_render=not no_render)
        if self.cfg.shot_path:
            pyxel.screen.save(self.cfg.shot_path, 1)
        result = {
            "ok": True,
            "ticks": app.ticks,
            "draw_calls": app.draw_calls,
            "renders": app.renders,
            "fingerprint": app.game.fingerprint(),
            "shots_saved": self.shots_saved,
            "shift_count": app.sim.shift_count,
            "driver": self.cfg.driver,
            "wall_s": round(wall, 4),
            "pyxel_frame_count": pyxel.frame_count,
            "pyxel_version": pyxel.VERSION,
            "cwd_before_init": app.cwd_before_init,
            "cwd_after_init": app.cwd_after_init,
            "app_root": str(app.root),
            "cars": [c["id"] for c in app.cars],
            "track_points": len(app.track),
            "pyxres_pixel": app.pyxres_pixel,
            "logo_size": [app.logo.width, app.logo.height],
            "screen_colors": sorted({pyxel.pget(x, y) for x in range(0, 320, 4) for y in range(0, 240, 4)}),
        }
        tmp = self.cfg.result_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        os.replace(tmp, self.cfg.result_path)
        print(f"SMOKE_OK ticks={app.ticks} renders={app.renders} fingerprint={result['fingerprint']}")
        sys.stdout.flush()
        self.done = True
        if self.cfg.driver == "run":
            # Inside pyxel.run: SystemExit keeps the exit code and lets Python flush its buffers.
            # pyxel.quit() would also end the process, but always with code 0 and without
            # flushing Python-level buffers.
            sys.exit(0)
