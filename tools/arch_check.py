"""層の分離の検査。純Pythonの層（cp_core、cp_ui）のソースをASTで解析し、許可した一覧と照らす。

  python3 tools/arch_check.py     0＝違反なし、1＝違反あり、2＝調べるファイルが無い

実行時にimportを見張る方式には頼らない。関数の中のimport、try/except の陰のimport、
まだ誰も読み込んでいないモジュールのimportは、実行しないと見えないため（試作の実測）。
ふだんは tools/check.py の arch の節から呼ぶ。
"""
import ast
import sys
from pathlib import Path

from _common import APP, FAIL, INCOMPLETE, OK, PURE_PACKAGES, finish

# 純Pythonの層で使ってよい標準ライブラリ。ここに無いimportは全部違反にする。
# 置くのは、計算とデータの形のためのものだけ。ファイル、環境、時刻、乱数に届くもの（os、pathlib、io など）は入れない。
# 足すときは、足した行の注に、使う所と理由を書く。os を足すときは、使ってよい属性も縛る（os.urandom や os.environ に届くため）。
STDLIB_ALLOWED = frozenset({
    "__future__", "array", "base64", "bisect", "collections", "dataclasses", "enum", "functools", "hashlib",
    "heapq", "itertools", "json", "math", "struct", "typing", "zlib",
})
# 層ごとに、呼んでよい自前のパッケージ。依存は一方向（cp_app → cp_ui → cp_core）。
LAYER_ALLOWED = {
    "cp_core": frozenset({"cp_core"}),
    "cp_ui": frozenset({"cp_core", "cp_ui"}),
}
# よくある違反に添える理由。
REASONS = {
    "pyxel": "Pyxelに触れるのは cp_app だけ",
    "js": "ブラウザに触れるのは cp_app だけ",
    "pyodide": "ブラウザに触れるのは cp_app だけ",
    "cp_app": "依存は一方向。上の層を呼ばない",
    "cp_ui": "依存は一方向。上の層を呼ばない",
    "random": "標準の乱数は使わない。同じ入力から同じ結果を出すため",
    "time": "実時間を読まない。同じ入力から同じ結果を出すため",
    "datetime": "実時間を読まない。同じ入力から同じ結果を出すため",
    "importlib": "動的なimportは使わない",
    "builtins": "動的なimportの抜け道になる",
    "sys": "読み込み済みのモジュールへの抜け道になる",
    "os": "ファイル、環境、乱数（os.urandom）に届く。ファイルの保存先は cp_app/storage_file.py に置いた（純Pythonの層では使わない）",
    "pathlib": "ファイルに届く。定義データを読む区切りで、理由を書いて足す",
    "io": "ファイルに届く。要る区切りで、理由を書いて足す",
}
# 使ってはいけない名前。呼び出しだけでなく、名前として読む所も違反にする（別名に入れて呼ぶ形を拾うため）。
BANNED_NAMES = {
    "__import__": "動的なimportは使わない",
    "__builtins__": "動的なimportの抜け道になる",
    "eval": "文字列の実行は使わない",
    "exec": "文字列の実行は使わない",
    "compile": "文字列の実行は使わない",
    "hash": "組み込みの hash() は、文字列に対してプロセスごとに違う値を返す",
}


def check_source(source: str, package: str, where: str = "<source>", parents: tuple = ()) -> list:
    """ソースの文字列を、package（"cp_core" か "cp_ui"）の決まりで調べ、違反の一覧を返す。

    where は報告に付けるファイル名。parents は package から下のパッケージ名の並び
    （cp_core/vehicle/model.py なら ("vehicle",)）。相対importが層の外へ出ないかを見るのに使う。
    """
    if package not in LAYER_ALLOWED:
        raise ValueError(f"unknown pure package: {package!r}")
    try:
        tree = ast.parse(source, filename=where)
    except SyntaxError as exc:
        return [f"{where}:{exc.lineno}: 構文エラー：{exc.msg}"]
    allowed = STDLIB_ALLOWED | LAYER_ALLOWED[package]
    found = []  # (行, 文)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                names = [node.module or ""]
            elif node.level - 1 > len(parents):
                found.append((node.lineno, f"相対importが {package} の外へ出ている"))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in BANNED_NAMES:
            found.append((node.lineno, f"{package} で {node.id} は使えない（{BANNED_NAMES[node.id]}）"))
        for name in names:
            top = name.split(".")[0]
            if top not in allowed:
                why = REASONS.get(top, "tools/arch_check.py の許可した一覧に無い")
                found.append((node.lineno, f"{package} は {name!r} をimportできない（{why}）"))
    return [f"{where}:{line}: {text}" for line, text in sorted(found)]


def check_tree(app_dir: Path) -> tuple:
    """app_dir の下の純Pythonの層を全部調べる。返すのは (調べたファイルの数, 違反の一覧)。"""
    files, problems = 0, []
    for package in PURE_PACKAGES:
        base = Path(app_dir) / package
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(base)
            if "__pycache__" in rel.parts:
                continue
            files += 1
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                problems.append(f"{package}/{rel.as_posix()}: UTF-8で読めない：{exc}")
                continue
            problems += check_source(source, package, f"{package}/{rel.as_posix()}", rel.parent.parts)
    return files, problems


def main() -> int:
    files, problems = check_tree(APP)
    for problem in problems:
        print(f"  arch: {problem}")
    if files == 0:
        return finish("arch", INCOMPLETE, "files=0 violations=0")
    return finish("arch", FAIL if problems else OK, f"files={files} violations={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
