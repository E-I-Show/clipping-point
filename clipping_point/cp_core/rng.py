"""乱数（純Python）。決まりは docs/design/overview.md の「決定性と保存」。

整数だけで作る（splitmix64）。デスクトップ版とブラウザ版で、同じ列になる。道具は2つ。
  乱数の流れ（RngStream、RngSet）       用途ごとに分けた乱数の列。状態は整数1個。用途の名は PURPOSES に登録する。
  ハッシュの抽選（hash_u64、hash_unit）  種と鍵から決まる、状態を持たない抽選。同じ種と鍵には、何度でも同じ値を返す。
新しく足す仕組みの抽選は、ハッシュの抽選を使い、いまある流れを引かない（流れを引くと、その後ろの値が全部ずれて、指紋が動く）。
ハッシュの抽選は、1回に、デスクトップ版で1〜3マイクロ秒、ブラウザ版で3〜9マイクロ秒かかる（鍵が4個で、うち2個が文字列のときが
いちばん遅い。この環境での実測）。毎tick、毎輪の内側では呼ばず、1度引いた値を持っておく。流れの unit() は、0.5 と 1.2 マイクロ秒。
標準の乱数（random）と、組み込みの hash()（文字列に対して、プロセスごとに違う値を返す）は使わない（層の分離の検査が拾う）。
[0, 1) の小数は、上位53ビットを 2**53 で割って作る。2の累乗での割り算なので、どの環境でも同じ値になる。
"""
import zlib

MASK_64 = (1 << 64) - 1
GAMMA = 0x9E3779B97F4A7C15  # splitmix64 の、状態の増分
MIX_1, MIX_2 = 0xBF58476D1CE4E5B9, 0x94D049BB133111EB  # splitmix64 の、かき混ぜの掛け数
TWO_53 = 9007199254740992.0  # 2**53
# 用途の名。足すときは、末尾に足す（並びは、世界の要約の項目の順になる）。いまは、AIのばらつきだけ（引く所は段3で作る）。
PURPOSES = ("ai",)
STREAM_KEY = "stream"  # 流れの始まりの状態を、種から作るときの鍵の頭


def _mix(z: int) -> int:
    z = ((z ^ (z >> 30)) * MIX_1) & MASK_64
    z = ((z ^ (z >> 27)) * MIX_2) & MASK_64
    return z ^ (z >> 31)


def _seed(seed) -> int:
    """種。bool でない整数だけを受ける。"""
    if type(seed) is not int:
        raise TypeError(f"seed={seed!r} must be int (bool and float are not accepted)")
    return seed


def _key(key) -> int:
    """ハッシュの抽選の鍵を、整数にする。受けるのは、bool でない整数と、文字列だけ。"""
    if type(key) is int:
        return key & MASK_64
    if type(key) is str:
        # 文字列は crc32 と長さから作る。組み込みの hash() は、プロセスごとに違う値を返すので使わない。
        return zlib.crc32(key.encode("utf-8")) | (len(key) << 32)
    raise TypeError(f"hash key must be int or str, got {type(key).__name__} ({key!r})")


def hash_u64(seed: int, *keys) -> int:
    """種と鍵の並びから決まる、64ビットの整数。状態を持たない。鍵の順を替えると、違う値になる。"""
    value = _mix((_seed(seed) + GAMMA) & MASK_64)
    for key in keys:
        value = _mix(((value ^ _key(key)) + GAMMA) & MASK_64)
    return value


def hash_unit(seed: int, *keys) -> float:
    """種と鍵の並びから決まる、[0, 1) の小数。"""
    return (hash_u64(seed, *keys) >> 11) / TWO_53


class RngStream:
    """乱数の流れの1本（splitmix64）。状態は、整数1個（state）。"""

    __slots__ = ("state",)

    def __init__(self, state: int) -> None:
        self.state = _seed(state) & MASK_64

    def next_u64(self) -> int:
        """次の、64ビットの整数。"""
        self.state = (self.state + GAMMA) & MASK_64
        return _mix(self.state)

    def unit(self) -> float:
        """次の、[0, 1) の小数。"""
        return (self.next_u64() >> 11) / TWO_53

    def uniform(self, low: float, high: float) -> float:
        """次の、[low, high) の小数。"""
        return low + (high - low) * self.unit()

    def below(self, n: int) -> int:
        """次の、0以上 n 未満の整数。"""
        if type(n) is not int:
            raise TypeError(f"n={n!r} must be int")
        if n <= 0:
            raise ValueError(f"n={n!r} must be positive")
        # 割り切り：余りで取るので、n が2の累乗でないと、ごくわずかに偏る（n が 2**24 未満なら 2**-40 未満）。
        # 偏りが効く使い方（大きい n）が出てきた時に見直す。
        return self.next_u64() % n

    def shuffle(self, items: list) -> None:
        """並びを、その場で混ぜる（後ろから、前のどれかと入れ替える）。"""
        for index in range(len(items) - 1, 0, -1):
            other = self.below(index + 1)
            items[index], items[other] = items[other], items[index]


class RngSet:
    """用途ごとの、乱数の流れの組。流れを1本引いても、ほかの流れは動かない。登録の無い用途の名は KeyError。"""

    def __init__(self, seed: int) -> None:
        self.seed = _seed(seed)
        self._streams = {name: RngStream(hash_u64(seed, STREAM_KEY, name)) for name in PURPOSES}

    def stream(self, name: str) -> RngStream:
        """用途の名の流れ。PURPOSES に無い名は KeyError（黙って新しい流れを作らない）。"""
        if name not in self._streams:
            raise KeyError(f"unknown rng purpose {name!r} (registered: {PURPOSES})")
        return self._streams[name]

    def state(self) -> dict:
        """全部の流れの状態。{用途の名: 整数}。並びは PURPOSES の順。"""
        return {name: stream.state for name, stream in self._streams.items()}

    def restore(self, state: dict) -> None:
        """state() で取った状態へ戻す。用途の名が合わない、値が64ビットの整数でない、のどちらでも、何も変えずに例外。"""
        if type(state) is not dict or set(state) != set(self._streams):
            raise ValueError(f"rng state must have exactly the purposes {PURPOSES}, got {state!r}")
        for name, value in state.items():
            if type(value) is not int:
                raise TypeError(f"rng state of {name!r} must be int, got {value!r}")
            if not 0 <= value <= MASK_64:
                raise ValueError(f"rng state of {name!r} must be in 0..2**64-1, got {value!r}")
        for name, value in state.items():
            self._streams[name].state = value
