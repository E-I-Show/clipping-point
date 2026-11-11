"""正本の要約値の写し（tests/snapshots/canon_digest.json）を見る、取り直す。

  python3 tools/claude/canon_digest.py            いまの要約値と写しを並べて出す。0＝同じ、1＝違う、2＝写しが無い
  python3 tools/claude/canon_digest.py --update   写しを取り直す

--update を使ってよいのは、人が採った改訂案を正本に当てる単独のコミットだけ。
正本そのものは、この台本も書き換えない。見張りの本体は tools/canon_guard.py（check と守りのテストが使う）。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # tools/ を読めるようにする

from _common import FAIL, INCOMPLETE, OK, ROOT, finish  # noqa: E402
from canon_guard import SNAPSHOT, check_canon, current_digests, read_snapshot  # noqa: E402

NOTE = (
    "正本（docs/canon/）の内容の要約値（sha256）の写し。check と守りのテストが照らす。"
    "取り直しは tools/claude/canon_digest.py --update。人が採った改訂案を当てる単独のコミットでだけ行う。"
)


def snapshot_text(digests: dict) -> str:
    return json.dumps({"_notes": NOTE, "files": digests}, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="正本の要約値の写しを見る、取り直す")
    ap.add_argument("--update", action="store_true", help="写しを取り直す（改訂案を当てる単独のコミットでだけ）")
    args = ap.parse_args()
    current = current_digests(ROOT)
    if args.update:
        if not current:
            return finish("canon_digest", INCOMPLETE, "files=0 updated=0")
        path = ROOT / SNAPSHOT
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(snapshot_text(current), encoding="utf-8")
        for rel, digest in current.items():
            print(f"  {rel}: {digest}")
        return finish("canon_digest", OK, f"files={len(current)} updated={len(current)}")
    recorded = read_snapshot(ROOT) or {}
    for rel in sorted(set(current) | set(recorded)):
        print(f"  {rel}: now={current.get(rel, '-')} snapshot={recorded.get(rel, '-')}")
    examined, problems = check_canon(ROOT)
    code = INCOMPLETE if examined == 0 else FAIL if problems else OK
    return finish("canon_digest", code, f"files={examined} problems={len(problems)} updated=0")


if __name__ == "__main__":
    sys.exit(main())
