"""保存する項目（cp_core.profile）のテスト。設定の往復、保存しない項目の一覧、保存する項目の一覧の写し、読み込みの場合分け、移行の仕組み。

保存して読み直すと、全部の項目が一致すること。見本は、全部の項目が既定値と違う（0 と 0 を比べない）。
項目を足す、消す、型を変えると、保存する項目の一覧の写し（tests/snapshots/profile_schema.json）のテストが落ちる。
実在する古い形式バージョンは、まだ無い。移行の仕組みは、作り物の、古い形式バージョンの見本で確かめる。
"""
import base64
import dataclasses
import json

import pytest

import fingerprint
from conftest import ROOT
from cp_app.storage_file import FileBackend
from cp_app.storage_web import WebStorageBackend
from cp_core import profile, storage
from cp_core.profile import (
    NOT_SAVED,
    SELFCHECK_SETTINGS,
    SETTINGS_KEY,
    SETTINGS_VERSION,
    Loaded,
    ProfileError,
    Settings,
    decode,
    encode,
    load_settings,
    save_settings,
    schema,
    selfcheck,
)
from cp_core.storage import MemoryBackend, NewerVersionError, SaveStore, StorageError, StorageFull, wrap
from test_storage_web import FakeJs, FakeStorage

MAIN_KEY = "main.settings"  # 保存先での、設定の鍵
BAD_KEY = "main.settings.bad"  # 退避の鍵
DEFAULTS = Settings()


def backends(tmp_path) -> list:
    """3つの保存先（メモリ、ファイル、localStorage の偽物）。"""
    return [MemoryBackend(), FileBackend(tmp_path / "saves"), WebStorageBackend(FakeJs(FakeStorage()))]


def raw(payload: dict | bytes, version: int = SETTINGS_VERSION) -> bytes:
    """封筒つきの値。payload が辞書なら、JSONにする。"""
    body = payload if isinstance(payload, bytes) else json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return wrap(body, version)


def plain(**changes) -> dict:
    """往復の見本の、保存の本体の辞書。changes で、項目を書き換える。"""
    return {**profile.to_plain(SELFCHECK_SETTINGS), **changes}


class RefusingBackend(MemoryBackend):
    """決めた鍵への書き込みを断る保存先。"""

    def __init__(self, refuse: str, error=StorageFull) -> None:
        super().__init__()
        self.refuse, self.error, self.refused = refuse, error, 0

    def write(self, key, data) -> None:
        if key == self.refuse:
            self.refused += 1
            raise self.error(key)
        super().write(key, data)


class UnreadableBackend(MemoryBackend):
    """読むと StorageError になる保存先。書き込みと削除を数える。"""

    def __init__(self) -> None:
        super().__init__()
        self.changes = 0

    def read(self, key):
        raise StorageError(f"{key}: cannot be read")

    def write(self, key, data) -> None:
        self.changes += 1

    def delete(self, key) -> None:
        self.changes += 1


# --- 往復 ---
def test_profile_selfcheck_sample_differs_from_the_default_in_every_item():
    # 見本が既定値と同じ項目は、往復で落ちても拾えない。
    for field in dataclasses.fields(Settings):
        assert getattr(SELFCHECK_SETTINGS, field.name) != getattr(DEFAULTS, field.name), f"{field.name}: 見本が既定値と同じ"
        assert type(getattr(SELFCHECK_SETTINGS, field.name)) is type(getattr(DEFAULTS, field.name))


def test_profile_round_trip_keeps_every_item_on_every_backend(tmp_path):
    for backend in backends(tmp_path):
        store = SaveStore(backend)
        assert load_settings(store) == Loaded(DEFAULTS, "", True)  # まだ無い
        save_settings(store, SELFCHECK_SETTINGS)
        loaded = load_settings(store)
        assert loaded == Loaded(SELFCHECK_SETTINGS, "", True), type(backend).__name__
        for field in dataclasses.fields(Settings):
            name = f"Settings.{field.name}"
            value, want = getattr(loaded.settings, field.name), getattr(SELFCHECK_SETTINGS if name not in NOT_SAVED else DEFAULTS, field.name)
            assert value == want and type(value) is type(want), name
        assert encode(loaded.settings) == encode(SELFCHECK_SETTINGS)
        assert store.get(SETTINGS_KEY) == (SETTINGS_VERSION, encode(SELFCHECK_SETTINGS))
        assert store.keys() == [SETTINGS_KEY]


def test_profile_default_settings_round_trip_too():
    store = SaveStore(MemoryBackend())
    save_settings(store, DEFAULTS)
    assert load_settings(store) == Loaded(DEFAULTS, "", True)


def test_profile_payload_is_compact_json_with_sorted_keys():
    payload = encode(SELFCHECK_SETTINGS)
    assert payload == b'{"assist":false,"bgm_volume":8,"race_serial":12,"sfx_volume":3,"transmission":"MT","view":"bumper"}'
    assert json.loads(payload.decode("utf-8")) == profile.to_plain(SELFCHECK_SETTINGS)
    assert decode(payload) == SELFCHECK_SETTINGS


# --- 保存しない項目の一覧 ---
def test_profile_not_saved_list_names_real_items_with_a_reason():
    real = {f"{cls.__name__}.{field.name}" for cls in profile.SAVED_CLASSES for field in dataclasses.fields(cls)}
    assert set(NOT_SAVED) <= real, f"もう無い項目が、保存しない項目の一覧に残っている：{sorted(set(NOT_SAVED) - real)}"
    assert all(type(reason) is str and len(reason) > 10 for reason in NOT_SAVED.values()), "保存しない項目には、理由を書く"


def test_profile_every_item_is_either_saved_or_listed_as_not_saved():
    saved = set(schema()["fields"])
    for cls in profile.SAVED_CLASSES:
        for field in dataclasses.fields(cls):
            name = f"{cls.__name__}.{field.name}"
            assert (name in saved) != (name in NOT_SAVED), name
    assert set(profile.to_plain(DEFAULTS)) == {name.split(".", 1)[1] for name in saved}


def test_profile_an_item_listed_as_not_saved_stays_out_of_the_payload(monkeypatch):
    monkeypatch.setitem(profile.NOT_SAVED, "Settings.view", "planted: shown in this test only")
    assert "view" not in profile.to_plain(SELFCHECK_SETTINGS)
    assert "Settings.view" not in schema()["fields"]
    store = SaveStore(MemoryBackend())
    save_settings(store, SELFCHECK_SETTINGS)
    loaded = load_settings(store)
    assert loaded.notice == "" and loaded.settings.view == DEFAULTS.view  # 保存しない項目は、既定値で戻る
    assert loaded.settings == dataclasses.replace(SELFCHECK_SETTINGS, view=DEFAULTS.view)


# --- 保存する項目の一覧の写し ---
def test_profile_schema_lists_the_saved_items_and_their_types():
    assert schema() == {
        "version": 1,
        "fields": {
            "Settings.sfx_volume": "int", "Settings.bgm_volume": "int", "Settings.transmission": "str",
            "Settings.assist": "bool", "Settings.view": "str", "Settings.race_serial": "int",
        },
    }
    assert json.loads(json.dumps(schema())) == schema()


def test_profile_saved_item_list_matches_the_snapshot():
    # 項目を足す、消す、名を変える、型を変えると、ここが落ちる。形式バージョンを上げて移行を書くか、NOT_SAVED に入れるかを
    # 決めてから、単独のコミットで、理由を添えて、保存する項目の一覧の写しを取り直す（python3 tools/fingerprint.py --update）。
    recorded = fingerprint.read_schema_snapshot(ROOT)
    assert recorded is not None, f"保存する項目の一覧の写し（{fingerprint.SCHEMA_SNAPSHOT}）が無いか、読めない。黙って作らない"
    assert fingerprint.compare_schema(recorded, schema()) == []
    assert recorded == schema()


def test_profile_schema_comparison_names_what_changed():
    current = schema()
    added = {"version": current["version"], "fields": {**current["fields"], "Settings.hud_visible": "bool"}}
    retyped = {"version": current["version"], "fields": {**current["fields"], "Settings.assist": "int"}}
    removed = {"version": current["version"], "fields": {name: kind for name, kind in current["fields"].items() if name != "Settings.view"}}
    bumped = {"version": current["version"] + 1, "fields": current["fields"]}
    assert fingerprint.compare_schema(current, current) == []
    for other, word in ((added, "Settings.hud_visible"), (retyped, "Settings.assist"), (removed, "Settings.view"), (bumped, "version")):
        lines = fingerprint.compare_schema(current, other)
        assert len(lines) == 1 and word in lines[0]


# --- 設定の型と範囲 ---
@pytest.mark.parametrize("changes", [
    {"sfx_volume": 0}, {"sfx_volume": 10}, {"bgm_volume": 0}, {"bgm_volume": 10}, {"transmission": "MT"}, {"assist": False},
    {"view": "bumper"}, {"race_serial": 0}, {"race_serial": 10**12},
])
def test_profile_settings_accept_the_whole_range(changes):
    assert dataclasses.replace(DEFAULTS, **changes) == Settings(**changes)


@pytest.mark.parametrize("changes, error", [
    ({"sfx_volume": -1}, ValueError), ({"sfx_volume": 11}, ValueError), ({"bgm_volume": 11}, ValueError),
    ({"sfx_volume": 5.0}, TypeError), ({"sfx_volume": True}, TypeError), ({"bgm_volume": "5"}, TypeError), ({"sfx_volume": None}, TypeError),
    ({"transmission": "CVT"}, ValueError), ({"transmission": "at"}, ValueError), ({"transmission": 1}, TypeError),
    ({"assist": 1}, TypeError), ({"assist": 0}, TypeError), ({"assist": "ON"}, TypeError), ({"assist": None}, TypeError),
    ({"view": "heli"}, ValueError), ({"view": None}, TypeError),
    ({"race_serial": -1}, ValueError), ({"race_serial": 1.0}, TypeError), ({"race_serial": False}, TypeError),
])
def test_profile_settings_reject_values_of_the_wrong_type_or_range(changes, error):
    with pytest.raises(error):
        Settings(**changes)


def test_profile_settings_cannot_be_changed_and_have_the_documented_defaults():
    assert dataclasses.asdict(DEFAULTS) == {"sfx_volume": 5, "bgm_volume": 5, "transmission": "AT", "assist": True, "view": "chase", "race_serial": 0}
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULTS.sfx_volume = 1
    with pytest.raises(TypeError):
        save_settings(SaveStore(MemoryBackend()), {"sfx_volume": 5})


# --- 読み込みの表（1行ずつ） ---
def test_profile_load_row_1_missing_key_gives_defaults_and_touches_nothing():
    backend = MemoryBackend()
    assert load_settings(SaveStore(backend)) == Loaded(DEFAULTS, "", True)
    assert backend.items == {}


def test_profile_load_row_2_current_version_is_read_and_left_alone():
    backend = MemoryBackend()
    backend.items[MAIN_KEY] = raw(plain())
    before = dict(backend.items)
    assert load_settings(SaveStore(backend)) == Loaded(SELFCHECK_SETTINGS, "", True)
    assert backend.items == before


def old_sample_migrations() -> dict:
    """作り物の移行の表。形式バージョン1は音量が1つ（volume）、2は視点が無い、3がいまの形、という見本。"""

    def from_1(data: dict) -> dict:
        data = dict(data)
        volume = data.pop("volume")
        return {**data, "sfx_volume": volume, "bgm_volume": volume}

    def from_2(data: dict) -> dict:
        return {**data, "view": "chase"}

    return {1: from_1, 2: from_2}


OLD_V1 = {"volume": 7, "transmission": "MT", "assist": False, "race_serial": 4}
OLD_V2 = {"sfx_volume": 2, "bgm_volume": 9, "transmission": "MT", "assist": False, "race_serial": 4}


def test_profile_load_row_3_old_versions_are_migrated_step_by_step_and_not_rewritten(monkeypatch):
    monkeypatch.setattr(profile, "SETTINGS_VERSION", 3)
    migrations = old_sample_migrations()
    for old, version, want in (
        (OLD_V1, 1, Settings(sfx_volume=7, bgm_volume=7, transmission="MT", assist=False, view="chase", race_serial=4)),
        (OLD_V2, 2, Settings(sfx_volume=2, bgm_volume=9, transmission="MT", assist=False, view="chase", race_serial=4)),
    ):
        backend = MemoryBackend()
        backend.items[MAIN_KEY] = raw(old, version)
        before = dict(backend.items)
        assert load_settings(SaveStore(backend), migrations) == Loaded(want, "", True)
        assert backend.items == before  # 書き直しは、次の保存で
        # 次の保存で、いまの形式バージョンになる。
        save_settings(SaveStore(backend), want)
        assert SaveStore(backend).get(SETTINGS_KEY) == (3, encode(want))
        assert load_settings(SaveStore(backend), migrations) == Loaded(want, "", True)


def test_profile_load_row_4_newer_version_gives_defaults_and_is_not_touched():
    backend = MemoryBackend()
    backend.items[MAIN_KEY] = raw({**plain(), "from_the_future": 1}, SETTINGS_VERSION + 1)
    before = dict(backend.items)
    assert load_settings(SaveStore(backend)) == Loaded(DEFAULTS, storage.NOTICE_NEWER_VERSION, False)
    assert backend.items == before  # 退避も、上書きもしない


def test_profile_newer_version_cannot_be_overwritten_by_settings_made_again():
    # 読み込みの結果の「書いてよいか」を見ずに、設定を作り直して保存しても、保存の口の守りが止める。
    backend = MemoryBackend()
    backend.items[MAIN_KEY] = raw(plain(), SETTINGS_VERSION + 1)
    before = dict(backend.items)
    store = SaveStore(backend)
    loaded = load_settings(store)
    assert loaded.writable is False
    for settings in (loaded.settings, Settings(sfx_volume=1), SELFCHECK_SETTINGS):
        with pytest.raises(NewerVersionError):
            save_settings(store, settings)
    assert backend.items == before


CORRUPT_VALUES = {
    "envelope_cut_short": raw(plain())[:-1],
    "envelope_one_bit_flipped": bytes([raw(plain())[0] ^ 1]) + raw(plain())[1:],
    "not_an_envelope": b"sfx_volume=5",
    "empty": b"",
    "payload_not_json": raw(b"{not json"),
    "payload_not_utf8": raw(b"\xff\xfe"),
    "payload_not_an_object": raw(b"[1,2,3]"),
    "payload_null": raw(b"null"),
    "unknown_item": raw(plain(hud_visible=True)),
    "missing_item": raw({name: value for name, value in plain().items() if name != "view"}),
    "integer_item_holds_true": raw(plain(sfx_volume=True)),
    "bool_item_holds_1": raw(plain(assist=1)),
    "integer_item_holds_a_float": raw(plain(bgm_volume=5.0)),
    "out_of_range": raw(plain(sfx_volume=11)),
    "unknown_choice": raw(plain(transmission="CVT")),
    "negative_serial": raw(plain(race_serial=-1)),
    "text_item_holds_null": raw(plain(view=None)),
}


@pytest.mark.parametrize("name", sorted(CORRUPT_VALUES))
def test_profile_load_row_5_corrupt_value_is_set_aside_and_rewritten_with_defaults(name):
    backend = MemoryBackend()
    backend.items[MAIN_KEY] = CORRUPT_VALUES[name]
    store = SaveStore(backend)
    assert load_settings(store) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, True)
    assert backend.items[BAD_KEY] == CORRUPT_VALUES[name]  # 読めなかったバイト列を、そのまま退避してある
    assert store.get(SETTINGS_KEY) == (SETTINGS_VERSION, encode(DEFAULTS))  # 既定値で書き直してある
    assert sorted(backend.items) == [MAIN_KEY, BAD_KEY]
    assert load_settings(store) == Loaded(DEFAULTS, "", True)  # 次の起動では、知らせが出ない


def test_profile_load_row_5_old_version_without_a_migration_is_corrupt(monkeypatch):
    monkeypatch.setattr(profile, "SETTINGS_VERSION", 3)
    backend = MemoryBackend()
    backend.items[MAIN_KEY] = raw(OLD_V1, 1)
    old = backend.items[MAIN_KEY]
    # 移行の表に、形式バージョン1から2への関数が無い。
    assert load_settings(SaveStore(backend), {2: old_sample_migrations()[2]}) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, True)
    assert backend.items[BAD_KEY] == old
    assert SaveStore(backend).get(SETTINGS_KEY) == (3, encode(DEFAULTS))


def test_profile_load_row_5_migration_that_fails_is_corrupt(monkeypatch):
    monkeypatch.setattr(profile, "SETTINGS_VERSION", 3)
    migrations = old_sample_migrations()
    for payload, version in (({"transmission": "MT", "assist": False, "race_serial": 4}, 1), (b"[]", 2), ({**OLD_V2, "sfx_volume": 99}, 2)):
        # 1つ目は、移行の関数が KeyError（volume が無い）。2つ目は TypeError（辞書でない）。3つ目は、移行の後の値が範囲の外。
        backend = MemoryBackend()
        backend.items[MAIN_KEY] = raw(payload, version)
        old = backend.items[MAIN_KEY]
        assert load_settings(SaveStore(backend), migrations) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, True)
        assert backend.items[BAD_KEY] == old


def test_profile_load_row_5_rewrite_that_fails_does_not_change_the_result():
    # 退避はできたが、既定値での書き直しが失敗した。鍵が無い状態と同じ。
    backend = RefusingBackend(MAIN_KEY)
    backend.items[MAIN_KEY] = b"broken"
    assert load_settings(SaveStore(backend)) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, True)
    assert backend.items == {BAD_KEY: b"broken"} and backend.refused == 1


@pytest.mark.parametrize("error", [StorageFull, StorageError])
def test_profile_load_row_6_corrupt_value_that_cannot_be_set_aside_is_left_alone(error):
    backend = RefusingBackend(BAD_KEY, error)
    backend.items[MAIN_KEY] = b"broken"
    assert load_settings(SaveStore(backend)) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, False)
    assert backend.items == {MAIN_KEY: b"broken"}  # 元の鍵に触れていない


def test_profile_load_row_7_backend_that_cannot_be_read_gives_defaults_and_does_nothing():
    backend = UnreadableBackend()
    assert load_settings(SaveStore(backend)) == Loaded(DEFAULTS, storage.NOTICE_BACKEND_UNREADABLE, False)
    assert backend.changes == 0 and backend.items == {}


def test_profile_load_never_raises_a_storage_error_and_every_notice_is_a_known_one():
    cases = [MemoryBackend(), UnreadableBackend(), RefusingBackend(BAD_KEY), RefusingBackend(MAIN_KEY)]
    for value in (b"broken", raw(plain(), SETTINGS_VERSION + 1), raw(plain())):
        for backend in (RefusingBackend(BAD_KEY), RefusingBackend(MAIN_KEY), MemoryBackend()):
            backend.items[MAIN_KEY] = value
            cases.append(backend)
    for backend in cases:
        loaded = load_settings(SaveStore(backend))
        assert isinstance(loaded.settings, Settings) and type(loaded.writable) is bool
        assert loaded.notice == "" or loaded.notice in storage.NOTICES


def test_profile_the_four_notices_come_from_four_different_cases():
    # 保存先の切り替えの文は、保存先を選ぶ所（cp_app/storage_select.py）が出す。読み込みが出すのは、残りの3つ。
    newer, corrupt, unreadable = MemoryBackend(), MemoryBackend(), UnreadableBackend()
    newer.items[MAIN_KEY] = raw(plain(), SETTINGS_VERSION + 1)
    corrupt.items[MAIN_KEY] = b"broken"
    notices = [load_settings(SaveStore(backend)).notice for backend in (newer, corrupt, unreadable)]
    assert notices == [storage.NOTICE_NEWER_VERSION, storage.NOTICE_UNREADABLE, storage.NOTICE_BACKEND_UNREADABLE]
    assert set(notices) | {storage.NOTICE_MEMORY_FALLBACK} == set(storage.NOTICES)


# --- 移行の表 ---
def test_profile_migration_table_is_empty_until_an_old_version_exists():
    assert profile.MIGRATIONS == {} and SETTINGS_VERSION == 1
    assert SETTINGS_KEY == "settings"


def test_profile_decode_rejects_versions_it_cannot_read():
    payload = encode(SELFCHECK_SETTINGS)
    for version in (0, SETTINGS_VERSION + 1, -1, True, "1", None):
        with pytest.raises(ProfileError):
            decode(payload, version)
    assert decode(payload, SETTINGS_VERSION) == SELFCHECK_SETTINGS


# --- 組み合わせ：localStorage の保存先（偽の js） ---
def test_profile_value_that_is_not_base64_in_local_storage_is_set_aside_without_an_exception():
    fake = FakeStorage()
    fake.items["clippingpoint/main.settings"] = "not base64 at all!"
    store = SaveStore(WebStorageBackend(FakeJs(fake)))
    assert load_settings(store) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, True)
    assert sorted(fake.items) == ["clippingpoint/main.settings", "clippingpoint/main.settings.bad"]
    assert base64.b64decode(fake.items["clippingpoint/main.settings.bad"]) == b"not base64 at all!"  # 退避してある
    assert store.get(SETTINGS_KEY) == (SETTINGS_VERSION, encode(DEFAULTS))  # 既定値で書き直してある
    assert load_settings(store) == Loaded(DEFAULTS, "", True)


def test_profile_full_local_storage_keeps_the_corrupt_value_where_it_is():
    fake = FakeStorage(quota=30)
    fake.items["clippingpoint/main.settings"] = "not base64 at all!"
    store = SaveStore(WebStorageBackend(FakeJs(fake)))
    assert load_settings(store) == Loaded(DEFAULTS, storage.NOTICE_UNREADABLE, False)  # 退避できない
    assert fake.items == {"clippingpoint/main.settings": "not base64 at all!"}


def test_profile_newer_version_in_local_storage_is_kept():
    fake = FakeStorage()
    fake.items["clippingpoint/main.settings"] = base64.b64encode(raw(plain(), SETTINGS_VERSION + 1)).decode("ascii")
    before = dict(fake.items)
    store = SaveStore(WebStorageBackend(FakeJs(fake)))
    assert load_settings(store) == Loaded(DEFAULTS, storage.NOTICE_NEWER_VERSION, False)
    with pytest.raises(NewerVersionError):
        save_settings(store, SELFCHECK_SETTINGS)
    assert fake.items == before


# --- 保存の往復（検証の口のときに、アプリが回す） ---
def test_profile_selfcheck_passes_on_every_backend_and_leaves_its_key(tmp_path):
    for backend in backends(tmp_path):
        assert selfcheck(backend) == (True, ""), type(backend).__name__
        # 書いた鍵は、残す（道具が、自分で読んで照らす）。名前空間は selfcheck。ふつうの鍵（main）には触れない。
        assert backend.keys() == ["selfcheck.settings"]
        assert SaveStore(backend, profile.SELFCHECK_NAMESPACE).get(SETTINGS_KEY) == (SETTINGS_VERSION, encode(SELFCHECK_SETTINGS))
        assert selfcheck(backend) == (True, "")  # 2度目も通る（残っている鍵を、消してから回す）


def test_profile_selfcheck_does_not_touch_the_settings_of_the_player():
    backend = MemoryBackend()
    mine = Settings(sfx_volume=1, view="bumper")
    save_settings(SaveStore(backend), mine)
    before = backend.items[MAIN_KEY]
    assert selfcheck(backend) == (True, "")
    assert backend.items[MAIN_KEY] == before and load_settings(SaveStore(backend)).settings == mine
    assert profile.SELFCHECK_NAMESPACE == "selfcheck" != storage.DEFAULT_NAMESPACE


@pytest.mark.parametrize("backend", [MemoryBackend(capacity=5), UnreadableBackend(), RefusingBackend("selfcheck.settings", StorageError)])
def test_profile_selfcheck_reports_a_failure_with_its_reason_instead_of_raising(backend):
    ok, detail = selfcheck(backend)
    assert ok is False and detail


def test_profile_selfcheck_fails_when_the_value_does_not_come_back():
    class ForgetfulBackend(MemoryBackend):
        def write(self, key, data) -> None:
            pass  # 書いたふりをして、何も持たない

    class DamagingBackend(MemoryBackend):
        def write(self, key, data) -> None:
            super().write(key, data[:-1])  # 最後の1バイトを落として書く

    for backend in (ForgetfulBackend(), DamagingBackend()):
        ok, detail = selfcheck(backend)
        assert ok is False and detail
