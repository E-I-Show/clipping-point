"""Definition data (cars, tracks, assists, ai, audio): load + validate at load time. Pure Python.

Rules (every problem is collected, the error lists them all):
  * unknown key              -> error  (a typo must not become a silently ignored value)
  * missing required key     -> error
  * wrong type / out of range / not in enum -> error   (bool is not accepted where int is asked)
  * reference to an id that does not exist  -> error
  * duplicate id             -> error
  * text shown on screen must be printable ASCII and fit its width budget
Warnings (must stay empty for the shipped data; a test watches it):
  * a definition nobody references (audio / ai / assists)
Keys starting with "_" (e.g. "_note", "_placeholder") are free-form notes and are ignored.

Test data packs: a directory with the same file names. Entries are merged by id on top of the base
data (same id = replace, new id = append) and the merged result is validated again.
"""
import json
from pathlib import Path


class DataError(ValueError):
    def __init__(self, problems: list) -> None:
        super().__init__(f"{len(problems)} data problem(s):\n  " + "\n  ".join(problems))
        self.problems = problems


class Int:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def check(self, v):
        if type(v) is not int:
            return f"expected int, got {type(v).__name__}"
        if not self.lo <= v <= self.hi:
            return f"{v} outside {self.lo}..{self.hi}"


class Num:
    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def check(self, v):
        if type(v) not in (int, float):
            return f"expected number, got {type(v).__name__}"
        if not self.lo <= v <= self.hi:
            return f"{v} outside {self.lo}..{self.hi}"


class Bool:
    def check(self, v):
        if type(v) is not bool:
            return f"expected bool, got {type(v).__name__}"


class Enum:
    def __init__(self, *choices):
        self.choices = choices

    def check(self, v):
        if v not in self.choices or type(v) is not str:
            return f"{v!r} not in {list(self.choices)}"


class Ident:
    def check(self, v):
        if type(v) is not str or not v or not all(c.islower() or c.isdigit() or c == "_" for c in v) or not v.isascii():
            return f"{v!r} is not an id (lowercase ASCII, digits, _)"


class Label:
    """Text drawn with the built-in 4x6 font: printable ASCII, at most max_len characters."""

    def __init__(self, max_len):
        self.max_len = max_len

    def check(self, v):
        if type(v) is not str or not v:
            return f"expected non-empty text, got {v!r}"
        if not all(32 <= ord(c) <= 126 for c in v):
            return f"{v!r} has characters outside printable ASCII"
        if len(v) > self.max_len:
            return f"{v!r} is {len(v)} characters, budget is {self.max_len}"


class Ref:
    def __init__(self, table):
        self.table = table

    def check(self, v):
        if type(v) is not str:
            return f"expected an id of {self.table}, got {type(v).__name__}"


class ListOf:
    def __init__(self, item, min_len=1, max_len=64):
        self.item, self.min_len, self.max_len = item, min_len, max_len

    def check(self, v):
        if type(v) is not list or not self.min_len <= len(v) <= self.max_len:
            return f"expected a list of {self.min_len}..{self.max_len} items"
        for i, x in enumerate(v):
            msg = self.item.check(x)
            if msg:
                return f"[{i}] {msg}"


class Opt:
    def __init__(self, inner):
        self.inner = inner


CAR_NAME_MAX = 14  # width budget of the car name field on the 320x240 screens
TRACK_NAME_MAX = 14

SCHEMA = {
    "audio": {"id": Ident(), "kind": Enum("engine", "sfx", "bgm"), "channel": Int(0, 3), "base_hz": Opt(Num(20, 2000))},
    "assists": {
        "id": Ident(),
        "steer_curve": Num(1.0, 3.0),
        "throttle_curve": Num(0.5, 3.0),
        "brake_curve": Num(0.5, 3.0),
        "speed_steer_limit": Num(0.1, 1.0),
        "countersteer_relief": Num(0.0, 1.0),
    },
    "ai": {"id": Ident(), "level": Enum("EASY", "NORMAL", "HARD"), "pace": Num(0.5, 1.05), "brake_margin_m": Num(0.0, 40.0)},
    "cars": {
        "id": Ident(),
        "name": Label(CAR_NAME_MAX),
        "layout": Enum("FF", "FR", "MR", "4WD"),
        "car_class": Enum("A", "B"),
        "power_ps": Int(40, 600),
        "mass_kg": Int(500, 2500),
        "turbo": Bool(),
        "engine_sound": Ref("audio"),
        "default_assist": Ref("assists"),
    },
    "tracks": {
        "id": Ident(),
        "name": Label(TRACK_NAME_MAX),
        "length_m": Num(300, 10000),
        "corners": Int(1, 40),
        "lap_choices": ListOf(Int(1, 99), 1, 5),
        "ai_profiles": ListOf(Ref("ai"), 1, 3),
        "bgm": Opt(Ref("audio")),
    },
}
LOAD_ORDER = ("audio", "assists", "ai", "cars", "tracks")
REFERENCED_TABLES = ("audio", "assists", "ai")


class GameData:
    def __init__(self, tables: dict, warnings: list, packs: list) -> None:
        self.tables = tables  # table -> {id: entry}
        self.warnings = warnings
        self.packs = packs

    @property
    def save_namespace(self) -> str:
        """Saves made while a test pack is loaded go to their own namespace."""
        return "main" if not self.packs else "pack_" + "_".join(self.packs)

    def table(self, name: str) -> dict:
        return self.tables[name]


def _read(path: Path, table: str, problems: list):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{path.name}: cannot read ({exc})")
        return []
    extra = sorted(k for k in doc if k != table and not k.startswith("_")) if isinstance(doc, dict) else None
    if extra is None or extra or not isinstance(doc.get(table), list):
        problems.append(f"{path.name}: top level must be {{\"{table}\": [...]}} (unexpected: {extra})")
        return []
    return doc[table]


def load_game_data(base_dir, packs: tuple = (), packs_root=None) -> GameData:
    base_dir = Path(base_dir)
    problems: list = []
    tables: dict = {}
    for table in LOAD_ORDER:
        entries = {}
        sources = [base_dir / f"{table}.json"]
        for pack in packs:
            p = Path(packs_root) / pack / f"{table}.json"
            if p.exists():
                sources.append(p)
        for n, src in enumerate(sources):
            seen_here = set()
            for i, entry in enumerate(_read(src, table, problems)):
                where = f"{src.parent.name}/{src.name}:{table}[{i}]"
                if not isinstance(entry, dict) or type(entry.get("id")) is not str:
                    problems.append(f"{where}: entry needs a string 'id'")
                    continue
                if entry["id"] in seen_here or (n == 0 and entry["id"] in entries):
                    problems.append(f"{where}: duplicate id {entry['id']!r}")
                seen_here.add(entry["id"])
                entries[entry["id"]] = (where, entry)  # a pack replaces a base entry with the same id
        tables[table] = entries
        if not entries:
            problems.append(f"{table}.json: no entries")
    referenced = {t: set() for t in REFERENCED_TABLES}
    for table in LOAD_ORDER:
        spec = SCHEMA[table]
        for where, entry in tables[table].values():
            for key in entry:
                if key not in spec and not key.startswith("_"):
                    problems.append(f"{where}.{key}: unknown key")
            for key, rule in spec.items():
                optional = isinstance(rule, Opt)
                rule = rule.inner if optional else rule
                if key not in entry:
                    if not optional:
                        problems.append(f"{where}.{key}: missing")
                    continue
                msg = rule.check(entry[key])
                if msg:
                    problems.append(f"{where}.{key}: {msg}")
                    continue
                refs = []
                if isinstance(rule, Ref):
                    refs = [(rule.table, entry[key])]
                elif isinstance(rule, ListOf) and isinstance(rule.item, Ref):
                    refs = [(rule.item.table, v) for v in entry[key]]
                for target, ref_id in refs:
                    if ref_id not in tables[target]:
                        problems.append(f"{where}.{key}: no {target} with id {ref_id!r}")
                    else:
                        referenced[target].add(ref_id)
    if problems:
        raise DataError(problems)
    warnings = [
        f"{t}.{i}: defined but never referenced" for t in REFERENCED_TABLES for i in sorted(set(tables[t]) - referenced[t])
    ]
    return GameData({t: {i: e for i, (_, e) in v.items()} for t, v in tables.items()}, warnings, list(packs))
