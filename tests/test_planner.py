import pytest

from realdelta import estimate_cost, plan_trials


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
