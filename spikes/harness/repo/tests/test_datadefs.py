import json
import shutil

import pytest

from cp_core.datadefs import LOAD_ORDER, SCHEMA, DataError, load_game_data
from conftest import ROOT

DATA = ROOT / "app" / "data"
PACKS = ROOT / "testpacks"


def test_data_shipped_data_loads_with_no_warnings():
    data = load_game_data(DATA)
    assert data.warnings == []
    assert sorted(data.table("cars")) == ["arashi_4t", "kazane_rs", "shirogane_gtt", "tsubame_1600"]
    assert {t: len(data.table(t)) for t in LOAD_ORDER} == {"audio": 3, "assists": 2, "ai": 3, "cars": 4, "tracks": 1}
    assert data.save_namespace == "main"


def test_data_every_test_pack_loads_and_goes_to_its_own_save_namespace():
    packs = sorted(p.name for p in PACKS.iterdir() if p.is_dir())
    assert packs, "no test packs found"
    for pack in packs:
        data = load_game_data(DATA, (pack,), PACKS)
        assert data.warnings == [] and data.save_namespace == f"pack_{pack}"
    ext = load_game_data(DATA, ("extreme",), PACKS)
    assert ext.table("cars")["kazane_rs"]["name"] == "KAZANE RS TEST"  # same id: replaced
    assert "wide_test_car" in ext.table("cars") and len(ext.table("cars")) == 5  # new id: appended
    assert load_game_data(DATA).table("cars")["kazane_rs"]["name"] == "KAZANE RS"  # base untouched


def edit(tmp_path, table, fn):
    d = tmp_path / "data"
    if not d.exists():
        shutil.copytree(DATA, d)
    doc = json.loads((d / f"{table}.json").read_text())
    fn(doc[table])
    (d / f"{table}.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


BROKEN = {
    "unknown key": ("cars", lambda t: t[0].update(pwoer_ps=1), "unknown key"),
    "missing key": ("cars", lambda t: t[0].pop("mass_kg"), "missing"),
    "bool where int": ("cars", lambda t: t[0].update(power_ps=True), "expected int"),
    "string where int": ("cars", lambda t: t[0].update(power_ps="165"), "expected int"),
    "out of range": ("cars", lambda t: t[0].update(mass_kg=90), "outside"),
    "bad enum": ("cars", lambda t: t[0].update(layout="RR"), "not in"),
    "dangling ref": ("cars", lambda t: t[0].update(engine_sound="eng_v8"), "no audio with id"),
    "dangling ref in list": ("tracks", lambda t: t[0].update(ai_profiles=["akane_easy", "nobody"]), "no ai with id"),
    "duplicate id": ("cars", lambda t: t.append(dict(t[0])), "duplicate id"),
    "non-ascii label": ("cars", lambda t: t[0].update(name="ツバメ"), "printable ASCII"),
    "label too long": ("cars", lambda t: t[0].update(name="X" * 15), "budget"),
    "bad id": ("cars", lambda t: t[0].update(id="Tsubame 1600"), "not an id"),
    "empty table": ("ai", lambda t: t.clear(), "no entries"),
    "list too long": ("tracks", lambda t: t[0].update(lap_choices=[1, 2, 3, 4, 5, 6]), "expected a list"),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_data_broken_definitions_are_rejected(tmp_path, case):
    table, fn, expect = BROKEN[case]
    with pytest.raises(DataError) as info:
        load_game_data(edit(tmp_path, table, fn))
    assert any(expect in p for p in info.value.problems), info.value.problems


def test_data_all_problems_are_reported_at_once_and_notes_are_allowed(tmp_path):
    d = edit(tmp_path, "cars", lambda t: (t[0].update(pwoer_ps=1, _note="placeholder"), t[1].update(layout="RR")))
    edit(tmp_path, "tracks", lambda t: t[0].update(bgm="nope"))
    with pytest.raises(DataError) as info:
        load_game_data(d)
    assert len(info.value.problems) == 3 and not any("_note" in p for p in info.value.problems)


def test_data_unreferenced_definition_is_a_warning(tmp_path):
    d = edit(tmp_path, "audio", lambda t: t.append({"id": "sfx_unused", "kind": "sfx", "channel": 2}))
    assert load_game_data(d).warnings == ["audio.sfx_unused: defined but never referenced"]


def test_data_every_schema_table_has_a_file_and_a_broken_case():
    assert set(SCHEMA) == set(LOAD_ORDER) == {p.stem for p in DATA.glob("*.json")}
