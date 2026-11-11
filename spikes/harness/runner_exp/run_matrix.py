import json, subprocess, sys, re
from pathlib import Path
HERE = Path(__file__).resolve().parent
rows = []
def run(label, cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
    rows.append({"case": cwd.name, "runner": label, "exit": p.returncode, "last_line": tail[0][:110]})
PY = sys.executable
for case in sorted((HERE / "cases").iterdir()):
    run("pytest", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], case)
    run("unittest", [PY, "-m", "unittest", "discover", "-s", ".", "-t", "."], case)
ok = HERE / "cases" / "c_ok"
run("pytest -k nomatch", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "zzz_nomatch"], ok)
run("unittest -k nomatch", [PY, "-m", "unittest", "discover", "-s", ".", "-t", ".", "-k", "zzz_nomatch"], ok)
run("pytest -k 'one or typo'", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "one or twoo"], ok)
run("unittest -k one -k typo", [PY, "-m", "unittest", "discover", "-s", ".", "-t", ".", "-k", "one", "-k", "twoo"], ok)
run("pytest missing path", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "no_such_dir"], ok)
run("unittest missing module", [PY, "-m", "unittest", "no_such_test_module"], ok)
run("unittest discover missing dir", [PY, "-m", "unittest", "discover", "-s", "no_such_dir"], ok)
run("pytest bad -k syntax", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "one or or"], ok)
lf = HERE / "cases" / "c_loadfail"
run("pytest -k one (loadfail in other file)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-k", "one"], lf)
run("pytest --continue-on-collection-errors", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors"], lf)
run("pytest test_b.py only (loadfail file not named)", [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_b.py"], lf)
json.dump(rows, open(HERE.parent / "results" / "runner_matrix.json", "w"), indent=1)
for r in rows:
    print(f"{r['case']:13s} {r['runner']:44s} exit={r['exit']}  {r['last_line']}")
