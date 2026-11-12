"""巡回の口。見本データ（cp_ui.fixtures）で画面を組み立てて描き、画像を保存し、描画命令と実際の画素を照らす。

デスクトップ版だけで動く。ブラウザ版には環境変数が無く、cp_app/app.py の main() は、ブラウザ版ではここを読まない。
このモジュール自身は pyxel をimportしない。Pyxel（のモジュール）は、run() の引数で受ける。

環境変数（tools/tour.py が使う）。CP_TOUR が無ければ、普通に起動する。
  CP_TOUR=<結果ファイル（JSON）の絶対パス>   あれば、画面なしでPyxelを始め、巡回して、結果ファイルを書いて終わる
  CP_TOUR_DIR=<画像の置き場の絶対パス>       要る。置き場は、道具が先に作る
  CP_TOUR_ONLY=<画面の名 か scene>           省けば、全部の画面と、3Dの絵。画面の名なら、その画面だけ。scene なら、3Dの絵だけ
CP_TOUR と CP_TOUR_DIR が絶対パスでない、CP_TOUR_ONLY の名の画面が無い、CP_SMOKE と CP_TOUR の両方がある、
のどれでも、起動時に ValueError（pyxel.init が作業ディレクトリを変えるので、相対パスは受けない）。

3Dの場面（cp_app/render.py の Scene）は、run() の引数で受ける（作るのは main()）。Pyxelを始めた後に、場面を組む
（Scene.build。パレットも、ここで当たる。保存する画像の色は、アプリと同じ）。判定用の柱と印も作る（巡回の口は、検証の口）。

3Dの絵（見本は SCENE_SHOTS。決めた車の位置と向き）ごとに、次を行う。2Dの描画命令は、重ねない。
  絵        ふだんの実描画と同じ描く口（Scene.draw）で、走行の絵を描いて、SHOT_SCALE 倍で保存する（scene_<見本の名>.png）。
  判定      同じ車の位置と向きで、判定用の実描画（Scene.judge）を回し、数えた値を、結果の scenes に入れる（形は tools/scene_reference.py）。

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
画素は、pyxel.Image.data_ptr() でまとめて読む（1画素1バイト、左上から行ごと。読む口は cp_app/render.py の read_pixels）。
1画素ずつ読む pget の約260倍速い（実測）。
描く順の誤り（文字が、後から描いた下地に隠れる）と、3Dの絵の見た目（色、欠け、向き）は、ここでは拾えない。保存した画像を、目で見る。
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
from .render import read_pixels

MARGIN = 16  # 検査用の裏画面で、画面の外側に取る余白（ピクセル）
SHOT_SCALE = 2  # 保存する画像の拡大率
CHECK_BACK, CHECK_BACK_ALT = 0, 1  # 命令ごとの照合で、検査用の裏画面を消す色。命令の色と同じなら、もう一方を使う
PROBLEM_OUTSIDE, PROBLEM_NO_INK = "ink_outside", "no_ink"  # 命令ごとの照合の、問題の種類
SCENE_ONLY = "scene"  # CP_TOUR_ONLY に渡すと、3Dの絵だけを回す名。画面の名と、重ならないこと
SCENE_FILE_HEAD = "scene_"  # 3Dの絵の、画像の名の頭（scene_<見本の名>.png）
# 3Dの絵の見本（決めた車の位置と向き）。(名, コースに沿った距離 m, 横のずれ m（左が正）, コースの向きからのずれ rad（左が正）)。
# 車の位置と向きは、コースの表から引く（Track.pose_at）。仮の周回路（test_loop）での値：
#   straight  1本目の直線の、スタート位置。向き0、z=0（向きの符号の誤りと、z の反転の付け忘れが、絵に出ない所）
#   corner    最初のコーナーの途中。向きは約1.1 rad（π/4〜3π/4 の間）、z は約25 m
#   wall      2つ目のコーナーの、外側の壁の近く。壁の側へ向いている。向きは約−2.58 rad（0、±π/2、π のどれからも、0.3 rad以上離れている）
# 割り切り：見本は、仮の周回路の寸法で決めた値。コースが変わると、狙った所（直線、コーナー、壁の近く）から外れる（条件は tests/test_tour.py が見る）。
# 本物のコースを作る段1の「コースデータと照会」の区切りで、コースごとの見本にする。
SCENE_SHOTS = (
    ("straight", 60.0, 0.0, 0.0),
    ("corner", 262.0, 1.5, 0.0),
    ("wall", 620.0, -11.5, -0.35),
)


@dataclass(frozen=True)
class TourConfig:
    """巡回の指定（結果ファイル、画像の置き場、回す画面）。"""

    result_path: str
    shot_dir: str
    only: str = ""  # 回す画面の名。空なら全部（画面と、3Dの絵）。SCENE_ONLY なら、3Dの絵だけ


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
    if only and only != SCENE_ONLY and only not in SCREENS:
        raise ValueError(f"CP_TOUR_ONLY must be one of {sorted([*SCREENS, SCENE_ONLY])}, got {only!r}")
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


def scene_pose(track, sample) -> tuple:
    """3Dの絵の見本（SCENE_SHOTS の1件）から、車の位置と向き (x, z, 向き) を引く。ロジックの座標。track は、コースの表。"""
    _, s, lateral, turn = sample
    x, z, heading = track.pose_at(s, lateral)
    return x, z, heading + turn


def shoot_scene(sample, scene, shot, shot_dir: str) -> dict:
    """3Dの絵1枚を描いて、保存して、同じ車の位置と向きで、判定用の実描画を回す。返すのは、結果ファイルに入れる1件。

    scene は、組んだ場面（cp_app/render.py の Scene。判定用の柱と印つき）。shot は、保存する画像（画面の大きさ）。
    絵は、ふだんの実描画と同じ描く口（Scene.draw。描くものは、既定）で描く。2Dの描画命令は、重ねない。
    """
    name = sample[0]
    x, z, heading = scene_pose(scene.track, sample)
    scene.draw(shot, scene.chase(x, z, heading), x, z, heading)
    file = f"{SCENE_FILE_HEAD}{name}.png"
    shot.save(os.path.join(shot_dir, file), SHOT_SCALE)
    # 判定。保存した絵の画素を渡す（判定用の3枚目と、同じ絵のはず）。判定は、shot とは別の絵へ描く。
    judged = scene.judge(read_pixels(shot), (), x, z, heading)
    return {
        "name": name, "file": file, "x_mm": round(x * 1000.0), "z_mm": round(z * 1000.0), "heading_mrad": round(heading * 1000.0),
        "scene": judged, "chunks_drawn": scene.stats.get("chunks_drawn"), "triangles_drawn": scene.stats.get("triangles_drawn"),
    }


def run(pyxel, config: TourConfig, scene) -> dict:
    """画面なしでPyxelを始め、巡回して、結果ファイルを書く。返すのは、書いた結果。終了はしない（呼ぶ側が sys.exit する）。

    scene は、3Dの場面（cp_app/render.py の Scene。作るのは main()）。Pyxelを始めた後に、ここで組む（パレットも、ここで当たる）。
    """
    started_s = time.perf_counter()
    pyxel.init(SCREEN_W, SCREEN_H, title=TITLE, quit_key=pyxel.KEY_NONE, capture_sec=0, headless=True)
    scene.build(probes=True, clock=time.perf_counter)  # 巡回の口は、検証の口。判定用の柱と印も作る
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
    scenes = []
    if config.only in ("", SCENE_ONLY):
        for sample in SCENE_SHOTS:
            scenes.append(shoot_scene(sample, scene, shot, config.shot_dir))
    result = {
        "shots": shots,
        "scenes": scenes,
        "scene_stats": dict(scene.stats),
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
