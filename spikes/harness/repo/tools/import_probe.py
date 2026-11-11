"""Logic isolation, by running: import every module of the pure packages in a fresh process and
look at what got loaded.

  python3 tools/import_probe.py            import all, then fail if a forbidden module is in sys.modules
  python3 tools/import_probe.py --block    (comparison only) make forbidden imports raise instead
"""
import importlib
import pkgutil
import sys

from _common import APP, FAIL, INCOMPLETE, OK, PURE_PACKAGES, finish

FORBIDDEN = ("pyxel", "js", "pyodide", "cp_app")


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in FORBIDDEN:
            raise ImportError(f"{name} is forbidden in the pure packages")
        return None


def main() -> int:
    if "--block" in sys.argv:
        sys.meta_path.insert(0, Blocker())
    sys.path.insert(0, str(APP))
    loaded, problems = 0, []
    for package in PURE_PACKAGES:
        try:
            pkg = importlib.import_module(package)
            names = [package] + [m.name for m in pkgutil.walk_packages(pkg.__path__, package + ".")]
            for name in names:
                importlib.import_module(name)
                loaded += 1
        except Exception as exc:  # noqa: BLE001 - any import-time failure is a finding
            problems.append(f"import failed in {package}: {type(exc).__name__}: {exc}")
    for name in FORBIDDEN:
        if name in sys.modules and "--block" not in sys.argv:
            problems.append(f"importing the pure packages loaded {name!r}")
    for p in problems:
        print("IMPORT:", p)
    if loaded == 0 and not problems:
        return finish("import-probe", INCOMPLETE, "no modules imported")
    return finish("import-probe", FAIL if problems else OK, f"modules={loaded} problems={len(problems)}")


if __name__ == "__main__":
    sys.exit(main())
