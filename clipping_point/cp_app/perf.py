"""更新1回と実描画1回の時間と、毎秒の回数を集める（cp_app の中だけで使う）。

時計は読まない。実時間（秒）は呼ぶ側（app.py）が渡す。pyxel も読み込まない。
測った値は、見た目と検証のためのもの。世界（Sim）へは渡さない。同じ入力から同じ結果を出す決まりの外にある。
いまは、ブラウザ版の煙テストが回すtick数を渡したときだけ使う。画面に出す表示は、段0 区切り10で足す。
"""

P95 = 0.95


def percentile(values: list, fraction: float):
    """小さい順に並べて、頭から fraction の所の値。値が無ければ None。"""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * fraction))]


class PerfMeter:
    """更新と実描画の、始まりと終わりの実時間を受けて、要約を作る。

    頭の warmup_ticks 回の更新と、その間の実描画は測らない。起動の直後は、ブラウザ版のPythonが遅いため。
    """

    def __init__(self, warmup_ticks: int = 0) -> None:
        if warmup_ticks < 0:
            raise ValueError("warmup_ticks must be >= 0")
        self.warmup_ticks = warmup_ticks
        self._updates_seen = 0
        self._update_starts_s: list = []
        self._update_ms: list = []
        self._render_starts_s: list = []
        self._render_ms: list = []

    def on_update(self, start_s: float, end_s: float) -> None:
        """更新1回ごとに呼ぶ。"""
        self._updates_seen += 1
        if self._updates_seen > self.warmup_ticks:
            self._update_starts_s.append(start_s)
            self._update_ms.append((end_s - start_s) * 1000.0)

    def on_render(self, start_s: float, end_s: float) -> None:
        """実描画1回ごとに呼ぶ。"""
        if self._updates_seen > self.warmup_ticks:
            self._render_starts_s.append(start_s)
            self._render_ms.append((end_s - start_s) * 1000.0)

    def report(self) -> dict:
        """要約。測った区間は、測った最初の更新の始まりから、最後の更新の始まりまで。

        毎秒の回数は、区間が取れなければ None。時間は、1回も測っていなければ None。
        """
        updates = len(self._update_starts_s)
        span_s = self._update_starts_s[-1] - self._update_starts_s[0] if updates >= 2 else 0.0
        first_s = self._update_starts_s[0] if updates else 0.0
        # 実描画は、区間の中で始まったものだけを数える（区間の終わりちょうどは入れない）。
        renders_in_span = sum(1 for start_s in self._render_starts_s if first_s <= start_s < first_s + span_s)
        update_p95 = percentile(self._update_ms, P95)
        render_p95 = percentile(self._render_ms, P95)
        return {
            "updates": updates,
            "renders": len(self._render_ms),
            "span_s": round(span_s, 3),
            "updates_per_s": round((updates - 1) / span_s, 2) if span_s > 0 else None,
            "renders_per_s": round(renders_in_span / span_s, 2) if span_s > 0 else None,
            "update_ms_p95": None if update_p95 is None else round(update_p95, 3),
            "render_ms_p95": None if render_p95 is None else round(render_p95, 3),
        }
