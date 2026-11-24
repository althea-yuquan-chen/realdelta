"""Validation of per-case posterior planning for `plan --from` (protocol: plan_from_validation_protocol_20261123).

Phase "truth": true power and false-alarm rate of each synthetic suite (no method involved); writes the truth file
and the list of decision cells (mean true power in [0.2, 0.9]). Phase "methods": estimates from one observed file
per suite with each method, compared with the saved truth. Uses realdelta's internal _delta_interval, the code
path plan_trials uses. Refuses to overwrite its outputs.

    python scripts/plan_from_validation.py truth   OUT_DIR
    python scripts/plan_from_validation.py methods OUT_DIR PROTOCOL_FILE
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from realdelta.stats import _delta_interval

SEED = 20261124
N_SUITES = 50
N_TRUE = 2000
N_EST = 200
DISTS = ["Beta(20,1)", "Beta(4,2)", "Beta(0.5,0.5)", "Mix"]
MS = [10, 30]
N_OBS = [3, 5]
SHIFT = -0.05
METHODS = ["P-Jeffreys", "P-uniform", "P-pooled", "Plug-in", "Oracle"]
POWER_BAND = (0.2, 0.9)
MIN_DECISION_CELLS = 8


def settings():
    return [(d, m, n) for d in DISTS for m in MS for n in N_OBS]


def changes(m):
    return [("break", 1), ("break", 2 if m == 10 else 3), ("shift", SHIFT)]


def n_plans(n_obs):
    return sorted({n_obs, 5, 10})


def true_rates(dist, m, rng):
    if dist == "Mix":
        r = np.ones(m)
        unstable = rng.random(m) < 0.2
        r[unstable] = rng.uniform(0.3, 0.9, unstable.sum())
        return r
    a, b = {"Beta(20,1)": (20, 1), "Beta(4,2)": (4, 2), "Beta(0.5,0.5)": (0.5, 0.5)}[dist]
    return rng.beta(a, b, m)


def suite(s_idx, j, dist, m, n_obs):
    rates = true_rates(dist, m, np.random.default_rng([SEED, s_idx, j, 0]))
    observed = np.random.default_rng([SEED, s_idx, j, 1]).binomial(n_obs, rates)
    return rates, observed


def candidate(rates, change, rng):
    kind, size = change
    if kind == "shift":
        return np.clip(rates + size, 0.0, 1.0)
    out = rates.copy()
    out[rng.choice(len(rates), size=size, replace=False)] = 0.0
    return out


def detect(rates, change, n, sims, rng, draw=None):
    """Power, false-alarm rate and mean realised change; draw() gives the rates for one simulation."""
    t = np.full(len(rates), float(n))
    hits = alarms = 0
    realised = 0.0
    for _ in range(sims):
        r = rates if draw is None else draw(rng)
        rc = candidate(r, change, rng)
        realised += rc.mean() - r.mean()
        a = rng.binomial(n, r).astype(float)
        b = rng.binomial(n, rc).astype(float)
        b0 = rng.binomial(n, r).astype(float)
        if _delta_interval(a, t, b, t, "suite", 0.95).high < 0:
            hits += 1
        if not _delta_interval(a, t, b0, t, "suite", 0.95).contains(0.0):
            alarms += 1
    return hits / sims, alarms / sims, realised / sims


def drawer(method, x, n_obs):
    if method == "Plug-in":
        p = x / n_obs
        return lambda rng: p
    if method == "P-pooled":
        pbar = (x.sum() + 0.5) / (n_obs * len(x) + 1)
        a0, b0 = 2 * pbar, 2 * (1 - pbar)
    else:
        a0 = b0 = 0.5 if method == "P-Jeffreys" else 1.0
    return lambda rng: rng.beta(x + a0, n_obs - x + b0)


def cell_key(dist, m, n_obs, change, n_plan):
    return f"{dist}|m={m}|n_obs={n_obs}|{change[0]}={change[1]}|n_plan={n_plan}"


def phase_truth(out: Path) -> None:
    rows = {}
    for s_idx, (dist, m, n_obs) in enumerate(settings()):
        for j in range(N_SUITES):
            rates, _ = suite(s_idx, j, dist, m, n_obs)
            for c_idx, change in enumerate(changes(m)):
                for n_plan in n_plans(n_obs):
                    rng = np.random.default_rng([SEED, s_idx, j, 2, c_idx, n_plan])
                    p, fa, rc = detect(rates, change, n_plan, N_TRUE, rng)
                    rows.setdefault(cell_key(dist, m, n_obs, change, n_plan), []).append(
                        {"suite": j, "power": p, "false_alarm": fa, "realised_change": rc})
        print("truth done:", dist, m, n_obs, flush=True)
    means = {k: float(np.mean([r["power"] for r in v])) for k, v in rows.items()}
    decision = sorted(k for k, v in means.items() if POWER_BAND[0] <= v <= POWER_BAND[1])
    (out / "truth.json").write_text(json.dumps({"seed": SEED, "n_true": N_TRUE, "rows": rows}, indent=0))
    (out / "decision_cells.json").write_text(json.dumps({"band": POWER_BAND, "mean_true_power": means,
                                                         "decision_cells": decision}, indent=1))
    print(f"{len(decision)} decision cells (need >= {MIN_DECISION_CELLS})")


def phase_methods(out: Path, protocol: Path) -> None:
    truth = json.loads((out / "truth.json").read_text())["rows"]
    decision = json.loads((out / "decision_cells.json").read_text())["decision_cells"]
    record = {"protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(), "seed": SEED, "n_est": N_EST,
              "decision_cells": decision, "cells": {}}
    for s_idx, (dist, m, n_obs) in enumerate(settings()):
        for j in range(N_SUITES):
            rates, x = suite(s_idx, j, dist, m, n_obs)
            for c_idx, change in enumerate(changes(m)):
                for n_plan in n_plans(n_obs):
                    key = cell_key(dist, m, n_obs, change, n_plan)
                    tr = truth[key][j]
                    est = {}
                    for meth in METHODS:
                        rng = np.random.default_rng([SEED, s_idx, j, 3, c_idx, n_plan])  # same stream per method
                        if meth == "Oracle":
                            p, fa, _ = detect(rates, change, n_plan, N_EST, rng)
                        elif meth == "Plug-in":
                            p, fa, _ = detect(x / n_obs, change, n_plan, N_EST, rng)
                        else:
                            p, fa, _ = detect(rates, change, n_plan, N_EST, rng, draw=drawer(meth, x, n_obs))
                        est[meth] = {"power": p, "false_alarm": fa}
                    record["cells"].setdefault(key, []).append({"suite": j, "true": tr, "est": est})
        print("methods done:", dist, m, n_obs, flush=True)
    (out / "methods.json").write_text(json.dumps(record, indent=0))


def main(argv):
    phase, out = argv[1], Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    target = out / ("truth.json" if phase == "truth" else "methods.json")
    if target.exists():
        raise SystemExit(f"refusing to overwrite {target}")
    if phase == "truth":
        phase_truth(out)
    else:
        phase_methods(out, Path(argv[3]))


if __name__ == "__main__":
    main(sys.argv)
