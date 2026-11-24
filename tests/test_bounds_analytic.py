"""Analytic checks of the population-scope floors (docs/calibration_protocol.md).

No simulation: coverage is computed exactly by enumerating every possible sample.
Committed before the floors exist, so each test is xfail(strict=True) until the
implementation commit removes the marks.
"""

import itertools
import math

import numpy as np
import pytest
from scipy import stats as st

TOL = 1e-12
M_VALUES = (5, 7, 10, 20, 30, 50, 100)


def _floor(total, m):
    from realdelta.stats import case_level_interval  # added in the implementation commit

    iv = case_level_interval(total, m, conf=0.95)
    return iv.low, iv.high


@pytest.mark.parametrize("m", M_VALUES)
def test_floor_exact_coverage_bernoulli(m):
    mus = np.concatenate([np.linspace(0.01, 0.99, 2000), np.linspace(0.99, 0.9999, 500)])
    bounds = np.array([_floor(float(x), m) for x in range(m + 1)])
    pmf = st.binom.pmf(np.arange(m + 1)[:, None], m, mus[None, :])
    inside = (bounds[:, :1] <= mus[None, :]) & (mus[None, :] <= bounds[:, 1:])
    coverage = (pmf * inside).sum(axis=0)
    assert coverage.min() >= 0.95 - TOL, f"min coverage {coverage.min():.4f} at mu={mus[coverage.argmin()]:.4f}"


@pytest.mark.parametrize("m", (5, 10, 20))
def test_floor_exact_coverage_three_point(m):
    worst = 1.0
    for c, w0, wc in itertools.product((0.25, 0.5, 0.75), (0.01, 0.05, 0.1, 0.2), (0.05, 0.1, 0.3)):
        w1 = 1.0 - w0 - wc
        mu = wc * c + w1
        cov = 0.0
        for k0 in range(m + 1):
            for kc in range(m - k0 + 1):
                k1 = m - k0 - kc
                p = math.exp(
                    math.lgamma(m + 1) - math.lgamma(k0 + 1) - math.lgamma(kc + 1) - math.lgamma(k1 + 1)
                    + k0 * math.log(w0) + kc * math.log(wc) + k1 * math.log(w1)
                )
                lo, hi = _floor(kc * c + k1, m)
                if lo <= mu <= hi:
                    cov += p
        worst = min(worst, cov)
    assert worst >= 0.95 - TOL, f"min coverage {worst:.4f}"


@pytest.mark.parametrize("m", M_VALUES)
def test_all_pass_lower_bound(m):
    from realdelta import pass_rate_interval

    iv = pass_rate_interval({f"c{i}": [True] * 5 for i in range(m)}, scope="population")
    assert iv.low ** m <= 0.025 + TOL


@pytest.mark.parametrize("m", M_VALUES)
def test_all_zero_differences_keep_case_level_width(m):
    from realdelta.stats import _delta_interval, _paired_counts  # not public (Amendment 1)

    # The most favourable data: every case passes every trial in both arms.
    outcomes = {f"c{i}": [True] * 10 for i in range(m)}
    iv = _delta_interval(*_paired_counts(outcomes, outcomes), "population", 0.95)
    half = 1.0 - 0.025 ** (1.0 / m)
    assert iv.low <= -half + TOL and iv.high >= half - TOL


@pytest.mark.parametrize("m", M_VALUES)
def test_delta_floor_half_width_pins_bonferroni_split(m):
    """Amendment 2: each side of the delta floor is bounded at level 1 - alpha/2."""
    from realdelta.stats import _delta_interval, _paired_counts

    outcomes = {f"c{i}": [True] * 10 for i in range(m)}
    iv = _delta_interval(*_paired_counts(outcomes, outcomes), "population", 0.95)
    half = 1.0 - 0.0125 ** (1.0 / m)
    assert abs(iv.high - half) <= TOL and abs(iv.low + half) <= TOL
