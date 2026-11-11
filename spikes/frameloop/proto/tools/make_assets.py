"""Generates the prototype's binary data and assets (run once; outputs are committed files).
Also plants files that `pyxel package` is expected to leave out."""
import math
import os
import sys
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "cp_proto"
sys.path.insert(0, str(APP))

from cp_core.datafiles import pack_track  # noqa: E402

import pyxel  # noqa: E402

pts = [(100 * math.cos(t) * (1 + 0.25 * math.sin(3 * t)), 60 * math.sin(t)) for t in [i * math.tau / 48 for i in range(48)]]
(APP / "data" / "track.bin").write_bytes(pack_track(pts))

pyxel.init(64, 64, headless=True, capture_sec=0)
pyxel.images[0].rect(0, 0, 16, 16, 9)
pyxel.images[0].rect(2, 2, 12, 12, 3)
pyxel.save(str(APP / "assets" / "proto.pyxres"))

logo = pyxel.Image(40, 10)
logo.cls(0)
logo.text(2, 2, "CP PROTO", 10)
logo.save(str(APP / "assets" / "logo.png"), 1)

# files expected to be excluded from the .pyxapp
(APP / "assets" / "excluded_demo.gif").write_bytes(b"GIF89a" + bytes(32))
with zipfile.ZipFile(APP / "assets" / "excluded_bundle.zip", "w") as zf:
    zf.writestr("x.txt", "x")
(APP / ".hidden_dir").mkdir(exist_ok=True)
(APP / ".hidden_dir" / "notes.txt").write_text("excluded: dot directory\n")
(APP / ".dotfile").write_text("excluded: dot file\n")
(APP / "data" / ".draft.json").write_text("{}\n")
print("assets written under", APP)
for p in sorted(APP.rglob("*")):
    if p.is_file() and "__pycache__" not in p.parts:
        print(f"  {p.relative_to(APP)}  {p.stat().st_size} B")
