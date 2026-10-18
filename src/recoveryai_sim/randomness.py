"""Keyed exogenous noise: invariant to policy branching and execution order."""
import hashlib
import math


class Noise:
    def __init__(self, seed: int):
        self.seed = seed

    def uniform(self, *key):
        data = repr((self.seed, key)).encode("utf-8")
        # Exactly representable grid in [0,1); never rounds up to 1 (Pareto safety).
        return (int.from_bytes(hashlib.sha256(data).digest()[:8], "big") >> 11) / 2**53

    def normal(self, *key):
        u = max(self.uniform(*key, "u"), 1e-15)
        return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * self.uniform(*key, "v"))

    def choose(self, values, *key):
        return values[min(len(values) - 1, int(self.uniform(*key) * len(values)))]
