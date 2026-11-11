"""Web capture test: drive detune / gain while the real Pyxel Web mixer output is recorded by capture_audio.js."""
import json
import sys
import time

import pyxel

WEB = sys.platform == "emscripten"
pyxel.init(160, 120, title="audio cap", fps=60, quit_key=pyxel.KEY_NONE, headless=not WEB)
T0 = time.perf_counter()
ch = pyxel.channels[0]
ch.gain = 0.3


def snd_mml(code):
    s = pyxel.Sound()
    s.mml(code)
    return s


LONG = snd_mml("T60 Q100 @0 V127 O3 C1&C1&C1&C1")
SEGS = [  # name, sound, kind
    ("A_noglide_1over60", snd_mml("T600 Q100 @0 V127 O3 L24 C"), "detune"),
    ("B_glide_1over60", snd_mml("T600 Q100 @0 V127 @GLI1{*,*} O3 L24 C"), "detune"),
    ("C_glide_3over60", snd_mml("T600 Q100 @0 V127 @GLI1{*,*} O3 L8 C"), "detune"),
    ("D_sustained", LONG, "detune"),
    ("E_replay_each_tick", LONG, "replay"),
    ("F_noise_loop_gain", snd_mml("T600 Q100 @3 V127 O6 L24 C"), "gain"),
    ("G_sustained_noise_gain", snd_mml("T60 Q100 @3 V127 O6 C1&C1&C1&C1"), "gain"),
    ("H_sustained_noise_tone_gain", snd_mml("T60 Q100 @3 V127 O6 C1&C1&C1&C1"), "tone_gain"),
]
SEG_TICKS = 170
GAP = 20
log = {"segments": [], "web": WEB}
state = {"tick": 0, "done": False, "cur": None}
PLAN = [("silence", 30), ("marker", 12), ("silence", GAP)]
for name, snd, kind in SEGS:
    PLAN += [(name, SEG_TICKS), ("silence", GAP)]
PLAN += [("end", 1)]
plan_i = [0, 0]  # index, tick inside
by_name = {n: (s, k) for n, s, k in SEGS}


def now():
    return round(time.perf_counter() - T0, 4)


def update():
    if state["done"]:
        return
    name, n = PLAN[plan_i[0]]
    i = plan_i[1]
    if name == "silence":
        if i == 0:
            pyxel.stop()
    elif name == "marker":
        if i == 0:
            log["segments"].append(dict(name="marker", t0=now(), cmd=[]))
            pyxel.play(0, "T120 Q100 @1 V127 O7 C16")
    elif name == "end":
        finish()
        return
    else:
        snd, kind = by_name[name]
        if i == 0:
            seg = dict(name=name, t0=now(), cmd=[], base_hz=130.81, kind=kind)
            log["segments"].append(seg)
            state["cur"] = seg
            ch.detune = 0
            ch.gain = 0.3
            pyxel.tones[3].gain = 0.6
            if kind == "tone_gain":
                pyxel.tones[3].gain = 0.0
            if kind == "gain" and name.startswith("F"):
                ch.gain = 0.0
            if kind != "replay":
                ch.play(snd, loop=(kind != "tone_gain" and not name.startswith(("D", "G"))))
        seg = state["cur"]
        if kind in ("detune", "replay"):
            v = int(2400 * min(max(i - 20, 0), 120) / 120)
            ch.detune = v
            if kind == "replay":
                ch.play(snd)
        elif kind == "gain":
            v = 0.4 * (i / 60 if i < 60 else max(0.0, 2 - i / 60))
            if name.startswith("G"):
                v = 0.3 * max(0.0, 1 - i / 60)
            ch.gain = v
        else:
            v = 0.6 * (i / 60 if i < 60 else max(0.0, 2 - i / 60))
            pyxel.tones[3].gain = v
        seg["cmd"].append((now(), round(v, 4)))
        if i == n - 1:
            seg["t1"] = now()
    plan_i[1] += 1
    if plan_i[1] >= n:
        plan_i[0] += 1
        plan_i[1] = 0


def finish():
    state["done"] = True
    pyxel.stop()
    log["wall_s"] = now()
    if WEB:
        import js
        log["cap_info"] = json.loads(str(js.window.__capInfo()))
        log["perf_now_at_T0_ms"] = round(float(js.performance.now()) - (time.perf_counter() - T0) * 1000, 1)
        log["saved_samples"] = int(js.window.__capSave("webcap.raw"))
        ctx = js.window.pyxelContext.pyodide._module.SDL2.audioContext
        log["ctx"] = dict(state=str(ctx.state), sr=float(ctx.sampleRate), base_latency=float(ctx.baseLatency),
                          output_latency=float(getattr(ctx, "outputLatency", -1)))
    print("SPIKE_RESULT " + json.dumps(log))
    state["end_at"] = pyxel.frame_count + 60


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, f"CAP {plan_i[0]}/{len(PLAN)}", 7)
    if state["done"] and pyxel.frame_count >= state.get("end_at", 0) and not state.get("said"):
        state["said"] = True
        print("SPIKE_DONE")
        if not WEB:
            sys.exit(0)


if WEB:
    pyxel.run(update, draw)
else:
    while True:
        update()
        draw()
        pyxel.flip()
