"""2つある週の枠の値を、作業記録の表の1行にする。作業用のスクリプト。

  python3 tools/claude/usage_row.py --overage-included 0.12 --seven-day 0.21 --resets-at 1794902400 \\
      --label "段0 区切り3のレビューの後" [--note "備考"] [--now 2026-11-11T08:27:00Z]

値は、主のエージェントがセッションのイベント（rate_limit_event の unifiedWindows）から読んで渡す。
このスクリプトからは読めない（セッションのログファイルに値が入っていない）。読み方は docs/worklog.md の「週の使用率の推移」。
週の枠は2つあり、役目が違う（2026-11-12 の人の指示）。
  --overage-included  seven_day_overage_included。このモデル（セッションに決められたClaudeのモデル）の週の枠。
                      停止の線（90%、95%）は、こちらだけで見る
  --seven-day         seven_day。全モデルの合計の週の枠。線には使わない。90%を超えたら、最後の1行に知らせの語
                      （notice=all_models_above_90%）を足すだけで、終了コードは変えない

出すもの：docs/worklog.md の「週の使用率の推移」の表に足す1行と、停止の線の判定。
表の列は、このモデルの週の枠が先、全モデルの合計の週の枠が後。週の経過は、（いまの時刻 − 切り替わりの7日前）÷ 7日。
終了コード：0＝線の内、1＝このモデルの週の枠が線を超えた、2＝値が読めない（週の枠の値が範囲の外、時刻が読めない、
切り替わりの時刻に直せない、切り替わりが週の外）。2のときは、表の1行を出さない。
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import FAIL, INCOMPLETE, OK, finish  # noqa: E402

# 停止の線。見るのは、このモデルの週の枠だけ。
# そろえる所：根のCLAUDE.mdの「最初に確かめること」、docs/standing-policy.md、tests/test_claude_tools.py。
NO_NEW_AGENTS_ABOVE = 0.90  # 超えたら、新しいサブエージェントとワークフローを始めない
STOP_ABOVE = 0.95  # 超えたら、作業の控えと作業記録を書いてコミットとpushをし、待機する
# 全モデルの合計の週の枠が、これを超えたら、最後の1行に知らせの語を足す。線ではない（判定も、終了コードも変えない）。
ALL_MODELS_NOTICE_ABOVE = 0.90
WEEK = timedelta(days=7)


def percent(value: float) -> str:
    return f"{round(value * 100)}%"


def line_message(verdict: str) -> str:
    """線を超えたときに出す文。数字は、上の定数から組み立てる。線の内なら、空の文字列。"""
    if verdict == "stop":
        return (
            f"線：{percent(STOP_ABOVE)}を超えた（このモデルの週の枠）。"
            "作業の控えと作業記録を書いてコミットとpushをし、待機する。再開は人の指示を待つ。"
        )
    if verdict == "no_new_agents":
        return f"線：{percent(NO_NEW_AGENTS_ABOVE)}を超えた（このモデルの週の枠）。新しいサブエージェントとワークフローを始めない。"
    return ""


def all_models_notice(all_models: float) -> str:
    """全モデルの合計の週の枠が、知らせる値を超えたときに、最後の1行に足す語。数字は、上の定数から組み立てる。内なら、空の文字列。"""
    return f"notice=all_models_above_{percent(ALL_MODELS_NOTICE_ABOVE)}" if all_models > ALL_MODELS_NOTICE_ABOVE else ""


def parse_now(text: str) -> datetime:
    """ISOの時刻（末尾のZも受ける）。時差の無いものはUTCとして読む。"""
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def build_row(seven_day: float, overage_included: float, resets_at: int, label: str, note: str, now: datetime) -> dict:
    """表の1行と、線の判定を作る（時計を読まない）。

    線は、このモデルの週の枠（overage_included）だけで見る。全モデルの合計の週の枠（seven_day）は、表に書くことと、
    知らせの語にだけ使う（どれだけ高くても、判定は変えない）。表の列は、このモデルの週の枠が先。
    """
    this_model, all_models = overage_included, seven_day
    reset = datetime.fromtimestamp(resets_at, tz=timezone.utc)
    elapsed = (now - (reset - WEEK)) / WEEK
    if this_model > STOP_ABOVE:
        verdict = "stop"
    elif this_model > NO_NEW_AGENTS_ABOVE:
        verdict = "no_new_agents"
    else:
        verdict = "ok"
    row = (
        f"| {now.astimezone(timezone.utc):%Y-%m-%d %H:%M} | {label} | {percent(this_model)} | {percent(all_models)} | "
        f"約{round(elapsed * 100)}% | {reset:%Y-%m-%d %H:%M} | {note} |"
    )
    return {
        "row": row, "verdict": verdict, "this_model": this_model, "all_models": all_models,
        "notice": all_models_notice(all_models), "elapsed": elapsed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="2つある週の枠の値を、作業記録の表の1行にする")
    ap.add_argument(
        "--seven-day", type=float, required=True,
        help="unifiedWindows.seven_day.utilization（0〜1）。全モデルの合計の週の枠。線には使わない",
    )
    ap.add_argument(
        "--overage-included", type=float, required=True,
        help="unifiedWindows.seven_day_overage_included.utilization（0〜1）。このモデルの週の枠。停止の線は、こちらだけで見る",
    )
    ap.add_argument("--resets-at", type=int, required=True, help="resetsAt（秒）")
    ap.add_argument("--label", required=True, help="区切りの名など")
    ap.add_argument("--note", default="", help="備考")
    ap.add_argument("--now", default="", help="時刻（ISO）。省けば、いまの時刻")
    args = ap.parse_args()
    for name, value in (("seven_day", args.seven_day), ("overage_included", args.overage_included)):
        if not 0.0 <= value <= 2.0:
            return finish("usage_row", INCOMPLETE, f"reason=value_out_of_range {name}={value}")
    try:
        now = parse_now(args.now) if args.now else datetime.now(timezone.utc)
    except ValueError:
        return finish("usage_row", INCOMPLETE, f"reason=bad_now now={args.now!r}")
    try:
        result = build_row(args.seven_day, args.overage_included, args.resets_at, args.label, args.note, now)
    except (ValueError, OverflowError, OSError):
        # 切り替わりの時刻に直せない値（秒ではなくミリ秒で渡した、など）。時刻の計算が上げる3つを、まとめて受ける。
        return finish("usage_row", INCOMPLETE, f"reason=bad_resets_at resets_at={args.resets_at}")
    if not 0.0 <= result["elapsed"] <= 1.0:
        # 切り替わりがもう過ぎているか、7日より先にある。別の週の値（古いイベント）を読んでいる。
        outside = f"resets_at={args.resets_at} elapsed={round(result['elapsed'] * 100)}%"
        return finish("usage_row", INCOMPLETE, f"reason=resets_at_outside_week {outside}")
    print(result["row"])
    message = line_message(result["verdict"])
    if message:
        print(message)
    summary = (
        f"this_model={percent(result['this_model'])} all_models={percent(result['all_models'])} "
        f"elapsed={round(result['elapsed'] * 100)}% verdict={result['verdict']}"
    )
    if result["notice"]:
        summary += " " + result["notice"]  # 全モデルの合計の週の枠の知らせ。終了コードは、判定（verdict）だけで決める
    return finish("usage_row", OK if result["verdict"] == "ok" else FAIL, summary)


if __name__ == "__main__":
    sys.exit(main())
