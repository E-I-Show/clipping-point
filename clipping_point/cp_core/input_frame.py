"""入力フレームと、その量子化（純Python）。決まりは docs/design/overview.md の「入力アダプタと入力フレーム」。

入力フレームは、毎tick 1度だけ入力を読んで作る、正規化した入力。機器ごとの差は入力アダプタ（cp_app）が吸収する。
アナログ値（小数）とデジタル値（整数）を並べて持つ。どちらを使うかは、ここでは決めない（決めるのは操作補正。段1）。
舵は左が正。値の範囲をそろえるだけで、遊びの除去と応答カーブは入れない。
「押した瞬間」は、作る側（入力アダプタか台本）が決める。受ける側は、押した瞬間だけを見て動く。
「押している」の立ち上がりを、受ける側で見ない（導き方が、入力アダプタと台本で1通りでないため）。
量子化と畳み込みは整数で行う。丸めの前の計算は掛け算だけにする（デスクトップ版とブラウザ版で同じ結果になる）。
"""
import math
from dataclasses import dataclass

# ボタンの名。並びは量子化のビットの順（頭が最下位のビット）。足すときは末尾に足す。
BUTTONS = ("shift_up", "shift_down", "view", "pause", "up", "down", "left", "right", "confirm", "back")
# 量子化した8個の整数の並び。入力フレームの項目の並びと同じ。
QUANTIZED_FIELDS = (
    "steer_analog", "steer_digital", "throttle_analog", "throttle_digital", "brake_analog", "brake_digital", "held", "pressed",
)
ANALOG_SCALE = 1000  # アナログ値は、千分率の整数に丸める
DIGEST_START = 2166136261  # 畳み込みの始まりの値
DIGEST_PRIME = 16777619
MASK_32 = 0xFFFFFFFF


def _analog(name: str, value, low: float, high: float) -> float:
    """アナログ値。bool でない整数は受けて、小数に直す（JavaScriptを通ると 1.0 が 1 になって届くため）。"""
    if type(value) is int:
        value = float(value)
    if type(value) is not float:
        raise TypeError(f"{name}={value!r} must be float (int is accepted, bool is not)")
    if math.isnan(value) or not low <= value <= high:
        raise ValueError(f"{name}={value!r} must be in {low}..{high}")
    return value


def _digital(name: str, value, allowed: tuple) -> int:
    """デジタル値。bool と小数は受けない。"""
    if type(value) is not int:
        raise TypeError(f"{name}={value!r} must be int (bool and float are not accepted)")
    if value not in allowed:
        raise ValueError(f"{name}={value!r} must be one of {allowed}")
    return value


def _buttons(name: str, value) -> frozenset:
    """ボタンの名の集まり。frozenset に直す。文字列1つは受けない（1文字ずつに割れるため）。"""
    if type(value) not in (frozenset, set, tuple, list):
        raise TypeError(f"{name}={value!r} must be a frozenset of button names")
    for item in value:
        if type(item) is not str:
            raise TypeError(f"{name} has a non-str entry: {item!r}")
    names = frozenset(value)
    unknown = sorted(names - set(BUTTONS))
    if unknown:
        raise ValueError(f"{name} has unknown button names: {unknown}")
    return names


@dataclass(frozen=True)
class InputFrame:
    """1 tick分の入力。作るときに、型、範囲、NaN、知らない名前を検査する。項目の並びは QUANTIZED_FIELDS と同じ。"""

    steer_analog: float = 0.0  # 舵のアナログ値。−1〜1、左が正
    steer_digital: int = 0  # 舵のデジタル値。−1、0、1、左が正
    throttle_analog: float = 0.0  # アクセルのアナログ値。0〜1
    throttle_digital: int = 0  # アクセルのデジタル値。0か1
    brake_analog: float = 0.0  # ブレーキのアナログ値。0〜1
    brake_digital: int = 0  # ブレーキのデジタル値。0か1
    held: frozenset = frozenset()  # 押しているボタンの名
    pressed: frozenset = frozenset()  # 押した瞬間のボタンの名。held に無い名もありうる（1回の更新の中で押して離した）

    def __post_init__(self) -> None:
        put = object.__setattr__  # 書き換えられない dataclass なので、検査して直した値はこの口で置く
        put(self, "steer_analog", _analog("steer_analog", self.steer_analog, -1.0, 1.0))
        put(self, "steer_digital", _digital("steer_digital", self.steer_digital, (-1, 0, 1)))
        put(self, "throttle_analog", _analog("throttle_analog", self.throttle_analog, 0.0, 1.0))
        put(self, "throttle_digital", _digital("throttle_digital", self.throttle_digital, (0, 1)))
        put(self, "brake_analog", _analog("brake_analog", self.brake_analog, 0.0, 1.0))
        put(self, "brake_digital", _digital("brake_digital", self.brake_digital, (0, 1)))
        put(self, "held", _buttons("held", self.held))
        put(self, "pressed", _buttons("pressed", self.pressed))


NEUTRAL = InputFrame()  # 何も押していない入力フレーム


def button_bits(names) -> int:
    """ボタンの名の集まりを、BUTTONS の並びのビットにする。"""
    return sum(1 << index for index, name in enumerate(BUTTONS) if name in names)


def button_names(bits: int) -> tuple:
    """button_bits の逆。BUTTONS の並びで返す。BUTTONS に無いビットが立っていれば ValueError。"""
    if type(bits) is not int:
        raise TypeError(f"bits={bits!r} must be int")
    if not 0 <= bits < 1 << len(BUTTONS):
        raise ValueError(f"bits={bits!r} has bits outside BUTTONS")
    return tuple(name for index, name in enumerate(BUTTONS) if bits >> index & 1)


def quantize(frame: InputFrame) -> tuple:
    """入力フレームを、8個の整数の組にする。並びは QUANTIZED_FIELDS。比較と保存は、この整数で行う。"""
    return (
        round(frame.steer_analog * ANALOG_SCALE),
        frame.steer_digital,
        round(frame.throttle_analog * ANALOG_SCALE),
        frame.throttle_digital,
        round(frame.brake_analog * ANALOG_SCALE),
        frame.brake_digital,
        button_bits(frame.held),
        button_bits(frame.pressed),
    )


def fold(digest: int, values) -> int:
    """整数の列を、32ビットの整数に畳み込む。同じ列からは同じ値、順を替えると違う値になる。始まりは DIGEST_START。"""
    if type(digest) is not int:
        raise TypeError(f"digest={digest!r} must be int")
    for value in values:
        if type(value) is not int:
            raise TypeError(f"fold takes integers only, got {value!r}")
        digest = ((digest ^ (value & MASK_32)) * DIGEST_PRIME) & MASK_32
    return digest
