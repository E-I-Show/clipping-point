"""E3: (1) does the screen keep its content when draw() draws nothing?
(2) catch-up: when a frame is slow, how are update/draw interleaved, and what does frame_count look like in draw?
Usage: e03_persist_catchup.py DRAW_SLEEP_MS UPDATE_SLEEP_MS NFRAMES
"""
import sys
import time

import pyxel

draw_sleep = float(sys.argv[1]) / 1000
update_sleep = float(sys.argv[2]) / 1000
n = int(sys.argv[3])

log = []  # ("U"|"D", frame_count)
persist_checks = []
rendered = 0
state = {"x": 0, "last_x": None}
t0 = time.perf_counter()


def update():
    log.append(("U", pyxel.frame_count))
    state["x"] += 1
    if update_sleep:
        time.sleep(update_sleep)
    if len([1 for k, _ in log if k == "U"]) >= n:
        finish()


def draw():
    global rendered
    log.append(("D", pyxel.frame_count))
    n_draw = len([1 for k, _ in log if k == "D"])
    if n_draw % 2 == 1:
        # real render: clear and draw a marker whose colour encodes state
        pyxel.cls(1)
        pyxel.rect(10, 10, 20, 20, 2 + (state["x"] % 13))
        state["last_x"] = state["x"]
        rendered += 1
    else:
        # skipped render: draw nothing, then check that the previous image is still there
        ok = (
            pyxel.pget(0, 0) == 1
            and pyxel.pget(15, 15) == 2 + (state["last_x"] % 13)
            and pyxel.screen.pget(15, 15) == 2 + (state["last_x"] % 13)
        )
        persist_checks.append(ok)
    if draw_sleep:
        time.sleep(draw_sleep)


def finish():
    wall = time.perf_counter() - t0
    seq = "".join(k for k, _ in log)
    n_u = seq.count("U")
    n_d = seq.count("D")
    draw_fc = [fc for k, fc in log if k == "D"]
    parity = {0: 0, 1: 0}
    for fc in draw_fc:
        parity[fc % 2] += 1
    # updates between consecutive draws
    runs = [len(r) for r in seq.split("D") if r]
    hist = {}
    for r in runs:
        hist[r] = hist.get(r, 0) + 1
    print(f"draw_sleep={draw_sleep*1000:.0f}ms update_sleep={update_sleep*1000:.0f}ms")
    print(f"  updates={n_u} draws={n_d} wall={wall:.2f}s  updates/s={n_u/wall:.1f} draws/s={n_d/wall:.1f}")
    print(f"  updates-per-draw histogram={dict(sorted(hist.items()))}")
    print(f"  frame_count parity at draw: even={parity[0]} odd={parity[1]}")
    print(f"  head of sequence: {seq[:60]}")
    print(f"  persistence checks: {sum(persist_checks)}/{len(persist_checks)} ok (0 checks would be a non-result)")
    sys.stdout.flush()
    sys.exit(0 if persist_checks and all(persist_checks) else 1)


pyxel.init(320, 240, fps=60, headless=True)
pyxel.run(update, draw)
