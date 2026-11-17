"""Post-hoc power calculation for the primary pair (PROTOCOL.md, Amendment 4).

With realdelta 0.1.1's suite-scope interval (95%), two independent arms (assumptions A3 and A5 hold) and per-task
pass rates drawn from a Beta distribution fitted by beta-binomial maximum likelihood to the per-task pass counts of
A and C (pinned files): how many trials per task does a 50-task comparison need to detect a 1-point change with
power 0.8, and which changes does it detect at 4 trials? Uses realdelta.plan_trials. These are simulation results
for synthetic suites, not a statement about submissions A or C. Writes examples/tau2_leaderboard/posthoc_power.md and posthoc_power.json; refuses to
overwrite them, to run on a dirty tree, or on files that do not match manifest.json.

Usage: python examples/tau2_leaderboard/plan_power.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import minimize
from scipy.stats import betabinom

import realdelta
from realdelta.planner import plan_trials

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = HERE / "data"
OUT_MD = HERE / "posthoc_power.md"
OUT_JSON = HERE / "posthoc_power.json"
FIT_FROM = {"A": "claude-opus-4-5_sierra_2026-02-26", "C": "gpt-5-2_sierra_2026-02-26"}
N_CASES = 50
N_TRIALS_OBSERVED = 4
SEED = 20261117
N_SIM = 1000
POWER_TARGET = 0.8
TRIALS_GRID = (4, 16, 64, 128, 256, 512, 1024)
DELTA_ONE_POINT = -0.01  # design target: one leaderboard point; not the observed A vs C difference
DELTA_GRID = (-0.01, -0.02, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.12, -0.15, -0.20)
BREAK_K = (1, 2, 5, 10)
REALDELTA_VERSION = "0.1.1"
DEFAULT_BETA = (8.0, 2.0)  # realdelta's planner default, shown for contrast
NEWLINE = chr(10)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def pass_counts(sub: str, manifest: dict) -> list[int]:
    name = f"{sub}.airline.results.json"
    raw = (DATA / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"].get(name):
        raise SystemExit(f"{name} does not match manifest.json")
    counts: dict[str, list[bool]] = {}
    for x in json.loads(raw)["simulation_index"]:
        if x["reward"] not in (0.0, 1.0):
            raise SystemExit(f"{sub}: reward {x['reward']!r} is not 0 or 1")
        counts.setdefault(str(x["task_id"]), []).append(x["reward"] == 1.0)
    if len(counts) != N_CASES or any(len(v) != N_TRIALS_OBSERVED for v in counts.values()):
        raise SystemExit(f"{sub}: not {N_CASES} tasks x {N_TRIALS_OBSERVED} trials")
    return [sum(v) for v in counts.values()]


def fit_beta(counts: np.ndarray) -> tuple[float, float, float, bool]:
    def nll(theta: np.ndarray) -> float:
        a, b = np.exp(theta)
        return -float(betabinom.logpmf(counts, N_TRIALS_OBSERVED, a, b).sum())

    fits = [minimize(nll, x0=np.log(x0), method="Nelder-Mead", options={"xatol": 1e-8, "fatol": 1e-10, "maxiter": 10000})
            for x0 in ([1.0, 1.0], [0.3, 0.3])]
    if not all(f.success for f in fits):
        raise SystemExit("beta-binomial fit did not converge")
    (a, b), (a2, b2) = np.exp(fits[0].x), np.exp(fits[1].x)
    if abs(a - a2) > 1e-3 * a or abs(b - b2) > 1e-3 * b:
        raise SystemExit(f"beta-binomial fit depends on the start: ({a}, {b}) vs ({a2}, {b2})")
    if min(a, b) < 0.01:
        raise SystemExit(f"degenerate beta-binomial fit: ({a}, {b})")
    return float(a), float(b), float(-fits[0].fun), True


def rows(**kw) -> list[dict]:
    return [{"trials": r.trials, "power": r.power, "power_se": r.power_se, "false_alarm_rate": r.false_alarm_rate,
             "false_alarm_se": r.false_alarm_se, "realised_change": r.realised_change, "total_runs": r.total_runs}
            for r in plan_trials(N_CASES, scope="suite", n_sim=N_SIM, seed=SEED, **kw)]


def first_reaching(rows_: list[dict]) -> tuple[dict | None, dict | None]:
    """The first row whose power point estimate reaches POWER_TARGET, and the row before it."""
    for i, r in enumerate(rows_):
        if r["power"] >= POWER_TARGET:
            return r, (rows_[i - 1] if i > 0 else None)
    return None, None


def read_false_alarms(r: dict) -> str:
    """The reading fixed in Amendment 4, for a 4-trial row only, with the Monte Carlo error."""
    fa, se = r["false_alarm_rate"], r["false_alarm_se"]
    if fa - 2 * se > 0.07:
        return f"{fa:.3f} (SE {se:.3f}): above the calibration gate of 0.07 by more than 2 SE"
    if fa + 2 * se < 0.05:
        return f"{fa:.3f} (SE {se:.3f}): below 0.05 by more than 2 SE, so the interval is conservative here"
    return f"{fa:.3f} (SE {se:.3f}): not distinguishable from 0.05-0.07 at this simulation size"


def main() -> int:
    if realdelta.__version__ != REALDELTA_VERSION:
        print(f"refusing to run: realdelta {realdelta.__version__}, Amendment 4 fixes {REALDELTA_VERSION}", file=sys.stderr)
        return 1
    if Path(realdelta.__file__).resolve().parent != (REPO / "src" / "realdelta").resolve():
        print(f"refusing to run: realdelta imported from {realdelta.__file__}", file=sys.stderr)
        return 1
    for out in (OUT_MD, OUT_JSON):
        if out.exists():
            print(f"refusing to overwrite {out.name}", file=sys.stderr)
            return 1
    if git("status", "--porcelain"):
        print("refusing to run: the working tree is not clean", file=sys.stderr)
        return 1
    commit = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        print(f"refusing to run: commit {commit!r} is not a full hash", file=sys.stderr)
        return 1
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    counts = np.array([c for sub in FIT_FROM.values() for c in pass_counts(sub, manifest)])
    a, b, loglik, _ = fit_beta(counts)
    try:
        aa, ab_, _, _ = fit_beta(np.array(pass_counts(FIT_FROM["A"], manifest)))
        sens = {"alpha": aa, "beta": ab_}
        sens_text = f"Beta({aa:.3f}, {ab_:.3f})"
    except SystemExit as e:  # a sensitivity check only; it does not stop the main result
        sens = {"not_available": str(e)}
        sens_text = f"not available ({e})"
    hist = {int(k): int((counts == k).sum()) for k in range(N_TRIALS_OBSERVED + 1)}
    fitted = {int(k): float(len(counts) * betabinom.pmf(k, N_TRIALS_OBSERVED, a, b))
              for k in range(N_TRIALS_OBSERVED + 1)}

    t1 = rows(delta=DELTA_ONE_POINT, trials_options=TRIALS_GRID, alpha=a, beta=b)
    t2 = [{"delta": d, **rows(delta=d, trials_options=(N_TRIALS_OBSERVED,), alpha=a, beta=b)[0]} for d in DELTA_GRID]
    t3 = rows(delta=DELTA_ONE_POINT, trials_options=TRIALS_GRID, alpha=DEFAULT_BETA[0], beta=DEFAULT_BETA[1])
    t4 = [{"k": k, **rows(change="break", k=k, trials_options=(N_TRIALS_OBSERVED,), alpha=a, beta=b)[0]} for k in BREAK_K]
    hit1, before1 = first_reaching(t1)
    hit2, before2 = first_reaching(t2)

    meta = {"commit": commit, "realdelta_version": realdelta.__version__, "manifest_fetched_at": manifest["fetched_at_utc"],
            "seed": SEED, "n_sim": N_SIM, "n_cases": N_CASES, "fit_from": FIT_FROM, "power_target": POWER_TARGET,
            "numpy": np.__version__, "scipy": scipy.__version__}
    fit = {"alpha": a, "beta": b, "loglik": loglik, "observed_count_histogram": hist, "fitted_expected": fitted,
           "sensitivity_fit_A_only": sens}

    def prev(r):
        return f"; the option before it has power {r['power']:.3f} (SE {r['power_se']:.3f})" if r else ""

    headline = [
        "- A 1-point change (a design target, not the observed A vs C difference): " +
        (f"power first reaches {POWER_TARGET} at {hit1['trials']} trials per task, power {hit1['power']:.3f} "
         f"(SE {hit1['power_se']:.3f}){prev(before1)}." if hit1 else
         f"power {POWER_TARGET} is not reached within the grid (up to {TRIALS_GRID[-1]} trials per task)."),
        f"- At {N_TRIALS_OBSERVED} trials per task: " +
        (f"power first reaches {POWER_TARGET} at a shift of {hit2['delta']:+.2f} (realised change "
         f"{hit2['realised_change']:+.4f}), power {hit2['power']:.3f} (SE {hit2['power_se']:.3f}){prev(before2)}." if hit2 else
         f"power {POWER_TARGET} is not reached within the grid (down to a shift of {DELTA_GRID[-1]:+.2f})."),
        "- Power is compared with the target as a point estimate; a row within about 2 SE of it could fall on either "
        "side with another seed."]
    L = ["# Post-hoc power for a 50-task airline comparison (PROTOCOL.md, Amendment 4)", "",
         f"Run at commit {commit}, realdelta {realdelta.__version__}; data fetched {manifest['fetched_at_utc']} "
         f"(manifest.json). realdelta.plan_trials, suite scope, 95%, {N_SIM} simulations per row, seed {SEED}. "
         "Not part of the pre-registered analysis. Simulation results for synthetic 50-task suites, not a "
         "statement about submissions A or C.", "",
         "Assumptions: realdelta 0.1.1's suite-scope interval; two independent arms (A3 and A5 hold); per-task rates "
         "from the fitted Beta. Four trials cannot tell a rate of 1 from 0.97, so rows with many trials depend on the "
         "fitted Beta's shape near 0 and 1: they are an extrapolation.", "",
         f"Power target {POWER_TARGET}:", *headline, "",
         f"Per-task pass rates: Beta({a:.3f}, {b:.3f}), fitted by beta-binomial maximum likelihood to the per-task pass "
         "counts (out of 4) of A and C: 50 tasks observed twice, not 100 independent tasks. Sensitivity, A only: "
         f"{sens_text}. numpy {np.__version__}, scipy {scipy.__version__}.", "",
         "| passes out of 4 | 0 | 1 | 2 | 3 | 4 |", "|---|---|---|---|---|---|",
         "| observed tasks (A and C) | " + " | ".join(str(hist[k]) for k in range(5)) + " |",
         "| expected under the fit | " + " | ".join(f"{fitted[k]:.1f}" for k in range(5)) + " |", "",
         f"## A 1-point change ({DELTA_ONE_POINT:+.2f}), fitted rates", "",
         "| trials per task | power (SE) | false alarms (SE) | realised change | total runs |", "|---|---|---|---|---|"]
    for r in t1:
        L.append(f"| {r['trials']} | {r['power']:.3f} ({r['power_se']:.3f}) | {r['false_alarm_rate']:.3f} "
                 f"({r['false_alarm_se']:.3f}) | {r['realised_change']:+.4f} | {r['total_runs']} |")
    L += ["", f"## Change sizes at {N_TRIALS_OBSERVED} trials per task, fitted rates", "",
          "All rows share one seed and the null run does not depend on the shift, so the false-alarm column repeats "
          "one estimate.", "",
          "| shift | power (SE) | false alarms (SE) | realised change |", "|---|---|---|---|"]
    for r in t2:
        L.append(f"| {r['delta']:+.2f} | {r['power']:.3f} ({r['power_se']:.3f}) | {r['false_alarm_rate']:.3f} "
                 f"({r['false_alarm_se']:.3f}) | {r['realised_change']:+.4f} |")
    L += ["", f"## Contrast: a 1-point change with the planner's default Beta{DEFAULT_BETA}", "",
          "| trials per task | power (SE) | false alarms (SE) | realised change |", "|---|---|---|---|"]
    for r in t3:
        L.append(f"| {r['trials']} | {r['power']:.3f} ({r['power_se']:.3f}) | {r['false_alarm_rate']:.3f} "
                 f"({r['false_alarm_se']:.3f}) | {r['realised_change']:+.4f} |")
    L += ["", f"## Contrast: k tasks break (rate set to 0) at {N_TRIALS_OBSERVED} trials per task, fitted rates", "",
          "The false-alarm column repeats the estimate of the change-size table (same seed, same null runs).", "",
          "| tasks broken | power (SE) | false alarms (SE) | realised change |", "|---|---|---|---|"]
    for r in t4:
        L.append(f"| {r['k']} | {r['power']:.3f} ({r['power_se']:.3f}) | {r['false_alarm_rate']:.3f} "
                 f"({r['false_alarm_se']:.3f}) | {r['realised_change']:+.4f} |")
    L += ["", "False alarms, read as fixed in Amendment 4 before the run. Only the 4-trial rows are read against the "
          "calibration gate: this is the study's setting (50 tasks, 4 trials). Rows with 16 or more trials lie outside "
          "the gated range (3-10 trials) and are reported, not judged.",
          f"- fitted rates, 4 trials: {read_false_alarms(t1[0])}",
          f"- planner default Beta{DEFAULT_BETA}, 4 trials: {read_false_alarms(t3[0])}", "",
          "The shift model adds the change to every task's rate and clips to [0, 1]; tasks at a rate of 0 cannot "
          "fall further, so the realised change can be smaller than the shift. 'power' counts intervals entirely "
          "below 0."]
    md = NEWLINE.join(L) + NEWLINE
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"meta": meta, "fit": fit, "one_point": t1, "change_sizes": t2,
                                    "default_beta_contrast": t3, "break_contrast": t4,
                                    "first_reaching_target_one_point": hit1,
                                    "first_reaching_target_at_4_trials": hit2}, indent=1), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
