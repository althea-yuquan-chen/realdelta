import math

import numpy as np
import pytest

from realdelta import compare, macro_pass_rate, pass_hat_k, pass_rate_interval, wilson_interval


def test_wilson_matches_closed_form():
    # 5/5 at 95%: lower bound is 1 / (1 + z^2/n) with z = 1.96, n = 5
    iv = wilson_interval(5, 5)
    assert iv.estimate == 1.0
    assert iv.high == 1.0
    assert iv.low == pytest.approx(0.5655, abs=1e-3)
    assert wilson_interval(10, 10).low == pytest.approx(0.7225, abs=1e-3)


def test_wilson_rejects_bad_input():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)
    with pytest.raises(ValueError):
        wilson_interval(6, 5)
    with pytest.raises(ValueError):
        wilson_interval(1, 5, conf=1.0)


def test_pass_hat_k_is_the_combinatorial_estimator():
    assert pass_hat_k(5, 5, 3) == 1.0
    assert pass_hat_k(4, 5, 2) == pytest.approx(math.comb(4, 2) / math.comb(5, 2))
    assert pass_hat_k(1, 5, 2) == 0.0
    with pytest.raises(ValueError):
        pass_hat_k(3, 5, 6)


def test_macro_rate_weighs_cases_equally():
    # 1 case with 10/10 and 1 case with 0/2: macro is 0.5, pooled would be 10/12
    outcomes = {"a": [True] * 10, "b": [False, False]}
    assert macro_pass_rate(outcomes) == 0.5


def test_empty_inputs_raise():
    with pytest.raises(ValueError):
        macro_pass_rate({})
    with pytest.raises(ValueError):
        macro_pass_rate({"a": []})


@pytest.mark.parametrize("scope", ["suite", "population"])
def test_interval_is_bracketed(scope):
    outcomes = {f"c{i}": [True, True, False, True, True] for i in range(20)}
    iv = pass_rate_interval(outcomes, scope=scope)
    assert 0.0 <= iv.low <= iv.estimate <= iv.high <= 1.0


def test_population_is_never_narrower_than_suite():
    rng = np.random.default_rng(0)
    for _ in range(50):
        outcomes = {f"c{i}": list(rng.random(4) < rng.random()) for i in range(15)}
        s = pass_rate_interval(outcomes, scope="suite")
        p = pass_rate_interval(outcomes, scope="population")
        assert p.low <= s.low and p.high >= s.high


@pytest.mark.parametrize("scope", ["suite", "population"])
def test_all_pass_suite_still_has_width(scope):
    # A naive bootstrap or plug-in variance of 20 cases at 5/5 gives a zero-width interval.
    outcomes = {f"c{i}": [True] * 5 for i in range(20)}
    iv = pass_rate_interval(outcomes, scope=scope)
    assert iv.high == 1.0
    assert iv.width > 0.01


def test_unknown_scope_and_single_case_population_raise():
    with pytest.raises(ValueError):
        pass_rate_interval({"a": [True]}, scope="everything")
    with pytest.raises(ValueError):
        pass_rate_interval({"a": [True, False]}, scope="population")


def test_compare_requires_same_cases():
    with pytest.raises(ValueError):
        compare({"a": [True]}, {"b": [True]})


def test_compare_identical_runs_is_not_significant():
    outcomes = {f"c{i}": [True, False, True] for i in range(12)}
    result = compare(outcomes, outcomes, seed=0)
    assert result.delta.estimate == 0.0
    assert result.p_value == 1.0
    assert result.delta.contains(0.0)


def test_compare_detects_a_large_improvement():
    base = {f"c{i}": [False, False, False, True, False] for i in range(30)}
    better = {f"c{i}": [True, True, True, True, False] for i in range(30)}
    result = compare(base, better, seed=0)
    assert result.delta.estimate == pytest.approx(0.6)
    assert result.delta.low > 0
    assert result.detected
    assert result.p_value < 0.001


def test_compare_is_symmetric_in_sign():
    rng = np.random.default_rng(3)
    base = {f"c{i}": list(rng.random(5) < 0.5) for i in range(25)}
    cand = {f"c{i}": list(rng.random(5) < 0.7) for i in range(25)}
    fwd = compare(base, cand, seed=5)
    rev = compare(cand, base, seed=5)
    assert fwd.delta.estimate == pytest.approx(-rev.delta.estimate)
    assert fwd.p_value == pytest.approx(rev.p_value, abs=0.02)


def test_population_delta_is_not_public_in_v0_1():
    """Amendment 1/2: the population-scope delta failed the width rule."""
    from realdelta import delta_interval, plan_trials

    outcomes = {f"c{i}": [True, False, True] for i in range(10)}
    with pytest.raises(NotImplementedError):
        delta_interval(outcomes, outcomes, scope="population")
    with pytest.raises(NotImplementedError):
        compare(outcomes, outcomes, scope="population")
    with pytest.raises(NotImplementedError):
        plan_trials(10, 0.1, trials_options=(3,), scope="population", n_sim=2, seed=0)


def test_suite_delta_is_mover_over_wilson_arms():
    """Pins the shipped suite delta (docs/calibration_protocol.md: MOVER over Wilson arm intervals).

    When every case in an arm has the same count k of n, that arm's effective sample size is m * n
    and its suite interval is the Wilson interval for m * k of m * n trials, so the expected delta
    interval follows from the public wilson_interval and Newcombe's hybrid score formula.
    Formula pin, not a calibration gate: added after mutation checks (Wilson arms survived every
    other test); the expected value comes from the public wilson_interval and does not depend on
    the grid.
    """
    from realdelta import delta_interval

    m, n, k_a, k_b = 12, 5, 4, 2
    baseline = {f"c{i}": [True] * k_a + [False] * (n - k_a) for i in range(m)}
    candidate = {f"c{i}": [True] * k_b + [False] * (n - k_b) for i in range(m)}
    a, b = wilson_interval(m * k_a, m * n), wilson_interval(m * k_b, m * n)
    d = b.estimate - a.estimate
    want_low = d - math.sqrt((b.estimate - b.low) ** 2 + (a.high - a.estimate) ** 2)
    want_high = d + math.sqrt((b.high - b.estimate) ** 2 + (a.estimate - a.low) ** 2)
    iv = delta_interval(baseline, candidate)
    assert iv.low == pytest.approx(want_low, abs=1e-12)
    assert iv.high == pytest.approx(want_high, abs=1e-12)


def test_population_pass_rate_hull_includes_the_t_interval():
    """Pins the t term of the population hull (protocol: hull of suite, t and case-level floor).

    Ten cases with one trial each, five failing and five passing: the t interval (about 0.123 to
    0.877) is wider than the suite and floor terms (Clopper-Pearson 5 of 10, about 0.187 to 0.813)
    on both sides and is not clipped at 0 or 1. Formula pin, not a calibration gate: added after
    mutation checks (dropping the t term survived every other test); the expected value is an
    independent scipy computation and does not depend on the grid.
    """
    from scipy import stats as st

    outcomes = {f"c{i}": [i >= 5] for i in range(10)}
    rates = np.array([0.0] * 5 + [1.0] * 5)
    half = st.t.ppf(0.975, 9) * rates.std(ddof=1) / math.sqrt(10)
    iv = pass_rate_interval(outcomes, scope="population")
    assert 0.0 < iv.low and iv.high < 1.0
    assert iv.low == pytest.approx(0.5 - half, abs=1e-12)
    assert iv.high == pytest.approx(0.5 + half, abs=1e-12)


def test_suite_delta_is_antisymmetric_in_the_two_arms():
    """delta(a, b) == -delta(b, a). With it, the gated +0.05/+0.10 delta rows also cover the
    reversed pairs (drops of the same realised size from the shifted baseline). Arms are built with
    different key orders, so summation order differs; hence the 1e-12 tolerance."""
    from realdelta import delta_interval

    rng = np.random.default_rng(3)
    for _ in range(300):
        m = int(rng.integers(2, 40))
        trials = rng.choice([1, 3, 5, 10], size=m)
        a = {f"c{i}": list(rng.random(int(trials[i])) < rng.random()) for i in range(m)}
        b = {f"c{i}": list(rng.random(int(trials[i])) < rng.random()) for i in reversed(range(m))}
        forward, backward = delta_interval(a, b), delta_interval(b, a)
        assert forward.estimate == pytest.approx(-backward.estimate, abs=1e-12)
        assert forward.low == pytest.approx(-backward.high, abs=1e-12)
        assert forward.high == pytest.approx(-backward.low, abs=1e-12)
