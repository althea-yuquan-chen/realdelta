"""Snapshot of plan_trials' shift model, committed before the Phase 2 planner change.

The Phase 2 plan adds a "break" model and new PlanRow fields. The shift model must not change, so
this file pins the four original fields to the values produced at commit 7eedf80. It must not be
edited after the planner change; a failure here means the shift model's behaviour changed.
"""

from realdelta import plan_trials

CASES = [
    (dict(n_cases=20, delta=0.1, trials_options=(1, 3, 5), n_sim=50, seed=123),
     [(1, 0.08, 0.0, 40), (3, 0.24, 0.04, 120), (5, 0.5, 0.04, 200)]),
    (dict(n_cases=12, delta=-0.15, trials_options=(2, 10), alpha=20.0, beta=1.0, n_sim=40, seed=7),
     [(2, 0.275, 0.0, 48), (10, 0.95, 0.025, 240)]),
]


def test_shift_model_matches_snapshot():
    for kwargs, expected in CASES:
        rows = plan_trials(**kwargs)
        assert [(r.trials, r.power, r.false_alarm_rate, r.total_runs) for r in rows] == expected, kwargs
