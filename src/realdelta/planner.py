"""How many trials does an A/B comparison need, and what will it cost?

The planner simulates the comparison you are about to run: a suite of cases whose
pass rates look like yours, a candidate that changes every case by ``delta``, and a
given number of trials per case. It reports how often the comparison detects the
change (power) and how often it raises a false alarm when nothing changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .simulate import SimulatedSuite
from .stats import Scope, delta_interval


@dataclass(frozen=True)
class PlanRow:
    trials: int
    power: float
    false_alarm_rate: float
    total_runs: int


def plan_trials(
    n_cases: int,
    delta: float,
    trials_options: Sequence[int] = (1, 3, 5, 10, 20),
    alpha: float = 8.0,
    beta: float = 2.0,
    scope: Scope = "suite",
    conf: float = 0.95,
    n_sim: int = 300,
    seed: int | None = None,
) -> list[PlanRow]:
    """Simulated power and false-alarm rate for each trials-per-case option.

    Per-case baseline pass rates are drawn from Beta(alpha, beta); the default
    Beta(8, 2) has mean 0.8. The candidate adds ``delta`` to every case's rate,
    clipped to [0, 1], so near a 100% pass rate the realised shift is smaller
    than ``delta``. A detection is a ``delta`` interval that excludes 0 with the
    same sign as ``delta``.
    """
    if delta == 0:
        raise ValueError("delta must be non-zero; it is the change you want to detect")
    rng = np.random.default_rng(seed)
    rows = []
    for trials in trials_options:
        hits = 0
        false_alarms = 0
        for _ in range(n_sim):
            base = SimulatedSuite.from_beta(n_cases, alpha, beta, seed=int(rng.integers(2**32)))
            cand = base.shifted(delta)
            a = base.run(trials, rng)
            b = cand.run(trials, rng)
            null_b = base.run(trials, rng)
            effect = delta_interval(a, b, scope=scope, conf=conf)
            null = delta_interval(a, null_b, scope=scope, conf=conf)
            if (effect.low > 0) if delta > 0 else (effect.high < 0):
                hits += 1
            if not null.contains(0.0):
                false_alarms += 1
        rows.append(PlanRow(trials, hits / n_sim, false_alarms / n_sim, total_runs=2 * n_cases * trials))
    return rows


@dataclass(frozen=True)
class CostEstimate:
    runs: int
    input_tokens: int
    output_tokens: int
    usd: float


def estimate_cost(
    n_cases: int,
    trials: int,
    arms: int,
    input_tokens_per_run: int,
    output_tokens_per_run: int,
    usd_per_million_input: float,
    usd_per_million_output: float,
) -> CostEstimate:
    """Back-of-the-envelope cost of an eval. Prices are passed in, never hard-coded."""
    runs = n_cases * trials * arms
    tin = runs * input_tokens_per_run
    tout = runs * output_tokens_per_run
    usd = tin / 1e6 * usd_per_million_input + tout / 1e6 * usd_per_million_output
    return CostEstimate(runs, tin, tout, round(usd, 4))
