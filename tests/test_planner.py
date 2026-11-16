import numpy as np
import pytest

from realdelta import SimulatedSuite, estimate_cost, plan_trials


def test_estimate_cost_arithmetic():
    est = estimate_cost(
        n_cases=40, trials=5, arms=2,
        input_tokens_per_run=3000, output_tokens_per_run=500,
        usd_per_million_input=1.0, usd_per_million_output=5.0,
    )
    assert est.runs == 400
    assert est.input_tokens == 1_200_000
    assert est.output_tokens == 200_000
    assert est.usd == pytest.approx(1.2 + 1.0)


def test_plan_trials_power_grows_with_trials():
    rows = plan_trials(n_cases=30, delta=-0.1, trials_options=(1, 10), n_sim=150, seed=0)
    assert [r.trials for r in rows] == [1, 10]
    assert rows[1].power > rows[0].power + 0.2
    assert all(r.false_alarm_rate <= 0.1 for r in rows)
    assert rows[1].total_runs == 2 * 30 * 10


def test_plan_trials_rejects_zero_delta():
    with pytest.raises(ValueError):
        plan_trials(n_cases=10, delta=0.0)


# Phase 2: "break" model (plan v2 section 3)

def test_break_cases_sets_exactly_k_rates_to_zero_and_keeps_the_rest():
    from realdelta.planner import break_cases

    suite = SimulatedSuite({f"c{i}": 0.5 + i / 100 for i in range(20)})
    for k in (1, 7, 20):
        out = break_cases(suite, k, np.random.default_rng(4))
        changed = [n for n in suite.true_rates if out.true_rates[n] != suite.true_rates[n]]
        assert len(changed) == k
        assert all(out.true_rates[n] == 0.0 for n in changed)
        assert list(out.true_rates) == list(suite.true_rates)
    again = break_cases(suite, 7, np.random.default_rng(4))
    assert again == break_cases(suite, 7, np.random.default_rng(4))


def test_break_and_shift_share_the_null_with_the_same_seed():
    kwargs = dict(n_cases=15, trials_options=(1, 3), n_sim=60, seed=11)
    shift = plan_trials(delta=-0.1, **kwargs)
    brk = plan_trials(change="break", k=3, **kwargs)
    assert [r.false_alarm_rate for r in shift] == [r.false_alarm_rate for r in brk]


def test_break_realised_change_and_power():
    rows = plan_trials(20, change="break", k=4, alpha=50.0, beta=1.0, trials_options=(1, 20), n_sim=80, seed=2)
    for r in rows:
        # four of twenty cases at rate ~0.98 dropped to 0: about -0.196
        assert -0.2 < r.realised_change < -0.19
    assert rows[1].power > 0.95 and rows[1].power > rows[0].power
    assert rows[1].power_se == pytest.approx((rows[1].power * (1 - rows[1].power) / 80) ** 0.5)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(change="shift"),
        dict(change="shift", delta=0.0),
        dict(change="shift", delta=0.1, k=2),
        dict(change="break"),
        dict(change="break", k=0),
        dict(change="break", k=11),
        dict(change="break", k=True),
        dict(change="break", k=2, delta=0.1),
        dict(change="flip", k=2),
    ],
)
def test_bad_planner_arguments(kwargs):
    with pytest.raises(ValueError):
        plan_trials(10, trials_options=(1,), n_sim=2, seed=0, **kwargs)


def test_population_scope_raises_before_simulating(monkeypatch):
    import realdelta.planner as planner

    def boom(*args, **kwargs):
        raise AssertionError("simulation started")

    monkeypatch.setattr(planner.SimulatedSuite, "from_beta", boom)
    for kwargs in (dict(delta=0.1), dict(change="break", k=2)):
        with pytest.raises(NotImplementedError):
            plan_trials(10, scope="population", trials_options=(1,), n_sim=2, seed=0, **kwargs)
