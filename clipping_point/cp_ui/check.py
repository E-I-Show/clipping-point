"""はみ出しの検査（純Python）。Canvas にためた描画命令と囲みから、はみ出しを数える。Pyxelは使わない。

数えるのは5種類（KINDS）。
  empty         空の矩形（幅か高さが0以下）。この命令や囲みは、ほかの判定をしない
  off_screen    矩形が、画面（canvas.w × canvas.h）の内に収まっていない。端にちょうど接するのは、内
  out_of_box    命令か囲みが、親の囲みの内に収まっていない
  bad_char      文字の命令に、印字できるASCII（文字の番号が32〜126）と改行のほかの字がある。内蔵フォントは、黙って描かない
  text_overlap  文字の命令どうしの矩形が、重なっている（囲みは問わない）
文字と矩形、矩形どうしの重なりは数えない（下地の上に文字を置くため）。
文字数の上限は、ここでは見ない（定義データの読み込み検査の側に置く。段0 区切り8）。
描く順の誤り（文字が、後から描いた下地に隠れる）も、ここでは拾えない。巡回が保存した画像を、目で見る。
文字の矩形は、インクの箱（cp_ui.canvas.text_size）。式が実物の画素と合うことは、巡回（tools/tour.py）が照らす。
"""
from dataclasses import dataclass

from cp_ui.canvas import SCREEN_BOX, Canvas

KINDS = ("empty", "off_screen", "out_of_box", "bad_char", "text_overlap")  # はみ出しの種類。並びは、判定の順
PRINTABLE_FIRST, PRINTABLE_LAST = 32, 126  # 内蔵フォントで出せる字の、文字の番号の範囲（印字できるASCII）


@dataclass(frozen=True)
class Violation:
    """はみ出しの1件。"""

    kind: str  # 種類。KINDS のどれか
    text: str  # 読める文（どの命令か、位置と大きさ）


def is_drawable(s: str) -> bool:
    """s が、印字できるASCIIと改行だけか。"""
    return all(PRINTABLE_FIRST <= ord(ch) <= PRINTABLE_LAST or ch == "\n" for ch in s)


def _inside(inner: tuple, outer: tuple) -> bool:
    """矩形 inner が、矩形 outer の内に収まっているか。端にちょうど接するのは、内。"""
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return x >= ox and y >= oy and x + w <= ox + ow and y + h <= oy + oh


def _overlap(a: tuple, b: tuple) -> bool:
    """2つの矩形が、1画素でも重なっているか。辺が隣り合うだけなら、重なっていない。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _describe(bounds: tuple) -> str:
    x, y, w, h = bounds
    return f"at ({x},{y}) {w}x{h}"


def _command_label(index: int, command) -> str:
    detail = f" {command.text!r}" if command.kind == "text" else ""
    return f"command #{index} {command.kind}{detail} {_describe(command.bounds)}"


def _box_label(index: int, box) -> str:
    return f"box #{index} {box.name!r} {_describe(box.bounds)}"


def _placement(label: str, bounds: tuple, parent: int, canvas: Canvas) -> list:
    """命令と囲みに共通の判定（empty、off_screen、out_of_box）。empty なら、ほかの判定をしない。"""
    _, _, w, h = bounds
    if w <= 0 or h <= 0:
        return [Violation("empty", f"{label} has no area")]
    found = []
    if not _inside(bounds, (0, 0, canvas.w, canvas.h)):
        found.append(Violation("off_screen", f"{label} leaves the {canvas.w}x{canvas.h} screen"))
    if parent != SCREEN_BOX:
        outer = canvas.boxes[parent]
        if not _inside(bounds, outer.bounds):
            found.append(Violation("out_of_box", f"{label} leaves {_box_label(parent, outer)}"))
    return found


def find_violations(canvas: Canvas) -> list:
    """canvas のはみ出しの列を返す（空なら、問題なし）。並びは、囲み、命令、文字どうしの重なりの順。"""
    found = []
    for index, box in enumerate(canvas.boxes):
        found += _placement(_box_label(index, box), box.bounds, box.parent, canvas)
    texts = []  # 重なりを見る文字の命令。(番号, 命令)。空の矩形のものは入れない
    for index, command in enumerate(canvas.commands):
        label = _command_label(index, command)
        placed = _placement(label, command.bounds, command.box, canvas)
        found += placed
        if placed and placed[0].kind == "empty":
            continue
        if command.kind == "text":
            texts.append((index, command))
            if not is_drawable(command.text):
                found.append(Violation("bad_char", f"{label} has characters the built-in font does not draw (printable ASCII only)"))
    for position, (index_a, a) in enumerate(texts):
        for index_b, b in texts[position + 1:]:
            if _overlap(a.bounds, b.bounds):
                found.append(Violation("text_overlap", f"{_command_label(index_a, a)} overlaps {_command_label(index_b, b)}"))
    return found
