"""Everything that persists between sessions (pure Python).

  settings      sound / display options and the last selection
  controls      input curves, dead zone, assist, AT/MT, key bindings
  setups        the 6 setting steps per car
  best_laps     best lap per (track, car); the ghost itself is a separate blob 'ghost.<track>.<car>'
  shelf         index of the replay shelf; each replay is a separate blob 'replay.<slot>'

The codec walks the dataclass fields, so a new field is saved automatically. A field that must
NOT be saved has to be listed in NOT_SAVED; tests/test_profile.py fails for a field that is in
neither place and for a NOT_SAVED entry that no longer exists.
"""
import json
from dataclasses import dataclass, field, fields, is_dataclass

from .storage import CorruptError, SaveStore

PROFILE_VERSION = 1
PROFILE_KEY = "profile"
SHELF_SLOTS = 12
SHELF_MAX_BYTES = 3 * 1024 * 1024
SETUP_STEPS = {"gear": 5, "wing": 5, "suspension": 5, "brake_balance": 5, "traction": 5, "steering": 3}

# "Class.field" -> why it is not saved. Screen-side caches and per-session flags only.
NOT_SAVED = {
    "Profile.dirty": "true while there are unsaved changes; meaningless after a load",
    "Profile.load_warnings": "messages from the last load, shown once",
}


@dataclass
class Settings:
    sfx_volume: int = 5
    bgm_volume: int = 5
    hud_visible: bool = True
    speed_unit: str = "KMH"
    last_mode: str = "TIME_ATTACK"
    last_car: str = ""
    last_track: str = ""
    race_laps: int = 3
    ai_level: str = "NORMAL"


@dataclass
class Controls:
    transmission: str = "AT"
    assist: bool = True
    steer_curve: float = 1.6
    steer_deadzone: float = 0.12
    throttle_curve: float = 1.0
    brake_curve: float = 1.3
    speed_steer_limit: float = 0.6
    countersteer_relief: float = 0.5
    bindings: dict = field(default_factory=lambda: {"shift_up": ["KEY_X", "PAD_RB"], "shift_down": ["KEY_Z", "PAD_LB"]})


@dataclass
class CarSetup:
    gear: int = 3
    wing: int = 3
    suspension: int = 3
    brake_balance: int = 3
    traction: int = 3
    steering: int = 2


@dataclass
class BestLap:
    track_id: str = ""
    car_id: str = ""
    lap_ticks: int = 0
    setup: CarSetup = field(default_factory=CarSetup)
    has_ghost: bool = False


@dataclass
class ShelfEntry:
    slot: int = 0
    title: str = ""
    mode: str = "TIME_ATTACK"
    track_id: str = ""
    car_id: str = ""
    ticks: int = 0
    size_bytes: int = 0


@dataclass
class Profile:
    settings: Settings = field(default_factory=Settings)
    controls: Controls = field(default_factory=Controls)
    setups: dict = field(default_factory=dict)  # car_id -> CarSetup
    best_laps: list = field(default_factory=list)  # [BestLap]
    shelf: list = field(default_factory=list)  # [ShelfEntry]
    dirty: bool = False
    load_warnings: list = field(default_factory=list)


# container element types that plain annotations cannot express
ELEMENT_TYPES = {"Profile.setups": CarSetup, "Profile.best_laps": BestLap, "Profile.shelf": ShelfEntry}


class ProfileError(ValueError):
    pass


def to_plain(obj):
    if is_dataclass(obj):
        cls = type(obj).__name__
        return {f.name: to_plain(getattr(obj, f.name)) for f in fields(obj) if f"{cls}.{f.name}" not in NOT_SAVED}
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    return obj


def from_plain(cls, data, where: str = ""):
    """Strict: an unknown key or a missing key is an error (a save from another version must be
    migrated explicitly, never half-read)."""
    if not isinstance(data, dict):
        raise ProfileError(f"{where or cls.__name__}: expected an object")
    names = {f.name: f for f in fields(cls) if f"{cls.__name__}.{f.name}" not in NOT_SAVED}
    unknown = sorted(set(data) - set(names))
    missing = sorted(set(names) - set(data))
    if unknown or missing:
        raise ProfileError(f"{where or cls.__name__}: unknown keys {unknown}, missing keys {missing}")
    obj = cls()
    for name, f in names.items():
        value = data[name]
        current = getattr(obj, name)
        path = f"{cls.__name__}.{name}"
        elem = ELEMENT_TYPES.get(path)
        if is_dataclass(current):
            value = from_plain(type(current), value, path)
        elif elem is not None and isinstance(current, dict):
            value = {k: from_plain(elem, v, f"{path}[{k}]") for k, v in value.items()}
        elif elem is not None and isinstance(current, list):
            value = [from_plain(elem, v, f"{path}[{i}]") for i, v in enumerate(value)]
        elif type(value) is not type(current) and not (isinstance(current, float) and type(value) is int):
            raise ProfileError(f"{path}: expected {type(current).__name__}, got {type(value).__name__}")
        setattr(obj, name, value)
    return obj


def encode(profile: Profile) -> bytes:
    return json.dumps(to_plain(profile), sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode(payload: bytes) -> Profile:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"not JSON: {exc}") from exc
    return from_plain(Profile, data)


def save_profile(store: SaveStore, profile: Profile) -> None:
    store.put(PROFILE_KEY, encode(profile), PROFILE_VERSION)
    profile.dirty = False


def load_profile(store: SaveStore) -> Profile:
    """Never raises for bad stored data: the broken blob is kept as 'profile.bad', the player gets
    defaults and a warning. (Silently overwriting a save the game could not read loses data.)"""
    try:
        got = store.get(PROFILE_KEY)
        if got is None:
            return Profile()
        version, payload = got
        if version != PROFILE_VERSION:
            raise ProfileError(f"version {version} (this build reads {PROFILE_VERSION}; add a migration)")
        return decode(payload)
    except (CorruptError, ProfileError) as exc:
        store.quarantine(PROFILE_KEY)
        fresh = Profile()
        fresh.load_warnings.append(f"SAVE DATA UNREADABLE: {exc}")
        return fresh
