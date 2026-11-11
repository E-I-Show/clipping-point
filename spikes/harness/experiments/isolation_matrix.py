"""Which isolation check catches which way of pulling pyxel into cp_core? (Q1)"""
import json, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parent / "repo"
MUTANTS = {
    # name: (file relative to app/, text appended)
    "m01_top_level_import": ("cp_core/rng.py", "\nimport pyxel\n"),
    "m02_from_import": ("cp_core/rng.py", "\nfrom pyxel import btn\n"),
    "m03_lazy_import_in_uncalled_function": ("cp_core/rng.py", "\ndef debug_draw():\n    import pyxel\n    pyxel.cls(0)\n"),
    "m04_importlib_top_level": ("cp_core/rng.py", "\nimport importlib\npx = importlib.import_module('pyxel')\n"),
    "m05_dunder_import_built_name_top_level": ("cp_core/rng.py", "\npx = __import__('py' + 'xel')\n"),
    "m06_via_adapter_package": ("cp_core/rng.py", "\nfrom cp_app.canvas_pyxel import PyxelCanvas\n"),
    "m07_guarded_optional_import": ("cp_core/rng.py", "\ntry:\n    import pyxel\nexcept ImportError:\n    pyxel = None\n"),
    "m08_new_module_nobody_imports": ("cp_core/debug_overlay.py", "import pyxel\n"),
    "m09_exec_string": ("cp_core/rng.py", "\nexec('import pyxel')\n"),
    "m10_getattr_builtins_in_uncalled_function": ("cp_core/rng.py", "\ndef sneak():\n    import builtins\n    return getattr(builtins, '__imp' + 'ort__')('pyxel')\n"),
    "m11_ui_imports_adapter": ("cp_ui/screens.py", "\nfrom cp_app import canvas_pyxel\n"),
    "m12_stdlib_random": ("cp_core/world.py", "\nimport random\n"),
    "m00_control_no_change": ("cp_core/rng.py", "\n"),
}
METHODS = {"ast": ["tools/arch_check.py"], "runtime_sys_modules": ["tools/import_probe.py"], "runtime_block": ["tools/import_probe.py", "--block"]}
rows = []
for name, (rel, text) in MUTANTS.items():
    with tempfile.TemporaryDirectory(dir=HERE.parent / "results") as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(REPO, work, ignore=shutil.ignore_patterns("out", "dist", "__pycache__", ".saves"))
        target = work / "app" / rel
        target.write_text((target.read_text() if target.exists() else "") + text)
        row = {"mutant": name}
        for method, cmd in METHODS.items():
            p = subprocess.run([sys.executable, *cmd], cwd=work, capture_output=True, text=True)
            row[method] = "caught" if p.returncode == 1 else ("MISSED" if p.returncode == 0 else f"exit{p.returncode}")
        rows.append(row)
        print(f"{name:44s} ast={row['ast']:7s} sys_modules={row['runtime_sys_modules']:7s} block={row['runtime_block']}")
json.dump(rows, open(HERE.parent / "results" / "isolation_matrix.json", "w"), indent=1)
