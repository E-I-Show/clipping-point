"""作業の補助（tools/claude/ の handoff_hook、review_summary、usage_row）のテスト。

どれも、gitにもネットワークにも触れない関数を、値を渡して確かめる。
"""
import json
import sys
from datetime import datetime, timezone

import pytest

from conftest import ROOT

sys.path.append(str(ROOT / "tools" / "claude"))

import handoff_hook  # noqa: E402
import review_summary  # noqa: E402
import usage_row  # noqa: E402

HANDOFF = "<!-- 作業の控え -->\nHEAD: abc1234　書いた刻: 2026-11-11 08:00 UTC　ブランチ: dev\n\n段と区切り: 段0 ／ 区切り4\n"
FULL_MARK = "--- docs/handoff.md ---"


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


def test_handoff_warns_when_not_on_the_work_branch():
    on_other = handoff_hook.build_message("startup", HANDOFF, "main", "def5678", 1)
    on_dev = handoff_hook.build_message("startup", HANDOFF, "dev", "def5678", 1)
    assert "作業ブランチは dev。いまは main" in on_other
    assert "作業ブランチは dev。いまは" not in on_dev


# --- review_summary ---
def finding(fid):
    return {"id": fid, "severity": "中", "tag": "確かめた", "where": "x.py:1", "case": "c", "fix": "f"}


def verdict(fid, word):
    return {"id": fid, "verdict": word, "reason": "r", "checked": "x.py:1"}


def lens(key, findings, verdicts):
    review = None if findings is None else {"scope": "s", "findings": findings, "unevaluated": []}
    refute = None if verdicts is None else {"verdicts": verdicts, "unevaluated": []}
    return {"key": key, "review": review, "refute": refute}


def test_review_counts_passed_and_rejected():
    data = {"step": "s", "results": [lens("a", [finding("a-1"), finding("a-2")], [verdict("a-1", "通った"), verdict("a-2", "退け")])]}
    summary = review_summary.summarize(data)
    assert [item["finding"]["id"] for item in summary["passed"]] == ["a-1"]
    assert [item["finding"]["id"] for item in summary["rejected"]] == ["a-2"]
    assert summary["findings"] == 2 and summary["unevaluated"] == []


def test_review_lens_with_no_findings_is_evaluated():
    summary = review_summary.summarize({"step": "s", "results": [lens("a", [], [])]})
    assert summary["findings"] == 0 and summary["unevaluated"] == []


@pytest.mark.parametrize("row", [
    lens("a", None, None),  # レビュー役が結果を返していない
    lens("a", [finding("a-1")], None),  # 反証役が結果を返していない
    lens("a", [finding("a-1"), finding("a-2")], [verdict("a-1", "通った")]),  # 反証の付いていない指摘がある
    lens("a", [finding("a-1")], [verdict("a-1", "たぶん")]),  # 知らない語の反証
])
def test_review_missing_results_are_unevaluated_not_zero_findings(row):
    summary = review_summary.summarize({"step": "s", "results": [row]})
    assert len(summary["unevaluated"]) == 1


def run_review_main(tmp_path, monkeypatch, data):
    path = tmp_path / "result.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["review_summary.py", str(path)])
    return review_summary.main()


def test_review_main_exit_codes(tmp_path, monkeypatch, capsys):
    good = {"step": "s", "results": [lens("a", [finding("a-1")], [verdict("a-1", "通った")])]}
    assert run_review_main(tmp_path, monkeypatch, {"result": good}) == 0  # ワークフローの出力の形
    assert run_review_main(tmp_path, monkeypatch, good) == 0  # 中身だけの形
    assert "review_summary: OK findings=1 passed=1 rejected=0 unevaluated=0" in capsys.readouterr().out
    assert run_review_main(tmp_path, monkeypatch, {"step": "s", "results": [lens("a", None, None)]}) == 1
    assert run_review_main(tmp_path, monkeypatch, {"step": "s"}) == 2
    monkeypatch.setattr(sys, "argv", ["review_summary.py", str(tmp_path / "missing.json")])
    assert review_summary.main() == 2


# --- usage_row ---
RESETS_AT = 1794902400  # 2026-11-17 08:00 UTC
NOW = datetime(2026, 11, 11, 8, 0, tzinfo=timezone.utc)  # 切り替わりのちょうど6日前＝週の初めから1日後


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
