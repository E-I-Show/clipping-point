"""Shared by every wrapper in tools/. Exit codes: 0 pass, 1 problems found, 2 could not finish
(nothing ran, 0 items, crash, timeout, missing prerequisite). 2 is never reported as a pass."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OUT = ROOT / "out"
PACKS = ROOT / "testpacks"
PURE_PACKAGES = ("cp_core", "cp_ui")
OK, FAIL, INCOMPLETE = 0, 1, 2
WORD = {OK: "OK", FAIL: "FAILED", INCOMPLETE: "INCOMPLETE"}


def use_app_path() -> None:
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))


def child_env(**extra) -> dict:
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("CP_SMOKE"):
            del env[k]
    env.pop("PYTHONUNBUFFERED", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def run(cmd, timeout=300, env=None, cwd=None):
    """-> (returncode or None on timeout, stdout, stderr)"""
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=timeout, env=env or child_env(), cwd=cwd or ROOT)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return None, out, err


def finish(tool: str, code: int, summary: str) -> int:
    print(f"{tool.upper().replace('-', '_')}_{WORD[code]} {summary}")
    return code


def pack_names() -> list:
    return sorted(p.name for p in PACKS.iterdir() if p.is_dir()) if PACKS.is_dir() else []
