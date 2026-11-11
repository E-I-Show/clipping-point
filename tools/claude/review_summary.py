"""区切りのレビュー（tools/claude/step_review.js）の結果をまとめる。作業用のスクリプト。

  python3 tools/claude/review_summary.py <結果のJSON> [--case id,id] [--rejected] [--notes] [--out <パス>]

結果のJSONは、ワークフローの出力（{"result": {...}}）か、その中身（{"step": …, "results": […]}）。
出すもの：観点ごとに、反証を通った指摘のid、重さ、札、所、直し方、反証の理由。--case で挙げたidは、起きる場合も出す。
--rejected を付けると、退けた指摘のidと理由も出す。
--notes を付けると、役（レビュー役、反証役）が自分で書いた「見られなかった所」も出す。
--out を付けると、同じ形の文の全部（通った指摘の全部に起きる場合と反証の理由、退けた指摘と理由、役が書いた
「見られなかった所」、最後の1行）を、UTF-8のファイルに書く。コンテナが替わっても、レビューの結果を残すため。

最後に、件数の1行を出す。lenses＝観点、findings＝指摘、passed＝反証を通った指摘、rejected＝退けた指摘、
unevaluated＝未評価（結果を返さなかった観点と、反証の付いていない指摘）、role_notes＝役が書いた「見られなかった所」。

終了コード：0＝全観点に結果があり、全指摘に反証が付いている、1＝未評価がある、2＝読めない、観点が無い、--out に書けない。
結果を返さなかった役を「指摘0件」に数えない。未評価は、主のエージェントが回し直すか、自分で見る。
role_notes は終了コードを変えない。0でなければ、--notes で読む。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import FAIL, INCOMPLETE, OK, WORD, finish  # noqa: E402

TOOL = "review_summary"
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


def role_notes(key: str, role: str, part) -> list:
    """役が自分で書いた「見られなかった所」を、観点と役の名を付けた行にする。"""
    raw = part.get("unevaluated") if isinstance(part, dict) else None
    if not raw:
        return []
    return [f"{key}（{role}）: {note}" for note in (raw if isinstance(raw, list) else [raw])]


def summarize(data: dict) -> dict:
    """観点ごとの結果を数える。返すのは、通った指摘、退けた指摘、未評価、役が書いた「見られなかった所」の一覧と件数。"""
    passed, rejected, unevaluated, notes = [], [], [], []
    findings_total = 0
    for row in data["results"]:
        key = row.get("key", "?") if isinstance(row, dict) else "?"
        review = row.get("review") if isinstance(row, dict) else None
        refute = row.get("refute") if isinstance(row, dict) else None
        if not isinstance(review, dict) or not isinstance(review.get("findings"), list):
            unevaluated.append(f"{key}: レビュー役が結果を返していない")
            continue
        # 役が自分で書いた「見られなかった所」。未評価の件数にも終了コードにも入れず、件数を最後の1行に出す。
        notes += role_notes(key, "レビュー役", review) + role_notes(key, "反証役", refute)
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
    return {
        "passed": passed, "rejected": rejected, "unevaluated": unevaluated, "notes": notes,
        "findings": findings_total, "lenses": len(data["results"]),
    }


def render(data: dict, summary: dict, wanted=(), rejected: bool = False, notes: bool = False, every_case: bool = False) -> list:
    """出す文を、行の並びにする（最後の1行は入れない）。

    wanted は、起きる場合も出す指摘のid。every_case なら、通った指摘の全部に起きる場合を出す。
    """
    lines = [f"区切り：{data.get('step', '?')}"]
    lens = None
    for item in summary["passed"]:
        finding = item["finding"]
        if item["lens"] != lens:
            lens = item["lens"]
            lines += ["", f"== {lens}"]
        lines.append(f"■ {finding.get('id')} [{finding.get('severity')}/{finding.get('tag')}] 所：{finding.get('where')}")
        lines.append(f"   直し：{finding.get('fix')}")
        if every_case or finding.get("id") in wanted:
            lines.append(f"   場合：{finding.get('case')}")
        # 反証の理由は、いつも出す。直し方の案が誤っているとき、反証役はここにその旨を書く。
        lines.append(f"   反証：{(item['verdict'] or {}).get('reason')}")
    if rejected:
        lines += ["", "== 退けた指摘"]
        for item in summary["rejected"]:
            finding = item["finding"]
            lines.append(f"□ {finding.get('id')} [{finding.get('severity')}] {(item['verdict'] or {}).get('reason')}")
    if notes:
        lines += ["", "== 役が書いた、見られなかった所"]
        lines += [f"・{line}" for line in summary["notes"]]
    lines += [f"未評価：{line}" for line in summary["unevaluated"]]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="区切りのレビューの結果をまとめる")
    ap.add_argument("path", help="結果のJSON")
    ap.add_argument("--case", default="", help="起きる場合も出す指摘のid（カンマ区切り）")
    ap.add_argument("--rejected", action="store_true", help="退けた指摘も出す")
    ap.add_argument("--notes", action="store_true", help="役が書いた「見られなかった所」も出す")
    ap.add_argument("--out", default="", metavar="PATH", help="同じ形の文の全部を書くファイル（UTF-8。親のディレクトリが無ければ作る）")
    args = ap.parse_args()
    data = load(args.path)
    if data is None:
        return finish(TOOL, INCOMPLETE, f"reason=unreadable path={args.path}")
    summary = summarize(data)
    wanted = {word.strip() for word in args.case.split(",") if word.strip()}
    for line in render(data, summary, wanted, args.rejected, args.notes):
        print(line)
    counts = (
        f"lenses={summary['lenses']} findings={summary['findings']} passed={len(summary['passed'])} "
        f"rejected={len(summary['rejected'])} unevaluated={len(summary['unevaluated'])} role_notes={len(summary['notes'])}"
    )
    if not data["results"]:
        code, counts = INCOMPLETE, f"{counts} reason=no_lenses"
    else:
        code = FAIL if summary["unevaluated"] else OK
    if args.out:
        out = Path(args.out)
        if out.resolve() == Path(args.path).resolve():
            return finish(TOOL, INCOMPLETE, f"{counts} reason=out_is_the_input out={args.out}")
        # ファイルには、引数に関わらず全部を書く。最後の1行は、画面に出すもの（finish() の形）と同じにする。
        full = render(data, summary, rejected=True, notes=True, every_case=True)
        full.append(f"{TOOL}: {WORD[code]} {counts}")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(full) + "\n", encoding="utf-8")
        except OSError:
            return finish(TOOL, INCOMPLETE, f"{counts} reason=out_unwritable out={args.out}")
        print(f"書いた所：{args.out}")
    return finish(TOOL, code, counts)


if __name__ == "__main__":
    sys.exit(main())
