"""realdelta: is that change in your agent eval real, or noise?"""

from .io import (
    InspectOutcomes,
    ResultFileError,
    Tau2Outcomes,
    check_inspect_pairing,
    load_inspect_log,
    load_outcomes,
    load_tau2_results,
)
from .planner import CostEstimate, PlanRow, estimate_cost, plan_trials
from .simulate import SimulatedSuite
from .stats import (
    CaseChange,
    Comparison,
    Interval,
    case_changes,
    case_level_interval,
    compare,
    delta_interval,
    macro_pass_rate,
    pass_hat_k,
    pass_rate_interval,
    wilson_interval,
)

__all__ = [
    "CaseChange",
    "Comparison",
    "CostEstimate",
    "Interval",
    "InspectOutcomes",
    "PlanRow",
    "ResultFileError",
    "SimulatedSuite",
    "Tau2Outcomes",
    "case_changes",
    "case_level_interval",
    "check_inspect_pairing",
    "compare",
    "delta_interval",
    "estimate_cost",
    "load_inspect_log",
    "load_outcomes",
    "load_tau2_results",
    "macro_pass_rate",
    "pass_hat_k",
    "pass_rate_interval",
    "plan_trials",
    "wilson_interval",
]

__version__ = "0.2.0.dev0"
