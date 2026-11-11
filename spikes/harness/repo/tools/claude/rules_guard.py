"""Watches the Claude Code scaffolding: CLAUDE.md size, .claude/rules/*.md front matter, globs,
sizes and the index in CLAUDE.md.

  python3 tools/claude/rules_guard.py     exit 0 ok / 1 problems / 2 nothing to check
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RULES = ROOT / ".claude" / "rules"
ROOT_MD = ROOT / "CLAUDE.md"
MAX_ROOT_LINES = 200
MAX_RULE_BYTES = 6000  # placeholder: well below the size at which a rule file is loaded head-only
HUBS = ("app/main.py", "app/cp_app/app.py")  # files many areas touch: never in a glob


def parse_paths(text: str):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    return re.findall(r'^\s*-\s*"([^"]+)"\s*$', m.group(1), re.M)


def main() -> int:
    problems = []
    rule_files = sorted(RULES.glob("*.md")) if RULES.is_dir() else []
    if not ROOT_MD.exists() or not rule_files:
        print("RULES_GUARD_INCOMPLETE CLAUDE.md or .claude/rules/*.md not found")
        return 2
    root_text = ROOT_MD.read_text(encoding="utf-8")
    n = len(root_text.splitlines())
    if n > MAX_ROOT_LINES:
        problems.append(f"CLAUDE.md has {n} lines (limit {MAX_ROOT_LINES}): move area rules to .claude/rules/")
    indexed = set(re.findall(r"`\.claude/rules/([a-z0-9_-]+\.md)`", root_text))
    present = {p.name for p in rule_files}
    for name in sorted(present - indexed):
        problems.append(f".claude/rules/{name} is not in the index table of CLAUDE.md")
    for name in sorted(indexed - present):
        problems.append(f"CLAUDE.md lists .claude/rules/{name}, which does not exist")
    globs = 0
    for p in rule_files:
        text = p.read_text(encoding="utf-8")
        size = len(text.encode("utf-8"))
        if size > MAX_RULE_BYTES:
            problems.append(f"{p.name}: {size} bytes (limit {MAX_RULE_BYTES})")
        paths = parse_paths(text)
        if not paths:
            problems.append(f"{p.name}: no `paths:` front matter")
            continue
        for g in paths:
            globs += 1
            hits = [h for h in ROOT.glob(g) if h.is_file()]
            if not hits:
                problems.append(f"{p.name}: glob {g!r} matches no file")
            for h in hits:
                if h.relative_to(ROOT).as_posix() in HUBS:
                    problems.append(f"{p.name}: glob {g!r} hits hub file {h.relative_to(ROOT)}")
    for line in problems:
        print("RULES:", line)
    print(f"RULES_GUARD_{'FAILED' if problems else 'OK'} root_lines={n} rule_files={len(rule_files)} globs={globs} problems={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
