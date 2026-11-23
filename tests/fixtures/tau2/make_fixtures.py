"""Generate tau2-bench result-file fixtures with upstream tau2 code (not run in CI).

The files are synthetic: no model was called, and every simulation is built here. They are written by
tau2's own `Results.save`, and `expected.json` holds what tau2's own `get_metrics_df` and `compute_metrics`
report for them, so the realdelta loader is checked against the upstream implementation, not against our
reading of it.

Environment used (recorded in expected.json): sierra-research/tau2-bench at commit
768f3d8fe8528b4f32a5096f9ed008ae50f48ead (MIT licence), installed with `pip install <clone>` into a throwaway
venv on Python 3.13, plus `audioop-lts` because tau2 imports `audioop`, which Python 3.13 removed, and
`pandas==2.3.3`, the version upstream's uv.lock pins. tau2's pyproject allows pandas>=2.2.3, so a plain pip install
resolves pandas 3; with pandas 3.1.1 tau2's get_metrics_df did not drop infrastructure errors on these files (20
rows instead of 19, pass_hat_1 0.45 instead of 0.4667), so the script refuses to run under another pandas.

Run: TAU2_DATA_DIR=<clone>/data <venv>/bin/python tests/fixtures/tau2/make_fixtures.py
"""

import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

from tau2.data_model.simulation import Info, Results, RewardInfo, SimulationRun, TerminationReason, UserInfo
from tau2.data_model.tasks import EvaluationCriteria, Task, UserScenario
from tau2.environment.environment import EnvironmentInfo
from tau2.metrics.agent_metrics import compute_metrics, get_metrics_df

OUT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "768f3d8fe8528b4f32a5096f9ed008ae50f48ead"
T = TerminationReason


def info(domain="mock", num_trials=4):
    return Info(git_commit="synthetic", num_trials=num_trials, max_steps=100, max_errors=10,
                user_info=UserInfo(implementation="user_simulator"), agent_info={"implementation": "llm_agent"},
                environment_info=EnvironmentInfo(domain_name=domain, policy="synthetic policy"))


def task(tid):
    return Task(id=tid, user_scenario=UserScenario(instructions="synthetic"), evaluation_criteria=EvaluationCriteria())


def sim(tid, trial, reward, reason=T.USER_STOP):
    return SimulationRun(id=f"sim-{tid}-t{trial}", task_id=tid, start_time="2026-01-01T00:00:00",
                         end_time="2026-01-01T00:01:00", timestamp="2026-01-01T00:01:00", duration=60.0, termination_reason=reason, messages=[],
                         trial=trial, seed=7, reward_info=None if reward is None else RewardInfo(reward=reward))


# t0 passes always; t1 alternates; t2 probes the success threshold (1 - 5e-7 passes, 1 - 2e-6 fails);
# t3 has an agent_error without reward_info and one infrastructure error (3 trials remain after dropping it,
# so the macro and micro pass rates differ); t4 fails always.
MAIN = {
    "t0": [(1.0, T.USER_STOP)] * 4,
    "t1": [(1.0, T.USER_STOP), (0.0, T.USER_STOP), (1.0, T.USER_STOP), (0.0, T.USER_STOP)],
    "t2": [(1 - 5e-7, T.USER_STOP), (1 - 2e-6, T.USER_STOP), (1.0, T.USER_STOP), (0.0, T.USER_STOP)],
    "t3": [(None, T.AGENT_ERROR), (1.0, T.USER_STOP), (None, T.INFRASTRUCTURE_ERROR), (0.0, T.USER_STOP)],
    "t4": [(0.0, T.MAX_STEPS)] * 4,
}


def results(spec, extra_tasks=(), domain="mock"):
    sims = [sim(tid, i, r, why) for tid, rows in spec.items() for i, (r, why) in enumerate(rows)]
    return Results(timestamp="2026-01-01T00:00:00", info=info(domain), tasks=[task(t) for t in [*spec, *extra_tasks]],
                   simulations=sims)


def upstream_view(res):
    df, max_k = get_metrics_df(res)
    rows = sorted((str(r.task_id), int(r.trial), bool(r.success)) for r in df.itertuples())
    m = compute_metrics(res)
    return {"rows": rows, "pass_hat_1": m.pass_hat_ks.get(1), "avg_reward": m.avg_reward,
            "n_rows": len(rows), "max_k": int(max_k)}


def main():
    if importlib.metadata.version("pandas") != "2.3.3":
        raise SystemExit("run with pandas==2.3.3 (upstream uv.lock); see the module docstring")
    for p in OUT.glob("*"):
        if p.name != Path(__file__).name:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    expected = {"upstream_commit": UPSTREAM_COMMIT, "tau2_version": importlib.metadata.version("tau2"),
                "pandas_version": importlib.metadata.version("pandas"), "python": sys.version.split()[0]}

    r = results(MAIN)
    r.save(OUT / "main.json", format="json")
    r.save(OUT / "main_dir" / "results.json", format="dir")
    expected["main"] = upstream_view(r)
    assert expected["main"]["n_rows"] == 19, "upstream did not drop the infrastructure error"

    # A dir-format run loaded and saved again as one json file carries both simulations and the index.
    both = Results.load(OUT / "main_dir" / "results.json")
    both.save(OUT / "main_both.json", format="json")
    raw = json.loads((OUT / "main_both.json").read_text())
    expected["main_both_has_index_and_simulations"] = bool(raw.get("simulation_index")) and bool(raw.get("simulations"))
    # The realdelta loader reads the dir format's index only, as for the leaderboard bucket's files; the
    # per-simulation files are not needed and are not committed.
    shutil.rmtree(OUT / "main_dir" / "simulations")

    # A task whose every trial is an infrastructure error; upstream drops it from the metrics.
    r = results({**MAIN, "t5": [(None, T.INFRASTRUCTURE_ERROR)] * 4})
    r.save(OUT / "all_infra.json", format="json")
    expected["all_infra"] = upstream_view(r)

    # A task listed in `tasks` with no simulation at all (an unfinished run).
    r = results(MAIN, extra_tasks=("t6",))
    r.save(OUT / "missing_task.json", format="json")

    # Another domain, for the domain check in compare.
    results(MAIN, domain="other").save(OUT / "other_domain.json", format="json")

    (OUT / "expected.json").write_text(json.dumps(expected, indent=1) + "\n")
    print(json.dumps({k: v for k, v in expected.items() if k not in ("main", "all_infra")}, indent=1))
    for k in ("main", "all_infra"):
        print(k, {kk: vv for kk, vv in expected[k].items() if kk != "rows"})


if __name__ == "__main__":
    main()
