"""Uncertainty for agent eval results that are repeated per case.

An eval run produces, for every case, a list of trial outcomes (pass / fail).
Trials of the same case share that case's pass rate: given the case they are
independent draws, but across cases they are not exchangeable. The point
estimate is the macro pass rate: the mean of per-case pass rates, so every case
weighs the same however many trials it ran.

Two scopes answer two different questions:

* ``"suite"``: how sure are we about *this fixed set of cases*? Only
  trial-to-trial randomness counts. The pass-rate interval is Clopper-Pearson
  on the macro rate with an effective sample size taken from Agresti-Coull
  adjusted per-case variances, capped at the number of trials run (with equal
  trials per case this is Clopper-Pearson on the pooled pass count). It
  replaced a Wilson interval that under-covered near a 100% pass rate with few
  trials (docs/calibration_protocol.md, Amendments 1 and 2).
* ``"population"``: how sure are we about *cases like these*? Case-to-case
  spread counts too. The pass-rate interval is the hull of a t interval over
  per-case pass rates, the suite interval, and a case-level floor
  (:func:`case_level_interval`). The floor matters when a few cases fail
  every time: if every one of m cases passes, the lower bound is
  0.025 ** (1/m) (about 1 - 3.7/m for large m; 0.48 at m = 5), however many
  trials each case ran.

The delta (:func:`delta_interval`, :func:`compare`) is suite scope only in
v0.1: MOVER over the two arms' Wilson-based suite intervals. The
population-scope delta failed the pre-registered width rule and raises
NotImplementedError.

Assumptions (docs/calibration_protocol.md, README Limitations): A1 trials within a
case are i.i.d.; A2 cases are an i.i.d. draw from the population; A3 the two
arms' trial noise is independent; A4 the number of trials per case does not
depend on outcomes; A5 within an arm, cases do not share a run-level shock. The
suite scope needs A1, A4 and A5 (comparisons also A3); the population scope
needs A2 and A4. Measured violations are in README Limitations (grid rows V1
and V2, Diagnostic AD).

Validity evidence is limited to what the tests and the pre-registered grid
show: the floor is exact when every case is deterministic; otherwise coverage
is checked by simulation, not proven.
"""

from __future__ import annotations

import math
from fractions import Fraction
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


def _cp_bounds(x: float, n: float, conf: float) -> tuple[float, float]:
    """Clopper-Pearson beta quantiles for a (possibly real-valued) count x out of n."""
    alpha = 1.0 - conf
    _z(conf)  # validates conf
    x = min(max(float(x), 0.0), float(n))
    low = 0.0 if x <= 1e-12 else float(_sps.beta.ppf(alpha / 2.0, x, n - x + 1.0))
    high = 1.0 if x >= n - 1e-12 else float(_sps.beta.ppf(1.0 - alpha / 2.0, x + 1.0, n - x))
    if not (math.isfinite(low) and math.isfinite(high)):
        raise FloatingPointError(f"non-finite Clopper-Pearson bound for x={x}, n={n}")
    return low, high


def _suite_rate_interval(passes: np.ndarray, trials: np.ndarray, conf: float) -> Interval:
    """Suite-scope pass-rate interval (docs/calibration_protocol.md, Amendment 2, candidate C1).

    Clopper-Pearson on (estimate * N, N) with N = min(n_eff, total trials): the effective sample
    size is capped at the trials actually run. With one trial per case this is the ordinary
    Clopper-Pearson interval; with equal trials per case it is Clopper-Pearson on the pooled pass
    count, since n_eff >= m * n then.
    """
    z = _z(conf)
    m = len(passes)
    estimate = float(np.mean(passes / trials))
    var = float(np.sum(_adjusted_var(passes, trials, z)) / (m * m))
    p_bar = float(np.mean((passes + z * z / 2.0) / (trials + z * z)))
    n = min(p_bar * (1.0 - p_bar) / var, float(np.sum(trials)))
    low, high = _cp_bounds(estimate * n, n, conf)
    return Interval(estimate, low, high, conf)


def pass_rate_interval(outcomes: Outcomes, scope: Scope = "suite", conf: float = 0.95) -> Interval:
    """Interval for the macro pass rate of a suite run with repeated trials."""
    _, passes, trials = _counts(outcomes)
    _require_scope(scope, len(passes))
    suite = _suite_rate_interval(passes, trials, conf)
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
    low, high = _cp_bounds(x, float(m), conf)
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
    # intervals. Valid in the suite scope when the arms' trial noise is independent (A3) and no
    # arm has a run-level shock shared by its cases (A5); Diagnostic AD measures violations.
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

    Suite scope only in v0.1. The two arms' Wilson-based suite intervals are
    combined with the MOVER method (Newcombe's hybrid score interval,
    generalised to macro rates). Near a 100% pass rate with few trials, where
    Wilson bounds are known to under-cover, it is not covered by the gated
    calibration grid; a reported-only diagnostic found coverage >= 0.949 on 23
    settings with m >= 5, including three cases constructed to be adverse
    (results/delta_boundary_diagnostic_20261118.md). This is not a general
    guarantee for that regime, and power there is low.

    ``scope="population"`` raises NotImplementedError: it failed the
    pre-registered width rule (results/calibration_grid_20261116.md).
    """
    _reject_population_delta(scope)
    return _delta_interval(*_paired_counts(baseline, candidate), scope, conf)


_POPULATION_DELTA_MESSAGE = (
    "the population-scope delta is not in v0.1: it failed the pre-registered width rule "
    "(docs/calibration_protocol.md, results/calibration_grid_20261116.md); use scope='suite'"
)


def _reject_population_delta(scope: str) -> None:
    if scope == "population":
        raise NotImplementedError(_POPULATION_DELTA_MESSAGE)


@dataclass(frozen=True)
class CaseChange:
    """One case whose pass rate differs between the two versions (descriptive; no per-case test)."""

    case_id: str
    baseline_passes: int
    baseline_trials: int
    candidate_passes: int
    candidate_trials: int

    @property
    def change(self) -> float:
        return float(self.exact_change)

    @property
    def exact_change(self) -> Fraction:
        return (Fraction(self.candidate_passes, self.candidate_trials)
                - Fraction(self.baseline_passes, self.baseline_trials))

    @property
    def group(self) -> str:
        if self.candidate_passes == 0 and self.baseline_passes > 0:
            return "now_fails_every_trial"
        if self.candidate_passes == self.candidate_trials and self.baseline_passes < self.baseline_trials:
            return "now_passes_every_trial"
        return "other"


_GROUP_ORDER = {"now_fails_every_trial": 0, "now_passes_every_trial": 1, "other": 2}


def case_changes(baseline: Outcomes, candidate: Outcomes) -> tuple[CaseChange, ...]:
    """Cases whose pass rate differs: by group (now fail every trial, now pass every trial, other), then by size
    of the change, largest first (exact fractions), then by case id.

    Descriptive only: with a few trials per case a case's rate moves by chance, and no per-case test or
    multiple-comparison correction is applied.
    """
    _paired_counts(baseline, candidate)  # same validation as compare
    out = []
    for case in baseline:
        a, b = baseline[case], candidate[case]
        ch = CaseChange(str(case), int(sum(map(bool, a))), len(a), int(sum(map(bool, b))), len(b))
        if ch.baseline_passes * ch.candidate_trials != ch.candidate_passes * ch.baseline_trials:
            out.append(ch)
    return tuple(sorted(out, key=lambda c: (_GROUP_ORDER[c.group], -abs(c.exact_change), c.case_id)))


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
    case_changes: tuple[CaseChange, ...] = ()

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
    """Compare a candidate version against a baseline run on the same cases (suite scope only in v0.1)."""
    _reject_population_delta(scope)
    pa, ta, pb, tb = _paired_counts(baseline, candidate)
    delta = _delta_interval(pa, ta, pb, tb, scope, conf)
    p_value = _sign_flip_p_value(pb / tb - pa / ta, n_perm, np.random.default_rng(seed))
    return Comparison(delta=delta, p_value=p_value, n_cases=len(pa), scope=scope,
                      case_changes=case_changes(baseline, candidate))
