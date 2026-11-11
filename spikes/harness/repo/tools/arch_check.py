"""Logic isolation, by reading the source (AST): the pure packages may import only an allow-list.

  python3 tools/arch_check.py            exit 0 clean / 1 violations / 2 nothing was checked

Why source analysis is the primary check (measured in results/isolation_matrix.json): it sees
imports that never execute during a test run (inside a function, behind try/except, in a module
nobody imports yet). The runtime probe (tools/import_probe.py) is the second line: it sees what the
AST cannot (a name built at run time), but only on code paths that actually run.
"""
import ast
import sys

from _common import APP, FAIL, INCOMPLETE, OK, PURE_PACKAGES, finish

STDLIB_OK = {"array", "base64", "bisect", "collections", "dataclasses", "enum", "functools", "hashlib", "heapq", "io",
             "itertools", "json", "math", "os", "pathlib", "struct", "typing", "zlib", "__future__"}
ALLOWED = {"cp_core": STDLIB_OK | {"cp_core"}, "cp_ui": STDLIB_OK | {"cp_core", "cp_ui"}}
BANNED_CALLS = {"__import__": "dynamic import", "eval": "eval", "exec": "exec", "compile": "compile",
                "hash": "built-in hash() is salted per process for str: use cp_core.rng.hash_u64"}
REASON = {"pyxel": "engine", "js": "browser API", "pyodide": "browser API", "cp_app": "adapter layer",
          "random": "use cp_core.rng (streams / hash draws)", "time": "wall clock in logic breaks determinism",
          "datetime": "wall clock in logic breaks determinism", "importlib": "dynamic import"}


def check_file(path, package: str) -> list:
    rel = path.relative_to(APP)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}:{exc.lineno}: syntax error: {exc.msg}"]
    out = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [package] if node.level else [node.module or ""]  # relative import = own package
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            out.append(f"{rel}:{node.lineno}: {node.func.id}() is not allowed in {package} ({BANNED_CALLS[node.func.id]})")
        for name in names:
            top = name.split(".")[0]
            if top not in ALLOWED[package]:
                why = REASON.get(top, "not on the allow-list in tools/arch_check.py")
                out.append(f"{rel}:{node.lineno}: {package} must not import {name!r} ({why})")
    return out


def main() -> int:
    problems, files = [], 0
    for package in PURE_PACKAGES:
        for path in sorted((APP / package).rglob("*.py")):
            files += 1
            problems += check_file(path, package)
    for p in problems:
        print("ARCH:", p)
    if files == 0:
        return finish("arch", INCOMPLETE, "no source files found")
    return finish("arch", FAIL if problems else OK, f"files={files} violations={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
