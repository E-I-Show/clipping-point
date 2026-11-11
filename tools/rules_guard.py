"""規則ファイルの見張り。.claude/rules/*.md、根の CLAUDE.md、作業の控えの大きさと対応を調べる。

  python3 tools/rules_guard.py     0＝問題なし、1＝問題あり、2＝規則ファイルが1つも無い

見ること：
- どの規則ファイルも頭に paths: を持ち、どの当て先も1つ以上のファイルに当たる。
- 多くの分野が触るファイル（HUBS）には、どの規則ファイルも当てない。
- 規則ファイルの大きさが上限（tools/budgets.json の rule_file_max_bytes）の内。
- CLAUDE.md の「規則ファイルの目次」の表と、規則ファイルが過不足なく対応する。
- CLAUDE.md が200行以内、docs/handoff.md が25行以内。
ふだんは tools/check.py の rules の節から呼ぶ。
"""
import os
import re
import sys
from pathlib import Path

from _common import FAIL, INCOMPLETE, OK, ROOT, finish, load_budgets

CLAUDE_MD_MAX_LINES = 200  # 根の CLAUDE.md の決まり
HANDOFF_MAX_LINES = 25  # 作業の控えの決まり
INDEX_HEADING = "## 規則ファイルの目次"
# 多くの分野が触るファイル。当てると、どの作業でもその規則が読み込まれてしまう。
HUBS = ("clipping_point/main.py", "clipping_point/cp_app/app.py")
# 当て先を照らすときに見ない、根の直下のディレクトリ（git、生成物、設計時の試作）。
ROOT_SKIP_DIRS = frozenset({".git", "out", "dist", ".cache", "spikes"})


def list_files(root: Path) -> list:
    """root の下のファイルを、root からの相対パス（/ 区切り）で返す。"""
    files = []
    for folder, dirs, names in os.walk(root):
        rel = Path(folder).relative_to(root)
        skip = ROOT_SKIP_DIRS if rel == Path(".") else frozenset()
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and d not in skip)
        files += [(rel / name).as_posix() for name in sorted(names)]
    return files


def glob_to_regex(pattern: str):
    """当て先の書き方を正規表現にする。** は階層をまたぎ、* と ? は1つの階層の中だけに当たる。"""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def parse_paths(text: str):
    """規則ファイルの頭の paths: を読む。返すのは (当て先の一覧, 読めなかった行の一覧)。頭の区切りが無ければ None。"""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    paths, bad, in_paths = [], [], False
    for line in m.group(1).splitlines():
        if line.strip() == "paths:":
            in_paths = True
        elif in_paths and line.strip().startswith("-"):
            entry = re.fullmatch(r'\s*-\s*"([^"]+)"\s*', line)
            if entry:
                paths.append(entry.group(1))
            else:
                bad.append(line.strip())
        elif line.strip():
            in_paths = False
    return paths, bad


def parse_index(claude_md: str):
    """CLAUDE.md の「規則ファイルの目次」の表から、規則ファイルの名前を読む。節が無ければ None。"""
    lines = claude_md.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == INDEX_HEADING)
    except StopIteration:
        return None
    names = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        row = re.match(r"\|\s*`\.claude/rules/([^`/]+\.md)`\s*\|", line)
        if row:
            names.append(row.group(1))
    return names


def check_rules(root: Path, budgets: dict) -> tuple:
    """返すのは (調べた規則ファイルの数, 問題の一覧, 件数の要約)。"""
    root = Path(root)
    problems = []
    rule_files = sorted((root / ".claude" / "rules").glob("*.md"))
    present = [p.name for p in rule_files]
    max_bytes = budgets["rule_file_max_bytes"]

    claude_md = root / "CLAUDE.md"
    claude_lines = -1
    if not claude_md.is_file():
        problems.append("CLAUDE.md が無い")
    else:
        text = claude_md.read_text(encoding="utf-8")
        claude_lines = len(text.splitlines())
        if claude_lines > CLAUDE_MD_MAX_LINES:
            problems.append(f"CLAUDE.md が {claude_lines} 行（上限 {CLAUDE_MD_MAX_LINES} 行）。分野の決まりは .claude/rules/ へ移す")
        indexed = parse_index(text)
        if indexed is None:
            problems.append(f"CLAUDE.md に「{INDEX_HEADING}」の節が無い")
        else:
            for name in sorted(set(present) - set(indexed)):
                problems.append(f".claude/rules/{name} が CLAUDE.md の規則ファイルの目次に無い")
            for name in sorted(set(indexed) - set(present)):
                problems.append(f"CLAUDE.md の規則ファイルの目次にある .claude/rules/{name} が無い")
            for name in sorted({n for n in indexed if indexed.count(n) > 1}):
                problems.append(f"CLAUDE.md の規則ファイルの目次に .claude/rules/{name} が2度ある")

    handoff = root / "docs" / "handoff.md"
    handoff_lines = -1
    if not handoff.is_file():
        problems.append("docs/handoff.md が無い")
    else:
        handoff_lines = len(handoff.read_text(encoding="utf-8").splitlines())
        if handoff_lines > HANDOFF_MAX_LINES:
            problems.append(f"docs/handoff.md が {handoff_lines} 行（上限 {HANDOFF_MAX_LINES} 行）")

    files = list_files(root)
    targets = 0
    for path in rule_files:
        text = path.read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        if size > max_bytes:
            problems.append(f"{path.name}: {size} バイト（上限 {max_bytes} バイト）")
        parsed = parse_paths(text)
        if parsed is None or not parsed[0] and not parsed[1]:
            problems.append(f"{path.name}: 頭に paths: の当て先が無い")
            continue
        for line in parsed[1]:
            problems.append(f"{path.name}: paths: の行が読めない：{line}（- \"当て先\" の形で書く）")
        for target in parsed[0]:
            targets += 1
            regex = glob_to_regex(target)
            hits = [f for f in files if regex.match(f)]
            if not hits:
                problems.append(f"{path.name}: 当て先 {target!r} がどのファイルにも当たらない")
            for hub in HUBS:
                if hub in hits:
                    problems.append(f"{path.name}: 当て先 {target!r} が、多くの分野が触る {hub} に当たっている")
    detail = f"rule_files={len(rule_files)} targets={targets} claude_md_lines={claude_lines} handoff_lines={handoff_lines}"
    return len(rule_files), problems, detail


def main() -> int:
    count, problems, detail = check_rules(ROOT, load_budgets())
    for problem in problems:
        print(f"  rules: {problem}")
    code = INCOMPLETE if count == 0 else FAIL if problems else OK
    return finish("rules", code, f"{detail} problems={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
