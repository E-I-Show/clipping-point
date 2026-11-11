"""E2: is Python-level buffered output / finally / atexit preserved across pyxel.quit()?"""
import atexit
import sys

import pyxel

atexit.register(lambda: print("ATEXIT handler ran"))
f = open(sys.argv[1], "w")  # buffered file, never explicitly flushed
f.write("buffered file content\n")
print("line printed before quit (stdout buffered when piped)")
print("stdout isatty:", sys.stdout.isatty(), "line_buffering:", sys.stdout.line_buffering)
pyxel.init(64, 64, fps=60, headless=True)
try:
    pyxel.quit()
finally:
    print("FINALLY block ran")
print("AFTER QUIT")
