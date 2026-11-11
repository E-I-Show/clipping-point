"""2Dの全画面を、ふつうの値と極端な値で組み立て、はみ出しを数える。Pyxelは使わず、同じプロセスで回す。

  python3 tools/screen_check.py [--only 画面の名]

予定は、画面の登録（cp_ui.screens の SCREENS）の全部の画面 × 見本データ（cp_ui.fixtures）の全部の変種。
件ごとに、Canvas を作り、見本データで画面を組み立て、はみ出しの検査（cp_ui.check の find_violations）を当てる。
終了コード：0＝回り切って、はみ出しが無い、1＝はみ出しがある、
2＝回り切れない（予定が0件、--only の名が無い、画面か見本データが例外を出す、画面が命令を1つも残さない、
画面の登録と見本データを読み込めない）。
最後の1行の screens= は「回した件数/予定の件数」。はみ出しがあれば、failed= に「画面/変種」、kinds= に種類を出す。
文字の大きさの計算の誤りは、ここでは見えない（ためた命令だけを調べるため）。実物の画素と照らすのは、巡回（tools/tour.py）。
"""
import argparse
import sys

from _common import APP, FAIL, INCOMPLETE, OK, finish


def load_ui() -> tuple:
    """出荷するコードから、画面の登録、変種の並び、見本データを作る関数、Canvas、はみ出しの検査を読む。pyxel は読み込まない。"""
    if str(APP) not in sys.path:
        sys.path.append(str(APP))  # 後ろに足す（標準ライブラリの名前を隠さないように）
    from cp_ui import fixtures
    from cp_ui.canvas import Canvas
    from cp_ui.check import find_violations
    from cp_ui.screens import SCREENS

    return SCREENS, fixtures.VARIANTS, fixtures.build, Canvas, find_violations


def plan(screens, variants, only: str = "") -> list:
    """予定。回す (画面の名, 変種) の並び。only があれば、その画面だけ。"""
    return [(screen, variant) for screen in screens if only in ("", screen) for variant in variants]


def build_canvas(screens, build, canvas_type, screen: str, variant: str):
    """見本データで、画面を1つ組み立てる。返すのは (Canvas, 回り切れなかった理由)。どちらかが None。"""
    try:
        canvas = canvas_type()
        screens[screen](canvas, build(screen, variant))
    except Exception as exc:  # noqa: BLE001 - 組み立てられない画面は、合格にも不合格にもせず「調べていない」にする
        return None, f"{type(exc).__name__}: {exc}"
    if not canvas.commands:
        return None, "画面が、描画命令を1つも残さない"
    return canvas, None


def check_screens(planned: list, screens, build, canvas_type, find_violations) -> tuple:
    """予定を順に回す。返すのは (件ごとの行の一覧, 調べられなかった件の文の一覧)。

    行は {"screen", "variant", "commands", "violations"}。violations は、はみ出し（cp_ui.check の Violation）の一覧。
    """
    rows, not_checked = [], []
    for screen, variant in planned:
        canvas, reason = build_canvas(screens, build, canvas_type, screen, variant)
        if canvas is None:
            not_checked.append(f"{screen}/{variant}: {reason}")
            continue
        rows.append({"screen": screen, "variant": variant, "commands": len(canvas.commands), "violations": find_violations(canvas)})
    return rows, not_checked


def summarize(planned: list, rows: list, not_checked: list) -> tuple:
    """返すのは (終了コード, 最後の1行の中身)。予定が0件、回した件数が予定と違う、調べられなかった件がある、のどれでも2。"""
    violations = sum(len(row["violations"]) for row in rows)
    summary = f"screens={len(rows)}/{len(planned)} violations={violations} not_checked={len(not_checked)}"
    failed = [f"{row['screen']}/{row['variant']}" for row in rows if row["violations"]]
    if failed:
        kinds = sorted({violation.kind for row in rows for violation in row["violations"]})
        summary += f" failed={','.join(failed)} kinds={','.join(kinds)}"
    if not planned:
        return INCOMPLETE, summary + " reason=nothing_planned"
    if not_checked or len(rows) != len(planned):
        return INCOMPLETE, summary
    return (FAIL if violations else OK), summary


def main() -> int:
    ap = argparse.ArgumentParser(description="2Dの全画面を組み立てて、はみ出しを数える")
    ap.add_argument("--only", default="", metavar="SCREEN", help="この画面だけ回す")
    args = ap.parse_args()
    try:
        screens, variants, build, canvas_type, find_violations = load_ui()
    except Exception as exc:  # noqa: BLE001 - 読み込めなければ、何も調べていない
        print(f"  screen_check: 画面の登録と見本データを読み込めない：{type(exc).__name__}: {exc}")
        return finish("screen_check", INCOMPLETE, "screens=0/0 violations=0 not_checked=0 reason=cannot_load")
    if args.only and args.only not in screens:
        print(f"  screen_check: --only の名の画面が無い：{args.only!r}（ある名：{', '.join(sorted(screens))}）")
        return finish("screen_check", INCOMPLETE, f"screens=0/0 violations=0 not_checked=0 reason=unknown_screen only={args.only!r}")
    planned = plan(screens, variants, args.only)
    rows, not_checked = check_screens(planned, screens, build, canvas_type, find_violations)
    for row in rows:
        for violation in row["violations"]:
            print(f"  screen_check: {row['screen']}/{row['variant']}: {violation.kind}: {violation.text}")
    for line in not_checked:
        print(f"  screen_check: 調べられなかった：{line}")
    code, summary = summarize(planned, rows, not_checked)
    return finish("screen_check", code, summary)


if __name__ == "__main__":
    sys.exit(main())
