"""正本の見張り。docs/canon/ の各ファイルの要約値（sha256）を、正本の要約値の写しと照らす。

  python3 tools/canon_guard.py     0＝要約値の写しと同じ、1＝違う、2＝要約値の写しが無くて何も照らせない

正本（docs/canon/planning.md）は読むだけで、書き換えない。
正本の要約値の写しは tests/snapshots/canon_digest.json（ふるまいの写しの1つ）。
ここには要約値の写しを取り直す口を置かない。取り直すのは tools/claude/canon_digest.py --update だけで、
人が採った改訂案を当てる単独のコミットでだけ使う。
ふだんは tools/check.py の canon の節から呼ぶ。
"""
import hashlib
import json
import sys
from pathlib import Path

from _common import FAIL, INCOMPLETE, OK, ROOT, finish

CANON_DIR = "docs/canon"
SNAPSHOT = "tests/snapshots/canon_digest.json"


def canon_files(root: Path) -> list:
    """正本のファイルを、root からの相対パス（/ 区切り）で返す。"""
    base = Path(root) / CANON_DIR
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())


def digest_of(path: Path) -> str:
    """ファイルの中身（バイト列）の sha256。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_digests(root: Path) -> dict:
    """いまの正本の要約値。{相対パス: sha256}。"""
    return {rel: digest_of(Path(root) / rel) for rel in canon_files(root)}


def read_snapshot(root: Path):
    """正本の要約値の写しを読む。返すのは {相対パス: sha256}。無いか読めなければ None。"""
    path = Path(root) / SNAPSHOT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return files if isinstance(files, dict) else None


def check_canon(root: Path) -> tuple:
    """返すのは (照らしたファイルの数, 問題の一覧)。"""
    recorded = read_snapshot(root)
    if recorded is None:
        return 0, [f"正本の要約値の写し（{SNAPSHOT}）が無いか、読めない"]
    current = current_digests(root)
    names = sorted(set(recorded) | set(current))
    problems = []
    for rel in names:
        if rel not in current:
            problems.append(f"{rel}: 要約値の写しにあるが、ファイルが無い")
        elif rel not in recorded:
            problems.append(f"{rel}: 要約値の写しに無い正本のファイル")
        elif current[rel] != recorded[rel]:
            problems.append(
                f"{rel}: 正本が要約値の写しと違う（いま {current[rel][:12]}…、写したとき {str(recorded[rel])[:12]}…）。"
                "正本は書き換えない。ずれは docs/proposals/ に改訂案を起こす"
            )
    return len(names), problems


def main() -> int:
    examined, problems = check_canon(ROOT)
    for problem in problems:
        print(f"  canon: {problem}")
    code = INCOMPLETE if examined == 0 else FAIL if problems else OK
    return finish("canon", code, f"files={examined} problems={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
