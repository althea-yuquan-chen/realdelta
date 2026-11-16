"""Unit tests for the truth helpers and generators in scripts/calibration_grid.py.

They check the grid's ground truth independently of any interval method, which is
what the protocol requires before a grid-script bug can be fixed after a final run.
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import integrate
from scipy import stats as st

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "calibration_grid.py"
_spec = importlib.util.spec_from_file_location("calibration_grid", _PATH)
grid = importlib.util.module_from_spec(_spec)
sys.modules["calibration_grid"] = grid  # dataclasses look the module up while executing it
_spec.loader.exec_module(grid)


def test_mixture_mean():
    assert grid.mixture_mean({1.0: 0.8, 0.7: 0.1, 0.0: 0.1}) == pytest.approx(0.87)


@pytest.mark.parametrize("a,b,delta", [(4, 2, 0.05), (4, 2, 0.10), (20, 1, 0.05), (20, 1, 0.10)])
def test_shift_truth_matches_numerical_integration(a, b, delta):
    # E[clip(q + d) - q] = d - E[(q + d - 1)^+]
    excess, _ = integrate.quad(lambda q: (q + delta - 1.0) * st.beta.pdf(q, a, b), 1.0 - delta, 1.0)
    assert grid.shift_truth(a, b, delta) == pytest.approx(delta - excess, abs=5e-4)


def _share_changed(transform, base, n=400_000):
    rng = np.random.default_rng(0)
    pa = rng.choice(np.array(list(base.keys())), size=n, p=np.array(list(base.values())))
    pb = transform(rng, pa)
    return float(np.mean(pb - pa))


@pytest.mark.parametrize("g", [0.05, 0.10])
def test_break_and_fix_shares_are_shares_of_all_cases(g):
    assert _share_changed(grid.break_share(g, 0.95), {1.0: 0.95, 0.0: 0.05}) == pytest.approx(-g, abs=2e-3)
    assert _share_changed(grid.fix_share(g, 0.15), {1.0: 0.85, 0.0: 0.15}) == pytest.approx(+g, abs=2e-3)


def test_two_way_churn_has_zero_mean_change():
    assert _share_changed(grid.churn(0.5, 0.125), {1.0: 0.8, 0.0: 0.2}) == pytest.approx(0.0, abs=2e-3)


@pytest.mark.parametrize("sticky", [0.0, 0.5, 0.8])
def test_sticky_trials_keep_marginal_rate(sticky):
    rng = np.random.default_rng(1)
    rates = np.full(4000, 0.3)
    out = grid.simulate_trials(rng, rates, np.full(4000, 5), sticky=sticky)
    per_trial = np.array(list(out.values())).mean(axis=0)
    assert np.allclose(per_trial, 0.3, atol=0.02)


def test_deterministic_cases_ignore_shocks():
    rng = np.random.default_rng(2)
    out = grid.simulate_trials(rng, np.array([1.0, 0.0]), np.array([5, 5]), shocks=np.full(5, 3.0))
    assert out["c000"] == [True] * 5 and out["c001"] == [False] * 5


def test_grid_has_expected_shape():
    settings = grid.build_settings()
    ids = [s.id for s in settings]
    assert len(ids) == len(set(ids))
    assert sum(s.id.startswith("D4") for s in settings) == 16
    assert all(s.gated.keys() == set(s.scopes) for s in settings)


def test_amendment_1_drops_population_delta_rows():
    settings = grid.build_settings()
    assert grid.SEED_BASE == 20261117
    assert not any(s.kind == "delta" and "population" in s.scopes for s in settings)
    assert any(s.kind == "rate" and "population" in s.scopes for s in settings)
    assert len(settings) == 66
    assert sum(s.kind == "delta" and "suite" in s.scopes for s in settings) == 26  # D3 8, D4 16, D6 1, V2 1
