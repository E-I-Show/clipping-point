"""Strict end-to-end check of apps/_shared/web_bridge.py in the browser.

Visit 1: write replays to storage, hit the quota on purpose, export a file, import one through the
file dialog and one through drag and drop, read analog triggers. Visit 2 (after reload): the
replays written in visit 1 must still be there and identical.
Any exception here is a real failure (no try/except around the probes).
"""

import hashlib
import json

import pyxel
import web_bridge
from web_bridge import Storage, StorageFull

store = Storage("clippingpoint.spike")


def fake_replay(seed, size):
    # incompressible-ish deterministic bytes
    out = bytearray(size)
    x = seed * 2654435761 % 4294967296
    for i in range(size):
        x = (x * 1103515245 + 12345) % 4294967296
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


def sha(b):
    return hashlib.sha256(b).hexdigest()


REPLAYS = {"replay.%02d" % i: fake_replay(i + 1, 250_000) for i in range(12)}  # 12 x 250 kB = 3.0 MB

frame = 0
stage = "boot"
visit = 2 if store.get("replay.00") is not None else 1
received = []


def emit(name, data):
    print("RESULT_JSON %s %s" % (name, json.dumps(data)))


def set_stage(s):
    global stage
    stage = s
    print("STAGE " + s)


def update():
    global frame
    frame += 1
    for name, data in web_bridge.poll_files(pyxel):
        received.append({"name": name, "size": len(data), "sha256": sha(data)})
    errs = web_bridge.poll_errors()
    if errs:
        raise RuntimeError("file read failed: %s" % errs)

    if stage == "boot" and frame == 5:
        emit("visit", {"visit": visit, "is_web": web_bridge.IS_WEB, "keys": store.keys()})
        if visit == 2:
            ok = all(store.get(k) == v for k, v in REPLAYS.items())
            emit("persisted", {"all_12_identical": ok, "keys": store.keys(), "used_chars": store.used_chars()})
            for k in store.keys():
                store.delete(k)
            emit("cleanup", {"keys_after_delete": store.keys()})
            print("SPIKE_DONE visit=2")
            set_stage("end")
            return
        for k, v in REPLAYS.items():
            store.put(k, v)
        emit("stored", {"count": len(store.keys()), "used_chars": store.used_chars(), "bytes": sum(len(v) for v in REPLAYS.values()), "roundtrip_ok": all(store.get(k) == v for k, v in REPLAYS.items())})
        assert store.get("no.such.key") is None
        # Overflow on purpose: must raise StorageFull and must not damage what is stored.
        full = False
        extra = 0
        try:
            for i in range(40):
                store.put("overflow.%02d" % i, fake_replay(100 + i, 250_000))
                extra += 1
        except StorageFull:
            full = True
        for k in store.keys():
            if k.startswith("overflow."):
                store.delete(k)
        emit("quota", {"storage_full_raised": full, "extra_250kB_slots_that_fit": extra, "replays_still_ok": all(store.get(k) == v for k, v in REPLAYS.items())})
        web_bridge.save_file("demo_export.cpr", REPLAYS["replay.03"])
        emit("export", {"filename": "demo_export.cpr", "sha256": sha(REPLAYS["replay.03"])})
        set_stage("press_o")
    elif stage == "press_o" and pyxel.btnp(pyxel.KEY_O):
        web_bridge.request_open_file(".cpr")
        set_stage("wait_pick")
    elif stage == "wait_pick" and len(received) == 1:
        emit("picked", received[0])
        set_stage("drop")
    elif stage == "drop" and len(received) == 2:
        emit("dropped", received[1])
        set_stage("pad")
    elif stage == "pad":
        t = web_bridge.read_triggers(0)
        if t is not None and t[1] > 0:
            emit("triggers", {"left": t[0], "right": t[1], "pyxel_trigger_right": pyxel.btnv(pyxel.GAMEPAD1_AXIS_TRIGGERRIGHT)})
            print("SPIKE_DONE visit=1")
            set_stage("end")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "BRIDGE DEMO VISIT %d" % visit, 7)
    pyxel.text(4, 14, "STAGE %s" % stage.upper(), 10)
    pyxel.text(4, 24, "FILES %d" % len(received), 6)


pyxel.init(160, 120, title="bridge_demo", fps=60)
pyxel.run(update, draw)
