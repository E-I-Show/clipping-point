"""セッションの開始時に、作業の控えを差し込むフック（Claude Code の SessionStart）。作業用のスクリプト。

  .claude/settings.json から呼ばれる。標準入力にフックの入力（JSON）が来る。標準出力に出した文が、文脈に入る。

  新しいセッション（source が startup）   数行の案内だけを出す
  圧縮、再開、/clear の後（compact、resume、clear）   案内と、控え（docs/handoff.md）の全文を出す

控えを書いた時点のHEADと、いまのHEADを並べ、その後のコミットの数を添える。
失敗してもセッションを止めない。何が起きても終了コードは0で、出せる所までを出す。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HANDOFF = ROOT / "docs" / "handoff.md"
FULL_SOURCES = ("resume", "compact", "clear")  # 控えの全文を出す場合
WORK_BRANCH = "dev"  # 作業ブランチ（根のCLAUDE.mdの「gitの決まり」）
GIT_TIMEOUT_S = 5


def git(*args):
    """gitを回して、標準出力を返す。回せなければ None。"""
    try:
        p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def handoff_head(text: str):
    """控えの頭の行から、控えを書いた時点のHEADを読む。無ければ None。"""
    m = re.search(r"^HEAD:\s*([0-9a-f]{7,40})\b", text, re.M)
    return m.group(1) if m else None


def build_message(source: str, handoff_text, branch, head, commits_after) -> str:
    """文脈に入れる文を組み立てる（gitにもファイルにも触れない）。

    handoff_text は控えの全文（無ければ None）。commits_after は、控えを書いた時点のHEADから後のコミットの数（分からなければ None）。
    """
    lines = [
        "[clipping-point] 作業の控えの案内",
        "- 最初に、根のCLAUDE.mdの「最初に確かめること」（Claudeのモデルと週の使用率）と「再開のときに読む順」を守る。",
    ]
    if handoff_text is None:
        lines.append("- 作業の控え（docs/handoff.md）が無い。docs/worklog.md の頭の「状態の表」と「次の手」から読む。")
        return "\n".join(lines) + "\n"
    lines.append("- 作業の控えは docs/handoff.md。作業記録は docs/worklog.md の頭の「状態の表」と「次の手」。")
    where = f"- いまのブランチ：{branch or '読めない'}。HEAD：{head or '読めない'}。"
    written = handoff_head(handoff_text)
    if written is None:
        where += "控えに、書いた時点のHEADが無い。"
    elif commits_after is None:
        where += f"控えを書いた時点のHEAD：{written}（いまのHEADとの間が読めない。別のブランチかもしれない）。"
    elif commits_after <= 1:
        where += f"控えを書いた時点のHEAD：{written}（控えは新しい）。"
    else:
        where += f"控えを書いた時点のHEAD：{written}。その後のコミットが{commits_after}個ある（1個は控えを入れたコミット）。控えが古いかもしれない。"
    lines.append(where)
    if branch and branch != WORK_BRANCH:
        lines.append(f"- 作業ブランチは {WORK_BRANCH}。いまは {branch}。進める前に、{WORK_BRANCH} との違いを確かめる。")
    if source in FULL_SOURCES:
        lines += ["", "--- docs/handoff.md ---", handoff_text.rstrip("\n")]
    return "\n".join(lines) + "\n"


def read_source(stdin_text: str) -> str:
    """フックの入力（JSON）から source を読む。読めなければ startup として扱う。"""
    try:
        value = json.loads(stdin_text or "{}")
    except ValueError:
        return "startup"
    source = value.get("source") if isinstance(value, dict) else None
    return source if isinstance(source, str) else "startup"


def main() -> int:
    try:
        source = read_source(sys.stdin.read())
        handoff_text = HANDOFF.read_text(encoding="utf-8") if HANDOFF.is_file() else None
        branch = git("branch", "--show-current")
        head = git("rev-parse", "--short", "HEAD")
        commits_after = None
        written = handoff_head(handoff_text) if handoff_text else None
        if written:
            count = git("rev-list", "--count", f"{written}..HEAD")
            commits_after = int(count) if count and count.isdigit() else None
        sys.stdout.write(build_message(source, handoff_text, branch, head, commits_after))
    except Exception as exc:  # フックの失敗で、セッションを止めない
        sys.stdout.write(f"[clipping-point] 作業の控えの案内を出せなかった（{type(exc).__name__}）。docs/handoff.md を読む。\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
