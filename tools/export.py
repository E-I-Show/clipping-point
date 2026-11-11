"""配布物を作る。clipping_point/ → dist/clipping_point.pyxapp → dist/clipping_point.html。

  python3 tools/export.py

dist/ を作業場所にして `pyxel package` と `pyxel app2html` を回し、できた中身と大きさを検査する。
終了コード：0＝合格、1＝検査で問題あり、2＝ビルドの道具が回り切れない。
検査：要るファイル（main.py）がある。入ってはいけないもの（テスト、文書、道具、__pycache__）が無い。
知らない種類のファイルが無い。HTML内のデータが .pyxapp と一致する。HTMLが上限（tools/budgets.json）の内。
"""
import base64
import fnmatch
import re
import sys
import zipfile

from _common import APP, DIST, FAIL, INCOMPLETE, OK, finish, load_budgets, run, tail

NAME = APP.name  # pyxel package は、対象ディレクトリの名前を .pyxapp の名前にする
MUST_HAVE = (f"{NAME}/main.py",)  # 入口。直下に無いとパッケージをimportできない
# 入ってはいけないディレクトリ名（パスのどこかにあれば不合格）。
FORBIDDEN_DIRS = frozenset({"tests", "testpacks", "docs", "tools", "spikes", "out", "dist", "__pycache__"})
# 入ってはいけないファイル名の形（テスト、文書、キャッシュ）。
FORBIDDEN_FILES = ("test_*.py", "*_test.py", "conftest.py", "*.md", "*.pyc", "count_floor.txt")
# 出荷物に入ってよいファイルの種類。初期版は画像やモデルのファイルを持たない。足すときはここに足す。
SHIP_SUFFIXES = (".py", ".json")
STARTUP_MARKER = ".pyxapp_startup_script"  # pyxel package が自分で足す、入口の名前を書いたファイル


def inspect_names(names: list) -> list:
    """アーカイブの中のパスの一覧を調べ、問題の一覧を返す。"""
    problems = []
    for must in MUST_HAVE:
        if must not in names:
            problems.append(("missing", f"要るファイルが入っていない：{must}"))
    for name in names:
        parts = name.split("/")
        base = parts[-1]
        if parts[0] != NAME:
            problems.append(("outside", f"{NAME}/ の外のパスが入っている：{name}"))
        elif len(parts) == 2 and base == STARTUP_MARKER:
            continue
        elif FORBIDDEN_DIRS & set(parts[1:-1]) or any(fnmatch.fnmatch(base, pattern) for pattern in FORBIDDEN_FILES):
            problems.append(("forbidden", f"入ってはいけないものが入っている：{name}"))
        elif not base.endswith(SHIP_SUFFIXES):
            problems.append(("unknown_type", f"知らない種類のファイルが入っている：{name}"))
    return problems


def main() -> int:
    budgets = load_budgets()
    DIST.mkdir(parents=True, exist_ok=True)
    pyxapp, html = DIST / f"{NAME}.pyxapp", DIST / f"{NAME}.html"
    pyxapp.unlink(missing_ok=True)
    html.unlink(missing_ok=True)
    steps = (
        ("package", [sys.executable, "-m", "pyxel", "package", APP, APP / "main.py"]),
        ("app2html", [sys.executable, "-m", "pyxel", "app2html", pyxapp.name]),
    )
    for step, cmd in steps:
        code, out, err = run(cmd, cwd=DIST)  # どちらも、作業ディレクトリに出力を書く
        if code != 0:
            print(tail(out + "\n" + err))
            return finish("export", INCOMPLETE, f"reason=pyxel_{step}_failed exit={code}")
    if not pyxapp.is_file() or not html.is_file():
        return finish("export", INCOMPLETE, "reason=output_missing")

    with zipfile.ZipFile(pyxapp) as zf:
        names = zf.namelist()
    problems = inspect_names(names)
    text = html.read_text(encoding="utf-8")
    payload = re.search(r'base64: "([A-Za-z0-9+/=]+)"', text)
    if not payload or base64.b64decode(payload.group(1)) != pyxapp.read_bytes():
        problems.append(("payload", "HTML内のデータが .pyxapp と一致しない"))
    html_bytes, pyxapp_bytes = html.stat().st_size, pyxapp.stat().st_size
    limit = budgets["html_max_bytes"]
    if html_bytes > limit:
        problems.append(("size", f"HTMLが {html_bytes} バイト（上限 {limit} バイト）"))
    for _, message in problems:
        print(f"  export: {message}")
    summary = (
        f"files={len(names)} pyxapp_bytes={pyxapp_bytes} html_bytes={html_bytes} html_max_bytes={limit} "
        f"checks=6 problems={len(problems)}"
    )
    if problems:
        summary += " failed=" + ",".join(sorted({kind for kind, _ in problems}))
    return finish("export", FAIL if problems else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
