# realdelta

Is that change in your agent eval real, or noise?

You changed a prompt, a tool description or the model, re-ran your eval suite, and
the pass rate moved from 82% to 86%. `realdelta` tells you whether that move is
larger than the run-to-run noise of your agent, and how many repeated trials you
need before it can tell.

**Status:** version 0.1.0, early development, not published on PyPI. The statistics
core, its calibration checks, result-file loading, the command line, a synthetic demo
and one pre-registered demo on a real model are done; installation from a clone was
checked on Windows and Linux.

## Install

From a clone (Python 3.10 or later; depends on numpy and scipy):

```bash
git clone https://github.com/althea-yuquan-chen/realdelta
cd realdelta
pip install -e ".[dev]"      # the dev extra adds pytest
```

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
  from a Beta distribution) under one of two changes: every case shifted by the same
  amount, or k randomly chosen cases broken (pass rate 0), the common agent
  regression. It reports power and false-alarm rate, with Monte Carlo standard
  errors, for 1, 3, 5, 10 or 20 trials per case, and the realised change: shifts are
  clipped at 0 and 1, and a broken case removes its own pass rate. A separate
  function estimates cost from prices you supply.

```python
from realdelta import compare, pass_rate_interval

baseline = {"case-1": [True, True, False, True, True], "case-2": [...], ...}
candidate = {"case-1": [True, True, True, True, True], "case-2": [...], ...}

print(pass_rate_interval(candidate, scope="suite"))
result = compare(baseline, candidate)          # suite scope
print(result.delta, result.detected, result.p_value)
```

## Result files

One record per trial, as JSON Lines (`.jsonl`) or CSV (`.csv`), UTF-8:

```
{"case_id": "case-001", "passed": true}
{"case_id": "case-001", "passed": false}
```

```
case_id,passed
case-001,true
case-001,false
```

Fields: `case_id` (a non-empty string), `passed` (a boolean; in CSV one of true,
false, 1, 0) and, optionally, `trial` (a whole number, on every line or on none;
each case and trial pair must be unique). Any other field is rejected. File-format
error messages name the file, line and field, never the value; when `compare` finds
cases present in only one file, it shows up to three of their ids, cut to 40
characters. Record failed, crashed or
timed-out runs as failures: dropping or re-running a trial because of its outcome
breaks assumption A4 below. Without `trial`, a file concatenated twice cannot be
detected, so every command prints the number of cases and trials it read; check it.
`load_outcomes(path)` reads a file into the dictionary the Python API takes.

## Command line

```bash
python -m realdelta interval results.jsonl                    # pass rate with its interval
python -m realdelta compare baseline.jsonl candidate.jsonl    # paired change, suite scope
python -m realdelta plan --cases 40 --delta -0.05             # power per trials option
python -m realdelta plan --cases 40 --break-cases 2 --trials 3,5,10 \
    --input-tokens 3000 --output-tokens 500 --usd-per-m-input 1 --usd-per-m-output 5
```

After installing, `realdelta ...` is the same command as `python -m realdelta ...`.
Add `--json` for one JSON object. Reports from `compare` and `plan` (and
from `interval` in the population scope) end with notes on what the result cannot
tell you; warnings (on stderr) flag settings outside the tested range below, such
as fewer than 10 cases or fewer than 3 trials per case for a comparison. `compare`
uses seed 0 for its permutation p-value (with more than 16 cases; up to 16 it
enumerates every sign flip) unless you pass `--seed`.

## Synthetic demo

[`examples/synthetic_demo.py`](examples/synthetic_demo.py) simulates an agent with 40
cases that mostly pass (case pass rates from Beta(20,1); true pass rate 0.95507), run 5
times each, with one fixed seed (the first one tried) and no model calls. Its full
output is in [`examples/synthetic/transcript.txt`](examples/synthetic/transcript.txt);
a test re-runs it and compares the output byte for byte. The comparison runs only with
numpy 2.4.4, the version the transcript was recorded with (other versions skip it;
CI pins 2.4.4 so it runs there, on Linux and Windows).

- **Noise alone moves the number.** Across 500 pairs of runs of the *unchanged*
  agent, the pass rate moved by 2 points or more in 184 pairs (36.8%) and by 4 points
  or more in 35 (7.0%); the 95th percentile of the move is 4.0 points. `compare`
  flagged a change in 23 of the 500 (4.6%); its sign-flip p-value was below 0.05 in
  14 (2.8%).
- **A regression in a few cases is caught by the interval much more often than by
  the p-value.**
  In a candidate where 3 of the 40 cases fail every time (true change -0.073), the
  interval excluded 0 in 423 of 500 pairs of runs (84.6%); the sign-flip p-value was
  below 0.05 in 76 (15.2%). The sign-flip test asks whether cases moved in a
  consistent direction across the suite, and only 3 cases moved; the interval
  measures the trial-to-trial noise of this fixed suite, which is the suite scope's
  question. A permutation test within cases would match that scope; it is not
  implemented.
- **How many trials?** `plan` for suites like this one (40 cases, Beta(20,1), 3 cases
  broken; it draws a new suite in every simulation) gives a simulated power of
  0.13 +- 0.02 with 1 trial per case (below the gated range), 0.54 +- 0.03 with 3,
  0.85 +- 0.02 with 5 and 0.99 +- 0.01 with 10.

These are simulation results for this setting, not calibration claims.

## Demo on a real model

[`examples/real_model/`](examples/real_model/) runs 40 generated puzzles (arithmetic, letter
counting, weekdays, sorting; 10 each) on GPT-5.6 Luna served through Azure OpenAI, with reasoning
effort low. Azure's content filtering is part of the system measured. Everything that decides the
result was fixed in [`PROTOCOL.md`](examples/real_model/PROTOCOL.md) before any paid call; its
Amendment 1 changed the model from Claude Haiku 5.5 to GPT-5.6 Luna before any call was made. Three
arms, 5 trials per case each, 600 calls in one interleaved order: A1 and A2 use the same system prompt
(an A/A pair), B adds "Answer immediately; do not show your working." The run
([`run_20261116/summary.txt`](examples/real_model/run_20261116/summary.txt)) used 51,213 input and
52,408 output tokens with no re-issued calls, timeouts, refusals or truncated outputs. The run
directory is named after the local date; it started at 2026-11-17T00:54Z.

**What "pass" measures here.** A trial passes only if its value is right *and* its last line has the
form `ANSWER: <value>`, as the pre-registered grader requires. The prompts carry two format
instructions side by side: the system prompt asks for that line, the user message says "Give the
answer in this form: ...". Most failures in this run are a correct value without the prefix, so the
pass rates below mostly measure compliance with the answer format, not puzzle-solving accuracy.

| Arm | Pass rate (suite scope) | 95% interval |
|---|---|---|
| A1 | 0.875 | [0.821, 0.917] |
| A2 | 0.855 | [0.798, 0.901] |
| B | 0.820 | [0.760, 0.871] |

- **A1 vs A2:** -0.020, interval [-0.086, +0.046]. The A/A pair was not flagged. It is one
  realisation: in the synthetic demo, 4.6% of unchanged pairs were flagged.
- **A1 vs B:** -0.055. No change detected at this scale (40 cases, 5 trials); the interval
  [-0.123, +0.014] bounds the change. Given the point above, what this comparison measures is
  mostly format compliance, not accuracy.
- **Failures per arm** (pass / wrong value / no `ANSWER:` line; no other category occurred):
  A1 175 / 1 / 24, A2 171 / 1 / 28, B 164 / 2 / 34. The grader checks the answer line first, so a
  wrong value without the prefix counts as "no `ANSWER:` line".
- **Population scope:** because the cases are random draws from the puzzle generator (10 per family;
  treating that stratified sample as independent draws is usually conservative), A1's pass rate for
  puzzles from this generator is 0.875 with interval [0.732, 0.958].

Descriptive, not pre-registered, and not tested:

- **Value correctness ignoring the prefix:** reading the last line's value with or without `ANSWER:`,
  A1 has 196 of 200 trials right, A2 199 and B 197. 82 of the 86 "no `ANSWER:` line" trials carry the
  right value.
- **Failures by puzzle family** (any category):

  | Family | A1 | A2 | B |
  |---|---|---|---|
  | arithmetic | 9 | 6 | 3 |
  | letters | 0 | 5 | 21 |
  | weekday | 15 | 17 | 6 |
  | sort | 1 | 1 | 6 |

  In this run B failed more on letter counting and sorting and less on weekdays and arithmetic, so
  per-family differences partly cancel in the overall rate. No per-family difference was tested.
- **Flaky cases:** 15 to 20 cases per arm passed on some trials and failed on others.

A1 appears in both comparisons, so they are not independent, and each can raise a false alarm (4.6%
of unchanged pairs in the synthetic demo; the calibration tests allow up to 7%). The task set is
synthetic and says nothing about other tasks. Dollar cost is not quoted here because Azure's price
for this model is uncertain; `summary.txt` gives an upper estimate.

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

Swapping baseline and candidate negates the delta interval exactly (a test pins
this), so the +0.05 and +0.10 delta rows also cover drops of the same realised size
from the shifted baseline; they do not cover drops from Beta(4,2) or Beta(20,1)
themselves, nor a few cases breaking outright.
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
  identically on every case", and in the synthetic demo's setting (3 of 40 cases
  broken) it rejected in 15.2% of runs against 84.6% for the interval.

## Reproduce

After the install above, from the repository root:

```bash
python -m pytest                                    # unit, analytic and CI coverage tests
python scripts/calibration_grid.py --smoke          # 50 repetitions; not evidence
```

Both final grid runs are committed in `results/` with a provenance file, and each
ran once; the diagnostic records its commit in its own header. The grid script
refuses to overwrite existing results, and its current version uses seed base
20261117; the 20261116 run is reproducible from commit da182ba. The selection and diagnostic scripts are `scripts/suite_bounds_selection.py`
and `scripts/delta_boundary_diagnostic.py`.

## License

Apache-2.0
