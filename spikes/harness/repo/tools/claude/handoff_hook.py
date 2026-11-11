"""SessionStart hook: put the handoff note (docs/handoff.md, max 25 lines, IN git) in front of Claude.

This project is developed in throw-away cloud containers: nothing outside pushed git survives a
session, so the note cannot live outside git as the skill suggests. It is committed together with
every checkpoint commit and pushed.

  source = compact | resume  -> print the whole note, with HEAD, the note's commit and what is newer
  source = startup           -> print a 3-line pointer only (a fresh container always starts with
                                "startup", even when it continues the same work)
  source = clear             -> print nothing
Always adds a warning when the work tree has uncommitted files or commits that are not pushed.
Hook input: JSON on stdin with a "source" field. Output: plain text on stdout (added to context).
Never fails the session: any error ends with exit 0 and a one-line note.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
NOTE = ROOT / "docs" / "handoff.md"
MAX_LINES = 25


def git(*args) -> str:
    p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=10)
    return p.stdout.strip() if p.returncode == 0 else ""


def main() -> int:
    try:
        source = json.load(sys.stdin).get("source", "")
    except (json.JSONDecodeError, AttributeError):
        source = ""
    if source not in ("compact", "resume", "startup") or not NOTE.exists():
        return 0
    head = git("log", "-1", "--format=%h %cI %s")
    note_commit = git("log", "-1", "--format=%h %cI", "--", "docs/handoff.md")
    newer = git("rev-list", "--count", f"{note_commit.split()[0]}..HEAD") if note_commit else ""
    dirty = len([line for line in git("status", "--porcelain").splitlines() if line])
    unpushed = git("rev-list", "--count", "@{u}..HEAD")
    lines = NOTE.read_text(encoding="utf-8").splitlines()
    out = [f"[handoff] HEAD {head or '(no commits)'}", f"[handoff] note last committed: {note_commit or 'never (uncommitted)'}"]
    if newer and newer != "0":
        out.append(f"[handoff] {newer} commit(s) are NEWER than the note: trust git log over the note")
    if dirty:
        out.append(f"[handoff] {dirty} uncommitted path(s) in the work tree: they vanish with this container")
    if unpushed and unpushed != "0":
        out.append(f"[handoff] {unpushed} commit(s) not pushed: push before stopping")
    if source == "startup":
        out.append("[handoff] docs/handoff.md exists. If this session continues that work, read it first, then the state table in docs/worklog.md.")
    else:
        out.append(f"--- docs/handoff.md ({len(lines)} lines) ---")
        out += lines[:MAX_LINES]
        if len(lines) > MAX_LINES:
            out.append(f"[handoff] note is {len(lines)} lines; only {MAX_LINES} shown. Trim it.")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"[handoff] hook error ignored: {type(exc).__name__}: {exc}")
        sys.exit(0)
