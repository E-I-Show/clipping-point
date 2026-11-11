"""Deterministic random numbers. Integer-only, so results are bit-identical on every platform.

Two tools:
  RngStream / RngSet  - one sequential stream per purpose ("grid", "ai", ...). State = one int.
  hash_u64 / hash_unit - a stateless draw from (seed, keys...). Use it for every NEW feature and
                         for anything that must give the same answer when a replay is rewound:
                         it consumes nothing from the streams, so existing fingerprints stay put.
The standard `random` module and the built-in hash() (salted per process for str) are forbidden
in cp_core (tools/arch_check.py enforces it).
"""
import zlib

MASK64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_TWO53 = 9007199254740992.0


def _mix(z: int) -> int:
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def _key(k) -> int:
    if isinstance(k, bool) or not isinstance(k, (int, str)):
        raise TypeError(f"hash key must be int or str, got {type(k).__name__}")
    if isinstance(k, int):
        return k & MASK64
    return zlib.crc32(k.encode("utf-8")) | (len(k) << 32)


def hash_u64(seed: int, *keys) -> int:
    h = _mix((seed + _GAMMA) & MASK64)
    for k in keys:
        h = _mix(((h ^ _key(k)) + _GAMMA) & MASK64)
    return h


def hash_unit(seed: int, *keys) -> float:
    """[0, 1). 53 random bits / 2**53: exact in IEEE doubles, so identical everywhere."""
    return (hash_u64(seed, *keys) >> 11) / _TWO53


class RngStream:
    """splitmix64. The whole state is one integer (cheap to save, cheap to fingerprint)."""

    __slots__ = ("state",)

    def __init__(self, state: int) -> None:
        self.state = state & MASK64

    def next_u64(self) -> int:
        self.state = (self.state + _GAMMA) & MASK64
        return _mix(self.state)

    def unit(self) -> float:
        return (self.next_u64() >> 11) / _TWO53

    def uniform(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.unit()

    def below(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n must be positive")
        return self.next_u64() % n  # bias < 2**-40 for n < 2**24: irrelevant for a game

    def shuffle(self, items: list) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]


class RngSet:
    """One stream per purpose. Asking for an unknown purpose is an error (no silent new stream)."""

    PURPOSES = ("grid", "ai")

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams = {name: RngStream(hash_u64(seed, "stream", name)) for name in self.PURPOSES}

    def stream(self, name: str) -> RngStream:
        return self._streams[name]

    def state(self) -> dict:
        return {name: s.state for name, s in self._streams.items()}

    def restore(self, state: dict) -> None:
        if set(state) != set(self._streams):
            raise ValueError(f"rng state has streams {sorted(state)}, expected {sorted(self._streams)}")
        for name, value in state.items():
            self._streams[name].state = value
