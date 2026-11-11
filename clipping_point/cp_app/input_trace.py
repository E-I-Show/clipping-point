"""入力の跡。検証のときに、入力フレームの変わり目を残す（cp_app の中だけで使う）。

pyxel も js もimportしない。残した値は、検証のためのもの。世界（Sim）へは渡さない。
ブラウザ版の煙テストが、台本や偽のコントローラーの予定と照らす。外から頼まれたとき（window.CP_PROBE の trace_max が1以上）だけ使う。
残すのは、量子化した値（8個の整数。並びは cp_core.input_frame の QUANTIZED_FIELDS）が、前のtickと違ったtickだけ。
頭のtick 0は必ず入る。件数が上限に届いたら、打ち切り（truncated）を立てて、後は取らない。
打ち切られた入力の跡からは、列を戻せない（最後の値が続いたのか、取っていないのかを、見分けられない）。
形：{"changes": [[tick, [量子化した8個の整数]], …], "truncated": false}
"""
from cp_core.input_frame import QUANTIZED_FIELDS


class InputTrace:
    """入力フレームの変わり目を、上限の件数まで残す。"""

    def __init__(self, max_changes: int) -> None:
        if type(max_changes) is not int or max_changes < 1:
            raise ValueError(f"max_changes must be an integer >= 1, got {max_changes!r}")
        self.max_changes = max_changes
        self.truncated = False
        self._changes: list = []  # [(tick, 量子化した値の組), …]
        self._last = None  # 直前のtickの値

    def on_tick(self, tick: int, values: tuple) -> None:
        """更新1回ごとに呼ぶ。tick は、0始まりの更新の番号。values は、そのtickの入力フレームを量子化した値。"""
        if self.truncated or values == self._last:
            return
        self._last = values
        self._changes.append((tick, tuple(values)))
        if len(self._changes) >= self.max_changes:
            self.truncated = True

    def report(self) -> dict:
        """結果に足す形（JSONにそのまま書ける）。"""
        return {"changes": [[tick, list(values)] for tick, values in self._changes], "truncated": self.truncated}


def expand(report, ticks: int) -> list:
    """入力の跡（report() の形）を、tick 0 から ticks−1 までの、tickごとの値の組の列に戻す。

    形が違えば ValueError。打ち切られた跡、頭がtick 0でない跡、tickが増えていない跡、ticks 以上のtickを持つ跡は戻さない。
    """
    if not isinstance(report, dict) or report.get("truncated") is not False:
        raise ValueError("input trace is missing or truncated")
    changes = report.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("input trace has no changes (tick 0 is always recorded)")
    rows: list = []
    for change in changes:
        if not isinstance(change, list) or len(change) != 2:
            raise ValueError(f"input trace entry must be [tick, values], got {change!r}")
        tick, values = change
        # 頭はtick 0。その後は、前の変わり目より後のtick（rows の長さが、次に来てよい最小のtick）。
        if type(tick) is not int or tick >= ticks or (tick < len(rows) if rows else tick != 0):
            raise ValueError(f"input trace tick {tick!r} is out of order or out of range (ticks={ticks})")
        if not isinstance(values, list) or len(values) != len(QUANTIZED_FIELDS) or any(type(v) is not int for v in values):
            raise ValueError(f"input trace values must be {len(QUANTIZED_FIELDS)} integers, got {values!r}")
        if rows:
            rows += [rows[-1]] * (tick - len(rows))  # 変わり目の手前までは、前の値が続く
        rows.append(tuple(values))
    rows += [rows[-1]] * (ticks - len(rows))
    return rows
