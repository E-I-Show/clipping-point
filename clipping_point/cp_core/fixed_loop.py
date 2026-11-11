"""固定刻みのループの決まり。実描画するかどうかの判定（純Python）。

更新は毎秒60回で、Pyxelの更新1回が1 tick。実描画は毎秒30回に間引く。
ここでは時計を読まない。実時間は呼ぶ側（cp_app）が引数で渡す。
"""

TICK_HZ = 60  # 1 tick = 1/60秒。設計の前提（仮の値にしない）
RENDER_HZ = 30  # 実描画は毎秒30回。設計の前提（仮の値にしない）
RENDER_DIVISOR = TICK_HZ // RENDER_HZ  # 実描画1回あたりのtick数（2）
# 実時間の決まりに使う間。実描画の周期（33.3 ms）より少し短く、60 Hzの周期が2つ続くときの
# 最長の間（75 Hzの画面で26.7 ms）より長い。設計の「メインループ」の値。
RENDER_MIN_INTERVAL_MS = 30.0


class RenderGate:
    """描画の呼び出しごとに、重い実描画を行うかどうかを決める。

    実描画する条件は次のどちらか。
      (1) 前回の実描画から divisor tick以上たった。
      (2) 前回の実描画から1 tick以上たち、かつ実時間で min_interval_ms 以上たった。

    フレーム番号の偶奇で間引かない理由：Pyxelは処理落ちから追い付く間、描画1回につき更新を
    2回呼ぶ。描画から見える偶奇が固定され、実描画が0回か毎回になる（試作の実測）。

    (2) を置く理由：ブラウザ版は遅れた周期を1つ後の呼び出しで知らせる。(1) だけだと、
    毎秒30回が入る場面で毎秒20回に落ち着く。実描画は世界の進行に戻らないので、
    ここで実時間を使っても、同じ入力から同じ結果が出ることは変わらない。
    """

    def __init__(self, divisor: int = RENDER_DIVISOR, min_interval_ms: float | None = RENDER_MIN_INTERVAL_MS) -> None:
        if divisor < 1:
            raise ValueError("divisor must be >= 1")
        self.divisor = divisor
        self.min_interval_ms = min_interval_ms  # None なら (2) を使わない
        self._ticks_since_render = divisor  # 最初の描画の呼び出しで必ず実描画する
        self._last_render_ms: float | None = None

    def on_tick(self) -> None:
        """更新を1 tick進めるたびに呼ぶ。"""
        self._ticks_since_render += 1

    def should_render(self, now_ms: float | None = None) -> bool:
        """描画の呼び出しごとに1度呼ぶ。Trueなら実描画し、数え直す。

        now_ms は呼ぶ側が読んだ実時間（ミリ秒）。渡さなければ (1) だけで決める。
        """
        due = self._ticks_since_render >= self.divisor
        if (
            not due
            and now_ms is not None
            and self.min_interval_ms is not None
            and self._last_render_ms is not None
            and self._ticks_since_render >= 1  # 新しいtickが無ければ、同じ絵を描き直さない
        ):
            due = now_ms - self._last_render_ms >= self.min_interval_ms
        if due:
            self._ticks_since_render = 0
            self._last_render_ms = now_ms
        return due
