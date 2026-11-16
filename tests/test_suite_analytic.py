"""Exact coverage of the suite pass-rate interval (docs/calibration_protocol.md, Amendment 1).

Runs the pre-registered analytic sweeps S1-S3 from scripts/suite_bounds_selection.py on the public
pass_rate_interval(scope="suite"). The threshold 0.947 is 0.93 + 3 standard errors of a 2000-rep
coverage estimate at 0.93.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from realdelta import pass_rate_interval

_SPEC = importlib.util.spec_from_file_location(
    "suite_bounds_selection", Path(__file__).resolve().parents[1] / "scripts" / "suite_bounds_selection.py"
)
selection = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(selection)

PENDING = pytest.mark.xfail(strict=True, reason="suite pass-rate fix not implemented yet")


def _public_bounds(passes: np.ndarray, trials: np.ndarray) -> tuple[float, float]:
    outcomes = {f"c{i}": [True] * int(p) + [False] * int(t - p) for i, (p, t) in enumerate(zip(passes, trials))}
    iv = pass_rate_interval(outcomes, scope="suite")
    return iv.low, iv.high


@PENDING
def test_suite_pass_rate_exact_coverage():
    """One test over all of S1-S3, so a configuration the current method happens to pass cannot XPASS."""
    result = selection.sweep(_public_bounds)
    failing = [r for r in result["rows"] if r["min_coverage"] < selection.THRESHOLD]
    assert not failing, "; ".join(f"{r['config']}: {r['min_coverage']:.4f}" for r in failing)


def test_reference_wilson_fails_the_sweep():
    """The sweep must be able to fail: the current Wilson suite bounds miss the threshold."""
    assert selection.sweep(selection.wilson)["min_coverage"] < selection.THRESHOLD


def test_selection_script_reproduces_the_library_wilson_suite_bounds():
    """The sweep's candidates reuse estimate and n_eff; check that copy against the library."""
    from realdelta.stats import _suite_interval

    rng = np.random.default_rng(5)
    for _ in range(200):
        m = int(rng.integers(2, 30))
        trials = rng.choice([1, 3, 5, 10], size=m).astype(float)
        passes = np.floor(rng.random(m) * (trials + 1))
        iv = _suite_interval(passes, trials, 0.95)
        low, high = selection.wilson(passes, trials)
        assert abs(iv.low - low) < 1e-12 and abs(iv.high - high) < 1e-12


@pytest.mark.parametrize("n", (5, 10, 20, 50))
def test_wilson_cc_closed_form_matches_inverted_score_test(n):
    """B2's closed form equals the root of |p_hat - t| - 1/(2n) = z sqrt(t(1-t)/n)."""
    from scipy.optimize import brentq

    z = selection._z()
    for x in range(n + 1):
        p = x / n
        low, high = selection.wilson_cc_bounds(p, float(n), z)
        f_hi = lambda t: (t - p - 1 / (2 * n)) - z * np.sqrt(t * (1 - t) / n)
        f_lo = lambda t: (p - t - 1 / (2 * n)) - z * np.sqrt(t * (1 - t) / n)
        want_hi = 1.0 if x == n else brentq(f_hi, min(p + 1 / (2 * n), 1 - 1e-12), 1 - 1e-15)
        want_lo = 0.0 if x == 0 else brentq(f_lo, 1e-15, max(p - 1 / (2 * n), 1e-12))
        assert abs(low - want_lo) < 1e-9 and abs(high - want_hi) < 1e-9, (x, n)


@pytest.mark.parametrize("n", (5, 10, 20, 50))
def test_cp_bounds_match_scipy_exact_interval_at_integer_counts(n):
    from scipy.stats import binomtest

    for x in range(n + 1):
        ci = binomtest(x, n).proportion_ci(confidence_level=0.95, method="exact")
        low, high = selection.cp_bounds(float(x), float(n))
        assert abs(low - ci.low) < 1e-9 and abs(high - ci.high) < 1e-9, (x, n)


@pytest.mark.parametrize("m", (5, 10, 20, 50, 100))
def test_capped_candidate_is_exact_clopper_pearson_with_one_trial_per_case(m):
    """Amendment 2, C1: with n_i = 1 the cap gives N = m and the integer pass count."""
    from scipy.stats import binomtest

    for x in range(m + 1):
        low, high = selection.clopper_pearson_capped(np.array([1.0] * x + [0.0] * (m - x)), np.ones(m))
        ci = binomtest(x, m).proportion_ci(confidence_level=0.95, method="exact")
        assert abs(low - ci.low) < 1e-9 and abs(high - ci.high) < 1e-9, (x, m)


@pytest.mark.parametrize("m,n", [(5, 5), (10, 5), (30, 3), (20, 10)])
def test_capped_candidate_is_pooled_clopper_pearson_with_equal_trials(m, n):
    """Amendment 2, C1: with equal n_i, n_eff >= m * n (Jensen), so N = m * n and x = total passes."""
    from scipy.stats import binomtest

    rng = np.random.default_rng(m * 100 + n)
    for _ in range(200):
        passes = rng.integers(0, n + 1, size=m).astype(float)
        low, high = selection.clopper_pearson_capped(passes, np.full(m, float(n)))
        ci = binomtest(int(passes.sum()), m * n).proportion_ci(confidence_level=0.95, method="exact")
        assert abs(low - ci.low) < 1e-9 and abs(high - ci.high) < 1e-9, passes
