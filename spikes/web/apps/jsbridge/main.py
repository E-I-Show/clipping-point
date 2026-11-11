"""Probe Python -> JavaScript access from inside a Pyxel Web app.

Stages run from update(). Every probe reports what happened instead of raising, so one
failing probe does not hide the others. Console lines:
  RESULT_JSON <name> <json>   data
  STAGE <name>                marker the test driver reacts to
  SPIKE_DONE                  end

The first visit runs every probe and leaves a marker in localStorage. A visit that finds the
marker (after a reload, or a browser restart with the same profile) only reports persistence.
"""

import base64
import hashlib
import json
import sys
import time
import traceback

import pyxel

report = {}
log_lines = []


def emit(name, data):
    report[name] = data
    print("RESULT_JSON %s %s" % (name, json.dumps(data)))


def describe_exc(e):
    d = {"type": type(e).__name__, "str": str(e)[:300]}
    for attr in ("name", "message"):
        try:
            d["js_" + attr] = str(getattr(e, attr))[:200]
        except Exception:
            pass
    return d


def probe(name):
    """Decorator: run fn(), emit its dict, or emit the exception."""

    def wrap(fn):
        def run():
            try:
                emit(name, fn())
            except Exception as e:  # noqa: BLE001 - this is a probe
                d = describe_exc(e)
                d["traceback"] = traceback.format_exc()[-600:]
                emit(name, {"EXCEPTION": d})

        return run

    return wrap


# ------------------------------------------------------------------ environment


@probe("env")
def probe_env():
    out = {"sys.platform": sys.platform, "python": sys.version.split()[0]}
    try:
        import js

        out["import_js"] = True
        out["location.protocol"] = str(js.location.protocol)
        out["location.origin"] = str(js.location.origin)
        out["userAgent"] = str(js.navigator.userAgent)
        out["has_localStorage"] = hasattr(js, "localStorage")
        out["has_indexedDB"] = hasattr(js, "indexedDB")
        out["crossOriginIsolated"] = bool(js.crossOriginIsolated)
        out["has_savePyxelFile"] = hasattr(js.window, "_savePyxelFile")
        out["userActivation"] = {"isActive": bool(js.navigator.userActivation.isActive), "hasBeenActive": bool(js.navigator.userActivation.hasBeenActive)}
    except Exception as e:  # noqa: BLE001
        out["import_js"] = False
        out["import_js_error"] = describe_exc(e)
    try:
        import pyodide

        out["pyodide.__version__"] = pyodide.__version__
        import pyodide.ffi as ffi

        out["ffi_names"] = sorted(n for n in dir(ffi) if not n.startswith("_"))
    except Exception as e:  # noqa: BLE001
        out["pyodide_error"] = describe_exc(e)
    return out


# ------------------------------------------------------------------ localStorage

PREFIX = "cp_spike_"


def text_or_none(v):
    """localStorage.getItem returns JS null for a missing key. Pyodide 314 maps that to
    pyodide.ffi.jsnull (not None), so test for str instead of `is None`."""
    return v if isinstance(v, str) else None


def ls_keys():
    import js

    ls = js.localStorage
    return [str(ls.key(i)) for i in range(int(ls.length))]


@probe("localstorage_basic")
def probe_ls_basic():
    import js

    ls = js.localStorage
    out = {"keys_before": ls_keys()}
    out["persist_marker_before"] = text_or_none(ls.getItem(PREFIX + "persist"))  # None on a first visit
    ls.setItem(PREFIX + "a", "hello")
    out["roundtrip"] = ls.getItem(PREFIX + "a") == "hello"
    v = ls.getItem(PREFIX + "missing")
    out["missing_is_None"] = v is None
    out["missing_repr"] = repr(v)
    out["missing_type"] = type(v).__name__
    out["missing_is_falsy"] = not v
    try:
        from pyodide.ffi import jsnull

        out["missing_is_jsnull"] = v is jsnull
    except Exception as e:  # noqa: BLE001
        out["jsnull_import_error"] = describe_exc(e)
    out["undefined_attr_is_None"] = js.window.definitely_not_defined_xyz is None if hasattr(js.window, "definitely_not_defined_xyz") else "hasattr False"
    out["type_of_value"] = type(ls.getItem(PREFIX + "a")).__name__
    ls.removeItem(PREFIX + "a")
    out["removed"] = text_or_none(ls.getItem(PREFIX + "a")) is None
    return out


@probe("localstorage_binary")
def probe_ls_binary():
    """Two ways to put bytes in a string: base64 (4/3 chars per byte) and latin-1 (1 char per byte)."""
    import js

    ls = js.localStorage
    data = bytes(range(256)) * 2000  # 512,000 bytes containing every byte value incl. NUL
    out = {"bytes": len(data)}
    t0 = time.perf_counter()
    s = base64.b64encode(data).decode("ascii")
    t1 = time.perf_counter()
    ls.setItem(PREFIX + "b64", s)
    t2 = time.perf_counter()
    back = ls.getItem(PREFIX + "b64")
    t3 = time.perf_counter()
    ok = base64.b64decode(back) == data
    t4 = time.perf_counter()
    out["base64"] = {
        "chars": len(s),
        "roundtrip_ok": ok,
        "encode_ms": round((t1 - t0) * 1000, 2),
        "setItem_ms": round((t2 - t1) * 1000, 2),
        "getItem_ms": round((t3 - t2) * 1000, 2),
        "decode_ms": round((t4 - t3) * 1000, 2),
    }
    ls.removeItem(PREFIX + "b64")
    s = data.decode("latin-1")
    t1 = time.perf_counter()
    ls.setItem(PREFIX + "l1", s)
    t2 = time.perf_counter()
    back = ls.getItem(PREFIX + "l1")
    t3 = time.perf_counter()
    out["latin1"] = {
        "chars": len(s),
        "roundtrip_ok": back.encode("latin-1") == data,
        "setItem_ms": round((t2 - t1) * 1000, 2),
        "getItem_ms": round((t3 - t2) * 1000, 2),
    }
    ls.removeItem(PREFIX + "l1")
    return out


@probe("localstorage_quota")
def probe_ls_quota():
    import js

    ls = js.localStorage
    out = {"steps": []}
    key = PREFIX + "big"
    for size in (100_000, 500_000, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000, 5_500_000, 8_000_000):
        s = "x" * size
        t0 = time.perf_counter()
        try:
            ls.setItem(key, s)
            ok = True
            err = None
        except Exception as e:  # noqa: BLE001
            ok = False
            err = describe_exc(e)
        dt = (time.perf_counter() - t0) * 1000
        got = text_or_none(ls.getItem(key))
        out["steps"].append({"chars": size, "ok": ok, "ms": round(dt, 2), "stored_chars": None if got is None else len(got), "error": err})
        ls.removeItem(key)
    # Bisect the largest single value that fits (key length counts too).
    lo, hi = 1_000_000, 12_000_000
    while hi - lo > 1024:
        mid = (lo + hi) // 2
        try:
            ls.setItem(key, "x" * mid)
            lo = mid
        except Exception:  # noqa: BLE001
            hi = mid
        ls.removeItem(key)
    out["max_single_value_chars_ascii"] = lo
    # Same with non-Latin-1 characters (does the quota count characters or bytes?).
    lo, hi = 100_000, 12_000_000
    while hi - lo > 1024:
        mid = (lo + hi) // 2
        try:
            ls.setItem(key, "あ" * mid)
            lo = mid
        except Exception:  # noqa: BLE001
            hi = mid
        ls.removeItem(key)
    out["max_single_value_chars_nonlatin"] = lo
    # Quota is shared by all keys of the origin: 12 slots of 330,000 chars = 3.96 M chars (3 MB as base64 ~ 4.0 M chars).
    stored = 0
    err = None
    try:
        for i in range(12):
            ls.setItem(PREFIX + "slot%d" % i, "y" * 334_000)
            stored += 1
    except Exception as e:  # noqa: BLE001
        err = describe_exc(e)
    out["twelve_slots_of_334k_chars"] = {"stored": stored, "error": err}
    for i in range(12):
        ls.removeItem(PREFIX + "slot%d" % i)
    # What exactly is raised on overflow?
    try:
        ls.setItem(key, "x" * 20_000_000)
        out["overflow_exception"] = None
    except Exception as e:  # noqa: BLE001
        d = describe_exc(e)
        d["mro"] = [c.__name__ for c in type(e).__mro__]
        out["overflow_exception"] = d
    ls.removeItem(key)
    return out


@probe("localstorage_persist_write")
def probe_ls_persist_write():
    import js

    js.localStorage.setItem(PREFIX + "persist", "written-in-run-1")
    return {"written": True, "keys": ls_keys()}


# ------------------------------------------------------------------ download

PAYLOAD = bytes((i * 7 + 3) & 0xFF for i in range(200_000))  # deterministic 200 kB


@probe("download_blob")
def probe_download_blob():
    """Build a Blob from Python bytes and click an <a download> link."""
    import js
    from pyodide.ffi import create_once_callable, to_js

    u8 = to_js(PAYLOAD)  # bytes -> Uint8Array (copy)
    out = {"to_js_type": str(js.Object.prototype.toString.call(u8)), "len": int(u8.length)}
    parts = js.Array.new()
    parts.push(u8)
    opts = js.Object.new()
    opts.type = "application/octet-stream"
    blob = js.Blob.new(parts, opts)
    out["blob_size"] = int(blob.size)
    url = js.URL.createObjectURL(blob)
    a = js.document.createElement("a")
    a.href = url
    a.download = "spike_blob.cpr"
    a.style.display = "none"
    js.document.body.appendChild(a)
    a.click()
    js.document.body.removeChild(a)
    js.setTimeout(create_once_callable(lambda: js.URL.revokeObjectURL(url)), 2000)
    out["sha256"] = hashlib.sha256(PAYLOAD).hexdigest()
    return out


@probe("download_savePyxelFile")
def probe_download_runtime():
    """Use the runtime's own helper: write to the virtual FS, then window._savePyxelFile(path)."""
    import js

    path = "/tmp/spike_runtime.cpr"
    with open(path, "wb") as f:
        f.write(PAYLOAD)
    js.window._savePyxelFile(path)
    return {"path": path, "sha256": hashlib.sha256(PAYLOAD).hexdigest()}


# ------------------------------------------------------------------ file input

inbox = []  # filled by JS callbacks, drained by update()
keep_alive = []  # proxies must stay referenced while JS may call them


def open_file_dialog(tag, use_asyncio=False):
    """Create <input type=file>, click it, deliver (name, bytes) into `inbox` when the user picks a file."""
    import js
    from pyodide.ffi import create_proxy

    inp = js.document.createElement("input")
    inp.type = "file"
    inp.accept = ".cpr"
    inp.style.display = "none"
    js.document.body.appendChild(inp)

    def on_buffer(buf):  # buf: JS ArrayBuffer
        data = buf.to_bytes()
        inbox.append({"tag": tag, "name": str(inp.files.item(0).name), "data": data, "how": "then+create_proxy"})

    def on_error(err):
        inbox.append({"tag": tag, "error": str(err)})

    async def read_async(f):
        buf = await f.arrayBuffer()
        inbox.append({"tag": tag, "name": str(f.name), "data": buf.to_bytes(), "how": "asyncio+await"})

    def on_change(event):
        files = inp.files
        if int(files.length) == 0:
            inbox.append({"tag": tag, "error": "no file"})
            return
        f = files.item(0)
        if use_asyncio:
            import asyncio

            asyncio.ensure_future(read_async(f))
        else:
            p_ok = create_proxy(on_buffer)
            p_err = create_proxy(on_error)
            keep_alive.extend([p_ok, p_err])
            f.arrayBuffer().then(p_ok, p_err)

    def on_cancel(event):
        inbox.append({"tag": tag, "error": "cancel"})

    p_change = create_proxy(on_change)
    p_cancel = create_proxy(on_cancel)
    keep_alive.extend([p_change, p_cancel])
    inp.addEventListener("change", p_change)
    inp.addEventListener("cancel", p_cancel)
    inp.click()
    return {
        "clicked": True,
        "userActivation.isActive": bool(js.navigator.userActivation.isActive),
        "userActivation.hasBeenActive": bool(js.navigator.userActivation.hasBeenActive),
    }


# ------------------------------------------------------------------ stage machine

import js as _js  # noqa: E402  (module-level import must work for the app to start)

# Second visit (after a reload or a browser restart) is recognised by the marker left by the first.
RUN = 2 if text_or_none(_js.localStorage.getItem(PREFIX + "persist")) else 1

frame = 0
t_start = None
stage = "boot"
stage_t = 0.0
got = {}


def set_stage(name):
    global stage, stage_t
    stage = name
    stage_t = time.perf_counter()
    print("STAGE " + name)


def drain_inbox():
    while inbox:
        item = inbox.pop(0)
        if "data" in item:
            data = item.pop("data")
            item["size"] = len(data)
            item["sha256"] = hashlib.sha256(data).hexdigest()
            item["type"] = type(data).__name__
        got[item["tag"]] = item
        emit("file_" + item["tag"], item)


def drain_drops():
    # Web runtime delivers drops through the module attribute pyxel._dropped_files (see wasm/pyxel.js).
    legacy = getattr(pyxel, "_dropped_files", [])
    official = list(pyxel.dropped_files)
    if legacy or official:
        pyxel._dropped_files = []
        info = {"pyxel._dropped_files": list(legacy), "pyxel.dropped_files": official, "files": []}
        for path in list(legacy) + official:
            with open(path, "rb") as f:
                data = f.read()
            info["files"].append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        got["drop"] = info
        emit("drop", info)


def update():
    global frame, t_start
    frame += 1
    now = time.perf_counter()
    if t_start is None:
        t_start = now
    drain_inbox()
    drain_drops()
    since = now - stage_t

    if stage == "boot" and frame == 5:
        probe_env()
        probe_ls_basic()
        if RUN == 2:
            emit("persist_after_reload", {"value": text_or_none(_js.localStorage.getItem(PREFIX + "persist")), "keys": ls_keys()})
            _js.localStorage.removeItem(PREFIX + "persist")
            print("SPIKE_DONE run=2")
            set_stage("end")
            return
        probe_ls_binary()
        probe_ls_quota()
        probe_ls_persist_write()
        set_stage("download1")
    elif stage == "download1" and since > 0.3:
        probe_download_blob()
        set_stage("download2")
    elif stage == "download2" and since > 1.0:
        probe_download_runtime()
        set_stage("wait_activation_expiry")
    elif stage == "wait_activation_expiry" and (now - t_start) > 8.0:
        # More than 5 s after the start click: transient user activation has expired.
        try:
            emit("filedialog_without_gesture", open_file_dialog("nogesture"))
        except Exception as e:  # noqa: BLE001
            emit("filedialog_without_gesture", {"EXCEPTION": describe_exc(e)})
        set_stage("after_nogesture")
    elif stage == "after_nogesture" and since > 1.5:
        emit("filedialog_without_gesture_result", {"delivered": "nogesture" in got, "item": got.get("nogesture")})
        set_stage("press_o")  # driver presses "o"
    elif stage == "press_o" and pyxel.btnp(pyxel.KEY_O):
        emit("filedialog_after_keypress", open_file_dialog("then"))
        set_stage("wait_file_then")
    elif stage == "wait_file_then" and "then" in got:
        set_stage("press_p")  # driver presses "p"
    elif stage == "press_p" and pyxel.btnp(pyxel.KEY_P):
        emit("filedialog_after_keypress_asyncio", open_file_dialog("asyncio", use_asyncio=True))
        set_stage("wait_file_asyncio")
    elif stage == "wait_file_asyncio" and "asyncio" in got:
        set_stage("drop")  # driver drops a file
    elif stage == "drop" and "drop" in got:
        set_stage("end")
        print("SPIKE_DONE run=1")
    elif stage not in ("boot", "end") and since > 20.0:
        emit("stage_timeout", {"stage": stage})
        set_stage("end")
        print("SPIKE_TIMEOUT")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "JS BRIDGE RUN %d" % RUN, 7)
    pyxel.text(4, 14, "STAGE %s" % stage.upper(), 10)
    pyxel.text(4, 24, "FRAME %d" % frame, 6)
    y = 40
    for name in list(report)[-18:]:
        pyxel.text(4, y, name.upper()[:38], 11)
        y += 8


pyxel.init(160, 200, title="jsbridge", fps=30)
pyxel.run(update, draw)
