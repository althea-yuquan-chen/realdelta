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

## Amendment 1 (2026-11-16, after the final grid at seed base 20261116)

Appended after `results/calibration_grid_20261116.{json,md}` were committed (da182ba). The text
above is unchanged. Everything in this amendment is committed before any candidate below is run.

### Outcome of the 20261116 grid under the rules above

- One gated row fails: G2 Beta(50,1) m=5 n=1, suite scope, coverage 0.917, every miss with the truth
  above the upper bound. The suite pass rate blocks v0.1 until fixed under a new grid.
- Width rule: D4 Beta(4,2) m=50 n=10 population delta rows have mean width 0.368 and 0.364 (> 0.30).
  `delta_interval(scope="population")` and `compare(scope="population")` raise `NotImplementedError`
  in v0.1, and so does `plan_trials(scope="population")`, which calls `delta_interval`. The width
  rule is final at seed base 20261116; later grids do not re-evaluate it. The implementation stays
  as private code; tests that exercised it through the public API call the private function with
  unchanged assertions.

### Diagnosis

With few total trials and a truth near 1, a single failure moves the Wilson upper bound below the
truth (4 of 5 passing: Wilson upper 0.964, Clopper-Pearson upper 0.995, truth about 0.980 under
Beta(50,1)). This is Wilson's known under-coverage near the boundary, not an implementation bug.

### Method change (suite pass rate only)

- The suite pass rate (`pass_rate_interval(scope="suite")`) gets new bounds chosen by the rule below,
  keeping the current estimate and effective sample size `n_eff`. The population pass rate's hull
  uses the new suite interval in place of the Wilson one.
- The suite delta (MOVER) keeps Wilson-based arm intervals, Newcombe's original method. It has no
  grid row at m=5, n=1 near 100% and inherits Wilson's boundary behaviour; the README states this
  as an untested limitation.
- Candidates, both on the real-valued `(x_eff, n_eff)` with `x_eff = estimate * n_eff`:
  B1 Clopper-Pearson beta quantiles; B2 Wilson with continuity correction (Newcombe 1998, method 4).
  Neither is claimed exact: `n_eff` is not the trial count and `x_eff` is not an integer in general.

### Selection rule

Exact analytic sweeps (`scripts/suite_bounds_selection.py`, no simulation): S1 homogeneous,
one trial per case, m in {5, 10, 20, 50, 100}; S2 homogeneous, five trials per case, m in {5, 10};
S3 one trial per case, k cases at rate 1 and m - k at rate q, (m, k) in {(5, 2), (5, 4), (20, 10),
(20, 16)}. Parameter range [0.5, 0.9999]. Minimum coverage is taken over a fixed grid plus the
one-sided limits (+-1e-9) at every interval endpoint in range, so it does not depend on grid
placement. Mean width: exact expected width per grid point, equal weight over grid points, then
over configurations.

1. Criterion: minimum coverage >= 0.947 on every configuration. 0.947 = 0.93 + 3 * sqrt(0.93 *
   0.07 / 2000): a method at or above it fails a 2000-rep grid row by Monte Carlo noise with
   probability about 0.1% (for the configurations the sweep covers; heterogeneous grid rows are
   not covered by it). Candidates below it are eliminated.
2. Survivors are ordered by mean width, narrowest first.
3. The first survivor is implemented and the full test suite runs, with `tests/test_calibration.py`
   unchanged (suite coverage in [0.93, 0.995]). A candidate that fails only the 0.995 upper bound
   moves to the step-4 pool; a candidate that fails the 0.93 lower bound or any other test is
   eliminated. Then the next survivor is tried.
4. If no survivor passes step 3 and the step-4 pool is non-empty: the 0.995 upper bound for the
   suite pass rate is dropped (the relaxation already applied to the population scope) and the
   narrowest candidate in the pool is used. This is a gate change: it is reviewed, written into
   Amendment 2 and reported to the owner before the new grid runs. If the pool is empty, or no
   candidate survives step 1, stop: v0.1 is blocked and the decision returns to the owner.
5. One new grid, seed base 20261117. If any gated suite row fails, no further suite method is tried
   before 2027-01-11; v0.1 is blocked and the owner decides. A failing population pass-rate row
   follows the original Hoeffding-Bentkus fallback above.

### Tests and grid changes

- `tests/test_suite_analytic.py`: the S1-S3 sweep on the public suite pass rate, one test,
  `xfail(strict=True)` until the implementation commit; a check that the current Wilson bounds fail
  the sweep; a check that the script's copy of `n_eff` matches the library.
- `scripts/calibration_grid.py` (a declared deviation from the Runs clause, which allows script fixes
  only for bugs): seed base 20261117; population-scope delta rows are not run; width-rule reporting
  removed; refuses to overwrite existing results. Settings, repetitions, truths and the gate are
  otherwise unchanged. The 20261116 run stays reproducible from commit da182ba.

## Amendment 2 (2026-11-16, after the Amendment 1 selection)

Appended after `results/suite_bounds_selection.{json,md}` were committed (3be2276). Amendment 1
stopped at step 1: B1 reached a minimum coverage of 0.9449 (S1 m=100), B2 0.9434 (S3 m=5 k=4), both
below 0.947. The owner chose to add one more candidate under the same rule. Everything in this
amendment is committed before the candidate is run.

### Disclosure

C1 was designed after seeing the Amendment 1 sweep: B1 fell short in S1 at m=50 and m=100, where
`n_eff` exceeds the number of trials. The analytic sweep is therefore not an independent test of C1.
The independent evidence for C1 is the unchanged CI tests and the grid at seed base 20261117,
which has not been run. The README lists both amendments and the failed candidates.

### Candidate C1

Clopper-Pearson beta quantiles on `(x, N)` with `N = min(n_eff, sum_i n_i)` and `x = estimate * N`:
the effective sample size is capped at the number of trials actually run. With one trial per case,
`N = m` and `x` is the integer pass count, so C1 is the ordinary Clopper-Pearson interval and its
coverage in S1 is at least 0.95. With equal trials per case, `n_eff >= m * n` (Jensen's inequality on
the per-case adjusted variances), so the cap always binds: C1 is the pooled Clopper-Pearson interval
on the total pass count out of `m * n` trials, and `n_eff` plays no role. For the suite estimand
(the mean of this sample's case rates) the total is Poisson-binomial with variance at most the
binomial's, so ignoring case clustering is conservative, not an error; coverage under heterogeneous
rates is still checked, not proven. Only with unequal trials does `n_eff` stay in use (`x` is then
non-integer). For equal trials this departs from Amendment 1's "keeping the current ... `n_eff`"
and is declared here. A test checks the equal-trials equivalence.

### Rule

Amendment 1's selection rule applies unchanged with C1 as the only candidate: step 1 (minimum exact
coverage >= 0.947 on S1-S3, endpoint limits included), then step 3 (full test suite,
`tests/test_calibration.py` unchanged), with the step-3/step-4 split of failure types, step 4's gate
change requiring review, Amendment 3 and the owner's sign-off, and step 5's single grid at seed base
20261117. If C1 fails step 1, or fails step 3 on anything other than the 0.995 upper bound, stop:
v0.1 is blocked and no further suite candidate is added before 2027-01-11. Under step 4, an
owner who does not sign off leaves v0.1 blocked.

Expected outcome, stated before the run: step 1 should pass, since S1 and S2 reduce to exact
Clopper-Pearson on integer counts and S3 was already at 0.972 for the narrower B1. The selection
output reports C1's mean width next to the reference Wilson (reported, not gated). The cost: with
equal trials the interval has pooled-binomial width, wider than needed for suites of mostly
deterministic cases; the README says so.

S4, reported only: unequal trials, m=5, `n_i = (1, 1, 3, 3, 10)`, homogeneous p, exact enumeration
with endpoint limits. Added by Amendment 2 because unequal trials are the one regime with neither a
proof nor a sweep configuration. It does not gate; if its minimum coverage is below 0.947 the README
lists it as a known weakness. If it is below 0.93, the README states the value and the configuration
in the same paragraph as the main coverage claim.

Test changes allowed in the implementation commit, and no others: remove the `PENDING` marks in
`tests/test_suite_analytic.py`; point `test_selection_script_reproduces_the_library_wilson_suite_bounds`
at the library function that keeps the Wilson suite bounds for MOVER (assertions unchanged); switch
population-delta call sites to the private function as stated in Amendment 1; add two new tests,
defined here: (1) `delta_interval`, `compare` and `plan_trials` called with `scope="population"`
raise `NotImplementedError`; (2) on data where every case passes all 10 trials in both arms, the
private population delta has half-width exactly `1 - 0.0125 ** (1 / m)` (to 1e-12) for m in
{5, 7, 10, 20, 30, 50, 100}, which pins the Bonferroni split of the delta floor.

### Run

`python scripts/suite_bounds_selection.py --amendment 2` writes
`results/suite_bounds_selection_a2.{json,md}` and refuses to overwrite. Amendment 1 mode is
unchanged; reproducing 3be2276's files needs them moved aside first because of the overwrite check.

## Outcome record (appended after grid 20261117; no rule changes)

- Amendment 2 selection (`results/suite_bounds_selection_a2.md`, 7f2cd3e): C1 minimum exact
  coverage 0.9503; S4 (reported only) 0.9583. Step 1 had little screening power for C1, since S1
  and S2 reduce to exact Clopper-Pearson on integer counts; the independent evidence is the grid
  below and the unchanged CI gates.
- Step 3: full test suite passed on C1 (implementation 9743ad8); CI suite pass-rate coverage on
  the 8 settings 0.970-0.978. Step 4 was not triggered.
- Grid 20261117 (`results/calibration_grid_20261117.md`, ab80eec, run once at 9743ad8): 0 gated
  rows fail. Lowest gated rows: suite pass rate 0.956, population pass rate 0.951, suite delta
  0.945. The row that failed in 20261116 (G2 Beta(50,1) m=5 n=1, suite) is 0.998. Suite pass-rate
  mean width versus 20261116: median ratio 1.11 (1.05-1.24; different seeds, so noisy).
- Seven suite pass-rate rows exceed 0.995 (maximum 0.999). The grid has no upper gate; the
  interval is conservative for suites of near-deterministic cases, and the README says so.
- Added after the grid, outside Amendment 2's test-change list: a regression test pinning the
  library's suite interval to C1 (7e8c59e). It is new, not a relaxation, and not a gate.
- Final runs to list in the README: 20261116 (failed one suite row and the width rule) and
  20261117 (passed).

## Diagnostic DB (declared 2026-11-16, before it is run; reported only)

The suite delta (MOVER over Wilson-based arm intervals) has no gated grid row with both arms near
100% and few trials, and the Wilson arm intervals reach 0.815-0.838 minimum exact coverage in the
Amendment 1/2 sweeps. `scripts/delta_boundary_diagnostic.py` measures the suite delta there, with
truth mean(p_b - p_a), 2000 reps per row, generator `default_rng([20261118, row index])`:
- Random rows (20): baseline rates Beta(a, 1), a in {50, 20}; m in {5, 20}; n in {1, 3}; candidate
  equal to the baseline (null) or lowered by 0.05 per case, clipped at 0; for a = 20 also raised by
  0.05, clipped at 1.
- Adversarial rows (3): every baseline case at rate 1; every candidate case at the fixed rate
  1 - z^2 / (N + z^2) - 0.01 with N = m * n, for (m, n) in {(5, 1), (20, 1), (5, 3)}. This sits just
  below the Wilson lower bound for an all-pass arm of N trials, where MOVER over Wilson arms is
  expected to under-cover (hand calculation, not verified). These are constructed worst cases.
It runs once; output (with commit and the location of the imported realdelta) is committed as
produced. A `--smoke` mode (50 reps, seed base 1, temp directory) checks that it runs; its output
is not evidence.

It gates nothing and changes no method. The Gate section's "a failing suite row blocks the
release" does not apply: these rows are reported only. The Runs section's bug rule applies: a fix
to the script uses a new seed base and earlier output stays. Disposition, fixed now:
- Every row >= 0.93: the README reports the lowest random-row and lowest adversarial-row coverage,
  limited to these settings (null, -0.05, +0.05 at Beta(20,1), and the three constructed cases;
  m >= 5). It does not say the delta is safe near 100% in general. The `delta_interval` docstring
  keeps its warning, reworded to cite this diagnostic.
- Any row < 0.93: the README states the lowest coverage and its configuration in the same paragraph
  as the main coverage claim, and the `delta_interval` docstring names the regime. The owner then
  chooses one of two options: (a) fix the suite delta in v0.1 under a new amendment, whose new grid
  includes these 23 settings as gated rows with a new seed base; or (b) release with the disclosure
  and the docstring warning. Re-running with another seed or dropping rows is not an option. This
  diagnostic is not reused to choose a fix.

## Note on cited commit hashes (2026-11-16; no rule or result changes)

The commit messages in this repository were edited after the fact, and one commit that only
recorded that edit was dropped. A commit's hash covers its message, so the commit hashes cited in
this protocol, in `README.md`, in two docstrings, in later commit messages, in the provenance files
under `results/` and `examples/real_model/run_20261116/`, and in the diagnostic's two output files
under `results/` were then updated mechanically to the edited commits. Apart from those hash
strings, no file content changed, and every commit kept its author and commit dates and its order.
Each cited commit therefore has the same timestamps, and the same files apart from cited hash
strings, as the commit the citation originally named.

## Diagnostic AD: dependence between and within arms (declared 2026-11-16, before the full run; reported only)

Why: README Limitations and the command-line assumption note say that if the two arms share seeds, caches
or an outage window, intervals are too narrow, and cite the grid's V2 row (suite delta coverage 0.894).
V2 is a shock drawn separately for each arm and shared by that arm's cases. That is dependence across cases
within one arm, not randomness shared between the arms. MOVER over the arms' intervals assumes the arms'
trial noise is independent (stats.py, `_delta_interval`), and the direction of a violation has not been
measured. `scripts/arm_dependence_diagnostic.py` measures the suite delta (realdelta.delta_interval, suite
scope, 95%). Truth is mean(p_b - p_a) over the sample's cases. 2000 reps per row; generator
`default_rng([20261122, row index])`; m = 30, n = 5. Rows:
- X0, within-arm shock (V2's structure, a different random stream, so not expected to reproduce 0.894
  exactly): each arm draws its own logit shock N(0, 0.3^2) per trial index, shared by its cases; null;
  Beta(4,2).
- X1, latent coupling per (case, trial): arm a passes when Phi(z_a) < p_a,i and arm b when
  Phi(z_b) < p_b,i, with (z_a, z_b) standard normal and correlation rho.
  - Null, Beta(4,2): rho in {-0.5, 0, 0.5, 0.9, 1.0}. rho = 0 is the independent reference; rho > 0
    models shared seeds; rho = 1 is the same random number in both arms.
  - Shift +0.05, Beta(4,2): rho in {0, 0.9}. rho = 0 is the power reference.
  - Null, Beta(20,1): rho = 0.9.
- X2, correlated run-level shocks: as X0, but the arms' shocks for trial index t have correlation c.
  - Null, Beta(4,2): c in {0.5, 1.0}.
  - Shift +0.05, Beta(4,2): c = 1.0.

Disclosure. A `--smoke` run (50 reps, seed base 1) of an earlier version of the script was made before this
section was committed, to check that it runs. That version had X0, X1 null at rho 0.5, 0.9 and 1.0, X1 shift
at rho 0.9, X1 Beta(20,1) and X2 at c = 1 (null and shift). Every number it printed was seen:
- coverage: X0 0.900; X1 0.960, 1.000, 1.000, 1.000 (shift), 1.000 (Beta(20,1)); X2 1.000 (null) and
  0.940 (shift);
- excludes 0: X0 0.100; X1 null rho 0.5 0.040, rho 0.9 0.000, rho 1.0 0.000; X1 shift 0.020; X1 Beta(20,1)
  0.000; X2 null 0.000; X2 shift 0.180.
The power clause below and the rows rho = 0 (null and shift), rho = -0.5 and c = 0.5 were added after that
output, at a reviewer's request. After the final edits the script was run once more with `--smoke` only to
confirm exit code 0; that output was not viewed. The smoke output is not evidence. Seed base 20261122 is used
nowhere else.

It runs once; the output (with the commit and the location of the imported realdelta) is committed as
produced. It gates nothing and changes no method. The Runs section's bug rule applies.

Disposition, fixed now:
- Two mechanisms are described separately everywhere they are mentioned:
  - Dependence within an arm: one shock shared by all cases of one arm's run. X0 and V2 measure it. The text
    quotes both numbers: the grid's reported-only V2 row (0.894 coverage, 0.105 false alarms) and X0 from
    this run.
  - Coupling between the arms: shared seeds (X1, rho > 0), opposite coupling (X1, rho < 0) and run-level
    shocks shared by both arms (X2).
- For the coupling between the arms, the text makes three separate statements, one per coupling type:
  positive latent coupling (X1, rho > 0), negative latent coupling (X1, rho < 0), and correlated run-level
  shocks (X2, c > 0). Each statement quotes the lowest coverage and the largest false-alarm rate over that
  type's null rows, and the shift rows' power next to the rho = 0 reference where the type has a shift row.
  A type whose rows all cover at least 0.93 is described as not making intervals too narrow in the tested
  rows (its rho or c values, m = 30, n = 5, these rate distributions). A type with a row below 0.93 is
  described as able to make intervals too narrow, with that row's configuration and coverage.
  Caches that make a case's trials repeat each other are A1 violations (the grid's V1), not covered here, and
  are not called harmless.
- Assumptions in README, stats.py and the command-line note:
  - A3 stays "the two arms' trial noise is independent", with the measured direction and power cost of
    the tested violations attached.
  - A new assumption A5 is added: within an arm, cases do not share a run-level shock (X0, V2). It is
    marked as measured for the suite delta only; its effect on pass-rate intervals is not measured.
  - The A3 text earlier in this protocol (Section "Assumptions") and the V2 label stay as written; this
    section records the correction.
- Places to change, listed now:
  - README.md Limitations (the assumptions bullet);
  - src/realdelta/cli.py NOTE_ASSUMPTIONS;
  - src/realdelta/stats.py module docstring (assumptions) and the `_delta_interval` comment on independence;
  - tests/test_cli.py, which asserts the note's first words "Note: Assumptions A1 and A3". If the note
    changes, the test changes with it, and the change is listed in the commit.
- Not changed: examples/real_model/PROTOCOL.md "Call order (A3)". It is a committed pre-registration, and its
  interleaving puts drift on both arms alike (X2's structure). The README's real-model section gets a
  one-line pointer if its A3 wording conflicts with the new text.
