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
