"""Simulated agents with known pass rates.

They make it possible to check, before spending anything on a real model, that an
interval covers the truth as often as it claims and that a comparison flags a
change of a given size. They also let the planner estimate how many trials a real
experiment needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class SimulatedSuite:
    """A suite whose cases have known true pass rates."""

    true_rates: Mapping[str, float]

    @classmethod
    def from_beta(cls, n_cases: int, alpha: float, beta: float, seed: int | None = None) -> "SimulatedSuite":
        """Draw per-case true pass rates from Beta(alpha, beta)."""
        if n_cases <= 0:
            raise ValueError("n_cases must be positive")
        rng = np.random.default_rng(seed)
        rates = rng.beta(alpha, beta, size=n_cases)
        return cls({f"case-{i:03d}": float(r) for i, r in enumerate(rates)})

    def shifted(self, delta: float) -> "SimulatedSuite":
        """The same suite with every case's true rate moved by ``delta`` (clipped to [0, 1])."""
        return SimulatedSuite({k: float(np.clip(p + delta, 0.0, 1.0)) for k, p in self.true_rates.items()})

    @property
    def true_macro_rate(self) -> float:
        return float(np.mean(list(self.true_rates.values())))

    def run(self, trials: int, rng: np.random.Generator) -> dict[str, list[bool]]:
        """Simulate ``trials`` independent runs of every case."""
        if trials <= 0:
            raise ValueError("trials must be positive")
        return {k: list(rng.random(trials) < p) for k, p in self.true_rates.items()}


def flatten(outcomes: Mapping[str, Sequence[bool]]) -> tuple[int, int]:
    """Pool every trial into one (passes, trials) pair. Used to show why pooling misleads."""
    passes = sum(sum(bool(r) for r in v) for v in outcomes.values())
    total = sum(len(v) for v in outcomes.values())
    return passes, total
