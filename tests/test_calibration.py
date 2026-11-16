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

REPS = 1000

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
    cov = hits / REPS
    assert 0.93 <= cov <= 0.995, f"coverage {cov:.3f}"


def test_pooled_binomial_interval_under_covers_population():
    """Fault injection: the coverage check must reject the naive pooled interval."""
    rng = np.random.default_rng(7)
    m, n, ab = 50, 10, (2, 2)
    hits = 0
    for _ in range(REPS):
        x = rng.binomial(n, rng.beta(*ab, size=m))
        hits += wilson_interval(int(x.sum()), m * n).contains(0.5)
    assert hits / REPS < 0.85


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
        iv = delta_interval(_outcomes(rng, pa, trials), _outcomes(rng, pb, trials), scope=scope)
        hits += iv.contains(float(np.mean(pb - pa)) if scope == "suite" else pop_truth)
    cov = hits / REPS
    assert 0.93 <= cov <= 0.995, f"coverage {cov:.3f}"


@pytest.mark.parametrize("scope", ["suite", "population"])
@pytest.mark.parametrize("m,spec,ab", [(30, 5, (4, 2)), (20, 5, (20, 1)), (10, 3, (8, 2))])
def test_false_alarm_rate_when_nothing_changed(scope, m, spec, ab):
    rng = np.random.default_rng(11)
    alarms = 0
    for _ in range(REPS):
        rates = rng.beta(*ab, size=m)
        trials = _trials(rng, m, spec)
        iv = delta_interval(_outcomes(rng, rates, trials), _outcomes(rng, rates, trials), scope=scope)
        alarms += not iv.contains(0.0)
    assert alarms / REPS <= 0.07
