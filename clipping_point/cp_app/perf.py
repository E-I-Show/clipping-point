"""更新1回と実描画1回の時間と、毎秒の回数を集める（cp_app の中だけで使う）。

時計は読まない。実時間（秒）は呼ぶ側（app.py）が渡す。pyxel も読み込まない。
測った値は、見た目と検証のためのもの。世界（Sim）へは渡さない。同じ入力から同じ結果を出す決まりの外にある。
測り方は、2つある。
  処理時間の輪（PerfRing）  直近の決まった回数ぶん（更新は UPDATE_RING 回、実描画は RENDER_RING 回）だけを持つ。ふつうの起動でも回し、
                            画面に出す、平均と最大と、毎秒の回数に使う。上限のないリストに、ためない
  全部をためる測り方（PerfMeter）  検証の口があるときだけ使う。煙テストの線の判定（95%点、毎秒の回数）に使う。要約には、平均と最大も出す
処理時間の輪の値を、仮の表示の、処理時間の値（cp_core.flow の PerfView）にするのは view_of()。表示の桁（cp_ui.screens の
MS_DIGITS、RATE_DIGITS、SECONDS_DIGITS）を超えた値は、桁いっぱいに頭打ちにして渡す（例外にしない）。
"""
from cp_core.fixed_loop import TICK_HZ
from cp_core.flow import PerfView, capped_tenths
from cp_ui.screens import MS_DIGITS, RATE_DIGITS, SECONDS_DIGITS

P95 = 0.95
TICK_MS = 1000.0 / TICK_HZ  # 1 tickの長さ（ms）
UPDATE_RING = 120  # 処理時間の輪が持つ、更新の回数（毎秒60回なら、直近の2秒）
RENDER_RING = 60  # 同じく、実描画の回数（毎秒30回なら、直近の2秒）


def percentile(values: list, fraction: float):
    """小さい順に並べて、頭から fraction の所の値。値が無ければ None。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


def _rounded(value):
    """要約に出す時間（ms）。無ければ None。"""
    return None if value is None else round(value, 3)


def summarize(update_starts_s: list, update_ms: list, render_starts_s: list, render_ms: list, cycle_ms=()) -> dict:
    """更新と実描画の、始まりの実時間と掛かった時間の並びから、要約を作る。

    区間は、最初の更新の始まりから、最後の更新の始まりまで。
    毎秒の回数は、区間が取れなければ None。時間（95%点、平均、最大）は、1回も無ければ None。
    cycle_ms は、実描画のある周期の長さ（ms）の並び。1 tickの長さを超えた回数（cycles_over_tick）と、最大（cycle_ms_max）を出す。
    """
    updates = len(update_starts_s)
    span_s = update_starts_s[-1] - update_starts_s[0] if updates >= 2 else 0.0
    first_s = update_starts_s[0] if updates else 0.0
    # 実描画は、区間の中で始まったものだけを数える（区間の終わりちょうどは入れない）。
    renders_in_span = sum(1 for start_s in render_starts_s if first_s <= start_s < first_s + span_s)
    return {
        "updates": updates,
        "renders": len(render_ms),
        "span_s": round(span_s, 3),
        "updates_per_s": round((updates - 1) / span_s, 2) if span_s > 0 else None,
        "renders_per_s": round(renders_in_span / span_s, 2) if span_s > 0 else None,
        "update_ms_p95": _rounded(percentile(update_ms, P95)),
        "render_ms_p95": _rounded(percentile(render_ms, P95)),
        "update_ms_mean": _rounded(sum(update_ms) / len(update_ms)) if update_ms else None,
        "render_ms_mean": _rounded(sum(render_ms) / len(render_ms)) if render_ms else None,
        "update_ms_max": _rounded(max(update_ms)) if update_ms else None,
        "render_ms_max": _rounded(max(render_ms)) if render_ms else None,
        "cycles_over_tick": sum(1 for took_ms in cycle_ms if took_ms > TICK_MS),
        "cycle_ms_max": _rounded(max(cycle_ms)) if cycle_ms else None,
    }


class PerfRing:
    """処理時間の輪。直近の size 回ぶんの、始まりの実時間と、掛かった時間だけを持つ。古い値は、捨てる。

    時計は読まない。始まりと終わりの実時間（秒）は、呼ぶ側が渡す。値が無いとき、区間が取れないときは、None（測れていない）を返す。
    例外にはしない（ふつうの起動の、更新か実描画の中で呼ぶ）。
    """

    def __init__(self, size: int) -> None:
        if type(size) is not int or size < 1:
            raise ValueError(f"size={size!r} must be an integer >= 1")
        self.size = size
        self._starts_s = [0.0] * size  # 始まりの実時間（秒）。輪
        self._took_ms = [0.0] * size  # 掛かった時間（ms）。輪
        self._next = 0  # 次に書く所
        self.count = 0  # 持っている回数（size まで）

    def add(self, start_s: float, end_s: float) -> None:
        """1回ぶんを足す。輪がいっぱいなら、いちばん古い値を捨てる。"""
        self._starts_s[self._next] = start_s
        self._took_ms[self._next] = (end_s - start_s) * 1000.0
        self._next = (self._next + 1) % self.size
        if self.count < self.size:
            self.count += 1

    def _held(self, values: list) -> list:
        """持っている値を、古い順に並べたもの。"""
        if self.count < self.size:
            return values[:self.count]
        return values[self._next:] + values[:self._next]

    def mean_ms(self):
        """直近の、掛かった時間の平均（ms）。1回も無ければ None。"""
        return sum(self._held(self._took_ms)) / self.count if self.count else None

    def max_ms(self):
        """直近の、掛かった時間の最大（ms）。1回も無ければ None。"""
        return max(self._held(self._took_ms)) if self.count else None

    def per_second(self):
        """直近の区間の、毎秒の回数。区間は、持っている中で、いちばん古い始まりから、いちばん新しい始まりまで。

        2回に満たないときと、区間が0以下のとき（始まりの時刻が、全部同じ。時計が粗いブラウザで、続けて呼ばれた更新）は、
        None（測れていない）。0で割らない。
        """
        if self.count < 2:
            return None
        starts = self._held(self._starts_s)
        span_s = starts[-1] - starts[0]
        return (self.count - 1) / span_s if span_s > 0 else None


def view_of(update_ring: PerfRing, render_ring: PerfRing, boot_s, page_s) -> PerfView:
    """処理時間の輪の値と、起動にかかった時間から、仮の表示の、処理時間の値を作る。値は、0.1 刻みの整数か、None（測れていない）。

    boot_s は、アプリの起動にかかった時間（秒。main() の始まりから、最初の更新まで）。page_s は、ブラウザ版だけ、ページを開いてから
    main() が始まるまで（秒）。デスクトップ版は None。表示の桁を超えた値は、桁いっぱいに頭打ちにする。
    """
    return PerfView(
        update_mean_ms_x10=capped_tenths(update_ring.mean_ms(), MS_DIGITS),
        update_max_ms_x10=capped_tenths(update_ring.max_ms(), MS_DIGITS),
        render_mean_ms_x10=capped_tenths(render_ring.mean_ms(), MS_DIGITS),
        render_max_ms_x10=capped_tenths(render_ring.max_ms(), MS_DIGITS),
        updates_per_s_x10=capped_tenths(update_ring.per_second(), RATE_DIGITS),
        renders_per_s_x10=capped_tenths(render_ring.per_second(), RATE_DIGITS),
        boot_s_x10=capped_tenths(boot_s, SECONDS_DIGITS),
        page_s_x10=capped_tenths(page_s, SECONDS_DIGITS),
    )


class PerfMeter:
    """更新と実描画の、始まりと終わりの実時間を受けて、要約を作る。

    頭の warmup_ticks 回の更新と、その間の実描画は、慣らしとして要約から除く。起動の直後は、
    ブラウザ版のPythonが遅いため。除かない値も、要約の with_warmup に並べて出す。
    """

    def __init__(self, warmup_ticks: int = 0) -> None:
        if warmup_ticks < 0:
            raise ValueError("warmup_ticks must be >= 0")
        self.warmup_ticks = warmup_ticks
        self._update_starts_s: list = []
        self._update_ms: list = []
        self._render_starts_s: list = []
        self._render_ms: list = []
        self._renders_in_warmup = 0  # 慣らしの間の実描画の数
        self._cycle_ms: list = []  # 実描画のある周期の長さ（ms）。直前の更新の始まりから、実描画の終わりまで

    def on_update(self, start_s: float, end_s: float) -> None:
        """更新1回ごとに呼ぶ。"""
        self._update_starts_s.append(start_s)
        self._update_ms.append((end_s - start_s) * 1000.0)

    def on_render(self, start_s: float, end_s: float) -> None:
        """実描画1回ごとに呼ぶ。"""
        if len(self._update_ms) <= self.warmup_ticks:
            self._renders_in_warmup += 1
        self._render_starts_s.append(start_s)
        self._render_ms.append((end_s - start_s) * 1000.0)
        # 実描画のある周期。更新が1度も無ければ、実描画だけの長さ。
        cycle_start_s = self._update_starts_s[-1] if self._update_starts_s else start_s
        self._cycle_ms.append((end_s - cycle_start_s) * 1000.0)

    def report(self) -> dict:
        """要約。頭の慣らしを除いた値と、除かない値（with_warmup）。

        cycles_over_tick は、実描画のある周期（直前の更新の始まりから、実描画の終わりまで）が、1 tickの長さ（1/60秒）を超えた回数。
        cycle_ms_max は、その周期の最大（アプリが実時間を、実描画の判定へ渡していないと、こういう周期で、実描画の回数が落ちる。
        規則ファイル sim-core.md）。
        """
        skip_u, skip_r = self.warmup_ticks, self._renders_in_warmup
        measured = summarize(
            self._update_starts_s[skip_u:], self._update_ms[skip_u:], self._render_starts_s[skip_r:], self._render_ms[skip_r:], self._cycle_ms[skip_r:],
        )
        measured["with_warmup"] = summarize(self._update_starts_s, self._update_ms, self._render_starts_s, self._render_ms, self._cycle_ms)
        return measured
