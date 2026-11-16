"""Pre-registered selection of the suite pass-rate bounds (docs/calibration_protocol.md, Amendment 1).

Exact coverage of candidate suite intervals on three analytic sweeps (no simulation):

* S1 homogeneous, one trial per case: x ~ Bin(m, p).
* S2 homogeneous, five trials per case: per-case pass counts i.i.d. Bin(5, p), enumerated as multisets.
* S3 two-point heterogeneous, one trial per case: k cases at rate 1, m - k at rate q.

Minimum coverage includes the one-sided limits at every interval endpoint, so it does not
depend on where grid points fall.

Usage:
    python scripts/suite_bounds_selection.py               # Amendment 1: results/suite_bounds_selection.*
    python scripts/suite_bounds_selection.py --amendment 2 # Amendment 2: results/suite_bounds_selection_a2.*

``sweep`` is also used by tests/test_suite_analytic.py on the public pass_rate_interval.
Amendment 2 adds candidate C1 and a reported-only configuration S4 (unequal trials).
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Callable

import numpy as np
from scipy import stats as st

THRESHOLD = 0.947          # 0.93 + 3 * sqrt(0.93 * 0.07 / 2000), see Amendment 1
CONF = 0.95

# (passes, trials) -> (low, high)
Bounds = Callable[[np.ndarray, np.ndarray], tuple[float, float]]


# ---------------------------------------------------------------- sweeps
#
# Coverage is a step-weighted smooth function of the parameter, so its infimum is reached at one-sided
# limits at interval endpoints. min_coverage is therefore taken over the fixed grid PLUS every
# endpoint +- EPS that falls inside the parameter range; mean_width uses the fixed grid only.

EPS = 1e-9
P_MIN, P_MAX = 0.5, 0.9999


def _grid_s1() -> np.ndarray:
    return np.concatenate([np.linspace(0.5, 0.99, 2000), np.linspace(0.99, 0.9999, 500)])


def _grid_small() -> np.ndarray:
    return np.linspace(P_MIN, P_MAX, 200)


def _evaluate(lo, hi, weights, truth, grid, endpoint_params):
    """Coverage over grid and endpoint parameters; width over the grid.

    weights(theta) -> probability of each outcome; truth(theta) -> estimand.
    """
    extra = endpoint_params[(endpoint_params >= P_MIN) & (endpoint_params <= P_MAX)]
    cov = []
    for theta in np.concatenate([grid, extra]):
        w, t = weights(theta), truth(theta)
        cov.append(float(np.sum(w * ((lo <= t) & (t <= hi)))))
    wid = [float(np.sum(weights(theta) * (hi - lo))) for theta in grid]
    return np.array(cov), np.array(wid)


def _n1_intervals(bounds: Bounds, m: int):
    ivs = [bounds(np.array([1.0] * x + [0.0] * (m - x)), np.ones(m)) for x in range(m + 1)]
    return np.array([iv[0] for iv in ivs]), np.array([iv[1] for iv in ivs])


def _config_s1(bounds: Bounds, m: int):
    lo, hi = _n1_intervals(bounds, m)
    xs = np.arange(m + 1)
    ends = np.concatenate([hi + EPS, lo - EPS])
    return _evaluate(lo, hi, lambda p: st.binom.pmf(xs, m, p), lambda p: p, _grid_s1(), ends)


def _config_s2(bounds: Bounds, m: int, n: int = 5):
    multisets = list(itertools.combinations_with_replacement(range(n + 1), m))
    lo, hi, log_mult, counts = [], [], [], []
    for ms in multisets:
        l, h = bounds(np.array(ms, dtype=float), np.full(m, float(n)))
        lo.append(l)
        hi.append(h)
        reps = np.bincount(np.array(ms), minlength=n + 1)
        log_mult.append(math.lgamma(m + 1) - sum(math.lgamma(r + 1) for r in reps))
        counts.append(np.array(ms))
    lo, hi, log_mult, counts = np.array(lo), np.array(hi), np.array(log_mult), np.array(counts)

    def weights(p):
        return np.exp(log_mult + st.binom.logpmf(np.arange(n + 1), n, p)[counts].sum(axis=1))

    ends = np.concatenate([hi + EPS, lo - EPS])
    return _evaluate(lo, hi, weights, lambda p: p, _grid_small(), ends)


def _config_s3(bounds: Bounds, m: int, k: int):
    """k cases at rate 1, m - k at rate q; parameter q, estimand (k + (m - k) q) / m."""
    lo_all, hi_all = _n1_intervals(bounds, m)
    ys = np.arange(m - k + 1)
    lo, hi = lo_all[k + ys], hi_all[k + ys]
    to_q = lambda t: (t * m - k) / (m - k)
    ends = np.concatenate([to_q(hi + EPS), to_q(lo - EPS)])
    return _evaluate(lo, hi, lambda q: st.binom.pmf(ys, m - k, q), lambda q: (k + (m - k) * q) / m,
                     _grid_small(), ends)


def _config_s4(bounds: Bounds, n_i: tuple[int, ...] = (1, 1, 3, 3, 10)):
    """Amendment 2, reported only: unequal trials per case, homogeneous p, exact enumeration."""
    trials = np.array(n_i, dtype=float)
    outcomes = list(itertools.product(*[range(n + 1) for n in n_i]))
    ivs = [bounds(np.array(o, dtype=float), trials) for o in outcomes]
    lo, hi = np.array([iv[0] for iv in ivs]), np.array([iv[1] for iv in ivs])
    counts = np.array(outcomes)

    def weights(p):
        return np.prod([st.binom.pmf(counts[:, j], n, p) for j, n in enumerate(n_i)], axis=0)

    ends = np.concatenate([hi + EPS, lo - EPS])
    return _evaluate(lo, hi, weights, lambda p: p, _grid_small(), ends)


S3_K = [(5, 2), (5, 4), (20, 10), (20, 16)]   # (m, k): shares 0.4/0.8 at m=5, 0.5/0.8 at m=20

CONFIGS = (
    [(f"S1 m={m}", lambda b, m=m: _config_s1(b, m)) for m in (5, 10, 20, 50, 100)]
    + [(f"S2 m={m} n=5", lambda b, m=m: _config_s2(b, m)) for m in (5, 10)]
    + [(f"S3 m={m} k={k}", lambda b, m=m, k=k: _config_s3(b, m, k)) for m, k in S3_K]
)


def sweep(bounds: Bounds) -> dict:
    """Min coverage and mean width per configuration, plus the overall summary."""
    rows = []
    for name, fn in CONFIGS:
        cov, wid = fn(bounds)
        rows.append({"config": name, "min_coverage": float(cov.min()), "mean_width": float(wid.mean())})
    return {
        "rows": rows,
        "min_coverage": min(r["min_coverage"] for r in rows),
        "mean_width": float(np.mean([r["mean_width"] for r in rows])),
    }


# ---------------------------------------------------------------- candidates

def _z(conf: float = CONF) -> float:
    return NormalDist().inv_cdf(0.5 + conf / 2.0)


def _estimate_and_n_eff(passes: np.ndarray, trials: np.ndarray, z: float) -> tuple[float, float]:
    """Same estimate and effective sample size as realdelta.stats._suite_interval."""
    m = len(passes)
    estimate = float(np.mean(passes / trials))
    p_tilde = (passes + z * z / 2.0) / (trials + z * z)
    var = float(np.sum(p_tilde * (1.0 - p_tilde) / trials) / (m * m))
    p_bar = float(np.mean(p_tilde))
    return estimate, p_bar * (1.0 - p_bar) / var


def wilson(passes, trials):
    """Reference: the current suite bounds (expected to fail the sweep)."""
    z = _z()
    p, n = _estimate_and_n_eff(passes, trials, z)
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    half = z * math.sqrt(max(p * (1.0 - p), 0.0) / n + z * z / (4.0 * n * n))
    return max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom)


def cp_bounds(x: float, n: float, conf: float = CONF) -> tuple[float, float]:
    """Clopper-Pearson beta quantiles, applied to a real-valued count x out of n."""
    x = min(max(x, 0.0), n)
    a = 1.0 - conf
    low = 0.0 if x <= 1e-12 else float(st.beta.ppf(a / 2.0, x, n - x + 1.0))
    high = 1.0 if x >= n - 1e-12 else float(st.beta.ppf(1.0 - a / 2.0, x + 1.0, n - x))
    return low, high


def wilson_cc_bounds(p: float, n: float, z: float) -> tuple[float, float]:
    """Wilson score interval with continuity correction (Newcombe 1998, method 4)."""
    q = 1.0 - p
    denom = 2.0 * (n + z * z)
    if p <= 0.0:
        low = 0.0
    else:
        low = (2 * n * p + z * z - 1 - z * math.sqrt(max(z * z - 2 - 1 / n + 4 * p * (n * q + 1), 0.0))) / denom
    if p >= 1.0:
        high = 1.0
    else:
        high = (2 * n * p + z * z + 1 + z * math.sqrt(max(z * z + 2 - 1 / n + 4 * p * (n * q - 1), 0.0))) / denom
    return max(0.0, low), min(1.0, high)


def clopper_pearson(passes, trials):
    """B1: Clopper-Pearson beta quantiles on the real-valued (x_eff, n_eff)."""
    p, n = _estimate_and_n_eff(passes, trials, _z())
    return cp_bounds(p * n, n)


def wilson_cc(passes, trials):
    """B2: Wilson with continuity correction on (estimate, n_eff)."""
    z = _z()
    p, n = _estimate_and_n_eff(passes, trials, z)
    return wilson_cc_bounds(p, n, z)


def clopper_pearson_capped(passes, trials):
    """C1 (Amendment 2): Clopper-Pearson with the sample size capped at the trials actually run.

    N = min(n_eff, sum of trials), x = estimate * N. With one trial per case N = m and x is the
    integer pass count, so the interval is the ordinary Clopper-Pearson interval.
    """
    p, n_eff = _estimate_and_n_eff(passes, trials, _z())
    n = min(n_eff, float(np.sum(trials)))
    return cp_bounds(p * n, n)


CANDIDATES_BY_AMENDMENT = {
    1: {"B1 clopper_pearson": clopper_pearson, "B2 wilson_cc": wilson_cc},
    2: {"C1 clopper_pearson_capped": clopper_pearson_capped},
}
CANDIDATES = CANDIDATES_BY_AMENDMENT[1]
REFERENCE = {"reference wilson (current)": wilson}


def select(results: dict, candidates: dict = CANDIDATES) -> dict:
    survivors = [name for name in candidates if results[name]["min_coverage"] >= THRESHOLD]
    survivors.sort(key=lambda name: results[name]["mean_width"])
    return {"threshold": THRESHOLD, "survivors_narrowest_first": survivors,
            "first_choice": survivors[0] if survivors else None}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--amendment", type=int, choices=(1, 2), default=1)
    args = ap.parse_args(argv)
    candidates = CANDIDATES_BY_AMENDMENT[args.amendment]
    out = Path("results")
    stem = out / ("suite_bounds_selection" if args.amendment == 1 else "suite_bounds_selection_a2")
    if stem.with_suffix(".json").exists() or stem.with_suffix(".md").exists():
        print(f"refusing to overwrite {stem}.*", file=sys.stderr)
        return 1
    results = {name: sweep(fn) for name, fn in {**candidates, **REFERENCE}.items()}
    decision = select(results, candidates)
    if args.amendment == 2:
        reported = {}
        for name, fn in {**candidates, **REFERENCE}.items():
            cov, wid = _config_s4(fn)
            reported[name] = {"config": "S4 m=5 n_i=(1,1,3,3,10)", "min_coverage": float(cov.min()),
                              "mean_width": float(wid.mean())}
        decision["reported_not_gated"] = reported
    out.mkdir(exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps({"decision": decision, "results": results}, indent=1),
                                         encoding="utf-8")
    title = "# Suite pass-rate bounds: pre-registered selection"
    if args.amendment != 1:
        title += f" (Amendment {args.amendment})"
    lines = [title, "",
             f"Criterion: min exact coverage >= {THRESHOLD} on every configuration. "
             f"Survivors, narrowest first: {decision['survivors_narrowest_first']}. "
             f"First choice: {decision['first_choice']}.", "",
             "| method | config | min coverage | mean width |", "|---|---|---|---|"]
    for name, res in results.items():
        for r in res["rows"]:
            lines.append(f"| {name} | {r['config']} | {r['min_coverage']:.4f} | {r['mean_width']:.4f} |")
        lines.append(f"| {name} | **all** | **{res['min_coverage']:.4f}** | **{res['mean_width']:.4f}** |")
    if "reported_not_gated" in decision:
        lines += ["", "Reported, not gated (Amendment 2): unequal trials, homogeneous p.", "",
                  "| method | config | min coverage | mean width |", "|---|---|---|---|"]
        for name, r in decision["reported_not_gated"].items():
            lines.append(f"| {name} | {r['config']} | {r['min_coverage']:.4f} | {r['mean_width']:.4f} |")
    stem.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
