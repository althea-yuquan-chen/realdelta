"""How many trials does an A/B comparison need, and what will it cost?

The planner simulates the comparison you are about to run: a synthetic suite whose case pass
rates are drawn from a Beta distribution you choose, a candidate, and a given number of trials per
case. Two candidate models: ``"shift"`` moves every case's rate by ``delta`` (clipped to [0, 1]);
``"break"`` sets the rate of ``k`` randomly chosen cases to 0, the common agent regression where a
few cases start failing every time. It reports how often the comparison detects the change (power)
and how often it raises a false alarm when nothing changed, with Monte Carlo standard errors.
These are simulation results for the synthetic suite, not coverage claims.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .simulate import SimulatedSuite
from .stats import Scope, _reject_population_delta, delta_interval


@dataclass(frozen=True)
class PlanRow:
    trials: int
    power: float
    false_alarm_rate: float
    total_runs: int
    realised_change: float = 0.0
    power_se: float = 0.0
    false_alarm_se: float = 0.0


def break_cases(suite: SimulatedSuite, k: int, rng: np.random.Generator) -> SimulatedSuite:
    """The same suite with ``k`` cases, chosen at random, set to a pass rate of 0."""
    names = list(suite.true_rates)
    chosen = set(rng.choice(len(names), size=k, replace=False).tolist())
    return SimulatedSuite({n: (0.0 if i in chosen else p) for i, (n, p) in enumerate(suite.true_rates.items())})


def _se(p: float, n: int) -> float:
    return math.sqrt(p * (1.0 - p) / n)


def plan_trials(
    n_cases: int,
    delta: float | None = None,
    trials_options: Sequence[int] = (1, 3, 5, 10, 20),
    alpha: float = 8.0,
    beta: float = 2.0,
    scope: Scope = "suite",
    conf: float = 0.95,
    n_sim: int = 300,
    seed: int | None = None,
    change: str = "shift",
    k: int | None = None,
) -> list[PlanRow]:
    """Simulated power and false-alarm rate for each trials-per-case option.

    Per-case baseline pass rates are drawn from Beta(alpha, beta); the default Beta(8, 2) has mean
    0.8. With ``change="shift"`` the candidate adds ``delta`` to every case's rate, clipped to
    [0, 1], so near a 100% pass rate the realised shift is smaller than ``delta``; a detection is a
    delta interval that excludes 0 with the same sign as ``delta``. With ``change="break"`` the
    candidate sets ``k`` randomly chosen cases to a pass rate of 0 and a detection is an interval
    entirely below 0. ``realised_change`` is the mean true change in macro pass rate over the
    simulations. The false-alarm rate uses the same null in both models: the baseline run against
    an independent re-run of itself.
    """
    _reject_population_delta(scope)
    if type(n_cases) is not int or n_cases < 1:
        raise ValueError("n_cases must be a whole number of at least 1")
    if change == "shift":
        if delta is None:
            raise ValueError("change='shift' needs delta")
        if delta == 0:
            raise ValueError("delta must be non-zero; it is the change you want to detect")
        if k is not None:
            raise ValueError("k is only used with change='break'")
    elif change == "break":
        if delta is not None:
            raise ValueError("delta is not used with change='break'; give k instead")
        if type(k) is not int or not 1 <= k <= n_cases:
            raise ValueError(f"change='break' needs a whole number k between 1 and n_cases ({n_cases})")
    else:
        raise ValueError(f"change must be 'shift' or 'break', got {change!r}")
    rng = np.random.default_rng(seed)
    # The break choice has its own stream, so the main stream is consumed exactly as in shift.
    pick = np.random.default_rng(None if seed is None else [seed, 1])
    rows = []
    for trials in trials_options:
        hits = 0
        false_alarms = 0
        realised = 0.0
        for _ in range(n_sim):
            base = SimulatedSuite.from_beta(n_cases, alpha, beta, seed=int(rng.integers(2**32)))
            cand = base.shifted(delta) if change == "shift" else break_cases(base, k, pick)
            realised += cand.true_macro_rate - base.true_macro_rate
            a = base.run(trials, rng)
            b = cand.run(trials, rng)
            null_b = base.run(trials, rng)
            effect = delta_interval(a, b, scope=scope, conf=conf)
            null = delta_interval(a, null_b, scope=scope, conf=conf)
            upward = change == "shift" and delta > 0
            if (effect.low > 0) if upward else (effect.high < 0):
                hits += 1
            if not null.contains(0.0):
                false_alarms += 1
        power, fa = hits / n_sim, false_alarms / n_sim
        rows.append(PlanRow(trials, power, fa, total_runs=2 * n_cases * trials, realised_change=realised / n_sim,
                            power_se=_se(power, n_sim), false_alarm_se=_se(fa, n_sim)))
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
