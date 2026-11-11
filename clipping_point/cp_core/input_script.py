"""台本（純Python）。入力フレームを時刻順に書いたもの。テストと画面なしの実行で、入力フレームをそのまま差し込む。

形は、JSONにそのまま書ける辞書。
  {"segments": [{"ticks": 30, "steer_analog": 0.5, "throttle_digital": 1, "held": ["shift_up"]}, …]}
  ticks   必須。その入力が続くtick数（1以上の整数）
  ほか    入力フレームの6つの値（VALUE_KEYS）と held（ボタンの名の並び）。省けば0と空
「押した瞬間」（pressed）は書けない。区間の最初のtickで、前の区間（頭なら何も押していない状態）で
押していなかったボタンとして導く。同じボタンを2度押すには、間に、そのボタンを押していない区間を置く。
知らない鍵、型の違い、範囲の外、空の segments は ValueError。アナログ値の整数は受ける（入力フレームと同じ）。
ここではファイルを読まない。読むのは cp_app と道具で、ここは辞書を受けるだけ。
"""
from bisect import bisect_right
from dataclasses import replace

from cp_core.input_frame import NEUTRAL, InputFrame

TOP_KEYS = ("segments",)
VALUE_KEYS = ("steer_analog", "steer_digital", "throttle_analog", "throttle_digital", "brake_analog", "brake_digital")
SEGMENT_KEYS = ("ticks", *VALUE_KEYS, "held")


class InputScript:
    """検査済みの台本。parse() で作る。"""

    def __init__(self, segments: list) -> None:
        """segments は [(tick数, 押しているだけの入力フレーム), …]。検査は parse() が済ませている。"""
        self._starts: list = []  # 区間の最初のtick
        self._ends: list = []  # 区間の次のtick（区間に入らない）
        self._first: list = []  # 区間の最初のtickの入力フレーム（押した瞬間つき）
        self._rest: list = []  # 区間の残りのtickの入力フレーム
        start, previous_held = 0, frozenset()
        for ticks, frame in segments:
            self._starts.append(start)
            start += ticks
            self._ends.append(start)
            self._first.append(replace(frame, pressed=frame.held - previous_held))
            self._rest.append(frame)
            previous_held = frame.held
        self.total_ticks = start  # 台本の合計のtick数

    def frame_at(self, tick: int) -> InputFrame:
        """tick（0始まり。世界のtickが n のときに渡すのが n 番目）の入力フレーム。台本を過ぎたら NEUTRAL。"""
        if type(tick) is not int:
            raise TypeError(f"tick={tick!r} must be int")
        if tick < 0:
            raise ValueError(f"tick={tick!r} must be >= 0")
        if tick >= self.total_ticks:
            return NEUTRAL
        index = bisect_right(self._ends, tick)
        return self._first[index] if tick == self._starts[index] else self._rest[index]


def parse(value) -> InputScript:
    """辞書を検査して、台本を返す。形が違えば ValueError。"""
    if not isinstance(value, dict):
        raise ValueError(f"input script must be an object, got {type(value).__name__}")
    unknown = sorted(str(key) for key in set(value) - set(TOP_KEYS))
    if unknown:
        raise ValueError(f"input script has unknown keys: {unknown}")
    raw_segments = value.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("input script needs a non-empty list 'segments'")
    segments = []
    for index, raw in enumerate(raw_segments):
        where = f"segments[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where} must be an object, got {type(raw).__name__}")
        unknown = sorted(str(key) for key in set(raw) - set(SEGMENT_KEYS))
        if unknown:
            # pressed は書けない。前の区間で押していなかったボタンとして導く。
            raise ValueError(f"{where} has unknown keys: {unknown}")
        ticks = raw.get("ticks")
        if type(ticks) is not int or ticks < 1:  # bool と小数を受けない
            raise ValueError(f"{where}.ticks must be an integer >= 1, got {ticks!r}")
        held = raw.get("held", [])
        if not isinstance(held, list):
            raise ValueError(f"{where}.held must be a list of button names, got {held!r}")
        values = {key: raw[key] for key in VALUE_KEYS if key in raw}
        try:
            frame = InputFrame(held=frozenset(held), **values)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{where}: {exc}") from exc
        if len(frame.held) != len(held):
            raise ValueError(f"{where}.held names a button twice: {held!r}")
        segments.append((ticks, frame))
    return InputScript(segments)
