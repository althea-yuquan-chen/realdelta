"""Validation of per-case posterior planning for `plan --from`.

Round 1: protocol plan_from_validation_protocol_20261123 (run 2026-11-23 with commit 7f56072 of this script).
Round 2 (post-hoc): protocol plan_from_validation_round2_protocol_20261124.

Phase "truth": true power and false-alarm rate of each synthetic suite (no method involved); writes the truth file
and the list of decision cells (mean true power in [0.2, 0.9]). Phase "methods": estimates from one observed file
per suite with each method, compared with the saved truth. Uses realdelta's internal _delta_interval, the code
path plan_trials uses. Settings run in worker processes; every random stream is fixed by (seed, setting, suite,
...), so results do not depend on the number of workers. Refuses to overwrite its outputs.

    python scripts/plan_from_validation.py ROUND consistency OUT_DIR   (round 2)
    python scripts/plan_from_validation.py ROUND truth   OUT_DIR
    python scripts/plan_from_validation.py ROUND methods OUT_DIR PROTOCOL_FILE
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from realdelta.stats import _delta_interval

N_TRUE = 2000
N_EST = 200
SHIFT = -0.05
POWER_BAND = (0.2, 0.9)
MIN_DECISION_CELLS = 8

ROUNDS = {
    1: {
        "seed": 20261124,
        "n_suites": 50,
        "dists": ["Beta(20,1)", "Beta(4,2)", "Beta(0.5,0.5)", "Mix"],
        "ms": [10, 30],
        "n_obs": [3, 5],
        "big_k": lambda m: 2 if m == 10 else 3,
        "n_plan_extra": [5, 10],
        "methods": ["P-Jeffreys", "P-uniform", "P-pooled", "Plug-in", "Oracle"],
    },
    2: {
        "seed": 20261203,
        "n_suites": 100,
        "dists": ["Beta(20,1)", "Beta(4,2)", "Beta(0.5,0.5)", "Mix", "Beta(8,1)", "Tri", "Beta(50,1)", "Mix95",
                  "Mix90Z"],
        "ms": [20, 50, 120],
        "n_obs": [3, 4, 5],
        "big_k": lambda m: 3,
        "n_plan_extra": [5, 10, 20],
        "methods": ["P-pooled", "P-uniform", "Plug-in", "Oracle"],
        "f_min_candidates": [3, 6, 10],
        "min_gated_suites": 20,
        "near_ceiling": ["Beta(20,1)", "Mix", "Beta(50,1)", "Mix95", "Mix90Z"],
        "each_needed": ["Beta(50,1)", "Mix95", "Mix90Z"],  # each needs >= 2 decision cells at m in {50, 120}
        "consistency_seed": 20261202,
    },
}
BETAS = {"Beta(20,1)": (20, 1), "Beta(4,2)": (4, 2), "Beta(0.5,0.5)": (0.5, 0.5), "Beta(8,1)": (8, 1),
         "Beta(50,1)": (50, 1)}


def settings(cfg):
    return [(d, m, n) for d in cfg["dists"] for m in cfg["ms"] for n in cfg["n_obs"]]


def changes(cfg, m):
    return [("break", 1), ("break", cfg["big_k"](m)), ("shift", SHIFT)]


def n_plans(cfg, n_obs):
    return sorted({n_obs, *cfg["n_plan_extra"]})


def true_rates(dist, m, rng):
    if dist in ("Mix", "Mix95"):  # 80% (95%) exactly 1.0, the rest Uniform(0.3, 0.9)
        r = np.ones(m)
        unstable = rng.random(m) < (0.2 if dist == "Mix" else 0.05)
        r[unstable] = rng.uniform(0.3, 0.9, unstable.sum())
        return r
    if dist == "Mix90Z":  # 90% exactly 1.0, 5% exactly 0.0, 5% Uniform(0.3, 0.9)
        u = rng.random(m)
        r = np.where(u < 0.05, 0.0, 1.0)
        mid = (u >= 0.05) & (u < 0.10)
        r[mid] = rng.uniform(0.3, 0.9, mid.sum())
        return r
    if dist == "Tri":  # 30% exactly 0.0, 40% exactly 1.0, 30% Uniform(0.2, 0.8)
        u = rng.random(m)
        r = np.where(u < 0.3, 0.0, 1.0)
        mid = u >= 0.7
        r[mid] = rng.uniform(0.2, 0.8, mid.sum())
        return r
    a, b = BETAS[dist]
    return rng.beta(a, b, m)


def suite(seed, s_idx, j, dist, m, n_obs):
    rates = true_rates(dist, m, np.random.default_rng([seed, s_idx, j, 0]))
    observed = np.random.default_rng([seed, s_idx, j, 1]).binomial(n_obs, rates)
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


def truth_setting(rnd, s_idx):
    cfg = ROUNDS[rnd]
    dist, m, n_obs = settings(cfg)[s_idx]
    rows = {}
    for j in range(cfg["n_suites"]):
        rates, x = suite(cfg["seed"], s_idx, j, dist, m, n_obs)
        fails = int(n_obs * m - x.sum())
        fails_star = int(((n_obs - x) * (x > 0)).sum())  # failed trials in cases with at least one pass
        for c_idx, change in enumerate(changes(cfg, m)):
            for n_plan in n_plans(cfg, n_obs):
                rng = np.random.default_rng([cfg["seed"], s_idx, j, 2, c_idx, n_plan])
                p, fa, rc = detect(rates, change, n_plan, N_TRUE, rng)
                row = {"suite": j, "power": p, "false_alarm": fa, "realised_change": rc}
                if "f_min_candidates" in cfg:  # round 2: failed trials in the observed file (no method)
                    row["fails"] = fails
                    row["fails_star"] = fails_star
                rows.setdefault(cell_key(dist, m, n_obs, change, n_plan), []).append(row)
    print("truth done:", dist, m, n_obs, flush=True)
    return rows


def methods_setting(rnd, s_idx, truth):
    cfg = ROUNDS[rnd]
    dist, m, n_obs = settings(cfg)[s_idx]
    cells = {}
    for j in range(cfg["n_suites"]):
        rates, x = suite(cfg["seed"], s_idx, j, dist, m, n_obs)
        for c_idx, change in enumerate(changes(cfg, m)):
            for n_plan in n_plans(cfg, n_obs):
                key = cell_key(dist, m, n_obs, change, n_plan)
                est = {}
                for meth in cfg["methods"]:
                    rng = np.random.default_rng([cfg["seed"], s_idx, j, 3, c_idx, n_plan])  # same stream per method
                    if meth == "Oracle":
                        p, fa, _ = detect(rates, change, n_plan, N_EST, rng)
                    elif meth == "Plug-in":
                        p, fa, _ = detect(x / n_obs, change, n_plan, N_EST, rng)
                    else:
                        p, fa, _ = detect(rates, change, n_plan, N_EST, rng, draw=drawer(meth, x, n_obs))
                    est[meth] = {"power": p, "false_alarm": fa}
                cells.setdefault(key, []).append({"suite": j, "true": truth[key][j], "est": est})
    print("methods done:", dist, m, n_obs, flush=True)
    return cells


def _pool():
    return ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 2))


def phase_truth(rnd, out: Path) -> None:
    cfg = ROUNDS[rnd]
    idx = range(len(settings(cfg)))
    rows = {}
    with _pool() as pool:
        for part in pool.map(truth_setting, [rnd] * len(idx), idx):
            rows.update(part)
    (out / "truth.json").write_text(json.dumps({"round": rnd, "seed": cfg["seed"], "n_true": N_TRUE, "rows": rows},
                                               indent=0))
    if "f_min_candidates" not in cfg:
        means = {k: float(np.mean([r["power"] for r in v])) for k, v in rows.items()}
        decision = sorted(k for k, v in means.items() if POWER_BAND[0] <= v <= POWER_BAND[1])
        (out / "decision_cells.json").write_text(json.dumps({"band": POWER_BAND, "mean_true_power": means,
                                                             "decision_cells": decision}, indent=1))
        print(f"{len(decision)} decision cells (need >= {MIN_DECISION_CELLS})")
        return
    gates = {}
    for f_min in cfg["f_min_candidates"]:
        means, counts = {}, {}
        for k, v in rows.items():
            kept = [r["power"] for r in v if r["fails_star"] >= f_min]
            counts[k] = len(kept)
            if kept:
                means[k] = float(np.mean(kept))
        decision = sorted(k for k, v in means.items()
                          if counts[k] >= cfg["min_gated_suites"] and POWER_BAND[0] <= v <= POWER_BAND[1])
        cover = {}
        for m in cfg["ms"]:
            near = [k for k in decision if k.split("|")[0] in cfg["near_ceiling"] and k.split("|")[1] == f"m={m}"]
            cover[m] = {"near_ceiling_cells": len(near), "with_n_obs_3": sum("|n_obs=3|" in k for k in near)}
        by_dist_m = {}
        for k in decision:
            d, mm = k.split("|")[:2]
            by_dist_m[f"{d}|{mm}"] = by_dist_m.get(f"{d}|{mm}", 0) + 1
        each = {d: sum(n for dm, n in by_dist_m.items() if dm.split("|")[0] == d and dm.split("|")[1] != "m=20")
                for d in cfg["each_needed"]}
        # cells where the p90 criterion applies (>= 50 gated suites), per needed distribution
        each_p90 = {d: sum(1 for k in decision if k.split("|")[0] == d and counts[k] >= 50) for d in cfg["each_needed"]}
        eligible = (len(decision) >= MIN_DECISION_CELLS
                    and all(c["near_ceiling_cells"] >= 2 and c["with_n_obs_3"] >= 1 for c in cover.values())
                    and all(n >= 2 for n in each.values())
                    and all(n >= 1 for n in each_p90.values()))
        gates[str(f_min)] = {"decision_cells": decision, "gated_suites": counts, "mean_true_power_gated": means,
                             "coverage_by_m": cover, "cells_by_dist_m": by_dist_m, "each_needed_m50_120": each,
                             "each_needed_p90_cells": each_p90,
                             "eligible": eligible}
        print(f"F_min {f_min}: {len(decision)} decision cells; coverage {cover}; each needed {each}; "
              f"p90-constrained {each_p90}; "
              f"eligible {eligible}")
    (out / "decision_cells.json").write_text(json.dumps({"band": POWER_BAND, "gates": gates}, indent=1))


def phase_methods(rnd, out: Path, protocol: Path) -> None:
    cfg = ROUNDS[rnd]
    if "consistency_seed" in cfg and not (out / "consistency.txt").exists():
        raise SystemExit("run the consistency phase first")
    truth = json.loads((out / "truth.json").read_text())["rows"]
    dec = json.loads((out / "decision_cells.json").read_text())
    decision = dec["decision_cells"] if "decision_cells" in dec else {f: g["decision_cells"] for f, g in dec["gates"].items()}
    record = {"round": rnd, "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
              "seed": cfg["seed"], "n_est": N_EST, "methods": cfg["methods"], "decision_cells": decision, "cells": {}}
    idx = list(range(len(settings(cfg))))
    with _pool() as pool:
        futures = [pool.submit(methods_setting, rnd, s,
                               {k: v for k, v in truth.items() if k.startswith(_prefix(cfg, s))}) for s in idx]
        for f in futures:
            record["cells"].update(f.result())
    (out / "methods.json").write_text(json.dumps(record, indent=0))


def phase_consistency(rnd, out: Path) -> None:
    """Internal _delta_interval on counts vs public delta_interval on outcome dicts: identical intervals."""
    from realdelta import delta_interval
    cfg = ROUNDS[rnd]
    rng = np.random.default_rng(cfg["consistency_seed"])
    lines, bad = [], 0
    for dist in cfg["dists"]:
        checked = 0
        for _ in range(200):
            m = int(rng.choice(cfg["ms"]))
            n = int(rng.choice(cfg["n_obs"]))
            rates = true_rates(dist, m, rng)
            a = rng.binomial(n, rates)
            b = rng.binomial(n, np.clip(rates - 0.05, 0, 1))
            t = np.full(m, float(n))
            internal = _delta_interval(a.astype(float), t, b.astype(float), t, "suite", 0.95)
            outcomes = lambda x: {f"c{i}": [True] * int(v) + [False] * (n - int(v)) for i, v in enumerate(x)}
            public = delta_interval(outcomes(a), outcomes(b), scope="suite", conf=0.95)
            if (internal.estimate, internal.low, internal.high) != (public.estimate, public.low, public.high):
                bad += 1
            checked += 1
        lines.append(f"{dist}: {checked} files checked")
    lines.append(f"mismatches: {bad}")
    (out / "consistency.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if bad:
        raise SystemExit("consistency check failed: the run is void")


def _prefix(cfg, s_idx):
    dist, m, n_obs = settings(cfg)[s_idx]
    return f"{dist}|m={m}|n_obs={n_obs}|"


def main(argv):
    rnd, phase, out = int(argv[1]), argv[2], Path(argv[3])
    out.mkdir(parents=True, exist_ok=True)
    target = out / {"truth": "truth.json", "methods": "methods.json", "consistency": "consistency.txt"}[phase]
    if target.exists():
        raise SystemExit(f"refusing to overwrite {target}")
    if phase == "consistency":
        phase_consistency(rnd, out)
    elif phase == "truth":
        phase_truth(rnd, out)
    else:
        phase_methods(rnd, out, Path(argv[4]))


if __name__ == "__main__":
    main(sys.argv)
