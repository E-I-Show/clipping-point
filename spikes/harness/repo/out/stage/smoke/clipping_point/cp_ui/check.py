"""Overflow rules over a recorded Canvas. Returns a list of violations (empty = clean)."""
from .canvas import Canvas, Item


def _inside(a: Item, x, y, x2, y2) -> bool:
    return a.x >= x and a.y >= y and a.x2 <= x2 and a.y2 <= y2


def _overlap(a: Item, b: Item) -> bool:
    return a.x < b.x2 and b.x < a.x2 and a.y < b.y2 and b.y < a.y2


def find_violations(canvas: Canvas) -> list:
    out = []
    items = canvas.items
    for i, it in enumerate(items):
        what = f"{it.kind} {it.label!r} at ({it.x},{it.y}) {it.w}x{it.h}"
        if it.w <= 0 or it.h <= 0:
            out.append(f"empty: {what}")
            continue
        if not _inside(it, 0, 0, canvas.w, canvas.h):
            out.append(f"off_screen: {what} leaves the {canvas.w}x{canvas.h} screen")
        if it.box >= 0:
            p = items[it.box]
            if not _inside(it, p.x, p.y, p.x2, p.y2):
                out.append(f"out_of_box: {what} leaves box {p.label!r} ({p.x},{p.y}) {p.w}x{p.h}")
        if it.kind == "text" and not all(32 <= ord(c) <= 126 or c == "\n" for c in it.label):
            out.append(f"bad_char: {what} (built-in font draws printable ASCII only)")
    texts = [it for it in items if it.kind == "text"]
    for n, a in enumerate(texts):
        for b in texts[n + 1 :]:
            if _overlap(a, b):
                out.append(f"text_overlap: {a.label!r} at ({a.x},{a.y}) and {b.label!r} at ({b.x},{b.y})")
    return out


def stats(canvas: Canvas) -> dict:
    kinds = {}
    for it in canvas.items:
        kinds[it.kind] = kinds.get(it.kind, 0) + 1
    return kinds
