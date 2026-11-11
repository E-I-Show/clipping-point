"""区切りのレビュー（tools/claude/step_review.js）の結果をまとめる。作業用のスクリプト。

  python3 tools/claude/review_summary.py <結果のJSON> [--case id,id] [--rejected] [--notes]

結果のJSONは、ワークフローの出力（{"result": {...}}）か、その中身（{"step": …, "results": […]}）。
出すもの：観点ごとに、反証を通った指摘のid、重さ、札、所、直し方。--case で挙げたidは、起きる場合と反証の理由も出す。
--rejected を付けると、退けた指摘のidと理由も出す。最後に、件数の1行を出す。

終了コード：0＝全観点に結果があり、全指摘に反証が付いている、1＝未評価がある、2＝読めない。
結果を返さなかった役を「指摘0件」に数えない。未評価は、主のエージェントが回し直すか、自分で見る。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import FAIL, INCOMPLETE, OK, finish  # noqa: E402

PASSED, REJECTED = "通った", "退け"


def load(path: str):
    """結果のJSONを読み、{"step", "results"} の形にして返す。読めなければ None。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return None
    return data


def summarize(data: dict) -> dict:
    """観点ごとの結果を数える。返すのは、通った指摘、退けた指摘、未評価の一覧と件数。"""
    passed, rejected, unevaluated, notes = [], [], [], []
    findings_total = 0
    for row in data["results"]:
        key = row.get("key", "?") if isinstance(row, dict) else "?"
        review = row.get("review") if isinstance(row, dict) else None
        refute = row.get("refute") if isinstance(row, dict) else None
        if not isinstance(review, dict) or not isinstance(review.get("findings"), list):
            unevaluated.append(f"{key}: レビュー役が結果を返していない")
            continue
        findings = review["findings"]
        findings_total += len(findings)
        verdicts = {}
        if isinstance(refute, dict) and isinstance(refute.get("verdicts"), list):
            verdicts = {v.get("id"): v for v in refute["verdicts"] if isinstance(v, dict)}
        elif findings:
            unevaluated.append(f"{key}: 反証役が結果を返していない（指摘{len(findings)}件）")
            continue
        for finding in findings:
            verdict = verdicts.get(finding.get("id"))
            word = verdict.get("verdict") if verdict else None
            item = {"lens": key, "finding": finding, "verdict": verdict}
            if word == PASSED:
                passed.append(item)
            elif word == REJECTED:
                rejected.append(item)
            else:
                unevaluated.append(f"{key}: {finding.get('id')} に反証が付いていない")
        # 役が自分で書いた「見られなかった所」。未評価の件数には入れず、--notes で見せる。
        for note in (review.get("unevaluated") or []) + ((refute or {}).get("unevaluated") or []):
            notes.append(f"{key}: {note}")
    return {"passed": passed, "rejected": rejected, "unevaluated": unevaluated, "notes": notes, "findings": findings_total}


def main() -> int:
    ap = argparse.ArgumentParser(description="区切りのレビューの結果をまとめる")
    ap.add_argument("path", help="結果のJSON")
    ap.add_argument("--case", default="", help="起きる場合も出す指摘のid（カンマ区切り）")
    ap.add_argument("--rejected", action="store_true", help="退けた指摘も出す")
    ap.add_argument("--notes", action="store_true", help="役が書いた「見られなかった所」も出す")
    args = ap.parse_args()
    data = load(args.path)
    if data is None:
        return finish("review_summary", INCOMPLETE, f"reason=unreadable path={args.path}")
    summary = summarize(data)
    wanted = {word.strip() for word in args.case.split(",") if word.strip()}
    print(f"区切り：{data.get('step', '?')}")
    lens = None
    for item in summary["passed"]:
        finding = item["finding"]
        if item["lens"] != lens:
            lens = item["lens"]
            print(f"\n== {lens}")
        print(f"■ {finding.get('id')} [{finding.get('severity')}/{finding.get('tag')}] 所：{finding.get('where')}")
        print(f"   直し：{finding.get('fix')}")
        if finding.get("id") in wanted:
            print(f"   場合：{finding.get('case')}")
            print(f"   反証：{(item['verdict'] or {}).get('reason')}")
    if args.rejected:
        print("\n== 退けた指摘")
        for item in summary["rejected"]:
            finding = item["finding"]
            print(f"□ {finding.get('id')} [{finding.get('severity')}] {(item['verdict'] or {}).get('reason')}")
    if args.notes:
        print("\n== 役が書いた、見られなかった所")
        for line in summary["notes"]:
            print(f"・{line}")
    for line in summary["unevaluated"]:
        print(f"未評価：{line}")
    counts = (
        f"findings={summary['findings']} passed={len(summary['passed'])} rejected={len(summary['rejected'])} "
        f"unevaluated={len(summary['unevaluated'])}"
    )
    if summary["findings"] == 0 and not summary["unevaluated"] and not data["results"]:
        return finish("review_summary", INCOMPLETE, f"{counts} reason=no_lenses")
    return finish("review_summary", FAIL if summary["unevaluated"] else OK, counts)


if __name__ == "__main__":
    sys.exit(main())
