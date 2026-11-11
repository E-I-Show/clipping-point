"""Save -> load must give back every field. Fields that are not saved are listed, and the list
of saved fields itself is pinned so that a new field cannot slip into (or out of) the save format."""
from dataclasses import fields, is_dataclass

from cp_core import profile as P
from cp_core.storage import FileBackend, MemoryBackend, SaveStore
from snapshot import check_snapshot

CLASSES = [P.Settings, P.Controls, P.CarSetup, P.BestLap, P.ShelfEntry, P.Profile]


def changed(value, path):
    """A value of the same type that differs from the default (so equality cannot be 0 == 0)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.125
    if isinstance(value, str):
        return value + "_X"
    if is_dataclass(value):
        return fill(value)
    if isinstance(value, dict):
        elem = P.ELEMENT_TYPES.get(path)
        return {"kazane_rs": fill(elem()), "arashi_4t": fill(elem())} if elem else {**value, "extra_key": ["KEY_Q"]}
    if isinstance(value, list):
        elem = P.ELEMENT_TYPES.get(path)
        return [fill(elem()), elem()] if elem else [*value, "sample"]
    raise TypeError(f"{path}: no sample for type {type(value).__name__}; teach tests/test_profile.py")


def fill(obj):
    for f in fields(obj):
        setattr(obj, f.name, changed(getattr(obj, f.name), f"{type(obj).__name__}.{f.name}"))
    return obj


def saved_paths():
    return sorted(f"{c.__name__}.{f.name}:{type(getattr(c(), f.name)).__name__}" for c in CLASSES for f in fields(c)
                  if f"{c.__name__}.{f.name}" not in P.NOT_SAVED)


def test_profile_round_trip_keeps_every_field(tmp_path):
    for backend in (MemoryBackend(), FileBackend(tmp_path / "s")):
        store = SaveStore(backend)
        full = fill(P.Profile())
        default = P.Profile()
        for c in CLASSES:  # the sample really differs from the default in every saved field
            a, b = fill(c()), c()
            for f in fields(c):
                assert getattr(a, f.name) != getattr(b, f.name), f"{c.__name__}.{f.name} sample equals default"
        P.save_profile(store, full)
        back = P.load_profile(store)
        assert back.load_warnings == []
        for f in fields(P.Profile):
            if f"Profile.{f.name}" in P.NOT_SAVED:
                assert getattr(back, f.name) == getattr(default, f.name), f"{f.name} must come back as default"
            else:
                assert getattr(back, f.name) == getattr(full, f.name), f"{f.name} was not restored"
        assert P.encode(back) == P.encode(full)


def test_profile_not_saved_list_names_real_fields():
    real = {f"{c.__name__}.{f.name}" for c in CLASSES for f in fields(c)}
    assert set(P.NOT_SAVED) <= real, f"stale NOT_SAVED entries: {sorted(set(P.NOT_SAVED) - real)}"
    assert all(len(reason) > 10 for reason in P.NOT_SAVED.values()), "every NOT_SAVED entry needs its reason"


def test_profile_saved_field_list_is_pinned(request):
    """Fails when a field is added, removed, renamed or retyped. Then decide: bump PROFILE_VERSION
    and write a migration, or list the field in NOT_SAVED - and only then update the snapshot."""
    check_snapshot(request, "profile_schema", {"version": P.PROFILE_VERSION, "fields": saved_paths()})


def test_profile_unreadable_save_is_kept_aside_not_overwritten():
    backend = MemoryBackend()
    store = SaveStore(backend)
    P.save_profile(store, fill(P.Profile()))
    blob = bytearray(backend.items["main.profile"])
    blob[20] ^= 0xFF
    backend.items["main.profile"] = bytes(blob)
    p = P.load_profile(store)
    assert p.load_warnings and p.settings == P.Settings()
    assert backend.items["main.profile.bad"] == bytes(blob) and "main.profile" not in backend.items
    # unknown key / other version are refused the same way (no half-read saves)
    store.put("profile", b'{"settings":{}}', P.PROFILE_VERSION)
    assert P.load_profile(store).load_warnings
    store.put("profile", P.encode(P.Profile()), P.PROFILE_VERSION + 1)
    assert "version" in P.load_profile(store).load_warnings[0]
