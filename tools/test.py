"""ロジックのテスト（pytest）を、見かけの合格の穴をふさいで回す。

  python3 tools/test.py                    tests/ の全部
  python3 tools/test.py -k "sim or canvas" 名前で絞る（式のどの語も、どれかのテスト名に当たること）
  python3 tools/test.py --update-floor     件数の下限（tests/count_floor.txt）を、いまの件数に下げる

合格（0）にするのは、pytest が0で終わり、結果の報告（junit）があり、1件以上通り、スキップが0件で、
全部を回したときに件数が下限を下回らない場合だけ。
  1＝失敗、エラー、スキップ、件数が下限より少ない、テストのプロセスに pyxel が読み込まれた
  2＝何も確かめていない（0件、-k の語がどのテスト名にも当たらない、報告が無い＝途中でプロセスが消えた、時間切れ）
件数が下限より増えたら、下限を自動で上げる。下げるのは --update-floor だけ。
pytest の中では Pyxel を動かさない（pyxel.quit() は終了コード0で終わり、後ろの失敗を消す）。
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

from _common import FAIL, INCOMPLETE, OK, OUT, ROOT, TESTS, finish, run, tail

PYTEST = [sys.executable, "-m", "pytest", "-c", ROOT / "pytest.ini", "--rootdir", ROOT]
FLOOR = TESTS / "count_floor.txt"
REPORT = OUT / "test" / "junit.xml"
FORBIDDEN_MARK = "FORBIDDEN MODULES LOADED"  # tests/conftest.py が出す行の目印


def read_floor() -> int:
    try:
        return int(FLOOR.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ロジックのテスト")
    ap.add_argument("-k", default="", metavar="EXPR", help="テスト名で絞る式")
    ap.add_argument("--update-floor", action="store_true", help="件数の下限を、いまの件数に下げる")
    ap.add_argument("--timeout", type=int, default=600, help="秒")
    args = ap.parse_args()
    if args.k and args.update_floor:
        return finish("test", INCOMPLETE, "reason=update_floor_needs_full_run")
    if not TESTS.is_dir():
        return finish("test", INCOMPLETE, "collected=0 reason=no_tests")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.unlink(missing_ok=True)

    # 先に全テスト名を取る。0件と、-k の語の打ち間違いを見分けるため。
    code, out, err = run([*PYTEST, "--collect-only", "-q", TESTS], timeout=args.timeout)
    ids = [line.strip() for line in out.splitlines() if "::" in line]
    if code is None:
        return finish("test", INCOMPLETE, f"reason=timeout timeout_s={args.timeout}")
    if code not in (0, 5):
        print(tail(out + "\n" + err))
        return finish("test", FAIL, f"collected={len(ids)} reason=collection_error pytest_exit={code}")
    if not ids:
        print(tail(out + "\n" + err))
        return finish("test", INCOMPLETE, f"collected=0 reason=no_tests pytest_exit={code}")
    for word in re.findall(r"[^\s()]+", args.k):
        if word in ("and", "or", "not"):
            continue
        if not any(word.lower() in test_id.lower() for test_id in ids):
            return finish("test", INCOMPLETE, f"collected={len(ids)} k={args.k!r} reason=k_word_matches_nothing word={word!r}")

    cmd = [*PYTEST, "-q", "-rfEs", f"--junitxml={REPORT}", TESTS]
    if args.k:
        cmd += ["-k", args.k]
    code, out, err = run(cmd, timeout=args.timeout)
    shown = tail(out + "\n" + err)
    if code is None:
        print(shown)
        return finish("test", INCOMPLETE, f"collected={len(ids)} reason=timeout timeout_s={args.timeout}")
    try:
        suite = ET.parse(REPORT).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
        total, failures, errors, skipped = (int(suite.get(key, 0)) for key in ("tests", "failures", "errors", "skipped"))
    except (OSError, ET.ParseError, AttributeError, ValueError):
        print(shown)
        return finish("test", INCOMPLETE, f"collected={len(ids)} reason=no_report pytest_exit={code}")
    passed = total - failures - errors - skipped
    floor = read_floor()
    counts = f"passed={passed} failed={failures} errors={errors} skipped={skipped} selected={total} collected={len(ids)} floor={floor}"
    if args.k:
        counts += f" k={args.k!r}"
    if total == 0 or code == 5:
        print(shown)
        return finish("test", INCOMPLETE, f"{counts} reason=no_tests pytest_exit={code}")
    if failures or errors:
        print(shown)
        return finish("test", FAIL, f"{counts} reason=failed pytest_exit={code}")
    if code != 0:
        print(shown)
        reason = "pyxel_loaded" if FORBIDDEN_MARK in out else "pytest_exit"
        return finish("test", FAIL, f"{counts} reason={reason} pytest_exit={code}")
    if skipped:
        print(shown)
        return finish("test", FAIL, f"{counts} reason=skipped")
    if passed < 1:
        return finish("test", INCOMPLETE, f"{counts} reason=no_tests")
    if not args.k:
        if passed > floor or (args.update_floor and passed != floor):
            FLOOR.write_text(f"{passed}\n", encoding="utf-8")
            counts = counts.replace(f"floor={floor}", f"floor={passed}") + f" floor_was={floor}"
        elif passed < floor:
            return finish("test", FAIL, f"{counts} reason=below_floor")
    return finish("test", OK, counts)


if __name__ == "__main__":
    sys.exit(main())
