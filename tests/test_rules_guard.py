"""規則ファイルの見張り（tools/rules_guard.py）のテスト。

いまのリポジトリが見張りを通ることと、見張りそのものが崩れを拾うことの両方を確かめる。
"""
import json

import pytest

import rules_guard
from conftest import ROOT

BUDGETS = {"rule_file_max_bytes": 6000}
INDEX = "## 規則ファイルの目次\n\n| ファイル | 当たる所 |\n| --- | --- |\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rule_text(*targets):
    return "---\npaths:\n" + "".join(f'  - "{t}"\n' for t in targets) + "---\n\n# 見本の規則\n\n- 約束を1つ。\n"


def make_repo(root):
    """見張りを通る、最小の見本のリポジトリを作る。"""
    write(root / "CLAUDE.md", "# 見本\n\n" + INDEX + "| `.claude/rules/tools.md` | 道具 |\n| `.claude/rules/ui.md` | 画面 |\n")
    write(root / "docs" / "handoff.md", "控え\n")
    write(root / ".claude" / "rules" / "tools.md", rule_text("tools/**"))
    write(root / ".claude" / "rules" / "ui.md", rule_text("clipping_point/cp_ui/**", "tests/test_canvas.py"))
    write(root / "tools" / "check.py", "")
    write(root / "tools" / "claude" / "helper.py", "")
    write(root / "clipping_point" / "cp_ui" / "canvas.py", "")
    write(root / "clipping_point" / "cp_app" / "app.py", "")
    write(root / "clipping_point" / "main.py", "")
    write(root / "tests" / "test_canvas.py", "")
    return root


def problems_of(root):
    return rules_guard.check_rules(root, BUDGETS)[1]


def test_rules_this_repository_passes_the_guard():
    budgets = json.loads((ROOT / "tools" / "budgets.json").read_text(encoding="utf-8"))
    count, problems, _ = rules_guard.check_rules(ROOT, budgets)
    assert count >= 3
    assert problems == []


def test_rules_minimal_repository_passes(tmp_path):
    count, problems, detail = rules_guard.check_rules(make_repo(tmp_path), BUDGETS)
    assert (count, problems) == (2, [])
    assert "rule_files=2 targets=3" in detail


def test_rules_target_that_matches_no_file_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "ui.md", rule_text("clipping_point/cp_gui/**", "tests/test_canvas.py"))
    problems = problems_of(root)
    assert len(problems) == 1 and "cp_gui" in problems[0]


def test_rules_file_without_paths_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "ui.md", "# 画面\n\n- 頭に paths: が無い。\n")
    problems = problems_of(root)
    assert len(problems) == 1 and "ui.md" in problems[0]


def test_rules_unquoted_target_line_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "tools.md", "---\npaths:\n  - tools/**\n---\n\n# 道具\n")
    problems = problems_of(root)
    assert len(problems) == 1 and "tools.md" in problems[0]


def test_rules_comment_and_blank_lines_inside_paths_do_not_end_the_list():
    text = '---\npaths:\n  - "tools/**"\n  # テスト\n\n  - "tests/test_x.py"\n---\n\n# 見本\n'
    assert rules_guard.parse_paths(text) == (["tools/**", "tests/test_x.py"], [])


def test_rules_other_line_inside_paths_is_reported_as_unreadable():
    text = '---\npaths:\n  - "tools/**"\n  tests/test_x.py\n---\n\n# 見本\n'
    assert rules_guard.parse_paths(text) == (["tools/**"], ["tests/test_x.py"])


def test_rules_next_key_ends_the_paths_list():
    text = '---\npaths:\n  - "tools/**"\nnotes: x\n  - "ignored/**"\n---\n\n# 見本\n'
    assert rules_guard.parse_paths(text) == (["tools/**"], [])


def test_rules_file_listed_twice_in_the_index_is_reported(tmp_path):
    root = make_repo(tmp_path)
    claude_md = root / "CLAUDE.md"
    write(claude_md, claude_md.read_text(encoding="utf-8") + "| `.claude/rules/ui.md` | 画面（2度目） |\n")
    problems = problems_of(root)
    assert len(problems) == 1 and "2度" in problems[0]


def test_rules_file_missing_from_the_index_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "extra.md", rule_text("tools/check.py"))
    problems = problems_of(root)
    assert len(problems) == 1 and "extra.md" in problems[0]


def test_rules_file_in_a_subdirectory_is_also_checked(tmp_path):
    # 下のディレクトリに置いた規則ファイルも読み込まれるので、目次との対応を同じように見る。
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "sub" / "deep.md", rule_text("tools/check.py"))
    problems = problems_of(root)
    assert len(problems) == 1 and "sub/deep.md" in problems[0]
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    write(root / "CLAUDE.md", text + "| `.claude/rules/sub/deep.md` | 下のディレクトリ |\n")
    assert rules_guard.check_rules(root, BUDGETS)[:2] == (3, [])


def test_rules_index_row_without_a_file_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / ".claude" / "rules" / "ui.md").unlink()
    problems = problems_of(root)
    assert len(problems) == 1 and "ui.md" in problems[0]


def test_rules_index_is_read_only_from_its_own_section(tmp_path):
    # 目次の節の外で規則ファイルの名前に触れても、目次の行には数えない。
    root = make_repo(tmp_path)
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    write(root / "CLAUDE.md", text + "\n## ほかの節\n\n| `.claude/rules/ghost.md` | 目次の外 |\n")
    assert problems_of(root) == []


def test_rules_missing_index_section_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / "CLAUDE.md", "# 見本\n")
    assert any("規則ファイルの目次" in problem for problem in problems_of(root))


def test_rules_file_over_the_size_limit_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "tools.md", rule_text("tools/**") + "- 長い行。\n" * 600)
    problems = problems_of(root)
    assert len(problems) == 1 and "上限 6000" in problems[0]


def test_rules_target_on_a_hub_file_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / ".claude" / "rules" / "ui.md", rule_text("clipping_point/**", "tests/test_canvas.py"))
    problems = problems_of(root)
    assert sorted(hub for hub in rules_guard.HUBS if any(hub in problem for problem in problems)) == sorted(rules_guard.HUBS)


def test_rules_claude_md_over_200_lines_is_reported(tmp_path):
    root = make_repo(tmp_path)
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    write(root / "CLAUDE.md", "# 見本\n" + "- 埋め草\n" * 200 + text)
    problems = problems_of(root)
    assert len(problems) == 1 and "CLAUDE.md" in problems[0]


def test_rules_claude_md_of_exactly_200_lines_passes(tmp_path):
    root = make_repo(tmp_path)
    text = (root / "CLAUDE.md").read_text(encoding="utf-8")
    padding = 200 - len(text.splitlines())
    write(root / "CLAUDE.md", "- 埋め草\n" * padding + text)
    assert len((root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()) == 200
    assert problems_of(root) == []


def test_rules_handoff_over_25_lines_is_reported(tmp_path):
    root = make_repo(tmp_path)
    write(root / "docs" / "handoff.md", "控え\n" * 25)
    assert problems_of(root) == []
    write(root / "docs" / "handoff.md", "控え\n" * 26)
    problems = problems_of(root)
    assert len(problems) == 1 and "handoff.md" in problems[0]


def test_rules_missing_handoff_and_claude_md_are_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "handoff.md").unlink()
    (root / "CLAUDE.md").unlink()
    problems = problems_of(root)
    assert any("handoff.md" in problem for problem in problems)
    assert any("CLAUDE.md" in problem for problem in problems)


def test_rules_no_rule_files_counts_zero(tmp_path):
    root = make_repo(tmp_path)
    for path in (root / ".claude" / "rules").glob("*.md"):
        path.unlink()
    count, problems, _ = rules_guard.check_rules(root, BUDGETS)
    assert count == 0
    assert len(problems) == 2  # 目次の2行が、無いファイルを指している


@pytest.mark.parametrize(
    "pattern, path, expected",
    [
        ("tools/**", "tools/check.py", True),
        ("tools/**", "tools/claude/canon_digest.py", True),
        ("tools/**", "tests/tools/check.py", False),
        ("tools/*.py", "tools/check.py", True),
        ("tools/*.py", "tools/claude/canon_digest.py", False),
        ("clipping_point/**/*.py", "clipping_point/main.py", True),
        ("clipping_point/**/*.py", "clipping_point/cp_core/sim.py", True),
        ("clipping_point/cp_core/sim.py", "clipping_point/cp_core/sim.py", True),
        ("clipping_point/cp_core/sim.py", "clipping_point/cp_core/simx.py", False),
        ("tests/test_?.py", "tests/test_a.py", True),
        ("tests/test_?.py", "tests/test_ab.py", False),
    ],
)
def test_rules_target_pattern_matching(pattern, path, expected):
    assert bool(rules_guard.glob_to_regex(pattern).match(path)) is expected


def test_rules_generated_and_spike_directories_are_not_matched(tmp_path):
    # 生成物と設計時の試作だけに当たる当て先は、当たっていない扱いにする。
    root = make_repo(tmp_path)
    write(root / "out" / "run" / "result.json", "{}")
    write(root / "spikes" / "harness" / "tool.py", "")
    write(root / ".claude" / "rules" / "tools.md", rule_text("tools/**", "out/**", "spikes/**"))
    problems = problems_of(root)
    assert len(problems) == 2
