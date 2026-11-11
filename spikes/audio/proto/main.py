"""Audio spike demo: a scripted fake "logic" feeds AudioFrame to PyxelAudio every tick (60 Hz).

Native:  python3 main.py            (headless, pyxel.flip loop, optional SDL_AUDIODRIVER=disk capture)
Web:     packaged with pyxel package / app2html, runs under pyxel.run, prints one JSON line + SPIKE_DONE.
"""
import json
import sys
import time

import pyxel

import audio_iface as ai
import sound_data as sd
from pyxel_audio import PyxelAudio

WEB = sys.platform == "emscripten"
TOTAL_TICKS = 1140


def script(t: int) -> ai.AudioFrame:
    """Deterministic fake logic output for tick t."""
    f = ai.AudioFrame()
    if t < 60:
        f.scene = ai.Scene.MENU
        return f
    if t < 900:
        f.scene = ai.Scene.RACE
        car = ai.CarAudio(engine=0)
        f.player = car
        if t in (70, 110, 150):
            f.events.append((ai.Ev.COUNT_BEEP, 1.0))
        if t == 190:
            f.events.append((ai.Ev.COUNT_GO, 1.0))
        if t < 190:  # idle with two throttle blips
            blip = 1.0 if (100 <= t < 112 or 140 <= t < 152) else 0.0
            car.throttle = blip
            car.rpm = 900.0 + 2200.0 * blip * (1 - abs((t % 40 - 6) / 6 - 1) if blip else 0)
        elif t < 480:  # three gears: 2000 -> 7200 rpm, shift drops to 62 %
            k = t - 190
            gear = min(k // 100, 2)
            x = (k - gear * 100) / (100 if gear < 2 else 90)
            lo = 2000.0 if gear == 0 else 7200.0 * 0.62
            car.rpm = lo + (7200.0 - lo) * min(x, 1.0)
            car.throttle = 1.0
            car.speed = 10.0 + k * 0.12
            if k in (100, 200):
                f.events.append((ai.Ev.SHIFT, 1.0))
                car.throttle = 0.0
        else:  # cruise 5000 rpm with episodes
            car.rpm = 5000.0 + 300.0 * ((t // 7) % 3 - 1)
            car.throttle = 0.6
            car.speed = 40.0
            if 500 <= t < 590:  # slide
                car.slip = 1.0 - abs((t - 545) / 45)
            if 620 <= t < 680:  # curb, with a contact in the middle
                car.on_curb = True
                if t == 640:
                    f.events.append((ai.Ev.CONTACT, 0.8))
            if 700 <= t < 740:
                car.off_road = True
        # two other cars: one passes close, one stays far
        f.others = [ai.CarAudio(engine=1, rpm=5200.0, throttle=1.0, dist=abs(600 - t) * 0.25 + 4.0),
                    ai.CarAudio(engine=0, rpm=3000.0, throttle=0.5, dist=45.0)]
        if 800 <= t < 840:
            f.paused = True
        return f
    if t < 1020:
        f.scene = ai.Scene.REPLAY
        f.player = ai.CarAudio(engine=1, rpm=3000.0 + 20.0 * (t - 900), throttle=0.8)
        f.others = [ai.CarAudio(engine=0, rpm=4000.0, throttle=1.0, dist=12.0)]
        return f
    if t < 1110:
        f.scene = ai.Scene.RESULT
        return f
    f.scene = ai.Scene.SILENT
    return f


class App:
    def __init__(self):
        pyxel.init(160, 120, title="audio spike", fps=60, quit_key=pyxel.KEY_NONE, headless=not WEB)
        self.res = {"web": WEB, "platform": sys.platform, "python": sys.version.split()[0], "pyxel": pyxel.VERSION}
        t0 = time.perf_counter()
        self.audio = PyxelAudio(num_channels=8)
        self.res["setup_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        self.res["num_channels"] = len(pyxel.channels)
        self.res["num_tones"] = len(pyxel.tones)
        self.t = 0
        self.upd_us = []
        self.pos = []  # (tick, wall s, play_pos sec of ch0) to see how the audio clock advances
        self.playing = []  # which channels are playing at a few sample ticks
        self.wall0 = time.perf_counter()
        self.done = False

    def update(self):
        if self.done:
            return
        t = self.t
        f = script(t)
        a = time.perf_counter()
        self.audio.update(f)
        self.upd_us.append((time.perf_counter() - a) * 1e6)
        if 300 <= t < 420:
            p = pyxel.play_pos(0)
            self.pos.append((t, round(time.perf_counter() - self.wall0, 4), None if p is None else round(p[1], 5)))
        if t in (30, 120, 300, 545, 640, 660, 720, 820, 960, 1060, 1130):
            self.playing.append((t, [i for i in range(len(pyxel.channels)) if pyxel.play_pos(i) is not None],
                                 pyxel.channels[0].detune, round(pyxel.channels[0].gain, 4),
                                 round(pyxel.channels[1].gain, 4), round(pyxel.channels[3].gain, 4)))
        self.t += 1
        if self.t >= TOTAL_TICKS:
            self.finish()

    def draw(self):
        pyxel.cls(1)
        pyxel.text(4, 4, f"AUDIO SPIKE T={self.t}", 7)

    def finish(self):
        self.done = True
        u = sorted(self.upd_us)
        self.res["ticks"] = self.t
        self.res["wall_s"] = round(time.perf_counter() - self.wall0, 3)
        self.res["update_us_mean"] = round(sum(u) / len(u), 2)
        self.res["update_us_p50"] = round(u[len(u) // 2], 2)
        self.res["update_us_p99"] = round(u[int(len(u) * 0.99)], 2)
        self.res["update_us_max"] = round(u[-1], 2)
        self.res["playing_samples"] = self.playing
        # audio clock: does play_pos move, and in what steps?
        moved = [p for p in self.pos if p[2] is not None]
        self.res["play_pos_ch0_first"] = moved[:6]
        self.res["play_pos_distinct_values"] = len({p[2] for p in moved})
        self.res["play_pos_samples"] = len(moved)
        if WEB:
            try:
                import js
                ctx = js.window.pyxelContext.pyodide._module.SDL2.audioContext
                self.res["audio_context"] = dict(state=str(ctx.state), sample_rate=float(ctx.sampleRate),
                                                 current_time=float(ctx.currentTime),
                                                 base_latency=float(getattr(ctx, "baseLatency", -1)))
            except BaseException as e:  # noqa
                self.res["audio_context"] = f"{type(e).__name__}: {e}"
        print("SPIKE_RESULT " + json.dumps(self.res))
        print("SPIKE_DONE")
        if not WEB:
            sys.exit(0)

    def run(self):
        if WEB:
            pyxel.run(self.update, self.draw)
        else:
            while not self.done:
                self.update()
                self.draw()
                pyxel.flip()


App().run()
