"""処理時間と回数の集計（cp_app.perf）のテスト。時計は使わず、実時間（秒）を引数で渡す。"""
import pytest

from cp_app.perf import PerfMeter, percentile

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
