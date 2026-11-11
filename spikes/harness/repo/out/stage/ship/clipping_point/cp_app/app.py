"""Pyxel adapter: 60 Hz update, 30 fps scene render to a back buffer, plus the test modes.

Test modes (none of them exists in a normal start):
  native: environment variables, set by tools/run.py and tools/tour.py
     CP_SMOKE=<result.json>  CP_SMOKE_MODE=run|tour  CP_SMOKE_TICKS=<n>  CP_SMOKE_DRIVER=flip|run
     CP_SMOKE_SHOT_DIR=<dir>  CP_SMOKE_ONLY=<screen>  CP_SMOKE_PACK=<test pack>  CP_SMOKE_FAULT=<name>
  browser: a file smoke_config.json next to main.py, added only by tools/web_smoke.py to a staged
     copy of app/ (tools/export.py refuses to ship a build that contains it).
A run counts only if the result (file / RESULT_JSON console line) was written after every tick.
"""
import json
import os
import sys
import time
from pathlib import Path

import pyxel

from cp_core.datadefs import load_game_data
from cp_core.profile import BestLap, Profile, encode, load_profile, save_profile
from cp_core.session import AXIS_MAX, Session, script_events
from cp_core.storage import SaveStore
from cp_ui import fixtures
from cp_ui.canvas import SCREEN_H, SCREEN_W
from cp_ui.check import find_violations
from cp_ui.screens import SCREENS

from .canvas_pyxel import PyxelCanvas
from .storage_web import IS_WEB, default_backend

ROOT = Path(__file__).resolve().parent.parent  # pyxel.init chdir()s: always build paths from __file__
MARGIN = 16


def read_config():
    env = os.environ
    if env.get("CP_SMOKE"):
        return {"result": env["CP_SMOKE"], "mode": env.get("CP_SMOKE_MODE", "run"), "ticks": int(env.get("CP_SMOKE_TICKS", "120")),
                "driver": env.get("CP_SMOKE_DRIVER", "flip"), "shot_dir": env.get("CP_SMOKE_SHOT_DIR", ""),
                "only": env.get("CP_SMOKE_ONLY", ""), "pack": env.get("CP_SMOKE_PACK", ""), "fault": env.get("CP_SMOKE_FAULT", ""),
                "save_dir": env.get("CP_SMOKE_SAVE_DIR", "")}
    cfg_file = ROOT / "smoke_config.json"
    if cfg_file.exists():
        cfg = {"result": "", "mode": "run", "ticks": 120, "driver": "run", "shot_dir": "", "only": "", "pack": "", "fault": "", "save_dir": ""}
        cfg.update(json.loads(cfg_file.read_text(encoding="utf-8")))
        return cfg
    return None


class App:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        fast = cfg is not None and cfg["driver"] == "flip"
        pyxel.init(SCREEN_W, SCREEN_H, title="CLIPPING POINT", fps=1000 if fast else 60, quit_key=pyxel.KEY_NONE,
                   capture_sec=0 if cfg else 10, headless=cfg is not None and not IS_WEB)
        packs = (cfg["pack"],) if cfg and cfg["pack"] else ()
        self.data = load_game_data(ROOT / "data", packs, ROOT.parent / "testpacks")
        self.session = Session(self.data)
        self.back = pyxel.Image(SCREEN_W, SCREEN_H)
        self.ticks_since_render = 2
        self.renders = 0
        self.done = False
        self.t0 = time.perf_counter()

    # --- 60 Hz -------------------------------------------------------------------------
    def update(self) -> None:
        if self.done:
            return
        cfg = self.cfg
        if cfg:
            if cfg["fault"] == "update" and self.session.ticks == 5:
                raise RuntimeError("injected fault in update")
            if cfg["fault"] == "quit_early" and self.session.ticks == 5:
                pyxel.quit()  # exit code 0, no result file
            if cfg["fault"] == "stall" and self.session.ticks == 5:
                time.sleep(3600)
            for control, value in script_events(self.session.ticks):
                if control == "start":
                    pyxel.set_btn(pyxel.KEY_RETURN, value)
                elif control == "throttle_axis":
                    pyxel.set_btnv(pyxel.GAMEPAD1_AXIS_TRIGGERRIGHT, value)
                else:
                    pyxel.set_btnv(pyxel.GAMEPAD1_AXIS_LEFTX, value)
        self.session.tick(
            pyxel.btnp(pyxel.KEY_RETURN) or pyxel.btnp(pyxel.GAMEPAD1_BUTTON_START),
            pyxel.btnv(pyxel.GAMEPAD1_AXIS_TRIGGERRIGHT) or (AXIS_MAX if pyxel.btn(pyxel.KEY_UP) else 0),
            pyxel.btnv(pyxel.GAMEPAD1_AXIS_LEFTX),
        )
        self.ticks_since_render += 1
        if cfg and self.session.ticks >= cfg["ticks"]:
            self.finish_run()

    def draw(self) -> None:
        if self.ticks_since_render >= 2:
            self.render(self.back)
            self.ticks_since_render = 0
            self.renders += 1
        pyxel.blt(0, 0, self.back, 0, 0, SCREEN_W, SCREEN_H)

    def view_model(self) -> dict:
        s = self.session
        vm = fixtures.build(s.screen, "typical", self.data)
        if s.screen == "hud":
            p = s.world.player()
            vm.update(speed=int(p.v * 3.6), lap=p.lap + 1, time=fixtures.format_time(s.world.tick - p.lap_start_tick))
        return vm

    def render(self, img) -> None:
        if self.cfg and self.cfg["fault"] == "draw" and self.renders == 3:
            raise RuntimeError("injected fault in draw")
        img.cls(0)
        SCREENS[self.session.screen](PyxelCanvas(img, SCREEN_W, SCREEN_H), self.view_model())

    # --- test modes --------------------------------------------------------------------
    def storage_roundtrip(self) -> dict:
        """Save a non-default profile through the real backend of this platform and read it back."""
        store = SaveStore(default_backend(self.cfg["save_dir"] or str(ROOT / ".saves")), "smoke")
        p = Profile()
        p.settings.sfx_volume = 9
        p.controls.steer_curve = 2.25
        p.best_laps.append(BestLap("akane_short", "kazane_rs", 3777, has_ghost=True))
        save_profile(store, p)
        q = load_profile(store)
        store.put("blob", bytes(range(256)) * 4)
        blob = store.get("blob")
        ok = encode(q) == encode(p) and not q.load_warnings and blob is not None and blob[1] == bytes(range(256)) * 4
        return {"ok": ok, "keys": store.keys(), "used_bytes": store.used_bytes(), "backend": type(store.backend).__name__}

    def emit(self, result: dict) -> None:
        result.update(platform=sys.platform, python=sys.version.split()[0], pyxel=pyxel.VERSION)
        print("RESULT_JSON smoke " + json.dumps(result, sort_keys=True))
        if self.cfg["result"]:
            tmp = self.cfg["result"] + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=1, sort_keys=True)
            os.replace(tmp, self.cfg["result"])
        print("CP_SMOKE_DONE")
        sys.stdout.flush()
        self.done = True

    def finish_run(self) -> None:
        self.render(self.back)
        pyxel.blt(0, 0, self.back, 0, 0, SCREEN_W, SCREEN_H)
        s = self.session
        self.emit({
            "mode": "run", "ticks": s.ticks, "renders": self.renders, "fingerprint": s.fingerprint(), "visited": s.visited,
            "portable": s.world.summary_portable(), "storage": self.storage_roundtrip(),
            "screen_colors": sorted({pyxel.pget(x, y) for x in range(0, SCREEN_W, 4) for y in range(0, SCREEN_H, 4)}),
            "wall_s": round(time.perf_counter() - self.t0, 3),
        })
        if self.cfg["driver"] == "run" and not IS_WEB:
            sys.exit(0)  # SystemExit keeps the code; pyxel.quit() would always give 0

    def tour(self) -> None:
        """Draw every screen fixture, save a PNG each, and compare real ink with the recording."""
        cfg = self.cfg
        big = pyxel.Image(SCREEN_W + 2 * MARGIN, SCREEN_H + 2 * MARGIN)
        shots = []
        for name, draw in SCREENS.items():
            if cfg["only"] not in ("", name):
                continue
            for variant in fixtures.VARIANTS:
                vm = fixtures.build(name, variant, self.data)
                if cfg["fault"] == "tour_exception" and name == "settings":
                    raise RuntimeError("injected fault in tour")
                if cfg["fault"] == "tour_skip" and name == "theater":
                    continue
                big.cls(0)
                canvas = PyxelCanvas(big, SCREEN_W, SCREEN_H, MARGIN, MARGIN)
                draw(canvas, vm)
                covered = set()
                for it in canvas.items:
                    if it.kind != "box":
                        covered.update((x, y) for x in range(it.x, it.x2) for y in range(it.y, it.y2))
                ink_outside_screen = ink_unrecorded = ink = 0
                for y in range(big.height):
                    for x in range(big.width):
                        if big.pget(x, y) != 0:
                            ink += 1
                            sx, sy = x - MARGIN, y - MARGIN
                            if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
                                ink_outside_screen += 1
                            if (sx, sy) not in covered:
                                ink_unrecorded += 1
                pyxel.cls(0)
                pyxel.blt(0, 0, big, MARGIN, MARGIN, SCREEN_W, SCREEN_H)
                path = os.path.join(cfg["shot_dir"], f"{name}_{variant}.png")
                pyxel.screen.save(path, 2)
                shots.append({"screen": name, "variant": variant, "file": path, "items": len(canvas.items), "ink": ink,
                              "ink_outside_screen": ink_outside_screen, "ink_unrecorded": ink_unrecorded,
                              "violations": find_violations(canvas)})
        self.emit({"mode": "tour", "shots": shots})

    def run(self) -> None:
        cfg = self.cfg
        if cfg and cfg["mode"] == "tour":
            self.tour()
            sys.exit(0)
        if cfg and cfg["driver"] == "flip":
            while not self.done:  # own loop: native only (pyxel.flip is not available in the browser)
                self.update()
                self.draw()
                pyxel.flip()
            return
        pyxel.run(self.update, self.draw)


def main() -> None:
    App(read_config()).run()
