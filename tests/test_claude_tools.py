"""作業の補助（tools/claude/ の handoff_hook、review_summary、usage_row）と、Claude Codeの設定の見張りのテスト。

作業の補助は、gitにもネットワークにも触れない関数を、値を渡して確かめる。main() は、引数、git、控え、標準入力を
差し替えて通す。設定の見張りは、.claude/settings.json と、サブエージェントの型（.claude/agents/）の頭の項目を見る。
どちらも、綴りを誤ると黙って効かなくなり、ほかの検査では落ちないため。
"""
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.append(str(ROOT / "tools" / "claude"))

import handoff_hook  # noqa: E402
import review_summary  # noqa: E402
import usage_row  # noqa: E402

HANDOFF = "<!-- 作業の控え -->\nHEAD: abc1234　書いた刻: 2026-11-11 08:00 UTC　ブランチ: dev\n\n段と区切り: 段0 ／ 区切り4\n"
FULL_MARK = "--- docs/handoff.md ---"
GUIDE_MARK = "作業の控えの案内"


# --- handoff_hook ---
def test_handoff_head_is_read_from_the_first_line_that_names_it():
    assert handoff_hook.handoff_head(HANDOFF) == "abc1234"
    assert handoff_hook.handoff_head("控え\n") is None


def test_handoff_in_this_repository_names_its_head():
    text = (ROOT / "docs" / "handoff.md").read_text(encoding="utf-8")
    assert handoff_hook.handoff_head(text) is not None


@pytest.mark.parametrize("stdin_text, expected", [
    ('{"source": "compact"}', "compact"),
    ('{"source": "resume"}', "resume"),
    ("{}", "startup"),
    ("", "startup"),
    ("not json", "startup"),
    ("[1, 2]", "startup"),
    ('{"source": 3}', "startup"),
])
def test_handoff_source_falls_back_to_startup(stdin_text, expected):
    assert handoff_hook.read_source(stdin_text) == expected


def test_handoff_startup_gives_the_short_guide_only():
    message = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", 1)
    assert "最初に確かめること" in message
    assert "docs/handoff.md" in message
    assert FULL_MARK not in message
    assert "段と区切り" not in message


@pytest.mark.parametrize("source", ["compact", "resume", "clear"])
def test_handoff_full_text_after_compaction_resume_and_clear(source):
    message = handoff_hook.build_message(source, HANDOFF, "dev", "def5678", 1)
    assert FULL_MARK in message
    assert "段と区切り: 段0 ／ 区切り4" in message


def test_handoff_missing_file_is_said_plainly():
    message = handoff_hook.build_message("compact", None, "dev", "def5678", None)
    assert "が無い" in message
    assert FULL_MARK not in message


def test_handoff_reports_how_far_head_has_moved():
    fresh = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", 1)
    stale = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", 3)
    unknown = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", None)
    assert "控えは新しい" in fresh and "古いかもしれない" not in fresh
    assert "3個" in stale and "古いかもしれない" in stale
    assert "読めない" in unknown


@pytest.mark.parametrize("commits_after, fresh", [(0, True), (1, True), (2, False), (3, False)])
def test_handoff_is_stale_from_the_second_commit_after_it(commits_after, fresh):
    # 1個は、控えを入れたコミット。途中のコミットで控えを直さなかった場合（2個）から、古いと見る。
    message = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", commits_after)
    assert ("控えは新しい" in message) is fresh
    assert ("古いかもしれない" in message) is not fresh


def test_handoff_warns_when_not_on_the_work_branch():
    on_other = handoff_hook.build_message("startup", HANDOFF, "main", "def5678", 1)
    on_dev = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", 1)
    assert "作業ブランチは dev。いまは main" in on_other
    assert "作業ブランチは dev。いまは" not in on_dev


class BrokenStdin:
    """読もうとすると失敗する標準入力。"""

    def read(self):
        raise OSError("stdin is closed")


def fake_git(*args):
    """gitの代わり。ブランチ、HEAD、控えを書いた時点のHEADから後のコミットの数を返す。"""
    return {"branch": "dev", "rev-parse": "def5678", "rev-list": "3"}[args[0]]


def run_hook_main(monkeypatch, capsys, tmp_path, stdin, handoff_bytes=HANDOFF.encode("utf-8"), git=fake_git):
    """handoff_hook.main() を、git、控え、標準入力を差し替えて通す。返すのは (戻り値, 標準出力)。"""
    path = tmp_path / "handoff.md"
    if handoff_bytes is not None:
        path.write_bytes(handoff_bytes)
    monkeypatch.setattr(handoff_hook, "HANDOFF", path)
    monkeypatch.setattr(handoff_hook, "git", git)
    monkeypatch.setattr(sys, "stdin", stdin)
    code = handoff_hook.main()
    return code, capsys.readouterr().out


def test_handoff_main_puts_the_git_state_and_the_full_text_together(monkeypatch, capsys, tmp_path):
    code, out = run_hook_main(monkeypatch, capsys, tmp_path, io.StringIO('{"source": "compact"}'))
    assert code == 0
    assert "いまのブランチ：dev。HEAD：def5678。" in out
    assert "その後のコミットが3個ある" in out
    assert FULL_MARK in out and "段と区切り: 段0 ／ 区切り4" in out


def test_handoff_main_goes_on_when_git_gives_nothing(monkeypatch, capsys, tmp_path):
    code, out = run_hook_main(monkeypatch, capsys, tmp_path, io.StringIO('{"source": "compact"}'), git=lambda *args: None)
    assert code == 0
    assert GUIDE_MARK in out
    assert "いまのブランチ：読めない。HEAD：読めない。" in out
    assert "いまのHEADとの間が読めない" in out
    assert FULL_MARK in out and "段と区切り: 段0 ／ 区切り4" in out  # gitが回せなくても、控えの全文は出す


def test_handoff_main_says_so_when_the_handoff_is_missing(monkeypatch, capsys, tmp_path):
    code, out = run_hook_main(monkeypatch, capsys, tmp_path, io.StringIO('{"source": "resume"}'), handoff_bytes=None)
    assert code == 0
    assert GUIDE_MARK in out and "が無い" in out
    assert FULL_MARK not in out


def test_handoff_main_returns_zero_when_the_handoff_is_not_utf8(monkeypatch, capsys, tmp_path):
    code, out = run_hook_main(monkeypatch, capsys, tmp_path, io.StringIO('{"source": "compact"}'), handoff_bytes=b"HEAD: \xff\xfe\x80\n")
    assert code == 0
    assert GUIDE_MARK in out and "docs/handoff.md" in out


@pytest.mark.parametrize("stdin", [None, BrokenStdin()])
def test_handoff_main_returns_zero_when_stdin_cannot_be_read(monkeypatch, capsys, tmp_path, stdin):
    code, out = run_hook_main(monkeypatch, capsys, tmp_path, stdin)
    assert code == 0
    assert GUIDE_MARK in out and "docs/handoff.md" in out


# --- review_summary ---
def finding(fid):
    return {"id": fid, "severity": "中", "tag": "確かめた", "where": "x.py:1", "case": f"{fid} の起きる場合", "fix": f"{fid} の直し方"}


def verdict(fid, word, reason="r"):
    return {"id": fid, "verdict": word, "reason": reason, "checked": "x.py:1"}


def lens(key, findings, verdicts, review_notes=(), refute_notes=()):
    """観点1つの結果。findings か verdicts が None なら、その役が結果を返さなかった形。"""
    review = None if findings is None else {"scope": "s", "findings": findings, "unevaluated": list(review_notes)}
    refute = None if verdicts is None else {"verdicts": verdicts, "unevaluated": list(refute_notes)}
    return {"key": key, "review": review, "refute": refute}


# 通った指摘が2件（a-1、b-1）、退けた指摘が1件（a-2）、役が書いた「見られなかった所」が2件。
RICH = {"step": "段0 区切り4", "results": [
    lens(
        "a",
        [finding("a-1"), finding("a-2")],
        [verdict("a-1", "通った", "直し方の案は誤り"), verdict("a-2", "退け", "起きない場面")],
        review_notes=["docs/ を読めなかった"],
    ),
    lens("b", [finding("b-1")], [verdict("b-1", "通った", "実物どおり")], refute_notes=["b-1 の行を確かめられなかった"]),
]}
RICH_LAST_LINE = "review_summary: OK lenses=2 findings=3 passed=2 rejected=1 unevaluated=0 role_notes=2"


def test_review_counts_passed_and_rejected():
    data = {"step": "s", "results": [lens("a", [finding("a-1"), finding("a-2")], [verdict("a-1", "通った"), verdict("a-2", "退け")])]}
    summary = review_summary.summarize(data)
    assert [item["finding"]["id"] for item in summary["passed"]] == ["a-1"]
    assert [item["finding"]["id"] for item in summary["rejected"]] == ["a-2"]
    assert summary["findings"] == 2 and summary["unevaluated"] == []
    assert summary["lenses"] == 1 and summary["notes"] == []


def test_review_lens_with_no_findings_is_evaluated():
    summary = review_summary.summarize({"step": "s", "results": [lens("a", [], [])]})
    assert summary["findings"] == 0 and summary["unevaluated"] == []


@pytest.mark.parametrize("row", [
    lens("a", None, None),  # レビュー役が結果を返していない
    lens("a", [finding("a-1")], None),  # 反証役が結果を返していない
    lens("a", [finding("a-1"), finding("a-2")], [verdict("a-1", "通った")]),  # 反証の付いていない指摘がある
    lens("a", [finding("a-1")], [verdict("a-1", "たぶん")]),  # 知らない語の反証
    {"key": "a", "review": {"scope": "s", "unevaluated": []}, "refute": None},  # レビュー役の結果に findings が無い
    "a",  # 観点の結果が、辞書でない
])
def test_review_missing_results_are_unevaluated_not_zero_findings(row):
    summary = review_summary.summarize({"step": "s", "results": [row]})
    assert len(summary["unevaluated"]) == 1


def test_review_role_notes_name_the_lens_and_the_role():
    summary = review_summary.summarize(RICH)
    assert summary["notes"] == ["a（レビュー役）: docs/ を読めなかった", "b（反証役）: b-1 の行を確かめられなかった"]
    assert summary["unevaluated"] == []  # 役が書いた「見られなかった所」は、未評価の件数に入れない


def test_review_keeps_the_reviewer_notes_when_the_refuter_returned_nothing():
    row = lens("a", [finding("a-1")], None, review_notes=["x を読めなかった"])
    summary = review_summary.summarize({"step": "s", "results": [row]})
    assert summary["notes"] == ["a（レビュー役）: x を読めなかった"]
    assert len(summary["unevaluated"]) == 1


def run_review_main(tmp_path, monkeypatch, data, *flags):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["review_summary.py", str(path), *flags])
    return review_summary.main()


def test_review_main_exit_codes(tmp_path, monkeypatch, capsys):
    good = {"step": "s", "results": [lens("a", [finding("a-1")], [verdict("a-1", "通った")])]}
    assert run_review_main(tmp_path, monkeypatch, {"result": good}) == 0  # ワークフローの出力の形
    assert run_review_main(tmp_path, monkeypatch, good) == 0  # 中身だけの形
    assert capsys.readouterr().out.splitlines()[-1] == "review_summary: OK lenses=1 findings=1 passed=1 rejected=0 unevaluated=0 role_notes=0"
    assert run_review_main(tmp_path, monkeypatch, {"step": "s", "results": [lens("a", None, None)]}) == 1
    assert run_review_main(tmp_path, monkeypatch, {"step": "s"}) == 2
    monkeypatch.setattr(sys, "argv", ["review_summary.py", str(tmp_path / "missing.json")])
    assert review_summary.main() == 2


def test_review_main_with_no_lenses_is_incomplete(tmp_path, monkeypatch, capsys):
    assert run_review_main(tmp_path, monkeypatch, {"step": "s", "results": []}) == 2
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.startswith("review_summary: INCOMPLETE lenses=0 ") and last.endswith("reason=no_lenses")


def test_review_main_role_notes_are_counted_without_changing_the_exit_code(tmp_path, monkeypatch, capsys):
    data = {"step": "s", "results": [lens("a", [], [], review_notes=["tools/claude/ を読めなかった"])]}
    assert run_review_main(tmp_path, monkeypatch, data) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "review_summary: OK lenses=1 findings=0 passed=0 rejected=0 unevaluated=0 role_notes=1"
    assert "読めなかった" not in out  # 中身は --notes で読む


def test_review_main_shows_the_refute_reason_by_default_and_the_case_on_request(tmp_path, monkeypatch, capsys):
    assert run_review_main(tmp_path, monkeypatch, RICH) == 0
    plain = capsys.readouterr().out
    assert "反証：直し方の案は誤り" in plain and "反証：実物どおり" in plain
    for word in ("場合：", "退けた指摘", "起きない場面", "見られなかった所", "読めなかった"):
        assert word not in plain
    assert plain.splitlines()[-1] == RICH_LAST_LINE

    assert run_review_main(tmp_path, monkeypatch, RICH, "--case", "a-1") == 0
    with_case = capsys.readouterr().out
    assert "場合：a-1 の起きる場合" in with_case and "場合：b-1" not in with_case
    assert "反証：直し方の案は誤り" in with_case and "反証：実物どおり" in with_case  # --case は、起きる場合を足すだけ


def test_review_main_rejected_and_notes_flags(tmp_path, monkeypatch, capsys):
    assert run_review_main(tmp_path, monkeypatch, RICH, "--rejected", "--notes") == 0
    out = capsys.readouterr().out
    assert "□ a-2 [中] 起きない場面" in out
    assert "・a（レビュー役）: docs/ を読めなかった" in out and "・b（反証役）: b-1 の行を確かめられなかった" in out
    assert "場合：" not in out
    assert out.splitlines()[-1] == RICH_LAST_LINE


def test_review_out_file_keeps_everything_whatever_the_flags(tmp_path, monkeypatch, capsys):
    out_path = tmp_path / "reviews" / "deep" / "s0k4.txt"  # 親のディレクトリは、まだ無い
    assert run_review_main(tmp_path, monkeypatch, RICH, "--out", str(out_path)) == 0
    screen = capsys.readouterr().out
    assert "場合：" not in screen and "退けた指摘" not in screen  # 画面は、引数のとおり
    text = out_path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "区切り：段0 区切り4"
    assert text.splitlines()[-1] == screen.splitlines()[-1] == RICH_LAST_LINE
    for word in (
        "■ a-1 [中/確かめた] 所：x.py:1", "直し：a-1 の直し方", "場合：a-1 の起きる場合", "反証：直し方の案は誤り",
        "場合：b-1 の起きる場合", "反証：実物どおり", "□ a-2 [中] 起きない場面",
        "・a（レビュー役）: docs/ を読めなかった", "・b（反証役）: b-1 の行を確かめられなかった",
    ):
        assert word in text


def test_review_out_file_carries_the_unevaluated_lines_and_the_failed_last_line(tmp_path, monkeypatch, capsys):
    data = {"step": "s", "results": [*RICH["results"], lens("c", None, None)]}
    out_path = tmp_path / "review.txt"
    assert run_review_main(tmp_path, monkeypatch, data, "--out", str(out_path)) == 1
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert "未評価：c: レビュー役が結果を返していない" in lines
    assert lines[-1] == capsys.readouterr().out.splitlines()[-1]
    assert lines[-1] == "review_summary: FAILED lenses=3 findings=3 passed=2 rejected=1 unevaluated=1 role_notes=2"


def test_review_out_that_cannot_be_written_is_incomplete(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")  # ディレクトリを作りたい所に、ファイルがある
    assert run_review_main(tmp_path, monkeypatch, RICH, "--out", str(blocker / "review.txt")) == 2
    assert "reason=out_unwritable" in capsys.readouterr().out.splitlines()[-1]


def test_review_out_does_not_overwrite_the_result_it_reads(tmp_path, monkeypatch, capsys):
    assert run_review_main(tmp_path, monkeypatch, RICH, "--out", str(tmp_path / "result.json")) == 2
    assert "reason=out_is_the_input" in capsys.readouterr().out.splitlines()[-1]
    assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8")) == RICH


# --- usage_row ---
# 停止の線の値（90%、95%）は、ここにも書いてある。そろえる所は、usage_row.py の定数の注。
RESETS_AT = 1794902400  # 2026-11-17 08:00 UTC
NOW = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)  # 切り替わりのちょうど6日前＝週の初めから1日後
NOW_TEXT = "2026-11-11T08:00:00Z"
DAY_S = 24 * 60 * 60


def row(seven_day, overage_included):
    return usage_row.build_row(seven_day, overage_included, RESETS_AT, "段0 区切り4", "備考", NOW)


def test_usage_row_takes_the_higher_window_and_the_elapsed_week():
    result = row(0.21, 0.12)
    assert result["high"] == 0.21
    assert result["elapsed"] == pytest.approx(1 / 7)
    assert result["row"] == "| 2026-11-11 08:00 | 段0 区切り4 | 21% | 12% | 約14% | 2026-11-17 08:00 | 備考 |"
    assert row(0.12, 0.21)["high"] == 0.21


@pytest.mark.parametrize("high, verdict", [
    (0.89, "ok"), (0.90, "ok"), (0.91, "no_new_agents"), (0.95, "no_new_agents"), (0.96, "stop"), (1.0, "stop"),
])
def test_usage_row_lines_are_strictly_above_90_and_95_percent(high, verdict):
    assert row(0.5, high)["verdict"] == verdict


def test_usage_row_reads_iso_times_with_and_without_a_zone():
    assert usage_row.parse_now("2026-11-11T08:00:00Z") == NOW
    assert usage_row.parse_now("2026-11-11T08:00:00") == NOW
    with pytest.raises(ValueError):
        usage_row.parse_now("yesterday")


def test_usage_row_line_messages_are_built_from_the_constants(monkeypatch):
    assert "95%を超えた" in usage_row.line_message("stop")
    assert "90%を超えた" in usage_row.line_message("no_new_agents")
    assert usage_row.line_message("ok") == ""
    monkeypatch.setattr(usage_row, "STOP_ABOVE", 0.80)
    monkeypatch.setattr(usage_row, "NO_NEW_AGENTS_ABOVE", 0.70)
    assert row(0.5, 0.85)["verdict"] == "stop"
    assert "80%を超えた" in usage_row.line_message("stop") and "95%" not in usage_row.line_message("stop")
    assert "70%を超えた" in usage_row.line_message("no_new_agents") and "90%" not in usage_row.line_message("no_new_agents")


def run_usage_main(monkeypatch, capsys, high="0.50", resets_at=RESETS_AT, now=NOW_TEXT):
    """usage_row.main() を、引数を差し替えて通す。返すのは (戻り値, 標準出力の行)。"""
    argv = ["--seven-day", "0.10", "--overage-included", str(high), "--resets-at", str(resets_at), "--label", "段0 区切り4", "--now", now]
    monkeypatch.setattr(sys, "argv", ["usage_row.py", *argv])
    code = usage_row.main()
    return code, capsys.readouterr().out.splitlines()


def table_rows(lines):
    return [line for line in lines if line.startswith("|")]


@pytest.mark.parametrize("high, code, last, message", [
    ("0.90", 0, "usage_row: OK high=90% elapsed=14% verdict=ok", None),
    ("0.91", 1, "usage_row: FAILED high=91% elapsed=14% verdict=no_new_agents", "線：90%を超えた"),
    ("0.96", 1, "usage_row: FAILED high=96% elapsed=14% verdict=stop", "線：95%を超えた"),
])
def test_usage_main_exit_code_follows_the_lines(monkeypatch, capsys, high, code, last, message):
    got, lines = run_usage_main(monkeypatch, capsys, high=high)
    assert got == code
    assert lines[-1] == last
    assert len(table_rows(lines)) == 1 and lines[0].startswith("| 2026-11-11 08:00 | 段0 区切り4 |")
    said = [line for line in lines if line.startswith("線：")]
    if message is None:
        assert said == []
    else:
        assert len(said) == 1 and said[0].startswith(message)


@pytest.mark.parametrize("resets_at", [
    int(NOW.timestamp()),  # いまが、切り替わりのちょうどその時（週の経過が1）
    int(NOW.timestamp()) + 7 * DAY_S,  # いまが、週の初めのちょうどその時（週の経過が0）
])
def test_usage_main_accepts_both_ends_of_the_week(monkeypatch, capsys, resets_at):
    code, lines = run_usage_main(monkeypatch, capsys, resets_at=resets_at)
    assert code == 0 and len(table_rows(lines)) == 1


@pytest.mark.parametrize("kwargs, reason", [
    ({"high": "2.5"}, "reason=value_out_of_range"),  # 週の使用率が範囲の外
    ({"high": "-0.1"}, "reason=value_out_of_range"),
    ({"high": "nan"}, "reason=value_out_of_range"),
    ({"now": "yesterday"}, "reason=bad_now"),  # 読めない時刻
    ({"resets_at": 0}, "reason=resets_at_outside_week"),  # 切り替わりの時刻が0
    ({"resets_at": RESETS_AT - 7 * DAY_S}, "reason=resets_at_outside_week"),  # 切り替わりを過ぎた時刻（古いイベントの値）
    ({"resets_at": RESETS_AT + 7 * DAY_S}, "reason=resets_at_outside_week"),  # 切り替わりが7日より先
    ({"resets_at": RESETS_AT * 1000}, "reason=bad_resets_at"),  # 秒ではなくミリ秒で渡した
])
def test_usage_main_unreadable_values_are_incomplete_and_give_no_row(monkeypatch, capsys, kwargs, reason):
    code, lines = run_usage_main(monkeypatch, capsys, **kwargs)
    assert code == 2
    assert lines[-1].startswith("usage_row: INCOMPLETE ") and reason in lines[-1]
    assert table_rows(lines) == []  # 作業記録の表に足す1行は、出さない


# --- Claude Codeの設定（.claude/settings.json） ---
SETTINGS = ROOT / ".claude" / "settings.json"
HOOK_SCRIPT = "tools/claude/handoff_hook.py"
REPO = "/home/user/clipping-point"
# 使わないと決めた操作（根のCLAUDE.mdの「gitの決まり」）。`git -C <パス>` を付けた形も断つこと。
FORBIDDEN_COMMANDS = [
    "git push --force origin dev",
    "git push origin dev --force",
    "git push -f origin dev",
    "git push origin dev -f",
    "git reset --hard HEAD~1",
    "git clean -fd",
    f"git -C {REPO} push --force origin dev",
    f"git -C {REPO} push origin dev --force",
    f"git -C {REPO} push -f origin dev",
    f"git -C {REPO} push origin dev -f",
    f"git -C {REPO} reset --hard HEAD~1",
    f"git -C {REPO} clean -fd",
]
# 禁止の規則が広すぎて、ふだんの命令まで断たないこと。
USUAL_COMMANDS = ["git push -u origin dev", f"git -C {REPO} push -u origin dev", "git status --short", "git fetch origin dev"]


def load_settings() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def is_denied(command: str, settings: dict) -> bool:
    """permissions.deny の Bash の規則のどれかが、命令の全体に当たるか。規則の `*` は、何文字にも当たるものとして読む。

    規則の文字列そのものとは比べない。規則の書き方を変えても、断つ命令が同じなら通る。
    """
    for rule in settings["permissions"]["deny"]:
        body = re.fullmatch(r"Bash\((.+)\)", rule)
        if body and re.fullmatch(".*".join(re.escape(part) for part in body.group(1).split("*")), command, re.S):
            return True
    return False


def test_settings_file_is_json_with_deny_rules_and_a_session_start_hook():
    settings = load_settings()  # JSONとして読めなければ、ここで落ちる（読めない設定は、黙って飛ばされる）
    deny = settings["permissions"]["deny"]
    assert deny and all(isinstance(rule, str) and re.fullmatch(r"\w+\(.+\)", rule) for rule in deny)
    assert settings["hooks"]["SessionStart"]


@pytest.mark.parametrize("command", FORBIDDEN_COMMANDS)
def test_settings_deny_the_forbidden_git_operations(command):
    assert is_denied(command, load_settings())


@pytest.mark.parametrize("command", USUAL_COMMANDS)
def test_settings_do_not_deny_the_usual_git_commands(command):
    assert not is_denied(command, load_settings())


def test_settings_guard_notices_a_dropped_rule():
    settings = {"permissions": {"deny": ["Bash(git push --force*)", "Bash(git -C * clean *)"]}}
    assert is_denied("git push --force origin dev", settings)
    assert is_denied(f"git -C {REPO} clean -fd", settings)
    assert not is_denied(f"git -C {REPO} push --force origin dev", settings)  # `git -C` を付けた形の規則が無い
    assert not is_denied("git clean -fd", settings)
    assert not is_denied("git reset --hard HEAD~1", settings)


def test_settings_session_start_hook_points_at_the_existing_handoff_hook():
    groups = load_settings()["hooks"]["SessionStart"]
    commands = [hook["command"] for group in groups for hook in group["hooks"] if hook.get("type") == "command"]
    scripts = [path for command in commands for path in re.findall(r"\$\{CLAUDE_PROJECT_DIR\}/([\w./-]+)", command)]
    assert HOOK_SCRIPT in scripts
    for path in scripts:
        assert (ROOT / path).is_file(), path
    # 上で確かめている handoff_hook が、フックの呼ぶファイルそのものであること。
    assert Path(handoff_hook.__file__).resolve() == (ROOT / HOOK_SCRIPT).resolve()


# --- サブエージェントの型（.claude/agents/） ---
AGENTS = ROOT / ".claude" / "agents"
AGENT_TYPES = ("implementer", "reviewer", "reader")  # 根のCLAUDE.mdの「サブエージェントとレビュー」。型を足したら、ここにも足す
ALLOWED_FIELDS = ("name", "description", "tools", "model", "omitClaudeMd", "experimental")  # 知らない項目は、黙って無視される
REQUIRED_FIELDS = ("name", "description", "tools")  # tools が無いと、読むだけの縛りが外れる
READ_ONLY_TYPES = ("reviewer", "reader")
WRITING_TOOLS = {"Edit", "Write", "Bash"}  # 読むだけの型に持たせない
DELEGATING_TOOLS = {"Agent", "Workflow"}  # 実装役に持たせない（サブエージェントもワークフローも呼ばない）


def front_matter(text: str):
    """型のファイルの頭の項目（`---` で挟まれた部分）を {名: 値} で返す。挟まれていなければ None。

    YAMLのライブラリは使わない。字下げした行（`experimental:` の下など）は、上の項目の中身として読み飛ばす。
    """
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return None
    fields = {}
    for line in lines[1:lines.index("---", 1)]:
        if not line.strip() or line[0] in " \t":
            continue
        name, _, value = line.partition(":")
        fields[name.strip()] = value.strip()
    return fields


def agent_problems(name: str, text: str) -> list:
    """型のファイル1つの、頭の項目の崩れ。無ければ空の一覧。name は、ファイル名から拡張子を除いたもの。"""
    fields = front_matter(text)
    if fields is None:
        return ["頭の項目が --- で挟まれていない"]
    problems = [f"知らない項目：{field}" for field in fields if field not in ALLOWED_FIELDS]
    problems += [f"項目が無いか、空：{field}" for field in REQUIRED_FIELDS if not fields.get(field)]
    if fields.get("name") and fields["name"] != name:
        problems.append(f"name がファイル名と違う：{fields['name']}")
    tools = {part.strip().split("(")[0] for part in fields.get("tools", "").split(",") if part.strip()}
    banned = WRITING_TOOLS if name in READ_ONLY_TYPES else DELEGATING_TOOLS if name == "implementer" else set()
    problems += [f"tools に入れない名：{tool}" for tool in sorted(tools & banned)]
    return problems


def agent_text(name, tools="Read, Grep, Glob", extra="model: inherit"):
    """見張りを通る、見本の型のファイル。"""
    return f"---\nname: {name}\ndescription: 見本の型\ntools: {tools}\n{extra}\nexperimental:\n  cacheTtl: 1h\n---\n\n本文\n"


def test_agent_types_are_the_three_of_this_repository():
    assert sorted(path.stem for path in AGENTS.glob("*.md")) == sorted(AGENT_TYPES)


@pytest.mark.parametrize("name", AGENT_TYPES)
def test_agent_type_header_of_this_repository_passes_the_guard(name):
    assert agent_problems(name, (AGENTS / f"{name}.md").read_text(encoding="utf-8")) == []


def test_agent_guard_passes_sample_headers_and_skips_indented_lines():
    assert front_matter(agent_text("reader", extra="omitClaudeMd: true")) == {
        "name": "reader", "description": "見本の型", "tools": "Read, Grep, Glob", "omitClaudeMd": "true", "experimental": "",
    }
    assert agent_problems("reviewer", agent_text("reviewer")) == []
    assert agent_problems("reader", agent_text("reader", extra="omitClaudeMd: true")) == []
    assert agent_problems("implementer", agent_text("implementer", tools="Read, Grep, Glob, Edit, Write, Bash")) == []


@pytest.mark.parametrize("name, text, problems", [
    ("reader", agent_text("reader", extra="omitClaudeMD: true"), ["知らない項目：omitClaudeMD"]),  # 綴りの違い
    ("reviewer", agent_text("reviewer").replace("tools:", "tool:"), ["知らない項目：tool", "項目が無いか、空：tools"]),
    ("reviewer", agent_text("reviewer").replace("description: 見本の型\n", ""), ["項目が無いか、空：description"]),
    ("reviewer", agent_text("reviewr"), ["name がファイル名と違う：reviewr"]),
    ("reviewer", agent_text("reviewer", tools="Read, Grep, Glob, Bash"), ["tools に入れない名：Bash"]),
    ("reader", agent_text("reader", tools="Read, Write, Edit"), ["tools に入れない名：Edit", "tools に入れない名：Write"]),
    ("implementer", agent_text("implementer", tools="Read, Edit, Agent, Workflow"), ["tools に入れない名：Agent", "tools に入れない名：Workflow"]),
    ("reviewer", agent_text("reviewer").replace("---\n\n本文", "\n本文"), ["頭の項目が --- で挟まれていない"]),  # 閉じる --- が無い
    ("reviewer", "本文だけ\n", ["頭の項目が --- で挟まれていない"]),
])
def test_agent_guard_reports_broken_headers(name, text, problems):
    assert agent_problems(name, text) == problems
