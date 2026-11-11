"""検証の道具を決まった順に、1本ずつ回して、表を1つ出す。分野ごとに回す組の表は、ここの AREAS だけに持つ。

  python3 tools/verify.py --all [--selftest]                 全体の検証（check → test → run → run --realtime → export → web-smoke）
  python3 tools/verify.py --touched [--base REV] [--selftest] 変更したファイルから触れた分野を引いて回す
  python3 tools/verify.py --list                             分野ごとの組の表を出す

道具は並列に回さない（out/ と dist/ を取り合う）。1つ落ちても最後まで回し、落ちたものがあれば失敗にする。
回らなかった手順（道具が無い、時間切れ、起動できない）は失敗に数える。--selftest を付けると、最後に selftest-break も回す。
--touched の変更したファイルは、`git diff --name-only <基点>`（基点の既定は HEAD）と、gitの管理に入っていない新しいファイル。
触れた分野は申告ではなく、ファイルから引く。どの分野にも当たらないファイルは「全部」として扱う。
分野「検証の道具と検査の決まり」に触れたときは、--selftest を付けなくても selftest-break を回す。
終了コード：0＝計画した手順が全部0で終わった、1＝落ちた手順・回らなかった手順がある、
2＝何も回していない（変更したファイルが無い、gitが読めない、引数が無い）。
出荷するコードとテストの全ファイルが、どれかの分野に当たることは、tools/check.py の areas の節が見張る。
分野の行は、その分野の最初のファイルを作る区切りで足す（足さないと check が落ちる）。
組の中身は docs/plan.md の「検証の組」の表に合わせる。
"""
import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import rules_guard
from _common import APP, FAIL, INCOMPLETE, OK, OUT, ROOT, TESTS, TOOLS, finish, run, tail

PY = sys.executable
ALL = "ALL"  # テストの絞りでは「全部」、足す手順では「全体の検証」
# 割り切り：全体の検証が3分を超えるまでは、どの分野に触れても全体を回す。超えた時に True にする（docs/plan.md の「検証の組」）。
FOCUS_ENABLED = False
FULL_LIMIT_S = 180  # 全体の検証がこの秒数を超えたら、絞った検証へ切り替える時（計画の決まり。仮の値ではない）
STEP_TIMEOUT_S = 1800
# 手順の名前と、回すコマンド。並びは、全体の検証で回す順。
STEPS = {
    "check": [PY, TOOLS / "check.py"],
    "test": [PY, TOOLS / "test.py"],
    "run": [PY, TOOLS / "run.py"],
    "run-realtime": [PY, TOOLS / "run.py", "--realtime"],
    "export": [PY, TOOLS / "export.py"],
    "web-smoke": [PY, TOOLS / "web_smoke.py"],
}
SELFTEST = "selftest-break"
SELFTEST_CMD = [PY, TOOLS / "selftest_break.py"]
ALWAYS = ("check", "test")  # どの組でも、頭に回す手順
NOT_YET = ("screen-check", "tour", "drive", "race-sim", "audio")  # 後の区切りで足す手順。いまは回さない


@dataclass(frozen=True)
class Area:
    """分野ごとの組。"""

    name: str  # 分野の名前
    paths: tuple  # 当たるファイルの形。規則ファイルの当て先と同じ書き方（** は階層をまたぐ）
    tests: str  # tools/test.py の -k に渡す式。ALL なら全部
    steps: object  # check と test に足す手順の名前の並び。ALL なら全体の検証
    selftest: bool = False  # selftest-break も回すか


# 分野ごとに回す組の表。ここ1か所にだけ持つ。
AREAS = (
    Area(
        "画面（2D）",
        ("clipping_point/cp_ui/**", "clipping_point/cp_app/canvas_pyxel.py", "tests/test_canvas.py", "tests/test_screens.py"),
        "canvas or screens",
        ("run", "screen-check", "tour"),
    ),
    Area(
        "ブラウザ連携",
        ("clipping_point/cp_app/web_bridge.py", "tests/test_web_bridge.py"),
        "web_bridge",
        ("web-smoke",),
    ),
    Area(
        "メインループと世界の状態",
        (
            "clipping_point/main.py", "clipping_point/cp_app/__init__.py", "clipping_point/cp_app/app.py",
            "clipping_point/cp_app/perf.py", "clipping_point/cp_core/__init__.py", "clipping_point/cp_core/fixed_loop.py",
            "clipping_point/cp_core/sim.py", "tests/test_fixed_loop.py", "tests/test_sim.py", "tests/test_perf.py",
        ),
        ALL,
        ALL,
    ),
    Area(
        "検証の道具と検査の決まり",
        (
            "tools/**", "tests/conftest.py", "tests/count_floor.txt", "tests/snapshots/**", "tests/test_arch_guard.py",
            "tests/test_rules_guard.py", "tests/test_canon_guard.py", "tests/test_export_inspect.py", "tests/test_verify.py",
            "tests/test_web_smoke.py", "pytest.ini", "requirements-dev.txt",
        ),
        ALL,
        ALL,
        selftest=True,
    ),
)


def areas_of(path: str, areas=AREAS) -> list:
    """path（根からの相対パス。/ 区切り）が当たる分野の一覧。"""
    return [area for area in areas if any(rules_guard.glob_to_regex(pattern).match(path) for pattern in area.paths)]


def areas_for(files: list, areas=AREAS) -> tuple:
    """変更したファイルから、触れた分野を引く。返すのは (分野の一覧（表の順）, どの分野にも当たらないファイルの一覧)。"""
    touched, unknown = [], []
    for path in files:
        hits = areas_of(path, areas)
        if not hits:
            unknown.append(path)
        touched += [area for area in hits if area not in touched]
    return [area for area in areas if area in touched], unknown


def watched_files(root: Path = ROOT) -> list:
    """出荷するコード（clipping_point/）とテスト（tests/）の全ファイル。根からの相対パス。"""
    root = Path(root)
    files = []
    for base in (root / APP.name, root / TESTS.name):
        files += [p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(files)


def unassigned_files(root: Path = ROOT, areas=AREAS) -> tuple:
    """tools/check.py の areas の節。返すのは (調べたファイルの数, どの分野にも当たらないファイルについての文の一覧)。"""
    files = watched_files(root)
    return len(files), [f"{path}: どの分野にも当たらない（tools/verify.py の AREAS に足す）" for path in files if not areas_of(path, areas)]


def plan_for(areas: list, unknown: list, focused: bool = FOCUS_ENABLED, selftest: bool = False) -> tuple:
    """回す手順を決める。返すのは (手順の一覧 [(名前, コマンド)], "full" か "focused", まだ無い手順の名前の一覧)。

    全体を回すのは、絞らない設定のとき、どの分野にも当たらないファイルがあるとき、「全体の検証」の分野に触れたとき、
    分野が1つも無いとき。
    """
    full = not focused or bool(unknown) or not areas or any(area.steps == ALL for area in areas)
    if full:
        plan = [(name, list(cmd)) for name, cmd in STEPS.items()]
        not_yet = list(NOT_YET)
    else:
        words, wanted = [], []
        for area in areas:
            words += [word for word in area.tests.split(" or ") if word not in words]
            wanted += [step for step in area.steps if step not in wanted]
        plan = [("check", list(STEPS["check"])), ("test", [*STEPS["test"], "-k", " or ".join(words)])]
        plan += [(name, list(cmd)) for name, cmd in STEPS.items() if name in wanted and name not in ALWAYS]
        not_yet = [step for step in wanted if step not in STEPS]
    if selftest or any(area.selftest for area in areas):
        plan.append((SELFTEST, list(SELFTEST_CMD)))
    return plan, "full" if full else "focused", not_yet


def last_line(out: str, err: str) -> str:
    """道具の最後の1行。標準出力に何も無ければ、標準エラーの最後の行。"""
    for text in (out, err):
        lines = [line for line in text.strip().splitlines() if line.strip()]
        if lines:
            return lines[-1]
    return "(no output)"


def run_plan(plan: list, runner=run) -> list:
    """手順を順に、1本ずつ回す。1つ落ちても最後まで回す。返すのは、手順ごとの行の一覧。"""
    rows = []
    for name, cmd in plan:
        started = time.perf_counter()
        try:
            code, out, err = runner(cmd, timeout=STEP_TIMEOUT_S)
        except OSError as exc:  # コマンドを起動できない
            code, out, err = "not-run", "", f"{type(exc).__name__}: {exc}"
        if code is None:
            code = "timeout"
        if code != 0:
            print(f"--- {name}（終了コード {code}）---")
            print(tail(out + "\n" + err, 30))
        rows.append({"step": name, "exit": code, "seconds": round(time.perf_counter() - started, 2), "summary": last_line(out, err)[:300]})
    return rows


def failed_steps(plan: list, rows: list) -> list:
    """落ちた手順と、回らなかった手順の名前。計画にあって行が無い手順も数える。"""
    done = {row["step"]: row["exit"] for row in rows}
    return [name for name, _ in plan if done.get(name, "not-run") != 0]


def changed_files(base: str):
    """変更したファイル。git diff --name-only <基点> と、gitの管理に入っていない新しいファイル。読めなければ None。"""
    code, out, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT)
    if code != 0 or Path(out.strip()).resolve() != ROOT:
        return None  # ここがgitの作業ツリーの根でない（複製の中など）。親のリポジトリの変更を読まない
    code, out, _ = run(["git", "diff", "--name-only", "-z", base, "--"], cwd=ROOT)
    if code != 0:
        return None
    files = [name for name in out.split("\0") if name]
    code, out, _ = run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=ROOT)
    if code != 0:
        return None
    files += [entry[3:] for entry in out.split("\0") if entry.startswith("?? ")]
    return sorted(set(files))


def print_table() -> None:
    print("| 触れた分野 | 当たるファイル | テストの絞り | 足す手順 |")
    print("| --- | --- | --- | --- |")
    for area in AREAS:
        tests = "全部" if area.tests == ALL else f'`-k "{area.tests}"`'
        steps = "全体の検証" if area.steps == ALL else "、".join(area.steps)
        if area.selftest:
            steps += "とselftest-break"
        print(f"| {area.name} | {'、'.join(f'`{p}`' for p in area.paths)} | {tests} | {steps} |")
    print("| （どの分野にも当たらないファイル） | — | 全部 | 全体の検証 |")
    print(f"まだ無い手順（いまは回さない）：{'、'.join(NOT_YET)}")
    print(f"絞った検証：{'有効' if FOCUS_ENABLED else f'無効（全体の検証が {FULL_LIMIT_S} 秒を超えるまでは、どの分野でも全体を回す）'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="検証の道具を決まった順に回す")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="全体の検証")
    mode.add_argument("--touched", action="store_true", help="変更したファイルから触れた分野を引いて回す")
    mode.add_argument("--list", action="store_true", help="分野ごとの組の表を出す")
    ap.add_argument("--base", default="HEAD", metavar="REV", help="--touched の基点（既定は HEAD）")
    ap.add_argument("--selftest", action="store_true", help="最後に selftest-break も回す")
    args = ap.parse_args()
    if args.list:
        print_table()
        return finish("verify", OK, f"mode=list areas={len(AREAS)}")
    if args.all:
        plan, kind, not_yet = plan_for([], [], selftest=args.selftest)
        head = "mode=all"
    elif args.touched:
        files = changed_files(args.base)
        if files is None:
            return finish("verify", INCOMPLETE, f"mode=touched steps=0 reason=git_failed base={args.base}")
        if not files:
            return finish("verify", INCOMPLETE, f"mode=touched steps=0 reason=no_changes base={args.base}")
        areas, unknown = areas_for(files)
        for area in areas:
            hits = [path for path in files if area in areas_of(path)]
            print(f"  verify: 触れた分野「{area.name}」（{len(hits)} ファイル）")
        if unknown:
            print(f"  verify: どの分野にも当たらないファイル（全部として扱う）：{', '.join(unknown[:8])}" + (f" ほか {len(unknown) - 8} 件" if len(unknown) > 8 else ""))
        plan, kind, not_yet = plan_for(areas, unknown, selftest=args.selftest)
        head = f"mode=touched({kind}) base={args.base} files={len(files)} areas={len(areas)} unknown={len(unknown)}"
    else:
        return finish("verify", INCOMPLETE, "steps=0 reason=nothing_asked (--all | --touched | --list)")

    started = time.perf_counter()
    rows = run_plan(plan)
    total = time.perf_counter() - started
    print(f"{'step':15s} {'exit':>8s} {'sec':>7s}  summary")
    for row in rows:
        print(f"{row['step']:15s} {str(row['exit']):>8s} {row['seconds']:7.2f}  {row['summary']}")
    bad = failed_steps(plan, rows)
    (OUT / "verify").mkdir(parents=True, exist_ok=True)
    (OUT / "verify" / "last.json").write_text(
        json.dumps({"head": head, "rows": rows, "failed_steps": bad, "seconds": round(total, 1)}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    selftest_s = sum(row["seconds"] for row in rows if row["step"] == SELFTEST)
    if total - selftest_s > FULL_LIMIT_S and not FOCUS_ENABLED:
        print(f"  verify: 全体の検証が {FULL_LIMIT_S} 秒を超えた（{total - selftest_s:.0f} 秒）。絞った検証へ切り替える時（tools/verify.py の FOCUS_ENABLED）。")
    summary = f"{head} steps={len(plan)} ok={len(plan) - len(bad)} failed={len(bad)}"
    if bad:
        summary += " failed_steps=" + ",".join(bad)
    summary += f" seconds={total:.1f}"
    if not_yet:
        summary += f" not_yet={len(not_yet)}({','.join(not_yet)})"
    if not plan:
        return finish("verify", INCOMPLETE, summary)
    return finish("verify", FAIL if bad else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
