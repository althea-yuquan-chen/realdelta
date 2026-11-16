# Calibration protocol (pre-registered)

This file, `scripts/calibration_grid.py` and `tests/test_bounds_analytic.py` are committed
before the population-scope floors are implemented. Commit order is the pre-registration
record: every decision below was made before any result of the final grid existed.

## Methods under test (v0.1)

- **Suite scope** (pass rate and delta): unchanged from the first statistics commit. Wilson on
  the macro rate with an Agresti-Coull effective sample size; MOVER for the delta.
- **Population pass rate**: hull of {suite interval, t interval over per-case rates,
  case-level floor}. The floor applies the Clopper-Pearson beta-quantile formula to the
  real-valued total `x = sum(p_hat_i)` and `m` cases.
- **Population delta**: with `d_i = p_hat_b_i - p_hat_a_i`, `d+ = max(d, 0)`, `d- = max(-d, 0)`,
  a case-level floor at level `1 - alpha/2` on the mean of each, Bonferroni-combined to
  `[L+ - U-, U+ - L-]`, then hulled with the MOVER-suite and paired t intervals.

The floor is exact (coverage >= 1 - alpha) when every case is deterministic, because the
per-case rates are then Bernoulli. For other `[0, 1]`-valued case rates its validity is not
proven. The analytic tests and the grid check it; the claim is worded accordingly.

## Assumptions

- A1: trials within a case are independent and identically distributed.
- A2: cases are an i.i.d. draw from the population.
- A3: the two arms share no randomness (seeds, caches, outage windows).
- A4: the number of trials per case does not depend on outcomes (no re-runs after a failure).

Suite scope needs A1, A3, A4. Population pass rate needs A2, A4. Population delta needs A2, A4.

## Analytic tests (`tests/test_bounds_analytic.py`)

Marked `xfail(strict=True)` until the floors exist; the marks are removed in the
implementation commit, nothing else changes.

1. Exact coverage of the floor for Bernoulli case rates, m in {5, 7, 10, 20, 30, 50, 100},
   2000-point mu grid on [0.01, 0.99] plus 500 points on [0.99, 0.9999]: min coverage >= 0.95 - 1e-12.
2. Exact coverage of the floor for three-point case rates {0, c, 1} (multinomial enumeration),
   m in {5, 10, 20}, c in {0.25, 0.5, 0.75}, weight of 0 in {0.01, 0.05, 0.1, 0.2}, weight of c in
   {0.05, 0.1, 0.3}: min coverage >= 0.95 - 1e-12.
3. All-pass data: population lower bound L with L^m <= 0.025 + 1e-12, same m as test 1.
4. All-zero differences on the most favourable data (every case passes all 10 trials in both
   arms): population delta contains [-(1 - 0.025^(1/m)), +(1 - 0.025^(1/m))] (to 1e-12), same m.

## Frozen grid (`scripts/calibration_grid.py`)

Seed for setting i: `20261116 + i` (settings in file order). 2000 repetitions per setting.
Each setting evaluates the scopes listed for it on the same simulated data. Truths are
computed exactly as written in the script; the truth helpers have unit tests in
`tests/test_grid_truths.py`.

Settings are listed in the script; in summary:

- G2 Beta(a, b), (a, b) in {(0.5,0.5), (2,2), (4,2), (20,1), (50,1)}, m in {5, 20, 50}, n in {1, 5}; suite + population.
- G3 mixtures: {1:.8, .7:.1, 0:.1} m=30 n=5 [dev overlap: H2]; {1:.9, .5:.1} m=20 n=10;
  suite + population. {1:.95, 0:.05} m in {5, 20} n=3; population only.
- G4 homogeneous p in {0.5, 0.9}, m=30, n=5; suite + population.
- G5 unequal trials n_i uniform on {1, 3, 10}, Beta(4,2) and Beta(20,1), m=30; suite + population.
- D1 break: baseline p=1 w.p. 0.95 else 0; candidate turns a share g of ALL cases from 1 to 0,
  g in {0.05, 0.10}, m in {10, 20, 50}, n in {3, 10}; population only (suite is trivially exact).
  [dev overlap: H6 is g=0.05, m=20, n=10]
- D2 fix: baseline p=1 w.p. 0.85 else 0; candidate turns a share g of ALL cases from 0 to 1,
  same g, m, n; population only.
- D3 null: candidate rates equal baseline rates; baselines Beta(4,2), Beta(20,1), {1:.95, 0:.05};
  m in {10, 30}, n in {3, 10}; suite + population (suite only for non-deterministic baselines).
- D4 flaky shift: p_b = clip(p_a + delta, 0, 1), delta in {+0.05, +0.10}, Beta(4,2) and Beta(20,1),
  m in {20, 50}, n in {5, 10}; suite + population. Population truth: mean of
  clip(q + delta) - q over 2,000,000 draws of q with seed 20261116.
- D5 two-way churn: baseline p=1 w.p. 0.8 else 0; candidate flips each failing case to 1 w.p. 0.5
  and each passing case to 0 w.p. 0.125 (population truth 0); m in {20, 50}, n=5; population only.
- D6 unequal trials delta: Beta(4,2), delta +0.10, n_i uniform on {1, 3, 10}, m=30; suite + population.
- V1 sticky trials (violates A1): trial t > 0 copies trial t-1 w.p. r, otherwise a fresh draw,
  so each trial's marginal pass probability stays p_i. r in {0.5, 0.8}, Beta(4,2), m=30, n=5.
  Population rows gated; suite rows reported only.
- V2 batch effect (violates A3): null delta, Beta(4,2), m=30, n=5; for every trial index t each
  arm draws one shock s ~ N(0, 0.3^2) shared by all its cases, trial pass probability
  expit(logit(p_i) + s). Truth 0. Reported only.

## Gate

- Hard gate: two-sided coverage >= 0.93 on every gated row. Lower bound only.
- A failing suite-scope row blocks the v0.1 release until fixed under a new grid.
- A failing population row: that function switches to the Hoeffding-Bentkus floor (total
  rounded conservatively, one-sided level alpha / (2e)) and is re-run under a new grid. If it
  still fails, the function raises `NotImplementedError` in v0.1.
- Width rule: the population delta ships in v0.1 only if EACH D4 population row with m=50, n=10
  has mean width <= 0.30. Otherwise `delta_interval(scope="population")` and
  `compare(scope="population")` raise `NotImplementedError` in v0.1.
- Reported, not gated: lower and upper miss rates, mean width, power where truth != 0.
- Wording of claims: "coverage >= 0.93 across the tested grid", never "95% calibrated".

## Runs

- Smoke runs (`--smoke`: 50 repetitions, seed base 1) are allowed at any time to check that
  the script runs and the truths are right. Their output is not evidence and is not committed.
- The final grid runs once, after the implementation commit. Its output
  (`results/calibration_grid_<seed base>.json` and `.md`) is committed whether rows pass or fail.
- A fix to the grid script after the final run is allowed only for a bug demonstrable without
  the interval methods (for example a failing truth test). The fix uses a new seed base, earlier
  results stay in the repo, and the README lists every final run.

## CI regression tests (`tests/test_calibration.py`, 1000 repetitions, fixed seeds)

- The 8 original pass-rate settings: lower bound 0.93 for both scopes; upper bound 0.995 for
  the suite scope only.
- The 6 original delta settings: lower bound 0.93 for both scopes; upper bound 0.995 for the
  suite scope only. (Relaxation: the population upper bound is dropped because the floor makes
  that scope conservative by design; its width is reported instead.)
- False-alarm test (<= 0.07) unchanged.
- New, lower bound only: H1 (population pass rate, bimodal 0.95/0.05, m=20, n=10), H2
  (population pass rate, {1:.8, .7:.1, 0:.1}, m=30, n=5), H6 (population delta, break 5%, m=20, n=10).
  Marked `xfail(strict=True)` until the implementation commit.
- Fault injection under the same gate: pooled Wilson coverage < 0.93.
