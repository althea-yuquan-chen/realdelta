"""Uncertainty for agent eval results that are repeated per case.

An eval run produces, for every case, a list of trial outcomes (pass / fail).
Trials of the same case are correlated, so the case is the unit. The point
estimate is the macro pass rate: the mean of per-case pass rates, so every case
weighs the same however many trials it ran.

Two scopes answer two different questions:

* ``"suite"``: how sure are we about *this fixed set of cases*? Only
  trial-to-trial randomness counts. The interval is a Wilson score interval on
  the macro rate, with an effective sample size taken from Agresti-Coull
  adjusted per-case variances. The adjustment keeps the interval honest when
  cases pass every time, which is where agent suites usually sit.
* ``"population"``: how sure are we about *cases like these*? Case-to-case
  spread counts too. The interval is the hull of a t interval over per-case
  pass rates, the suite interval, and a case-level floor
  (:func:`case_level_interval`). The floor matters when a few cases fail
  every time: m cases cannot rule out a failure mode that affects roughly
  3.7/m of cases like them, however many trials each case ran.

Assumptions (docs/calibration_protocol.md): A1 trials within a case are i.i.d.;
A2 cases are an i.i.d. draw from the population; A3 compared arms share no
randomness (seeds, caches, outage windows); A4 the number of trials per case
does not depend on outcomes. The suite scope needs A1, A3 and A4; the
population scope needs A2 and A4.

Validity evidence is limited to what the tests and the pre-registered grid
show: the floor is exact when every case is deterministic; otherwise coverage
is checked by simulation, not proven.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal, Mapping, Sequence

import numpy as np
from scipy import stats as _sps

Outcomes = Mapping[str, Sequence[bool]]
Scope = Literal["suite", "population"]


@dataclass(frozen=True)
class Interval:
    """A point estimate with a two-sided interval at confidence level ``conf``."""

    estimate: float
    low: float
    high: float
    conf: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    @property
    def width(self) -> float:
        return self.high - self.low


def _z(conf: float) -> float:
    if not 0.0 < conf < 1.0:
        raise ValueError(f"conf must be in (0, 1), got {conf}")
    return NormalDist().inv_cdf(0.5 + conf / 2.0)


def _wilson_bounds(p: float, n: float, z: float) -> tuple[float, float]:
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    half = z * math.sqrt(max(p * (1.0 - p), 0.0) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom)


def wilson_interval(passes: int, trials: int, conf: float = 0.95) -> Interval:
    """Wilson score interval for one binomial proportion (one case's trials)."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0 <= passes <= trials:
        raise ValueError(f"passes must be in [0, {trials}], got {passes}")
    p = passes / trials
    low, high = _wilson_bounds(p, trials, _z(conf))
    return Interval(p, low, high, conf)


def pass_hat_k(passes: int, trials: int, k: int) -> float:
    """Unbiased estimate of the chance that k fresh trials of a case all pass.

    Uses C(passes, k) / C(trials, k), which is unbiased for p**k when the n
    trials are independent with the same pass probability p.
    """
    if not 1 <= k <= trials:
        raise ValueError(f"k must be in [1, {trials}], got {k}")
    if not 0 <= passes <= trials:
        raise ValueError(f"passes must be in [0, {trials}], got {passes}")
    return math.comb(passes, k) / math.comb(trials, k)


def _counts(outcomes: Outcomes) -> tuple[list[str], np.ndarray, np.ndarray]:
    if not outcomes:
        raise ValueError("outcomes is empty")
    ids = list(outcomes)
    passes = np.empty(len(ids))
    trials = np.empty(len(ids))
    for i, case_id in enumerate(ids):
        results = list(outcomes[case_id])
        if not results:
            raise ValueError(f"case {case_id!r} has no trials")
        passes[i] = sum(bool(r) for r in results)
        trials[i] = len(results)
    return ids, passes, trials


def macro_pass_rate(outcomes: Outcomes) -> float:
    """Mean of per-case pass rates."""
    _, passes, trials = _counts(outcomes)
    return float(np.mean(passes / trials))


def _adjusted_var(passes: np.ndarray, trials: np.ndarray, z: float) -> np.ndarray:
    """Per-case variance of the observed pass rate, Agresti-Coull adjusted.

    Plain p(1-p)/n is zero for a case at 5/5, which would claim certainty the
    data cannot support.
    """
    p_tilde = (passes + z * z / 2.0) / (trials + z * z)
    return p_tilde * (1.0 - p_tilde) / trials


def _suite_interval(passes: np.ndarray, trials: np.ndarray, conf: float) -> Interval:
    z = _z(conf)
    m = len(passes)
    estimate = float(np.mean(passes / trials))
    var = float(np.sum(_adjusted_var(passes, trials, z)) / (m * m))
    p_bar = float(np.mean((passes + z * z / 2.0) / (trials + z * z)))
    n_eff = p_bar * (1.0 - p_bar) / var
    low, high = _wilson_bounds(estimate, n_eff, z)
    return Interval(estimate, low, high, conf)


def _t_half_width(values: np.ndarray, conf: float) -> float:
    m = len(values)
    t = float(_sps.t.ppf(0.5 + conf / 2.0, m - 1))
    return t * float(np.std(values, ddof=1)) / math.sqrt(m)


def _require_scope(scope: str, m: int) -> None:
    if scope not in ("suite", "population"):
        raise ValueError(f"scope must be 'suite' or 'population', got {scope!r}")
    if scope == "population" and m < 2:
        raise ValueError("the population scope needs at least 2 cases")


def pass_rate_interval(outcomes: Outcomes, scope: Scope = "suite", conf: float = 0.95) -> Interval:
    """Interval for the macro pass rate of a suite run with repeated trials."""
    _, passes, trials = _counts(outcomes)
    _require_scope(scope, len(passes))
    suite = _suite_interval(passes, trials, conf)
    if scope == "suite":
        return suite
    rates = passes / trials
    half = _t_half_width(rates, conf)
    floor = case_level_interval(float(rates.sum()), len(rates), conf)
    low = max(0.0, min(suite.estimate - half, suite.low, floor.low))
    high = min(1.0, max(suite.estimate + half, suite.high, floor.high))
    return Interval(suite.estimate, low, high, conf)


def case_level_interval(total: float, m: int, conf: float = 0.95) -> Interval:
    """Clopper-Pearson interval for the mean of m case-level values in [0, 1].

    ``total`` is the sum of the values and may be fractional (e.g. per-case pass
    rates). The beta-quantile formula is applied to the real-valued total. It is
    exact (coverage >= conf) when every value is 0 or 1, i.e. deterministic cases.
    For other values coverage is checked in tests, not proven.
    """
    if m <= 0:
        raise ValueError("m must be positive")
    if not -1e-9 <= total <= m + 1e-9:
        raise ValueError(f"total must be in [0, {m}], got {total}")
    x = min(max(float(total), 0.0), float(m))
    alpha = 1.0 - conf
    _z(conf)  # validates conf
    low = 0.0 if x <= 1e-12 else float(_sps.beta.ppf(alpha / 2.0, x, m - x + 1.0))
    high = 1.0 if x >= m - 1e-12 else float(_sps.beta.ppf(1.0 - alpha / 2.0, x + 1.0, m - x))
    return Interval(x / m, low, high, conf)


def _paired_counts(baseline: Outcomes, candidate: Outcomes):
    if set(baseline) != set(candidate):
        differ = sorted(set(baseline) ^ set(candidate))
        raise ValueError(f"baseline and candidate must cover the same cases; they differ on {differ[:5]}")
    _, pb, tb = _counts(candidate)
    _, pa, ta = _counts({k: baseline[k] for k in candidate})
    return pa, ta, pb, tb


def _delta_interval(pa, ta, pb, tb, scope: Scope, conf: float) -> Interval:
    m = len(pa)
    _require_scope(scope, m)
    diffs = pb / tb - pa / ta
    estimate = float(diffs.mean())
    # MOVER (Newcombe's hybrid score method): combine the two arms' suite
    # intervals. Valid in the suite scope because the arms' trial noise is independent.
    a = _suite_interval(pa, ta, conf)
    b = _suite_interval(pb, tb, conf)
    low = estimate - math.hypot(b.estimate - b.low, a.high - a.estimate)
    high = estimate + math.hypot(b.high - b.estimate, a.estimate - a.low)
    if scope == "population":
        half = _t_half_width(diffs, conf)
        # Case-level floor: split each difference into its positive and negative
        # parts (both in [0, 1]), bound each mean at 1 - alpha/2, Bonferroni-combine.
        each = 1.0 - (1.0 - conf) / 2.0
        up = case_level_interval(float(np.maximum(diffs, 0.0).sum()), m, each)
        down = case_level_interval(float(np.maximum(-diffs, 0.0).sum()), m, each)
        low = min(low, estimate - half, up.low - down.high)
        high = max(high, estimate + half, up.high - down.low)
    return Interval(estimate, max(-1.0, low), min(1.0, high), conf)


def delta_interval(
    baseline: Outcomes, candidate: Outcomes, scope: Scope = "suite", conf: float = 0.95
) -> Interval:
    """Interval for the change in macro pass rate, candidate minus baseline, paired by case.

    In the suite scope the two arms' suite intervals are combined with the
    MOVER method (Newcombe's hybrid score interval, generalised to macro
    rates). In the population
    scope a paired t interval over per-case differences is used, widened where
    needed to contain the suite interval.
    """
    return _delta_interval(*_paired_counts(baseline, candidate), scope, conf)


@dataclass(frozen=True)
class Comparison:
    """Paired comparison of two versions run on the same cases (candidate minus baseline).

    ``delta`` is the decision rule: a change is detected when its interval
    excludes 0. ``p_value`` comes from a sign-flip permutation test of the sharp
    null "the two versions behave identically on every case"; it is exact when
    both arms ran the same number of trials per case.
    """

    delta: Interval
    p_value: float
    n_cases: int
    scope: Scope

    @property
    def detected(self) -> bool:
        return not self.delta.contains(0.0)


def _sign_flip_p_value(diffs: np.ndarray, n_perm: int, rng: np.random.Generator) -> float:
    """Two-sided sign-flip permutation test for a zero mean per-case difference."""
    if np.allclose(diffs, 0.0):
        return 1.0
    observed = abs(diffs.mean()) - 1e-12
    m = len(diffs)
    if m <= 16:
        signs = np.array(np.meshgrid(*[[-1.0, 1.0]] * m)).reshape(m, -1).T
        return float(np.mean(np.abs((signs * diffs).mean(axis=1)) >= observed))
    signs = rng.choice([-1.0, 1.0], size=(n_perm, m))
    hits = np.sum(np.abs((signs * diffs).mean(axis=1)) >= observed)
    return float((1 + hits) / (1 + n_perm))


def compare(
    baseline: Outcomes,
    candidate: Outcomes,
    scope: Scope = "suite",
    conf: float = 0.95,
    n_perm: int = 10000,
    seed: int | None = None,
) -> Comparison:
    """Compare a candidate version against a baseline run on the same cases."""
    pa, ta, pb, tb = _paired_counts(baseline, candidate)
    delta = _delta_interval(pa, ta, pb, tb, scope, conf)
    p_value = _sign_flip_p_value(pb / tb - pa / ta, n_perm, np.random.default_rng(seed))
    return Comparison(delta=delta, p_value=p_value, n_cases=len(pa), scope=scope)
