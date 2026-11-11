"""Which imports work in Pyxel Web, how long they take, and which ones make the runtime
probe the hosting server ("Attempting to fetch ..." console lines, one synchronous XHR each)?

The driver counts the "Attempting to fetch" lines that appear between IMPORT_BEGIN/IMPORT_END markers.
"""

import importlib
import json
import sys
import time

import pyxel

MODULES = [
    "math", "random", "struct", "zlib", "json", "base64", "binascii", "hashlib", "array", "time",
    "dataclasses", "enum", "typing", "collections", "itertools", "functools", "bisect", "heapq",
    "io", "os", "re", "copy", "pickle", "gzip", "zipfile", "datetime", "statistics", "fractions",
    "decimal", "operator", "abc", "contextlib", "weakref", "types", "numbers", "cmath", "string",
    "textwrap", "traceback", "logging", "warnings", "platform", "uuid", "tempfile", "pathlib",
    "csv", "tomllib", "asyncio", "unittest", "ctypes", "sqlite3", "ssl", "lzma", "bz2",
    "multiprocessing", "threading", "socket", "urllib.request", "tkinter",
    "js", "pyodide", "pyodide.ffi", "pyodide.http", "micropip", "numpy",
    "pkg_inside", "pkg_inside.sub",
]  # fmt: skip

import os

results = []


def run_imports(label):
    print("INFO %s cwd=%s sys.path=%s" % (label, os.getcwd(), json.dumps(sys.path)))
    for name in MODULES:
        already = name in sys.modules
        print("IMPORT_BEGIN " + name)
        t0 = time.perf_counter()
        try:
            importlib.import_module(name)
            ok, err = True, None
        except BaseException as e:  # noqa: BLE001
            ok, err = False, "%s: %s" % (type(e).__name__, str(e)[:120])
        ms = (time.perf_counter() - t0) * 1000
        print("IMPORT_END " + name)
        results.append({"module": name, "ok": ok, "error": err, "ms": round(ms, 1), "already_loaded": already})
    print("RESULT_JSON imports " + json.dumps(results))


# Module top level, BEFORE pyxel.init: this is where a game's imports normally run.
run_imports("before pyxel.init")

frame = 0


def update():
    global frame
    frame += 1
    if frame == 5:
        print("INFO after pyxel.init cwd=%s" % os.getcwd())
        print("IMPORT_BEGIN late_missing_module")
        try:
            importlib.import_module("late_missing_module")
        except ImportError as e:
            print("INFO late import failed as expected: %s" % e)
        print("IMPORT_END late_missing_module")
        import zlib

        blob = bytes((i * 31 + (i >> 3)) & 0xFF for i in range(500_000))
        t0 = time.perf_counter()
        z = zlib.compress(blob, 6)
        t1 = time.perf_counter()
        back = zlib.decompress(z)
        t2 = time.perf_counter()
        print("RESULT_JSON zlib " + json.dumps({"in": len(blob), "out": len(z), "compress_ms": round((t1 - t0) * 1000, 2), "decompress_ms": round((t2 - t1) * 1000, 2), "ok": back == blob}))
    if frame == 8:
        print("SPIKE_DONE")


def draw():
    pyxel.cls(1)
    pyxel.text(4, 4, "IMPORTS %d" % frame, 7)


pyxel.init(160, 120, title="imports", fps=30)
pyxel.run(update, draw)
