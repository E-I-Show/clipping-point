"""静的な検査。ゲームは1 tickも回さない。

  python3 tools/check.py [--only syntax|arch|rules|canon|areas]

  syntax   clipping_point/、tools/、tests/ の全 .py が compile できる
  arch     層の分離（tools/arch_check.py。純Pythonの層のソースをASTで解析し、許可した一覧と照らす）
  rules    規則ファイルの見張り（tools/rules_guard.py）
  canon    正本の見張り（tools/canon_guard.py）
  areas    出荷するコード（clipping_point/）とテスト（tests/）の全ファイルが、分野ごとの組の表
           （tools/verify.py の AREAS）のどれかの分野に当たる
終了コード：0＝全節が合格、1＝問題のある節がある、2＝調べた件数が0の節か、回り切れなかった節がある。
最後の1行の「節=数」は、その節で調べた件数。
"""
import argparse
import sys

import arch_check
import canon_guard
import rules_guard
import verify
from _common import APP, FAIL, INCOMPLETE, OK, ROOT, TESTS, TOOLS, finish, load_budgets

MAX_DETAILS = 40  # 1つの節で画面に出す問題の行数の上限


def syntax() -> tuple:
    files = sorted(p for d in (APP, TOOLS, TESTS) for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    problems = []
    for path in files:
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec", dont_inherit=True)
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{path.relative_to(ROOT).as_posix()}: {exc}")
    return len(files), problems


def arch() -> tuple:
    return arch_check.check_tree(APP)


def rules() -> tuple:
    count, problems, detail = rules_guard.check_rules(ROOT, load_budgets())
    print(f"  rules: {detail}")
    return count, problems


def canon() -> tuple:
    return canon_guard.check_canon(ROOT)


def areas() -> tuple:
    return verify.unassigned_files(ROOT)


SECTIONS = {"syntax": syntax, "arch": arch, "rules": rules, "canon": canon, "areas": areas}


def main() -> int:
    ap = argparse.ArgumentParser(description="静的な検査")
    ap.add_argument("--only", choices=sorted(SECTIONS), help="この節だけ回す")
    args = ap.parse_args()
    worst, counts, failed, empty, total = OK, [], [], [], 0
    for name, section in SECTIONS.items():
        if args.only and name != args.only:
            continue
        try:
            count, problems = section()
        except Exception as exc:  # noqa: BLE001 - 節が回り切れなければ、合格にも不合格にもせず2にする
            count, problems = 0, [f"節が例外で止まった：{type(exc).__name__}: {exc}"]
        for problem in problems[:MAX_DETAILS]:
            print(f"  {name}: {problem}")
        if len(problems) > MAX_DETAILS:
            print(f"  {name}: ほか {len(problems) - MAX_DETAILS} 件")
        code = INCOMPLETE if count == 0 else FAIL if problems else OK
        worst = max(worst, code)
        total += len(problems)
        counts.append(f"{name}={count}")
        if count == 0:
            empty.append(name)
        elif problems:
            failed.append(name)
    summary = " ".join(counts) + f" problems={total}"
    if failed:
        summary += " failed=" + ",".join(failed)
    if empty:
        summary += " empty=" + ",".join(empty)
    return finish("check", worst, summary)


if __name__ == "__main__":
    sys.exit(main())
