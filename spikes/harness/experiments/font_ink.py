"""Ink box of every printable ASCII glyph of Pyxel's built-in font (cell 4x6)."""
import json, sys
import pyxel
pyxel.init(64, 32, headless=True)
img = pyxel.Image(16, 16)
worst_w = worst_h = 0
wide, tall = [], []
for code in range(32, 127):
    img.cls(0)
    img.text(4, 4, chr(code), 7)
    xs = [x for x in range(16) for y in range(16) if img.pget(x, y)]
    ys = [y for x in range(16) for y in range(16) if img.pget(x, y)]
    if not xs:
        continue
    if min(xs) < 4 or min(ys) < 4:
        print("ink left/above origin:", chr(code))
    w, h = max(xs) - 4 + 1, max(ys) - 4 + 1
    worst_w, worst_h = max(worst_w, w), max(worst_h, h)
    if w > 3: wide.append(chr(code))
    if h > 5: tall.append(chr(code))
# multi-line advance and non-ASCII behaviour
img.cls(0); img.text(0, 0, "A\nB", 7)
rows = sorted({y for x in range(16) for y in range(16) if img.pget(x, y)})
img.cls(0); img.text(0, 0, "ツ", 7)
nonascii_ink = sum(1 for x in range(16) for y in range(16) if img.pget(x, y))
out = {"max_ink_w": worst_w, "max_ink_h": worst_h, "glyphs_wider_than_3": wide, "glyphs_taller_than_5": tall,
       "two_line_ink_rows": rows, "non_ascii_ink_pixels": nonascii_ink, "FONT_WIDTH": pyxel.FONT_WIDTH, "FONT_HEIGHT": pyxel.FONT_HEIGHT}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(out)
sys.exit(0)
