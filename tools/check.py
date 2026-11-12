"""静的な検査。ゲームは1 tickも回さない。

  python3 tools/check.py [--only syntax|arch|rules|canon|areas|data]

  syntax   clipping_point/、tools/、tests/ の全 .py が compile できる
  arch     層の分離（tools/arch_check.py。純Pythonの層のソースをASTで解析し、許可した一覧と照らす）
  rules    規則ファイルの見張り（tools/rules_guard.py）
  canon    正本の見張り（tools/canon_guard.py）
  areas    出荷するコード（clipping_point/）とテスト（tests/）の全ファイルが、分野ごとの組の表
           （tools/verify.py の AREAS）のどれかの分野に当たる
  data     定義データの読み込み検査（clipping_point/cp_core/datadefs.py）。調べる組は、出荷するデータ（clipping_point/data/）と、
           testpacks/ の下の各試験用データを重ねたもの（あるだけ調べる。0個でもよい）。どの組でも、警告を、問題として数える
           （道具 run の --pack も、警告0件を求める。同じ向き）。
           件数は、調べた組の数（読み込み検査まで届いた組。問題があった組も数える）
終了コード：0＝全節が合格、1＝問題のある節がある、2＝調べた件数が0の節か、回り切れなかった節がある。
最後の1行の「節=数」は、その節で調べた件数。
"""
import argparse
import sys
from pathlib import Path

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


SHIPPED_SET = "shipped"  # 出荷するデータだけの組の名。試験用データを重ねた組は、試験用データの名


def data_sets(data_dir, packs_root, tables=None) -> tuple:
    """data の節の中身。返すのは (調べた組の数, 問題の一覧)。置き場、試験用データの根、表の定義は、引数で受ける。

    組は、出荷するデータと、試験用データの根の下の各試験用データを重ねたもの。件数は、読み込み検査まで届いた組の数
    （問題があった組も数える）。警告は、どの組でも、問題として数える（試験用データを重ねた組の警告も。道具 run の
    --pack が、警告0件を求めるのと、同じ向き）。試験用データを重ねた組では、出荷するデータの組で挙げた行（問題も、警告も）を、
    もう1度は挙げない。重ねられない試験用データ（名の字が違う、空の置き場）と、根の直下の、置き場でないファイルは、
    問題にして、組には数えない。
    cp_core と cp_app は、ここでimportする（頭でimportすると、cp_core が無いときに、ほかの節まで回らなくなる）。
    """
    if str(APP) not in sys.path:
        sys.path.append(str(APP))  # 後ろに足す（標準ライブラリの名前を隠さないように）
    from cp_app import data_files
    from cp_core import datadefs

    tables = datadefs.TABLES if tables is None else tables
    sources = data_files.read_sources(data_dir)
    count, problems, shipped_lines, shipped_warnings = 1, [], [], []
    try:
        loaded = datadefs.load_game_data(sources, None, tables)
    except datadefs.DataError as exc:
        shipped_lines = list(exc.problems)
        problems += [f"({SHIPPED_SET}) {line}" for line in shipped_lines]
    else:
        shipped_warnings = list(loaded.warnings)
        problems += [f"({SHIPPED_SET}) warning: {line}" for line in shipped_warnings]
    root = Path(packs_root)
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        where = f"{datadefs.PACKS_DIR}/{path.name}"
        if not path.is_dir():
            problems.append(f"{where}: 試験用データの置き場（ディレクトリ）でない。試験用データは {datadefs.PACKS_DIR}/<名>/ に置く")
            continue
        try:
            pack = data_files.read_pack(path.name, root)
        except ValueError as exc:
            problems.append(f"{where}: 重ねられない：{exc}")
            continue
        count += 1
        try:
            overlaid = datadefs.load_game_data(sources, pack, tables)
        except datadefs.DataError as exc:
            problems += [f"({path.name}) {line}" for line in exc.problems if line not in shipped_lines]
        else:
            problems += [f"({path.name}) warning: {line}" for line in overlaid.warnings if line not in shipped_warnings]
    return count, problems


def data() -> tuple:
    return data_sets(APP / "data", ROOT / "testpacks")


SECTIONS = {"syntax": syntax, "arch": arch, "rules": rules, "canon": canon, "areas": areas, "data": data}


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
