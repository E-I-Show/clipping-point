"""Snapshot helper. A missing snapshot is a FAILURE (never written silently): otherwise the first
run after a deleted file compares a value with itself and passes."""
import json
from pathlib import Path

SNAP_DIR = Path(__file__).resolve().parent / "snapshots"


def check_snapshot(request, name: str, value) -> None:
    path = SNAP_DIR / f"{name}.json"
    text = json.dumps(value, indent=1, sort_keys=True) + "\n"
    if request.config.getoption("--update-snapshots"):
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"snapshot {path.name} is missing. Create it with: tools/test.py --update-snapshots (own commit)"
    old = json.loads(path.read_text(encoding="utf-8"))
    if old != value:
        diff = _diff(old, value)
        raise AssertionError(f"snapshot {name} changed in {len(diff)} place(s):\n  " + "\n  ".join(diff[:20]))


def _diff(a, b, where=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{where}/{k}: added {b[k]!r}")
            elif k not in b:
                out.append(f"{where}/{k}: removed")
            else:
                out += _diff(a[k], b[k], f"{where}/{k}")
        return out
    return [] if a == b else [f"{where}: {a!r} -> {b!r}"]
