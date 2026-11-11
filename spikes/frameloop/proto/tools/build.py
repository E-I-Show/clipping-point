"""Packaging: cp_proto/ -> dist/cp_proto.pyxapp -> dist/cp_proto.html, with checks.

  python3 tools/build.py

`pyxel package APP_DIR STARTUP.py` writes <APP_DIR name>.pyxapp into the CURRENT directory and
`pyxel app2html X.pyxapp` writes X.html into the CURRENT directory, so both run with cwd=dist/.
"""
import base64
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "cp_proto"
DIST = ROOT / "dist"
PYXEL = [sys.executable, "-m", "pyxel"]


def run(args, cwd):
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr)
        raise SystemExit(f"FAILED: {' '.join(map(str, args))} -> exit {proc.returncode}")
    return proc.stdout


def main() -> int:
    DIST.mkdir(exist_ok=True)
    out = run([*PYXEL, "package", str(APP), str(APP / "main.py")], DIST)
    pyxapp = DIST / "cp_proto.pyxapp"
    run([*PYXEL, "app2html", pyxapp.name], DIST)
    html = DIST / "cp_proto.html"

    with zipfile.ZipFile(pyxapp) as zf:
        names = zf.namelist()
        infos = zf.infolist()
        startup = zf.read("cp_proto/.pyxapp_startup_script").decode()
        comment = zf.comment.decode()
    print("package stdout (first lines):")
    print("  " + "\n  ".join(out.strip().splitlines()[:8]))
    print(f"zip comment (metadata from main.py header):\n  " + comment.replace("\n", "\n  "))
    print(f"startup marker content: {startup!r}")
    print("archive members:")
    for i in infos:
        print(f"  {i.filename:45s} {i.file_size:6d} -> {i.compress_size:6d}  method={i.compress_type}")

    failures = []
    must_have = [
        "cp_proto/main.py",
        "cp_proto/cp_core/sim.py",
        "cp_proto/cp_app/app.py",
        "cp_proto/data/cars.json",
        "cp_proto/data/track.bin",
        "cp_proto/assets/proto.pyxres",
        "cp_proto/assets/logo.png",
    ]
    must_not = [".gif", ".zip", "__pycache__", "/.hidden_dir/", "/.dotfile", "/.draft.json"]
    for m in must_have:
        if m not in names:
            failures.append(f"missing from archive: {m}")
    for n in names:
        if n == "cp_proto/.pyxapp_startup_script":
            continue
        for bad in must_not:
            if bad in n or n.endswith(bad):
                failures.append(f"should have been excluded: {n}")
    if startup != "main.py":
        failures.append(f"unexpected startup marker {startup!r}")

    text = html.read_text(encoding="utf-8")
    m = re.search(r'base64: "([A-Za-z0-9+/=]+)"', text)
    if not m:
        failures.append("no base64 payload found in html")
    else:
        payload = base64.b64decode(m.group(1))
        same = hashlib.sha256(payload).hexdigest() == hashlib.sha256(pyxapp.read_bytes()).hexdigest()
        print(f"html base64 payload == pyxapp bytes: {same}")
        if not same:
            failures.append("html payload differs from pyxapp")
    head = text[: text.index("base64:")]
    print("html without payload:\n  " + head.replace("\n", "\n  ") + 'base64: "..." });\n  </script>')
    src = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    print(
        f"sizes: app dir (all files, no __pycache__)={src} B, pyxapp={pyxapp.stat().st_size} B, "
        f"html={html.stat().st_size} B (html/pyxapp={html.stat().st_size / pyxapp.stat().st_size:.3f})"
    )
    for f in failures:
        print("BUILD CHECK FAILED:", f)
    print("BUILD_OK" if not failures else "BUILD_FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
