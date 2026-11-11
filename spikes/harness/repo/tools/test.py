"""Logic tests (pytest) with the holes closed.

  python3 tools/test.py                      everything under tests/
  python3 tools/test.py -k "rng or profile"  select by name (every word must match at least one test)
  python3 tools/test.py --update-snapshots   rewrite tests/snapshots (do it in its own commit)
  python3 tools/test.py --update-floor       accept a lower test count

Exit 0 only if: pytest exit 0, the junit report exists, passed >= 1, skipped == 0, and (full run)
the number of tests is not below tests/count_floor.txt. Exit 1 = failures. Exit 2 = nothing was
really tested (0 selected, a -k word that matches nothing, report missing = process died).
Measured holes this closes (results/runner_matrix.json): all-skipped -> pytest exit 0;
os._exit(0)/pyxel.quit() inside a test -> exit 0 with no output; -k "a or typo" -> exit 0;
exception only in a thread -> exit 0.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

from _common import FAIL, INCOMPLETE, OK, OUT, ROOT, finish, run

PYTEST = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--strict-markers", "--strict-config",
          "-W", "error::pytest.PytestUnhandledThreadExceptionWarning", "-W", "error::pytest.PytestUnraisableExceptionWarning"]
FLOOR = ROOT / "tests" / "count_floor.txt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="")
    ap.add_argument("--update-snapshots", action="store_true")
    ap.add_argument("--update-floor", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    report = OUT / "test" / "junit.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)

    code, out, err = run([*PYTEST, "--collect-only", "-q", "tests"])
    ids = [line for line in out.splitlines() if "::" in line]
    if code != 0 or not ids:
        print(out[-3000:], err[-2000:])
        return finish("test", FAIL if code not in (0, 5) else INCOMPLETE, f"collection failed or empty (pytest exit {code}, tests={len(ids)})")
    if args.k:
        for word in re.findall(r"[^\s()]+", args.k):
            if word in ("and", "or", "not"):
                continue
            if not any(word.lower() in i.lower() for i in ids):
                return finish("test", INCOMPLETE, f"-k word {word!r} matches none of the {len(ids)} tests")

    cmd = [*PYTEST, "-q", "-rfEs", f"--junitxml={report}", "tests"]
    if args.k:
        cmd += ["-k", args.k]
    if args.update_snapshots:
        cmd.append("--update-snapshots")
    code, out, err = run(cmd, timeout=args.timeout)
    tail = "\n".join((out + err).strip().splitlines()[-25:])
    if code is None:
        print(tail)
        return finish("test", INCOMPLETE, f"timeout after {args.timeout}s")
    try:
        suite = ET.parse(report).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
        total, failures, errors, skipped = (int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
    except (OSError, ET.ParseError, AttributeError) as exc:
        print(tail)
        return finish("test", INCOMPLETE, f"no usable junit report ({type(exc).__name__}): the test process ended without finishing (pytest exit {code})")
    passed = total - failures - errors - skipped
    counts = f"passed={passed} failed={failures} errors={errors} skipped={skipped} selected={total} collected={len(ids)}" + (f" k={args.k!r}" if args.k else "")
    if code != 0 or failures or errors:
        print(tail)
        return finish("test", INCOMPLETE if code == 5 or total == 0 else FAIL, counts + f" (pytest exit {code})")
    if skipped:
        print(tail)
        return finish("test", FAIL, counts + " - skipped tests are not accepted: delete the test or make it run")
    if passed < 1:
        return finish("test", INCOMPLETE, counts + " - nothing ran")
    if not args.k:
        floor = int(FLOOR.read_text().strip()) if FLOOR.exists() else 0
        if args.update_floor or passed > floor:
            FLOOR.write_text(f"{passed}\n")
        elif passed < floor:
            return finish("test", FAIL, counts + f" - fewer tests than the recorded floor {floor} (tests vanished? if intended: --update-floor)")
    return finish("test", OK, counts)


if __name__ == "__main__":
    sys.exit(main())
