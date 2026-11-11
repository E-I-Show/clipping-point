"""巡回。各画面のスクリーンショットを保存し、描画命令と実際の画素を照らす。アプリを、画面なしで別プロセスで回す。

  python3 tools/tour.py [--only 画面の名] [--timeout 秒]

予定は、画面の登録（cp_ui.screens の SCREENS）の全部の画面 × 見本データ（cp_ui.fixtures）の全部の変種。
out/tour/ を消して作り直し、アプリの巡回の口（clipping_point/cp_app/tour.py。環境変数 CP_TOUR、CP_TOUR_DIR、CP_TOUR_ONLY）を回す。
アプリは、画面 × 変種ごとに、画像（out/tour/<画面の名>_<変種>.png。画面の2倍）を保存し、数えた値を結果ファイルに書く。
合否は、ここで決める。
終了コード：
  2＝回り切れない。予定が0件、--only の名が無い、画面の登録と見本データを読み込めない・組み立てられない、時間切れ、
     アプリの終了コードが0でない、結果ファイルが無い・読めない、予定のどれかが結果に無い（missing_shot）、
     画像が無い（no_image）、画像の大きさが640×480でない（image_size）、画面が空（背景と違う画素が0。blank_screen）、
     照らした命令の数が0か、道具が同じ見本データでPyxelなしに組み立てた命令の数と違う（commands_checked）、
     結果の形が違う（result_shape）
  1＝問題あり。余白に画素がある（margin_ink）、命令の矩形の外に画素がある（ink_outside）、
     矩形の内に画素が無い命令がある（no_ink）、はみ出しがある（violation）
  0＝回り切って、問題が無い
アプリの終了コードが0でも、それだけでは合格にしない。全部の画面を回した後に書く結果ファイルと、画像を見る。
最後の1行の shots= は「回り切った枚数/予定の枚数」、commands= は、照らした命令の数の合計。
機械が見るのは、画像があることと、命令の矩形と画素が合うことまで。描く順の誤り（文字が、後から描いた下地に隠れる）は拾えない。
保存した画像は、目で見る（見た枚数と、見ていない枚数を、検証の行に分けて書く）。
"""
import argparse
import json
import shutil
import struct
import sys

import screen_check
from _common import APP, FAIL, INCOMPLETE, OK, OUT, child_env, finish, load_budgets, run, show_tail

WORK = OUT / "tour"
# 割り切り：画像は、あることと、大きさだけを見る。中身（全部の命令を描いた絵かどうか）は、偽の Pyxel のテスト
# （tests/test_tour.py）と、保存した画像を目で見ることに任せる。走行画面の巡回を足す段0 区切り10で、中身を照らすかを見直す。
IMAGE_SIZE = (640, 480)  # 保存する画像の大きさ。画面（320×240）の2倍
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_HEAD_BYTES = 24  # 署名（8）、最初のチャンクの長さと名（8）、幅と高さ（8）
MAX_DETAILS = 40  # 画面に出す問題の行数の上限


def png_size(path):
    """PNGの頭から、(幅, 高さ) を読む。ファイルが無い、PNGでない、のどちらでも None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(PNG_HEAD_BYTES)
    except OSError:
        return None
    if len(head) < PNG_HEAD_BYTES or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def judge(planned: list, want_commands: dict, data, sizes: dict) -> tuple:
    """結果ファイルの中身と、画像の大きさから、判定する。

    planned は (画面の名, 変種) の並び。want_commands は、道具が同じ見本データでPyxelなしに組み立てた命令の数。
    data は結果ファイルの中身。sizes は、画像の (幅, 高さ)（無ければ None）。どちらの辞書も、鍵は (画面の名, 変種)。
    返すのは (回り切れなかった所の一覧, 問題の一覧, 回り切った枚数, 照らした命令の数の合計)。一覧の中身は (種類, 文)。
    """
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list):
        return [("result_shape", "結果ファイルに、件の一覧（shots）が無い")], [], 0, 0
    by_key = {(shot.get("screen"), shot.get("variant")): shot for shot in shots if isinstance(shot, dict)}
    incomplete, problems, done, checked_total = [], [], 0, 0
    for key in planned:
        name = "/".join(key)
        shot = by_key.get(key)
        if shot is None:
            incomplete.append(("missing_shot", f"{name}: 予定の件が、結果に無い"))
            continue
        checked, screen_ink, margin_ink = shot.get("checked"), shot.get("screen_ink"), shot.get("margin_ink")
        command_problems, violations = shot.get("command_problems"), shot.get("violations")
        if (
            any(type(value) is not int for value in (checked, screen_ink, margin_ink))
            or not isinstance(command_problems, list)
            or not isinstance(violations, list)
        ):
            incomplete.append(("result_shape", f"{name}: 結果の形が違う"))
            continue
        gaps = []
        size = sizes.get(key)
        if size is None:
            gaps.append(("no_image", f"{name}: 画像が無い"))
        elif tuple(size) != IMAGE_SIZE:
            gaps.append(("image_size", f"{name}: 画像が {size[0]}x{size[1]}（{IMAGE_SIZE[0]}x{IMAGE_SIZE[1]} のはず。全体の絵から、画面の大きさを切り出して保存する）"))
        if screen_ink <= 0:
            gaps.append(("blank_screen", f"{name}: 画面が空（背景と違う画素が {screen_ink}）"))
        want = want_commands.get(key)
        if checked <= 0 or checked != want:
            gaps.append(("commands_checked", f"{name}: 照らした命令の数が {checked}（道具が同じ見本データで組み立てた命令の数は {want}）"))
        incomplete += gaps
        if not gaps:
            done += 1
            checked_total += checked
        if margin_ink:
            problems.append(("margin_ink", f"{name}: 余白に画素が {margin_ink} 個ある（画面の外へ描いている）"))
        for entry in command_problems:
            entry = entry if isinstance(entry, dict) else {}
            kind = entry.get("problem") if isinstance(entry.get("problem"), str) else "command_problem"
            problems.append((
                kind,
                f"{name}: 命令 #{entry.get('index')} {entry.get('kind')} {entry.get('text')!r} 矩形 {entry.get('bounds')}："
                f"矩形の外の画素 {entry.get('outside')}、内の画素 {entry.get('inside')}",
            ))
        for entry in violations:
            entry = entry if isinstance(entry, dict) else {}
            problems.append(("violation", f"{name}: はみ出し {entry.get('kind')}: {entry.get('text')}"))
    return incomplete, problems, done, checked_total


def kinds_of(entries: list) -> str:
    """一覧の種類を、出てきた順に、重ねずに並べる。"""
    kinds = []
    for kind, _ in entries:
        if kind not in kinds:
            kinds.append(kind)
    return ",".join(kinds)


def main() -> int:
    ap = argparse.ArgumentParser(description="各画面の画像を保存し、描画命令と実際の画素を照らす")
    ap.add_argument("--only", default="", metavar="SCREEN", help="この画面だけ回す")
    ap.add_argument("--timeout", type=float, default=None, help="秒。既定は tools/budgets.json の tour_timeout_s")
    args = ap.parse_args()
    timeout = args.timeout if args.timeout is not None else load_budgets()["tour_timeout_s"]
    try:
        screens, variants, build, canvas_type, _ = screen_check.load_ui()
    except Exception as exc:  # noqa: BLE001 - 読み込めなければ、何も調べていない
        print(f"  tour: 画面の登録と見本データを読み込めない：{type(exc).__name__}: {exc}")
        return finish("tour", INCOMPLETE, "shots=0/0 commands=0 problems=0 reason=cannot_load")
    if args.only and args.only not in screens:
        print(f"  tour: --only の名の画面が無い：{args.only!r}（ある名：{', '.join(sorted(screens))}）")
        return finish("tour", INCOMPLETE, f"shots=0/0 commands=0 problems=0 reason=unknown_screen only={args.only!r}")
    planned = screen_check.plan(screens, variants, args.only)
    none_done = f"shots=0/{len(planned)} commands=0 problems=0"
    if not planned:
        return finish("tour", INCOMPLETE, f"{none_done} reason=nothing_planned")
    # 道具の側で、同じ見本データで、Pyxelなしに組み立てた命令の数。アプリが照らした命令の数と比べる。
    want_commands = {}
    for screen, variant in planned:
        canvas, reason = screen_check.build_canvas(screens, build, canvas_type, screen, variant)
        if canvas is None:
            print(f"  tour: 組み立てられない：{screen}/{variant}: {reason}")
            return finish("tour", INCOMPLETE, f"{none_done} reason=cannot_build")
        want_commands[(screen, variant)] = len(canvas.commands)

    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    result_path = WORK / "result.json"
    env = child_env(CP_TOUR=result_path, CP_TOUR_DIR=WORK)
    if args.only:
        env["CP_TOUR_ONLY"] = args.only
    code, out, err = run([sys.executable, APP / "main.py"], timeout=timeout, env=env, cwd=WORK)
    tail = f"dir={WORK}"
    if code is None:
        show_tail(out, err)
        return finish("tour", INCOMPLETE, f"{none_done} reason=timeout timeout_s={timeout:g} {tail}")
    if code != 0:
        show_tail(out, err)
        return finish("tour", INCOMPLETE, f"{none_done} reason=app_exit_code app_exit={code} {tail}")
    if not result_path.exists():
        show_tail(out, err)
        return finish("tour", INCOMPLETE, f"{none_done} reason=no_result_file app_exit=0 {tail}")
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except ValueError:
        return finish("tour", INCOMPLETE, f"{none_done} reason=result_unreadable {tail}")

    sizes = {(screen, variant): png_size(WORK / f"{screen}_{variant}.png") for screen, variant in planned}
    incomplete, problems, done, checked_total = judge(planned, want_commands, data, sizes)
    shots = data.get("shots") if isinstance(data, dict) else None
    for shot in shots if isinstance(shots, list) else []:
        if isinstance(shot, dict):
            print(
                f"  tour: {shot.get('screen')}/{shot.get('variant')} commands={shot.get('commands')} checked={shot.get('checked')} "
                f"screen_ink={shot.get('screen_ink')} margin_ink={shot.get('margin_ink')} check_ms={shot.get('check_ms')} "
                f"file={WORK / str(shot.get('file'))}"
            )
    if isinstance(data, dict):
        print(f"  tour: アプリの中の時間 {data.get('wall_s')} 秒（Pyxelの起動を含む）")
    for label, entries in (("回り切れない", incomplete), ("問題", problems)):
        for _, text in entries[:MAX_DETAILS]:
            print(f"  tour: {label}：{text}")
        if len(entries) > MAX_DETAILS:
            print(f"  tour: {label}：ほか {len(entries) - MAX_DETAILS} 件")
    summary = f"shots={done}/{len(planned)} commands={checked_total} problems={len(problems)}"
    if problems:
        summary += f" failed={kinds_of(problems)}"
    if incomplete:
        summary += f" incomplete={kinds_of(incomplete)}"
    summary += f" {tail}"
    if incomplete or done != len(planned):
        return finish("tour", INCOMPLETE, summary)
    return finish("tour", FAIL if problems else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
