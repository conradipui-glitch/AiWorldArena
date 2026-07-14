from dataclasses import dataclass


_MASK_64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15


@dataclass(slots=True)
class DeterministicRng:
    """Small, version-stable SplitMix64 generator.

    Python's standard random module is intentionally avoided because research
    snapshots must not depend on interpreter implementation details.
    """

    state: int

    def __post_init__(self) -> None:
        self.state &= _MASK_64

    def next_u64(self) -> int:
        self.state = (self.state + _GOLDEN_GAMMA) & _MASK_64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK_64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK_64
        return (value ^ (value >> 31)) & _MASK_64

    def randbelow(self, upper_bound: int) -> int:
        if upper_bound <= 0:
            raise ValueError("upper_bound must be positive")
        limit = (1 << 64) - ((1 << 64) % upper_bound)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % upper_bound

    def chance(self, numerator: int, denominator: int) -> bool:
        if denominator <= 0 or numerator < 0 or numerator > denominator:
            raise ValueError("invalid probability")
        return self.randbelow(denominator) < numerator
