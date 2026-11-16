# realdelta

Is that change in your agent eval real, or noise?

You changed a prompt, a tool description or the model, re-ran your eval suite, and
the pass rate moved from 82% to 86%. `realdelta` tells you whether that move is
larger than the run-to-run noise of your agent, and how many repeated trials you
need before it can tell.

**Status:** early development, not released. The statistics core and its
calibration checks are done; the CLI, runner adapters and demo are not.

## What it does

- **Pass-rate intervals for repeated trials, in two scopes.** `suite` asks how sure
  we are about *this fixed set of cases*: given each case's pass rate, its trials
  are independent draws, so only trial-to-trial noise counts. `population` asks how
  sure we are about *cases like these*: the case is the unit, and case-to-case
  spread counts too.
- **Paired comparisons** (suite scope). Baseline and candidate run on the same
  cases; the change gets an interval and a sign-flip permutation p-value.
  `result.detected` means the interval excludes 0; it does not use the p-value, and
  the two can disagree.
- **Trial planning.** Simulates a synthetic suite you parameterise (case pass rates
  from a Beta distribution, every case shifted by the same amount) and reports power
  and false-alarm rate for 1, 3, 5, 10 or 20 trials per case. Near a 100% pass rate
  the realised shift is smaller than the one requested, because rates are clipped
  at 1. A separate function estimates cost from prices you supply.

```python
from realdelta import compare, pass_rate_interval

baseline = {"case-1": [True, True, False, True, True], "case-2": [...], ...}
candidate = {"case-1": [True, True, True, True, True], "case-2": [...], ...}

print(pass_rate_interval(candidate, scope="suite"))
result = compare(baseline, candidate)          # suite scope
print(result.delta, result.detected, result.p_value)
```

## How the intervals were checked

The calibration grid (its settings, the 0.93 gate and the rules for failures) was
pre-registered in [`docs/calibration_protocol.md`](docs/calibration_protocol.md)
before any final result existed. The suite pass-rate method was replaced after the
first final run failed; the steps are below. Each grid row simulates suites with
known case pass rates and counts how often the 95% interval contains the truth.

**Claim.** On the grid run [`results/calibration_grid_20261117.md`](results/calibration_grid_20261117.md)
(2000 repetitions per row, so a Monte Carlo standard error of about 0.005; 95% level),
every gated row has an estimated coverage of at least 0.93. The lowest rows are
0.956 for the suite pass rate (36 rows), 0.951 for the population pass rate (40 rows)
and 0.945 for the suite delta (25 rows). This is a statement about the tested
settings, not a guarantee of 95% coverage elsewhere.

**Tested settings** (gated rows; only the 95% level):

| Quantity | Cases | Trials per case | Case pass rates |
|---|---|---|---|
| Suite pass rate | 5 to 50 | 1 to 10, and unequal {1, 3, 10} | Beta(0.5,0.5), (2,2), (4,2), (20,1), (50,1); two mixtures; homogeneous 0.5 and 0.9 |
| Population pass rate | 5 to 50 | 1 to 10, and unequal {1, 3, 10} | as above, plus a 95%/5% pass/fail mixture and sticky trials (see Limitations) |
| Suite delta | 10 to 50 | 3 to 10, and unequal {1, 3, 10} at 30 cases | Beta(4,2) and Beta(20,1); no change, +0.05 and +0.10 |

The table gives ranges, not a full cross of every combination;
[`results/calibration_grid_20261117.md`](results/calibration_grid_20261117.md) lists every row.
File names carry the seed base (20261116, 20261117, 20261118), not a date; both grid
runs started on 2026-11-16 (see their provenance files).

**How we got there.** This history is part of the evidence, so it is listed in full.

1. The first final grid ([`results/calibration_grid_20261116.md`](results/calibration_grid_20261116.md))
   failed one suite row and the population-delta width rule. With 5 cases, 1 trial
   each and rates near 100%, the Wilson interval then used covered 0.917: a single
   failure pulls its upper bound below the truth.
2. Amendment 1 pre-registered an exact analytic check (minimum coverage >= 0.947)
   and two candidates: Clopper-Pearson on the effective sample size, and Wilson
   with a continuity correction. Both failed it, at 0.9449 and 0.9434
   ([`results/suite_bounds_selection.md`](results/suite_bounds_selection.md)).
3. Amendment 2 added one candidate: Clopper-Pearson with the effective sample size
   capped at the number of trials run. It was designed *after* seeing step 2's
   results, so the analytic check is not independent evidence for it. It passed
   that check with 0.9503 ([`results/suite_bounds_selection_a2.md`](results/suite_bounds_selection_a2.md)).
   The independent evidence is the CI coverage tests, whose gates did not change,
   and the 20261117 grid, which ran once after the implementation.

**The cost: wider, often conservative intervals.** Suite pass-rate intervals are
about 1.11 times as wide as the Wilson intervals of the 20261116 run (median across
rows, range 1.05 to 1.24; the two runs used different seeds, so the ratio is noisy).
Seven of the 36 suite pass-rate rows cover more than 99.5% (up to 0.999). With equal
trials per case the suite interval is Clopper-Pearson on the pooled pass count, which
is conservative when most cases are deterministic. The population pass rate is more
conservative still: if all m cases pass, its lower bound is 0.025^(1/m) (0.83 for 20
cases) however many trials each case ran, because m cases cannot rule out a failure
mode affecting a few percent of cases like them.

## Limitations

- **No population-scope delta in v0.1.** It failed the pre-registered width rule in
  the 20261116 run (mean width 0.368 and 0.364 against a limit of 0.30), so
  `delta_interval(scope="population")`, `compare(scope="population")` and
  `plan_trials(scope="population")` raise `NotImplementedError`.
- **The suite delta is gated only for 10 to 50 cases with 3 to 10 trials each**
  (plus one unequal-trials setting). It combines the two arms' Wilson-based
  intervals (MOVER), and Wilson bounds under-cover near 100%. A reported-only
  diagnostic ([`results/delta_boundary_diagnostic_20261118.md`](results/delta_boundary_diagnostic_20261118.md))
  covers part of the gap near 100%: with case rates from Beta(50,1) or Beta(20,1),
  5 or 20 cases and 1 or 3 trials each, under no change, a 0.05 drop and (Beta(20,1)
  only) a 0.05 rise, coverage was at least 0.971 across 20 settings. Three cases
  built by hand to be adverse (an all-pass baseline against a candidate just below
  the Wilson bound; not verified to be the worst) reached at least 0.949. Settings
  outside these, such as moderate pass rates with 1 trial per case or fewer than 10
  cases, have no evidence for the delta. `plan_trials` offers 1 trial per case by
  default, which falls in that untested region. Power near 100% is low: a 5-point
  drop is detected in at most 16.8% of runs (20 cases, 3 trials each), and in at most
  5.1% with 1 trial per case.
- **The pass-rate and delta intervals use different bounds** (Clopper-Pearson and
  Wilson), so one cannot be derived from the other on the same data.
- **Unequal trial counts** are covered by three grid settings (two pass-rate, one
  delta) and one exact, reported-only suite pass-rate configuration (5 cases with
  1, 1, 3, 3 and 10 trials, homogeneous rate: minimum coverage 0.958).
- **Assumptions.** A1: trials within a case are independent and identically
  distributed. A2: cases are an independent draw from a population. A3: the two arms
  share no randomness (seeds, caches, outage windows). A4: the number of trials per
  case does not depend on outcomes. The suite scope needs A1, A3 and A4; the
  population pass rate needs A2 and A4. The grid includes violations, reported and
  not gated: trials that repeat the previous outcome (violates A1) drop suite
  pass-rate coverage to 0.871 and 0.734; a shared per-trial shock in each arm
  (violates A3) drops suite delta coverage to 0.894, with a false-alarm rate of
  0.105. A2 holds only if your cases were sampled from the population you care
  about; for a hand-picked suite, the population scope describes a hypothetical
  population of similar cases.
- **Not checked:** confidence levels other than 95%, and the calibration of the
  p-value from `compare`. It tests the sharp null "the two versions behave
  identically on every case".

## Reproduce

From the repository root:

```bash
python -m pytest                                              # unit, analytic and CI coverage tests
PYTHONPATH=src python scripts/calibration_grid.py --smoke     # 50 repetitions; not evidence
```

In PowerShell, set the path first with `$env:PYTHONPATH = "src"`.

Both final grid runs are committed in `results/` with a provenance file, and each
ran once; the diagnostic records its commit in its own header. The grid script
refuses to overwrite existing results, and its current version uses seed base
20261117; the 20261116 run is reproducible from commit da182ba. The selection and diagnostic scripts are `scripts/suite_bounds_selection.py`
and `scripts/delta_boundary_diagnostic.py`.

## License

Apache-2.0
