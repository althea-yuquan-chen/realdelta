"""realdelta: is that change in your agent eval real, or noise?"""

from .io import ResultFileError, load_outcomes
from .planner import CostEstimate, PlanRow, estimate_cost, plan_trials
from .simulate import SimulatedSuite
from .stats import (
    Comparison,
    Interval,
    case_level_interval,
    compare,
    delta_interval,
    macro_pass_rate,
    pass_hat_k,
    pass_rate_interval,
    wilson_interval,
)

__all__ = [
    "Comparison",
    "CostEstimate",
    "Interval",
    "PlanRow",
    "ResultFileError",
    "SimulatedSuite",
    "case_level_interval",
    "compare",
    "delta_interval",
    "estimate_cost",
    "load_outcomes",
    "macro_pass_rate",
    "pass_hat_k",
    "pass_rate_interval",
    "plan_trials",
    "wilson_interval",
]

__version__ = "0.0.1"
