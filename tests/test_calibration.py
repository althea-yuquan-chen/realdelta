"""Does each interval cover the truth as often as it claims?

These tests simulate suites with known pass rates. They are the reason to trust
the library at all, so the settings include the hard ones: suites near a 100%
pass rate, a single trial per case, few cases and unequal trial counts. A
fault-injection test checks that the coverage check itself can fail: a pooled
binomial interval, the common shortcut, must under-cover the population target.

Seeds are fixed, so results are deterministic. With 1000 repetitions the
standard error of a coverage estimate near 95% is about 0.7 points; the lower
bound of 0.93 sits about 3 standard errors below nominal.
"""

import numpy as np
import pytest

from realdelta import delta_interval, pass_rate_interval, wilson_interval
from realdelta.stats import _delta_interval, _paired_counts


def _delta(baseline, candidate, scope):
    if scope == "population":  # not public (docs/calibration_protocol.md, Amendment 1)
        return _delta_interval(*_paired_counts(baseline, candidate), scope, 0.95)
    return delta_interval(baseline, candidate, scope=scope)

REPS = 1000
GATE = 0.93

# (cases, trials per case, Beta(a, b) of true per-case pass rates)
SETTINGS = [
    (30, 5, (4, 2)),
    (30, 5, (8, 2)),
    (10, 3, (4, 2)),
    (50, 10, (2, 2)),
    (30, 1, (4, 2)),
    (20, 5, (20, 1)),
    (20, 10, (50, 1)),
    (30, (1, 3, 10), (4, 2)),
]


def _trials(rng, m, spec):
    if isinstance(spec, int):
        return np.full(m, spec)
    return rng.choice(spec, size=m)


def _outcomes(rng, rates, trials):
    return {f"c{i}": list(rng.random(int(n)) < p) for i, (p, n) in enumerate(zip(rates, trials))}


@pytest.mark.parametrize("scope", ["suite", "population"])
@pytest.mark.parametrize("m,spec,ab", SETTINGS, ids=[f"m{m}-n{s}-beta{ab}" for m, s, ab in SETTINGS])
def test_pass_rate_interval_coverage(scope, m, spec, ab):
    rng = np.random.default_rng(2026)
    pop_truth = ab[0] / sum(ab)
    hits = 0
    for _ in range(REPS):
        rates = rng.beta(*ab, size=m)
        iv = pass_rate_interval(_outcomes(rng, rates, _trials(rng, m, spec)), scope=scope)
        hits += iv.contains(rates.mean() if scope == "suite" else pop_truth)
    _check(hits / REPS, scope)


def _check(cov, scope):
    # Gate from docs/calibration_protocol.md: lower bound everywhere; the 0.995 upper
    # bound only for the suite scope (the population scope is conservative by design).
    assert cov >= GATE, f"coverage {cov:.3f}"
    if scope == "suite":
        assert cov <= 0.995, f"coverage {cov:.3f} (over-conservative)"


def test_pooled_binomial_interval_under_covers_population():
    """Fault injection: the same gate must reject the naive pooled interval."""
    rng = np.random.default_rng(7)
    m, n, ab = 50, 10, (2, 2)
    hits = 0
    for _ in range(REPS):
        x = rng.binomial(n, rng.beta(*ab, size=m))
        hits += wilson_interval(int(x.sum()), m * n).contains(0.5)
    assert hits / REPS < GATE


DELTA_SETTINGS = [
    (30, 5, (4, 2), 0.1),
    (20, 5, (20, 1), -0.1),
    (20, 10, (50, 1), -0.05),
    (10, 3, (4, 2), 0.2),
    (30, 1, (4, 2), 0.15),
    (30, (1, 3, 10), (4, 2), 0.15),
]


@pytest.mark.parametrize("scope", ["suite", "population"])
@pytest.mark.parametrize("m,spec,ab,shift", DELTA_SETTINGS)
def test_delta_interval_coverage(scope, m, spec, ab, shift):
    rng = np.random.default_rng(99)
    big = rng.beta(*ab, size=2_000_000)
    pop_truth = float(np.mean(np.clip(big + shift, 0, 1) - big))
    hits = 0
    for _ in range(REPS):
        pa = rng.beta(*ab, size=m)
        pb = np.clip(pa + shift, 0, 1)
        trials = _trials(rng, m, spec)
        iv = _delta(_outcomes(rng, pa, trials), _outcomes(rng, pb, trials), scope)
        hits += iv.contains(float(np.mean(pb - pa)) if scope == "suite" else pop_truth)
    _check(hits / REPS, scope)


@pytest.mark.parametrize("scope", ["suite", "population"])
@pytest.mark.parametrize("m,spec,ab", [(30, 5, (4, 2)), (20, 5, (20, 1)), (10, 3, (8, 2))])
def test_false_alarm_rate_when_nothing_changed(scope, m, spec, ab):
    rng = np.random.default_rng(11)
    alarms = 0
    for _ in range(REPS):
        rates = rng.beta(*ab, size=m)
        trials = _trials(rng, m, spec)
        iv = _delta(_outcomes(rng, rates, trials), _outcomes(rng, rates, trials), scope)
        alarms += not iv.contains(0.0)
    assert alarms / REPS <= 0.07


# Known failure shapes found in review (regression tests, lower bound only).


def _deterministic(rng, m, share_pass):
    return (rng.random(m) < share_pass).astype(float)


def test_h1_bimodal_population_pass_rate():
    rng = np.random.default_rng(101)
    hits = 0
    for _ in range(REPS):
        rates = _deterministic(rng, 20, 0.95)
        hits += pass_rate_interval(_outcomes(rng, rates, np.full(20, 10)), scope="population").contains(0.95)
    assert hits / REPS >= GATE, f"coverage {hits / REPS:.3f}"


def test_h2_three_point_population_pass_rate():
    rng = np.random.default_rng(102)
    hits = 0
    for _ in range(REPS):
        rates = rng.choice([1.0, 0.7, 0.0], size=30, p=[0.8, 0.1, 0.1])
        hits += pass_rate_interval(_outcomes(rng, rates, np.full(30, 5)), scope="population").contains(0.87)
    assert hits / REPS >= GATE, f"coverage {hits / REPS:.3f}"


def test_h6_population_delta_when_candidate_breaks_five_percent():
    rng = np.random.default_rng(103)
    hits = 0
    for _ in range(REPS):
        pa = _deterministic(rng, 20, 0.95)
        pb = pa * (rng.random(20) >= 0.05 / 0.95)
        trials = np.full(20, 10)
        iv = _delta(_outcomes(rng, pa, trials), _outcomes(rng, pb, trials), "population")
        hits += iv.contains(-0.05)
    assert hits / REPS >= GATE, f"coverage {hits / REPS:.3f}"
