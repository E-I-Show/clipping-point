"""Pure tests: no Pyxel in this process (pyxel.quit()/pyxel.run() must never run inside pytest)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from cp_core.controls import RawInput, axis_to_unit, resolve, trigger_to_unit
from cp_core.datafiles import DataError, load_cars, load_track, pack_track
from cp_core.fixed_loop import RenderGate
from cp_core.input_script import DEMO_SCRIPT, reference_raw_inputs, validate_script
from cp_core.sim import Sim

APP = Path(__file__).resolve().parent.parent / "cp_proto"


def drive_gate(pattern: str, divisor: int = 2):
    """pattern: 'U' = update tick, 'D' = draw call. Returns list of tick numbers at which a render ran."""
    gate = RenderGate(divisor)
    tick = 0
    rendered_at = []
    for ch in pattern:
        if ch == "U":
            gate.on_tick()
            tick += 1
        elif gate.should_render():
            rendered_at.append(tick)
    return rendered_at


def test_gate_renders_every_second_tick_at_full_speed():
    rendered = drive_gate("UD" * 60)
    assert len(rendered) == 30
    assert all(b - a == 2 for a, b in zip(rendered, rendered[1:]))


def test_gate_renders_every_draw_when_pyxel_catches_up():
    # measured with a 20-30 ms draw at fps=60: U D UUD UUD UUD ...
    rendered = drive_gate("UD" + "UUD" * 59)
    assert len(rendered) == 60  # every draw call renders -> 30 fps


def test_gate_never_starves_under_irregular_patterns():
    for pattern in ("UD" + "UUUD" * 20, "UD" + "UUD" * 5 + "UD" * 9 + "UUUUUD" * 4):
        rendered = drive_gate(pattern)
        assert rendered, "0 renders must never count as a pass"
        longest_run = max(len(run) for run in pattern.split("D"))
        assert max(b - a for a, b in zip(rendered, rendered[1:])) <= max(2, longest_run) + 1


def test_frame_count_parity_gate_is_broken_under_catch_up():
    """Documents the trap: `if frame_count % 2 == 1: render` never renders once Pyxel does U U D."""
    frame_count = 0
    renders = 0
    # Pyxel: extra updates each bump frame_count; the last update and the draw share one value.
    for updates in [1] + [2] * 59:
        frame_count += updates - 1
        if frame_count % 2 == 1:
            renders += 1
        frame_count += 1
    assert renders == 0


def test_axis_normalisation_covers_sdl_range():
    assert axis_to_unit(32767) == 1.0
    assert axis_to_unit(-32768) == -1.0  # clamped (-32768/32767 < -1)
    assert axis_to_unit(0) == 0.0
    assert trigger_to_unit(32767) == 1.0
    assert trigger_to_unit(-5) == 0.0
    assert resolve(RawInput(steer_axis=2000, right=True)).steer == 1.0  # inside dead zone -> digital
    assert resolve(RawInput(steer_axis=-16000, right=True)).steer == pytest.approx(-16000 / 32767)


def test_sim_is_deterministic_and_script_counts_each_press_once():
    def run():
        sim = Sim()
        for raw in reference_raw_inputs(DEMO_SCRIPT, 120):
            sim.step(resolve(raw))
        return sim

    a, b = run(), run()
    assert a.fingerprint() == b.fingerprint()
    assert a.shift_count == 3
    c = Sim()
    for raw in reference_raw_inputs(DEMO_SCRIPT, 119):
        c.step(resolve(raw))
    assert c.fingerprint() != a.fingerprint()  # the fingerprint really depends on the state


def test_script_validation_rejects_bad_scripts():
    with pytest.raises(ValueError):
        validate_script([(5, "steer_axis", True)])
    with pytest.raises(ValueError):
        validate_script([(5, "nope", 1)])
    with pytest.raises(ValueError):
        validate_script([(5, "left", True), (4, "left", False)])


def test_shipped_data_loads():
    cars = load_cars(APP / "data" / "cars.json")
    assert [c["id"] for c in cars] == ["tsubame_1600", "kazane_rs", "shirogane_gtt", "arashi_4t"]
    assert len(load_track(APP / "data" / "track.bin")) == 48


@pytest.mark.parametrize(
    "mutate",
    [
        lambda cars: cars[0].pop("mass_kg"),
        lambda cars: cars[1].update(layout="RR"),
        lambda cars: cars[2].update(name="シロガネ"),
        lambda cars: cars[3].update(id=cars[0]["id"]),
        lambda cars: cars[0].update(power_ps="165"),
        lambda cars: cars.clear(),
    ],
)
def test_broken_car_data_is_rejected(tmp_path, mutate):
    doc = json.loads((APP / "data" / "cars.json").read_text())
    mutate(doc["cars"])
    bad = tmp_path / "cars.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(DataError):
        load_cars(bad)


def test_corrupt_track_is_rejected(tmp_path):
    blob = bytearray(pack_track([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]))
    good = tmp_path / "ok.bin"
    good.write_bytes(blob)
    assert len(load_track(good)) == 3
    blob[10] ^= 0xFF
    bad = tmp_path / "bad.bin"
    bad.write_bytes(blob)
    with pytest.raises(DataError):
        load_track(bad)
    with pytest.raises(DataError):
        load_track(tmp_path / "missing.bin")


def _imports_pyxel(modules: str) -> bool:
    code = f"import sys; sys.path.insert(0, {str(APP)!r}); import {modules}; print('pyxel' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    return out.strip().splitlines()[-1] == "True"


def test_core_does_not_import_pyxel():
    assert not _imports_pyxel("cp_core.sim, cp_core.controls, cp_core.datafiles, cp_core.fixed_loop, cp_core.input_script")
    # control: the check is able to say True
    assert _imports_pyxel("cp_app.input_pyxel")


def test_gate_wall_clock_rule_recovers_30fps_in_the_browser_lag_pattern():
    """Browser build: a late frame is reported one callback later (e12 desk model).
    Callback times in ms and ticks per callback: 0:1, 33.3:1, 66.7:2, 100:2 ..."""
    gate = RenderGate(2, 30.0)
    rendered = []
    for now_ms, ticks in [(0.0, 1), (33.3, 1), (66.7, 2), (100.0, 2), (133.3, 2)]:
        for _ in range(ticks):
            gate.on_tick()
        rendered.append(gate.should_render(now_ms))
    assert rendered == [True, True, True, True, True]
    # tick-count rule alone skips the second callback (-> 20 renders/s in the model)
    gate = RenderGate(2, None)
    rendered = []
    for now_ms, ticks in [(0.0, 1), (33.3, 1), (50.0, 2)]:
        for _ in range(ticks):
            gate.on_tick()
        rendered.append(gate.should_render(now_ms))
    assert rendered == [True, False, True]


def test_gate_wall_clock_rule_does_not_fire_at_normal_60hz_cadence_or_without_a_new_tick():
    gate = RenderGate(2, 30.0)
    rendered = []
    for i in range(8):
        gate.on_tick()
        rendered.append(gate.should_render(i * 16.67))
    assert rendered == [True, False, True, False, True, False, True, False]
    # 75 Hz display: gaps of 13.3 / 26.7 ms between frames must not trigger the time rule
    gate = RenderGate(2, 30.0)
    gate.on_tick()
    assert gate.should_render(0.0)
    gate.on_tick()
    assert not gate.should_render(26.7)
    # no new tick since the last render: never render again, however late it is
    gate = RenderGate(2, 30.0)
    gate.on_tick()
    assert gate.should_render(0.0)
    assert not gate.should_render(500.0)


def test_pause_toggles_once_per_start_press_and_freezes_the_sim():
    from cp_core.game import Game
    from cp_core.input_script import TOUR_SCRIPT, TOUR_TICKS

    game = Game()
    sim_ticks = []
    for raw in reference_raw_inputs(TOUR_SCRIPT, TOUR_TICKS):
        game.tick(raw)
        sim_ticks.append(game.sim.tick)
    assert game.ticks == TOUR_TICKS and not game.paused
    assert sim_ticks[11] == 12 and sim_ticks[12] == 12 and sim_ticks[23] == 12  # frozen 12..23
    assert sim_ticks[24] == 13  # resumed by the second press
    assert game.sim.tick == TOUR_TICKS - 12
