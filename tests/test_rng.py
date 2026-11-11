"""乱数（cp_core.rng）のテスト。乱数の流れと、ハッシュの抽選。

値は、数字で固定する（参照値）。式を変えると、ここが落ちる。整数だけで作るので、ブラウザ版でも同じ値になる。
文字列の集合の順に頼っていないことは、tests/test_fingerprint.py が、ハッシュの種を変えた別プロセスで見る。
"""
import pytest

from cp_core import rng
from cp_core.rng import PURPOSES, RngSet, RngStream, hash_u64, hash_unit


# --- 参照値 ---
def test_rng_stream_gives_the_published_splitmix64_values():
    # splitmix64 の参照値（始まりの状態 1234567）。公開されている算法のとおりであること。
    stream = RngStream(1234567)
    assert [stream.next_u64() for _ in range(3)] == [6457827717110365317, 3203168211198807973, 9817491932198370423]
    stream = RngStream(0)
    assert [stream.next_u64() for _ in range(3)] == [16294208416658607535, 7960286522194355700, 487617019471545679]


def test_rng_unit_values_are_pinned_and_stay_below_one():
    stream = RngStream(1234567)
    assert [stream.unit() for _ in range(3)] == [0.3500795420214081, 0.17364409667091263, 0.5322073040624192]
    values = [stream.unit() for _ in range(2000)]
    assert 0.0 <= min(values) and max(values) < 1.0
    assert 0.45 < sum(values) / len(values) < 0.55


def test_rng_unit_is_the_top_53_bits_over_two_to_the_53():
    # 2の累乗での割り算だけで作る（どの環境でも同じ値になる）。
    a, b = RngStream(99), RngStream(99)
    for _ in range(50):
        assert a.unit() == (b.next_u64() >> 11) / 2**53


def test_rng_hash_values_are_pinned():
    assert hash_u64(0) == 16294208416658607535
    assert hash_u64(1) == 10451216379200822465
    assert hash_u64(1, "brake", "kazane_rs", 3, 4) == 6213381099448417515
    assert hash_u64(-1, 5) == 3846658174030194800
    assert hash_unit(7, "x", 0) == 0.5690370516481271
    assert hash_unit(7, "x", 1) == 0.12320085265987946


def test_rng_set_starting_states_are_pinned():
    assert RngSet(0).state() == {"ai": 0x0AD0A11CEA5BD376}
    assert RngSet(1).state() == {"ai": 0x3C07E3CC992538ED}
    assert RngSet(20261111).state() == {"ai": 0x3581644B167E57B5}
    assert RngSet(0).stream("ai").next_u64() == 8270111946964754416


def test_rng_below_shuffle_and_uniform_are_pinned():
    stream = RngStream(42)
    assert [stream.below(10) for _ in range(8)] == [3, 1, 8, 4, 0, 2, 5, 8]
    stream, items = RngStream(42), list(range(8))
    stream.shuffle(items)
    assert items == [3, 1, 6, 2, 4, 0, 7, 5]
    assert RngStream(42).uniform(0.94, 1.0) == 0.9844938927263094


# --- 乱数の流れ ---
def test_rng_purposes_are_the_registered_ones():
    assert PURPOSES == ("ai",)
    assert tuple(RngSet(5).state()) == PURPOSES  # 状態の並びは、登録の順


def test_rng_drawing_from_one_stream_does_not_move_the_others(monkeypatch):
    # 用途が1つだと確かめられないので、ここでは用途を2つにして見る。
    monkeypatch.setattr(rng, "PURPOSES", ("ai", "extra"))
    drawn, untouched = RngSet(42), RngSet(42)
    for _ in range(100):
        drawn.stream("ai").unit()
    assert drawn.state()["ai"] != untouched.state()["ai"]
    assert drawn.state()["extra"] == untouched.state()["extra"]
    assert drawn.stream("extra").next_u64() == untouched.stream("extra").next_u64()
    # 流れごとに、始まりの状態が違う。
    assert untouched.state()["ai"] != RngSet(42).state()["extra"]


def test_rng_adding_a_purpose_at_the_end_does_not_move_the_existing_stream(monkeypatch):
    before = RngSet(7).state()["ai"]
    monkeypatch.setattr(rng, "PURPOSES", ("ai", "extra"))
    assert RngSet(7).state()["ai"] == before


def test_rng_unregistered_purpose_is_an_error_not_a_new_stream():
    streams = RngSet(1)
    for name in ("particles", "grid", "", "AI", None):
        with pytest.raises(KeyError):
            streams.stream(name)
    assert tuple(streams.state()) == PURPOSES  # 黙って増えていない


def test_rng_same_seed_gives_the_same_streams_and_another_seed_does_not():
    assert RngSet(3).state() == RngSet(3).state()
    assert RngSet(3).state() != RngSet(4).state()
    assert RngSet(3).seed == 3


def test_rng_state_can_be_saved_and_restored():
    streams = RngSet(42)
    for _ in range(10):
        streams.stream("ai").next_u64()
    state = streams.state()
    first = [streams.stream("ai").unit() for _ in range(5)]
    assert streams.state() != state
    streams.restore(state)
    assert streams.state() == state
    assert [streams.stream("ai").unit() for _ in range(5)] == first
    # 取った状態は、流れとつながっていない（後から書き換えても、流れは動かない）。
    state["ai"] = 0
    assert streams.state()["ai"] != 0


@pytest.mark.parametrize("bad", [{}, {"grid": 1}, {"ai": 1, "grid": 2}, [1], None, "ai"])
def test_rng_restore_rejects_a_state_with_other_purposes(bad):
    streams = RngSet(42)
    before = streams.state()
    with pytest.raises(ValueError):
        streams.restore(bad)
    assert streams.state() == before


@pytest.mark.parametrize("bad, error", [({"ai": 1.0}, TypeError), ({"ai": True}, TypeError), ({"ai": "1"}, TypeError), ({"ai": -1}, ValueError), ({"ai": 2**64}, ValueError)])
def test_rng_restore_rejects_a_state_that_is_not_a_64_bit_integer(bad, error):
    streams = RngSet(42)
    before = streams.state()
    with pytest.raises(error):
        streams.restore(bad)
    assert streams.state() == before


def test_rng_stream_state_stays_a_64_bit_integer():
    stream = RngStream(2**64 + 5)
    assert stream.state == 5  # 始まりの状態は、64ビットに収める
    for _ in range(200):
        value = stream.next_u64()
        assert type(value) is int and 0 <= value < 2**64
        assert type(stream.state) is int and 0 <= stream.state < 2**64


def test_rng_below_stays_in_range_and_rejects_bad_sizes():
    stream = RngStream(8)
    assert all(0 <= stream.below(7) < 7 for _ in range(500))
    assert {stream.below(1) for _ in range(20)} == {0}
    for bad in (0, -3):
        with pytest.raises(ValueError):
            stream.below(bad)
    for bad in (2.0, True, "3"):
        with pytest.raises(TypeError):
            stream.below(bad)


def test_rng_shuffle_keeps_the_items_and_is_repeatable():
    a, b = list(range(20)), list(range(20))
    RngStream(5).shuffle(a)
    RngStream(5).shuffle(b)
    assert a == b and sorted(a) == list(range(20)) and a != list(range(20))
    empty, one = [], ["x"]
    RngStream(5).shuffle(empty)
    RngStream(5).shuffle(one)
    assert empty == [] and one == ["x"]


# --- ハッシュの抽選 ---
def test_rng_hash_draw_has_no_state():
    first = hash_u64(1, "brake", "kazane_rs", 3, 4)
    streams = RngSet(1)
    before = streams.state()
    assert all(hash_u64(1, "brake", "kazane_rs", 3, 4) == first for _ in range(5))  # 何度引いても、同じ値
    assert streams.state() == before  # 流れは動かない


def test_rng_hash_draw_spreads_and_depends_on_the_order_of_the_keys():
    values = {hash_u64(1, "brake", "kazane_rs", lap, corner) for lap in range(50) for corner in range(9)}
    assert len(values) == 450
    assert hash_u64(1, "ab", "c") != hash_u64(1, "a", "bc")
    assert hash_u64(1, 2, 3) != hash_u64(1, 3, 2)
    assert hash_u64(1, "x") != hash_u64(2, "x")
    assert hash_u64(1, "1") != hash_u64(1, 1)  # 文字列の鍵と、整数の鍵は別
    units = [hash_unit(7, "x", index) for index in range(2000)]
    assert 0.0 <= min(units) and max(units) < 1.0 and 0.45 < sum(units) / len(units) < 0.55


@pytest.mark.parametrize("bad", [1.5, True, False, None, b"x", ("a",), 2.0])
def test_rng_hash_key_must_be_an_integer_or_a_string(bad):
    with pytest.raises(TypeError):
        hash_u64(1, bad)
    with pytest.raises(TypeError):
        hash_unit(1, "ok", bad)


@pytest.mark.parametrize("bad", [1.0, True, "1", None])
def test_rng_seed_must_be_an_integer(bad):
    with pytest.raises(TypeError):
        hash_u64(bad, "x")
    with pytest.raises(TypeError):
        RngSet(bad)
    with pytest.raises(TypeError):
        RngStream(bad)


def test_rng_module_does_not_use_the_standard_random_or_the_builtin_hash():
    # 層の分離の検査（tools/arch_check.py）が拾うことは tests/test_arch_guard.py。ここは、このモジュールが実際に通ること。
    import arch_check
    from conftest import ROOT

    source = (ROOT / "clipping_point" / "cp_core" / "rng.py").read_text(encoding="utf-8")
    assert arch_check.check_source(source, "cp_core", "cp_core/rng.py") == []
