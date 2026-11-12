"""処理時間と回数の集計（cp_app.perf）のテスト。時計は使わず、実時間（秒）を引数で渡す。

全部をためる測り方（PerfMeter。煙テストの線の判定に使う）と、処理時間の輪（PerfRing。ふつうの起動で、画面に出す値に使う）。
"""
import dataclasses

import pytest

from cp_app import perf
from cp_app.perf import RENDER_RING, UPDATE_RING, PerfMeter, PerfRing, percentile
from cp_core.flow import PERF_NOT_MEASURED, PerfView
from cp_ui import fixtures, screens

TICK_S = 1.0 / 60.0


def feed(meter: PerfMeter, ticks: int, update_ms: float = 0.5, render_ms: float = 3.0, slow_first: int = 0) -> None:
    """毎秒60回の更新と、2 tickごとの実描画を、きっちりの間隔で与える。頭の slow_first 回の更新だけ遅くする。"""
    for i in range(ticks):
        start_s = i * TICK_S
        took_ms = 50.0 if i < slow_first else update_ms
        meter.on_update(start_s, start_s + took_ms / 1000.0)
        if i % 2 == 1:
            render_start_s = start_s + 0.002
            meter.on_render(render_start_s, render_start_s + render_ms / 1000.0)


def test_perf_regular_loop_reports_60_updates_and_30_renders_per_second():
    meter = PerfMeter()
    feed(meter, 600)
    report = meter.report()
    assert report["updates"] == 600
    assert report["renders"] == 300
    assert report["updates_per_s"] == 60.0
    assert 29.9 <= report["renders_per_s"] <= 30.1
    assert report["update_ms_p95"] == pytest.approx(0.5, abs=0.001)
    assert report["render_ms_p95"] == pytest.approx(3.0, abs=0.001)


def test_perf_warmup_ticks_are_not_measured():
    meter = PerfMeter(warmup_ticks=60)
    feed(meter, 660, slow_first=60)
    report = meter.report()
    assert report["updates"] == 600
    assert report["renders"] == 300
    assert report["update_ms_p95"] == pytest.approx(0.5, abs=0.001)  # 慣らしの間の遅い更新は入らない
    assert report["updates_per_s"] == 60.0


def test_perf_values_with_the_warmup_are_reported_beside_the_measured_ones():
    # 慣らしを入れた値も出す。頭の引っ掛かりが、線の判定から外れたまま見えなくならないように。
    meter = PerfMeter(warmup_ticks=60)
    feed(meter, 660, slow_first=60)
    whole = meter.report()["with_warmup"]
    assert whole["updates"] == 660 and whole["renders"] == 330
    assert whole["update_ms_p95"] == pytest.approx(50.0, abs=0.001)  # 660回のうち、頭の60回が50 ms
    assert whole["updates_per_s"] == 60.0
    assert 29.9 <= whole["renders_per_s"] <= 30.1
    assert "with_warmup" not in whole


def test_perf_without_warmup_both_views_agree():
    meter = PerfMeter()
    feed(meter, 120)
    report = meter.report()
    whole = report.pop("with_warmup")
    assert report == whole


def test_perf_p95_sees_the_slow_tail():
    meter = PerfMeter()
    for i in range(100):
        meter.on_update(i * TICK_S, i * TICK_S + (0.009 if i >= 90 else 0.001))
    assert meter.report()["update_ms_p95"] == pytest.approx(9.0, abs=0.001)


def test_perf_renders_at_20_per_second_are_reported_as_such():
    # アプリが実時間を RenderGate へ渡さないと、ブラウザ版はこの回数に落ち着く。線（毎秒29回）の下に出ること。
    meter = PerfMeter()
    for i in range(600):
        meter.on_update(i * TICK_S, i * TICK_S + 0.0005)
        if i % 3 == 2:
            meter.on_render(i * TICK_S + 0.002, i * TICK_S + 0.005)
    assert 19.9 <= meter.report()["renders_per_s"] <= 20.1


def test_perf_nothing_measured_reports_none_not_zero():
    report = PerfMeter(warmup_ticks=10).report()
    assert report["updates"] == 0 and report["renders"] == 0
    assert report["updates_per_s"] is None and report["renders_per_s"] is None
    assert report["update_ms_p95"] is None and report["render_ms_p95"] is None


def test_perf_one_update_has_no_rate():
    meter = PerfMeter()
    meter.on_update(0.0, 0.001)
    report = meter.report()
    assert report["updates"] == 1
    assert report["updates_per_s"] is None
    assert report["update_ms_p95"] == pytest.approx(1.0, abs=0.001)


def test_perf_negative_warmup_is_rejected():
    with pytest.raises(ValueError):
        PerfMeter(warmup_ticks=-1)


def test_perf_percentile_of_nothing_is_none():
    assert percentile([], 0.95) is None
    assert percentile([4.0], 0.95) == 4.0
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0


# --- 全部をためる測り方の要約の、平均と最大 ---
def test_perf_report_has_the_mean_and_the_maximum_beside_the_95th_percentile():
    meter = PerfMeter()
    for i in range(100):
        meter.on_update(i * TICK_S, i * TICK_S + (0.009 if i >= 98 else 0.001))  # 100回のうち、2回だけ 9 ms
        if i % 2 == 1:
            meter.on_render(i * TICK_S + 0.002, i * TICK_S + 0.002 + (0.011 if i == 51 else 0.003))  # 50回のうち、1回だけ 11 ms
    report = meter.report()
    assert report["update_ms_p95"] == pytest.approx(1.0, abs=0.001)  # 95%点には、出ない
    assert report["update_ms_mean"] == pytest.approx(1.16, abs=0.001) and report["update_ms_max"] == pytest.approx(9.0, abs=0.001)
    assert report["render_ms_mean"] == pytest.approx(3.16, abs=0.001) and report["render_ms_max"] == pytest.approx(11.0, abs=0.001)
    assert report["with_warmup"]["update_ms_max"] == report["update_ms_max"]


def test_perf_mean_and_maximum_leave_the_warmup_out_and_are_none_when_nothing_was_measured():
    meter = PerfMeter(warmup_ticks=60)
    feed(meter, 660, slow_first=60)
    report = meter.report()
    assert report["update_ms_mean"] == pytest.approx(0.5, abs=0.001) and report["update_ms_max"] == pytest.approx(0.5, abs=0.001)
    assert report["with_warmup"]["update_ms_max"] == pytest.approx(50.0, abs=0.001)  # 慣らしの間の遅い更新は、こちらにだけ出る
    assert report["with_warmup"]["update_ms_mean"] == pytest.approx((60 * 50.0 + 600 * 0.5) / 660, abs=0.001)
    empty = PerfMeter().report()
    assert [empty[key] for key in ("update_ms_mean", "update_ms_max", "render_ms_mean", "render_ms_max")] == [None] * 4


# --- 処理時間の輪（直近の決まった回数ぶんだけを持つ） ---
def test_perf_ring_sizes_are_two_seconds_of_updates_and_of_renders():
    assert (UPDATE_RING, RENDER_RING) == (120, 60)


def test_perf_ring_reports_the_mean_the_maximum_and_the_rate_of_what_it_holds():
    ring = PerfRing(4)
    for index, took_ms in enumerate((1.0, 2.0, 6.0)):
        ring.add(index * TICK_S, index * TICK_S + took_ms / 1000.0)
    assert ring.count == 3 and ring.size == 4
    assert ring.mean_ms() == pytest.approx(3.0) and ring.max_ms() == pytest.approx(6.0)
    assert ring.per_second() == pytest.approx(60.0)  # 3回の始まりが、2 tickぶんの間に並ぶ


def test_perf_ring_throws_the_oldest_values_away():
    ring = PerfRing(4)
    for index in range(10):
        took_ms = 50.0 if index < 6 else 1.0 + index  # 頭の6回は遅い。残るのは、最後の4回（7、8、9、10 ms）
        ring.add(index * TICK_S, index * TICK_S + took_ms / 1000.0)
    assert ring.count == 4
    assert ring.mean_ms() == pytest.approx(8.5) and ring.max_ms() == pytest.approx(10.0)  # 古い 50 ms は、もう無い
    assert ring.per_second() == pytest.approx(60.0)
    # 上限のないリストに、ためない。持つのは、いつも size 個。
    assert len(ring._starts_s) == 4 and len(ring._took_ms) == 4
    for index in range(10, 5000):
        ring.add(index * TICK_S, index * TICK_S + 0.002)
    assert ring.count == 4 and len(ring._starts_s) == 4 and len(ring._took_ms) == 4
    assert ring.mean_ms() == pytest.approx(2.0) and ring.max_ms() == pytest.approx(2.0)


def test_perf_ring_rate_follows_the_real_time_between_the_starts_it_holds():
    ring = PerfRing(RENDER_RING)
    for index in range(200):
        ring.add(index / 20.0, index / 20.0 + 0.004)  # 毎秒20回に落ちた実描画
    assert ring.count == RENDER_RING and ring.per_second() == pytest.approx(20.0)
    for index in range(200, 200 + RENDER_RING):
        ring.add(10.0 + (index - 200) / 30.0, 10.0 + (index - 200) / 30.0 + 0.004)  # 毎秒30回に戻る
    assert ring.per_second() == pytest.approx(30.0)  # 直近の区間だけを見る


def test_perf_ring_with_nothing_or_one_value_has_no_rate():
    ring = PerfRing(UPDATE_RING)
    assert ring.count == 0 and ring.mean_ms() is None and ring.max_ms() is None and ring.per_second() is None
    ring.add(1.0, 1.002)
    assert ring.count == 1 and ring.mean_ms() == pytest.approx(2.0) and ring.max_ms() == pytest.approx(2.0)
    assert ring.per_second() is None  # 区間が取れない


def test_perf_ring_whose_starts_are_all_the_same_has_no_rate_and_does_not_divide_by_zero():
    # 時計が粗いブラウザで、続けて呼ばれた更新。始まりの時刻が、全部同じになる。毎秒の回数は「測れていない」。
    ring = PerfRing(4)
    for _ in range(6):
        ring.add(5.0, 5.0)
    assert ring.count == 4 and ring.per_second() is None
    assert ring.mean_ms() == 0.0 and ring.max_ms() == 0.0  # 掛かった時間は、0 と測れている
    # 時計が戻った（区間が負）ときも、測れていない。
    back = PerfRing(4)
    back.add(5.0, 5.001)
    back.add(4.0, 4.001)
    assert back.per_second() is None
    # 1つでも進めば、測れる。
    ring.add(5.1, 5.1)
    assert ring.per_second() == pytest.approx(30.0)  # 4回の始まりが、0.1秒の間に並ぶ


@pytest.mark.parametrize("size", [0, -1, 1.5, True, None, "4"])
def test_perf_ring_needs_a_size_of_one_or_more(size):
    with pytest.raises(ValueError):
        PerfRing(size)


def test_perf_ring_of_one_keeps_only_the_newest_value():
    ring = PerfRing(1)
    ring.add(0.0, 0.003)
    ring.add(1.0, 1.007)
    assert ring.count == 1 and ring.mean_ms() == pytest.approx(7.0) and ring.max_ms() == pytest.approx(7.0) and ring.per_second() is None


# --- 実描画のある周期が、1 tickの長さを超えた回数（全部をためる測り方） ---
def test_perf_report_counts_the_cycles_with_a_render_that_ran_over_one_tick():
    # 周期は、直前の更新の始まりから、実描画の終わりまで。ふつうの周期（更新0.5 ms、2 ms後に実描画3 ms）は、5 msで、数えない。
    meter = PerfMeter()
    feed(meter, 120)
    report = meter.report()
    assert report["cycles_over_tick"] == 0 and report["cycle_ms_max"] == pytest.approx(5.0, abs=0.001)
    # 実描画が20 msかかった周期を、3回足す。
    for index in range(120, 126):
        start_s = index * TICK_S
        meter.on_update(start_s, start_s + 0.0005)
        if index % 2 == 1:
            meter.on_render(start_s + 0.002, start_s + 0.022)
    report = meter.report()
    assert report["cycles_over_tick"] == 3 and report["cycle_ms_max"] == pytest.approx(22.0, abs=0.001)
    assert perf.TICK_MS == pytest.approx(1000.0 / 60.0)


def test_perf_cycles_over_one_tick_leave_the_warmup_out():
    meter = PerfMeter(warmup_ticks=4)
    for index in range(10):
        start_s = index * TICK_S
        meter.on_update(start_s, start_s + 0.0005)
        if index % 2 == 1:
            meter.on_render(start_s + 0.002, start_s + (0.030 if index < 4 else 0.004))  # 慣らしの間の2回だけ、重い
    report = meter.report()
    assert report["cycles_over_tick"] == 0 and report["with_warmup"]["cycles_over_tick"] == 2
    empty = PerfMeter().report()
    assert empty["cycles_over_tick"] == 0 and empty["cycle_ms_max"] is None


# --- 処理時間の輪の値を、仮の表示の、処理時間の値にする ---
def filled_rings(update_ms: float = 0.34, render_ms: float = 2.44) -> tuple:
    """毎秒60回の更新（120回）と、毎秒30回の実描画（60回）を足した、2つの輪。"""
    update_ring, render_ring = PerfRing(UPDATE_RING), PerfRing(RENDER_RING)
    for index in range(UPDATE_RING):
        update_ring.add(index * TICK_S, index * TICK_S + update_ms / 1000.0)
    for index in range(RENDER_RING):
        render_ring.add(index * 2 * TICK_S, index * 2 * TICK_S + render_ms / 1000.0)
    return update_ring, render_ring


def test_perf_view_holds_whole_tenths_of_what_the_rings_measured():
    view = perf.view_of(*filled_rings(), 1.234, None)
    assert view == PerfView(3, 3, 24, 24, 600, 300, 12, None)  # 0.34 ms → 0.3、2.44 ms → 2.4、毎秒60.0回と30.0回、1.2秒
    assert all(value is None or type(value) is int for value in dataclasses.astuple(view))
    # ブラウザ版は、ページを開いてからの時間も渡る。
    assert perf.view_of(*filled_rings(), 0.26, 4.48).page_s_x10 == 45


def test_perf_view_of_empty_rings_is_not_measured_and_does_not_raise():
    # 最初の数tick。輪に、まだ値が無い。起動にかかった時間も、最初の更新までは、決まっていない。
    assert perf.view_of(PerfRing(UPDATE_RING), PerfRing(RENDER_RING), None, None) == PERF_NOT_MEASURED
    one = PerfRing(UPDATE_RING)
    one.add(0.0, 0.001)
    view = perf.view_of(one, PerfRing(RENDER_RING), 0.5, None)
    assert (view.update_mean_ms_x10, view.updates_per_s_x10, view.render_mean_ms_x10, view.boot_s_x10) == (10, None, None, 5)


def test_perf_view_caps_the_values_at_the_digits_of_the_placeholder():
    # 表示の桁を超えた値は、桁いっぱいに頭打ちにして渡す（例外にしない）。桁は、画面の側の定数。
    update_ring, render_ring = PerfRing(4), PerfRing(4)
    for index in range(4):
        update_ring.add(index * 1e-6, index * 1e-6 + 5.0)  # 更新1回が5秒。毎秒100万回の始まり
        render_ring.add(index * 1e-6, index * 1e-6 + 0.5)
    view = perf.view_of(update_ring, render_ring, 86400.0, float("inf"))
    widest_ms, widest_rate, widest_s = (10 ** (digits + 1) - 1 for digits in (screens.MS_DIGITS, screens.RATE_DIGITS, screens.SECONDS_DIGITS))
    assert view == PerfView(widest_ms, widest_ms, widest_ms, widest_ms, widest_rate, widest_rate, widest_s, widest_s)
    assert view == fixtures.build("placeholder", "extreme").perf  # 見本データの極端な値と同じ
