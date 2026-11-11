"""巡回の口。見本データ（cp_ui.fixtures）で画面を組み立てて描き、画像を保存し、描画命令と実際の画素を照らす。

デスクトップ版だけで動く。ブラウザ版には環境変数が無く、cp_app/app.py の main() は、ブラウザ版ではここを読まない。
このモジュール自身は pyxel をimportしない。Pyxel（のモジュール）は、run() の引数で受ける。

環境変数（tools/tour.py が使う）。CP_TOUR が無ければ、普通に起動する。
  CP_TOUR=<結果ファイル（JSON）の絶対パス>   あれば、画面なしでPyxelを始め、巡回して、結果ファイルを書いて終わる
  CP_TOUR_DIR=<画像の置き場の絶対パス>       要る。置き場は、道具が先に作る
  CP_TOUR_ONLY=<画面の名>                    省けば、全部の画面
CP_TOUR と CP_TOUR_DIR が絶対パスでない、CP_TOUR_ONLY の名の画面が無い、CP_SMOKE と CP_TOUR の両方がある、
のどれでも、起動時に ValueError（pyxel.init が作業ディレクトリを変えるので、相対パスは受けない）。

画面 × 変種ごとに、次を行う。入力の注入では進めない（画面の状態を作る段1で足す）。
  全体      余白（MARGIN）つきの検査用の裏画面へ、(MARGIN, MARGIN) ずらして全部の命令を描く。
            余白に出た画素の数と、画面の内の、背景と違う画素の数を数える。
  命令ごと  全体の絵とは別の検査用の裏画面を、その命令の色と違う色で消し、その命令だけを描く。
            命令の矩形（bounds）の外の画素の数と、内の画素の数を数える。外に1つでもあるか、内に1つも無ければ、問題。
            空白だけの文字の命令は、内の画素が0でよい。
            全部を描いた後に数える形では、塗りの上の文字のはみ出し、背景と同じ色の画素、描かれていない命令が見えない。
  はみ出しの検査（cp_ui.check.find_violations）も当てて、結果に入れる。
  画像      全体の絵（命令ごとの照合で描き直した絵ではない）から、画面の大きさを切り出して、SHOT_SCALE 倍で保存する。
結果ファイルは、全部の画面を回した後にだけ書く（一時ファイルに書いて、差し替える）。合否は決めない（決めるのは tools/tour.py）。
pyxel.run も pyxel.flip も呼ばない。終わるときは、呼ぶ側（main()）が sys.exit を使う（pyxel.quit は、常に終了コード0で終わる）。
画素は、pyxel.Image.data_ptr() でまとめて読む（1画素1バイト、左上から行ごと）。1画素ずつ読む pget の約260倍速い（実測）。
描く順の誤り（文字が、後から描いた下地に隠れる）は、ここでは拾えない。保存した画像を、目で見る。
パレットを変えたら、ここでも同じパレットを当てる（保存する画像の色のため）。
"""
import json
import os
import sys
import time
from dataclasses import dataclass

from cp_ui import fixtures
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.check import find_violations
from cp_ui.screens import COL_BACK, SCREENS, TITLE

from .canvas_pyxel import execute

MARGIN = 16  # 検査用の裏画面で、画面の外側に取る余白（ピクセル）
SHOT_SCALE = 2  # 保存する画像の拡大率
CHECK_BACK, CHECK_BACK_ALT = 0, 1  # 命令ごとの照合で、検査用の裏画面を消す色。命令の色と同じなら、もう一方を使う
PROBLEM_OUTSIDE, PROBLEM_NO_INK = "ink_outside", "no_ink"  # 命令ごとの照合の、問題の種類


@dataclass(frozen=True)
class TourConfig:
    """巡回の指定（結果ファイル、画像の置き場、回す画面）。"""

    result_path: str
    shot_dir: str
    only: str = ""  # 回す画面の名。空なら全部


def read_config(env) -> TourConfig | None:
    """環境変数から、巡回の指定を読む。CP_TOUR が無ければ None（巡回しない）。"""
    result_path = env.get("CP_TOUR", "")
    if not result_path:
        return None
    if env.get("CP_SMOKE", ""):
        raise ValueError("CP_TOUR and CP_SMOKE cannot be used together")
    if not os.path.isabs(result_path):
        raise ValueError("CP_TOUR must be an absolute path (pyxel.init changes the working directory)")
    shot_dir = env.get("CP_TOUR_DIR", "")
    if not os.path.isabs(shot_dir):
        raise ValueError("CP_TOUR_DIR must be an absolute path (pyxel.init changes the working directory)")
    only = env.get("CP_TOUR_ONLY", "")
    if only and only not in SCREENS:
        raise ValueError(f"CP_TOUR_ONLY must be one of {sorted(SCREENS)}, got {only!r}")
    return TourConfig(result_path, shot_dir, only)


# --- 画素を照らす計算。Pyxelに触れない ---
def count_ink(pixels, width: int, height: int, back: int, rect: tuple) -> tuple:
    """back と違う色の画素を数える。返すのは (rect の外の数, rect の内の数)。

    pixels は、左上から行ごとに並んだ、1画素1バイトの色の番号（bytes）。rect は (x, y, w, h)。
    """
    if len(pixels) != width * height:
        raise ValueError(f"pixels has {len(pixels)} entries, expected {width}x{height}")
    x, y, w, h = rect
    left, right = max(x, 0), min(x + w, width)
    outside = inside = 0
    for row_index in range(height):
        row = pixels[row_index * width:(row_index + 1) * width]
        ink = width - row.count(back)
        if not ink:
            continue
        hit = 0
        if y <= row_index < y + h and left < right:
            part = row[left:right]
            hit = len(part) - part.count(back)
        inside += hit
        outside += ink - hit
    return outside, inside


def is_blank_text(command) -> bool:
    """空白と改行だけの文字の命令か。画素を1つも置かないのが正しい。"""
    return command.kind == "text" and not command.text.strip(" \n")


def command_problems(command, outside: int, inside: int) -> list:
    """命令を1つだけ描いた絵の数から、問題の種類の一覧を返す（空なら、問題なし）。"""
    problems = []
    if outside:
        problems.append(PROBLEM_OUTSIDE)  # 命令の矩形の外に画素がある
    if not inside and not is_blank_text(command):
        problems.append(PROBLEM_NO_INK)  # 矩形の内に画素が無い（描かれていない）
    return problems


def back_for(col: int) -> int:
    """命令ごとの照合で、検査用の裏画面を消す色。命令の色と違う色。"""
    return CHECK_BACK if col != CHECK_BACK else CHECK_BACK_ALT


# --- ここから下は、Pyxelの画像（pyxel.Image）に触れる ---
def read_pixels(image) -> bytes:
    """画像の全部の画素を、まとめて読む。1画素1バイト、左上から行ごと。"""
    pixels = bytes(image.data_ptr())
    if len(pixels) != image.width * image.height:
        raise RuntimeError(f"data_ptr() gave {len(pixels)} bytes for a {image.width}x{image.height} image")
    return pixels


def check_reader(image) -> None:
    """画素の読み方が、1画素ずつ置いた点と合うことを確かめる（並びが違えば、照合の全部が偽になる）。"""
    image.cls(CHECK_BACK)
    image.pset(1, 0, 2)
    image.pset(0, 1, 3)
    pixels = read_pixels(image)
    if pixels[1] != 2 or pixels[image.width] != 3 or len(pixels) - pixels.count(CHECK_BACK) != 2:
        raise RuntimeError("data_ptr() is not one byte per pixel in row order")


# 割り切り：見本データで描くので、アプリが画面を描く道（cp_app/app.py の render()）は通らない。そこは、道具 run と、
# 配線の守りのテスト（tests/test_screens.py）が見る。画面の状態を作る段1で、入力で画面を進める巡回を足す時に見直す。
def shoot(screen: str, variant: str, whole, single, shot, shot_dir: str) -> dict:
    """画面1つ × 変種1つを描いて、照らして、画像を保存する。返すのは、結果ファイルに入れる1件。

    whole は全体の絵を描く検査用の裏画面、single は命令を1つずつ描く検査用の裏画面（どちらも余白つき）、
    shot は保存する画像（画面の大きさ）。
    """
    canvas = Canvas()
    SCREENS[screen](canvas, fixtures.build(screen, variant))
    commands = canvas.commands
    width, height = whole.width, whole.height
    # 全体。余白に出た画素と、画面の内の、背景と違う画素。
    whole.cls(COL_BACK)
    execute(commands, whole, MARGIN, MARGIN)
    margin_ink, screen_ink = count_ink(read_pixels(whole), width, height, COL_BACK, (MARGIN, MARGIN, canvas.w, canvas.h))
    # 命令ごと。
    started_s = time.perf_counter()
    checked, problems = 0, []
    for index, command in enumerate(commands):
        back = back_for(command.col)
        single.cls(back)
        execute([command], single, MARGIN, MARGIN)
        x, y, w, h = command.bounds
        outside, inside = count_ink(read_pixels(single), width, height, back, (x + MARGIN, y + MARGIN, w, h))
        checked += 1
        for problem in command_problems(command, outside, inside):
            problems.append({
                "index": index, "kind": command.kind, "problem": problem, "outside": outside, "inside": inside,
                "bounds": [x, y, w, h], "text": command.text if command.kind == "text" else "",
            })
    check_ms = (time.perf_counter() - started_s) * 1000.0
    violations = [{"kind": violation.kind, "text": violation.text} for violation in find_violations(canvas)]
    # 画像。全体の絵から、画面の大きさを切り出す。
    file = f"{screen}_{variant}.png"
    path = os.path.join(shot_dir, file)
    shot.blt(0, 0, whole, MARGIN, MARGIN, SCREEN_W, SCREEN_H)
    shot.save(path, SHOT_SCALE)
    return {
        "screen": screen, "variant": variant, "file": file, "commands": len(commands), "checked": checked,
        "margin_ink": margin_ink, "screen_ink": screen_ink, "command_problems": problems, "violations": violations,
        "check_ms": round(check_ms, 3),
    }


def run(pyxel, config: TourConfig) -> dict:
    """画面なしでPyxelを始め、巡回して、結果ファイルを書く。返すのは、書いた結果。終了はしない（呼ぶ側が sys.exit する）。"""
    started_s = time.perf_counter()
    pyxel.init(SCREEN_W, SCREEN_H, title=TITLE, quit_key=pyxel.KEY_NONE, capture_sec=0, headless=True)
    whole = pyxel.Image(SCREEN_W + 2 * MARGIN, SCREEN_H + 2 * MARGIN)
    single = pyxel.Image(SCREEN_W + 2 * MARGIN, SCREEN_H + 2 * MARGIN)
    shot = pyxel.Image(SCREEN_W, SCREEN_H)
    check_reader(single)
    shots = []
    for screen in SCREENS:
        if config.only not in ("", screen):
            continue
        for variant in fixtures.VARIANTS:
            shots.append(shoot(screen, variant, whole, single, shot, config.shot_dir))
    result = {
        "shots": shots,
        "margin": MARGIN,
        "scale": SHOT_SCALE,
        "wall_s": round(time.perf_counter() - started_s, 3),
        "python": sys.version.split()[0],
        "pyxel": pyxel.VERSION,
    }
    tmp_path = config.result_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    os.replace(tmp_path, config.result_path)
    return result
