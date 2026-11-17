# Which gaps on the tau2-bench airline leaderboard exceed trial noise? (pre-registration)

Everything that decides the result is fixed here and committed, together with `fetch_data.py` and
`analyze.py`, before `fetch_data.py` is run. (Metadata, and A's results file, were read during the survey; see
Disclosure.) Changes after that are appended as dated amendments; a fix to `fetch_data.py` that does not change a
filter is recorded as an amendment too. Order:
1. commit this protocol and both scripts;
2. run `fetch_data.py`, which checks every filter and writes `manifest.json`;
3. commit `manifest.json`;
4. run `analyze.py` once;
5. commit its output as produced.

## Question and estimand

The tau2-bench leaderboard publishes, for some submissions, the outcome of every trial of every task. For
pairs of submissions on the same 50 airline tasks, does realdelta's suite-scope interval for the change in
pass rate exclude zero?

The estimand is the change in macro pass rate between two **submissions** on this fixed task set. These
runs were made by Sierra (the benchmark's maintainer), not by the model vendors. A submission is a model plus
everything that differed in its run: evaluation date, provider-side state, reasoning settings. This is not a
comparison of models in general, and not a statement about tasks outside this set. realdelta 0.1.1 has no
population-scope change interval. This study examines no vendor announcement.

## Data

Source: the public bucket behind the tau2-bench leaderboard,
`https://sierra-tau-bench-public.s3.us-west-2.amazonaws.com/submissions/<submission>/`, files
`submission.json` and `trajectories/airline/results.json`, and the `seed` field of each simulation file.
- The bucket states no licence. Terms of use for the leaderboard data have not been checked yet; that check is a
  precondition for any outward step (see below). This study commits only derived statistics and `manifest.json` (file hashes). Raw files stay in the
  git-ignored `data/` folder and are not redistributed.
- The bucket's content can change: the evaluation dates below are later than the folder-name dates. The
  analysis therefore runs only on the files pinned by the committed manifest.

Submissions, fixed now: A `claude-opus-4-5_sierra_2026-02-26`, B `claude-sonnet-4-5_sierra_2026-02-26`,
C `gpt-5-2_sierra_2026-02-26`, D `gpt-5-2-none_sierra_2026-02-26`.
- Selection rule: every airline submission with 4 trials on every task, the folder-name date 2026-02-26,
  submitter Sierra, seed 300, the same user simulator and the same tau2 version.
- The rule was set during the survey, before the evaluation dates were known. Its "same date" condition was
  meant to limit run-window confounding, and the evaluation dates show it does not achieve that.
- Two other Sierra airline submissions with seed 300 and 4 trials (glm-5-think and
  qwen3.5-397b-a17b-think, folder date 2026-03-02) are excluded by the folder-name date. The set is kept as
  first fixed.

Filters, asserted by `fetch_data.py`, which stops if any fails. They were checked on metadata only, without
reading rewards, before this protocol was written:
- tau2 1.0.1 and git commit 7324fb57cb6819e77937c79964db916f5b068e31;
- user simulator gpt-5.2 with reasoning_effort low;
- top-level seed 300 and 4 trials;
- the same 50 task IDs, trials 0-3 once each;
- every per-trial seed an integer, and the same per-(task, trial) seed in all four submissions.

Recorded differences. `fetch_data.py` asserts each one, and the report states it next to every result it
affects:
- evaluation_date: A and C 2026-05-05, B 2026-02-24, D 2026-05-26.
- B: the metadata fields disagree. The label says reasoning "enabled"; the run arguments give
  temperature 0.0 and no reasoning setting.
- D: the metadata fields disagree. The label says reasoning "none"; the run arguments say
  reasoning_effort "medium".
These are described as disagreeing metadata fields, not as errors by anyone.

Outcome per trial: `reward` from `simulation_index`. 1.0 is a pass and 0.0 a failure; any other value stops
the analysis.

## Comparisons

- Primary (one): A vs C. It is the only pair whose evaluation dates are the same.
- Descriptive (five): A-B, A-D, B-C, B-D, C-D, in this fixed order and with the same statistics. They are
  labelled descriptive, and no result from them is called a finding.
- Per submission: the suite-scope pass-rate interval.

If all six pairs were truly equal and every assumption held, the expected number of flags is about 6 x 0.05,
and up to 6 x 0.07 under the calibration gate. If A5 is violated (a run-level shock within a submission's
run), the false-alarm rate of a single pair can reach 0.085 (Diagnostic AD, X0) to 0.105 (grid V2). Pairs share
submissions, so their flags are not independent.

## Analysis

- Method: `realdelta.compare(baseline, candidate, seed=0)` from realdelta 0.1.1 (suite scope, 95%), with the
  first-named submission of each pair as the baseline. "Detected" means the interval excludes 0. The sign-flip
  p-value is reported but decides nothing.
- Coverage evidence: 50 tasks with 4 trials each is inside the gated range of the suite delta (10-50 cases,
  3-10 trials). The gated grid has no row for this combination; at 50 cases its delta rows use 5 and 10
  trials and Beta(4,2) or Beta(20,1) rates, and the per-task rate distribution here is unknown.

## Dependence between and within submissions (assumptions A3 and A5)

All four submissions use the same seed for each (task, trial).
- **If** the seed reaches the user simulator and couples two submissions' trials positively, that is the
  X1 structure (rho > 0) of Diagnostic AD (docs/calibration_protocol.md;
  results/arm_dependence_diagnostic_20261122.md). AD was run and committed before this protocol. At 30 cases x
  5 trials with Beta(4,2) rates:
  - positive coupling did not make intervals too narrow: coverage at least 0.987, false alarms at most 0.013;
  - it cut power: a +0.05 change was detected in 0.038 of runs at rho 0.9, against 0.162 at rho 0.
- Negative coupling (rho -0.5) gave coverage 0.926 and false alarms 0.073. Nothing suggests shared seeds
  couple the trials negatively, but that cannot be ruled out from these data.
- This study's setting (50 tasks x 4 trials, unknown rate distribution) was not simulated.

Pre-specified descriptive check, primary pair only:
- Statistic: for each task, centre each arm's four outcomes on that task's mean in that arm; correlate the
  arms' centred outcomes over all (task, trial) with matching trial index.
- Null reference: the same statistic after random permutation of one arm's trial indices within each task
  (10,000 permutations, generator default_rng(20261123)).
- Report:
  - the observed value;
  - the permutation 2.5-97.5% range;
  - the one-sided permutation p-value (observed greater than permuted);
  - the number of tasks whose outcomes vary in both arms (only these carry information).
- If no task varies in both arms, the check is reported as "not computable". The script also outputs whether
  the observed value is above the permutation 97.5% point, which selects the wording below.
- It decides nothing.

Wording for every result, primary or descriptive:
- If the check is above the permutation range, the report says: "a positive correlation between the arms is
  visible in the primary pair; under positive coupling the interval is expected to be conservative and low
  in power (Diagnostic AD)".
- Otherwise, the report says: "no correlation between the arms was visible at this size (n informative
  tasks); if shared seeds couple the arms positively, the interval is conservative and low in power; a
  negative coupling would make it too narrow (Diagnostic AD)".
- If the check is not computable, the report says: "the dependence check was not computable; if shared seeds
  couple the arms positively, the interval is conservative and low in power; a negative coupling would make
  it too narrow (Diagnostic AD)".
- Descriptive pairs quote only the "Otherwise" statement's conditional part (from "if shared seeds"). The
  check is not repeated for them.
- `analyze.py` writes the applicable statement, the A5 caveat and the status of the descriptive pairs into
  `summary.md` itself, because the output is committed as produced.

Run-window differences (a run-level shock within one submission's run, assumption A5) are the
anti-conservative threat: AD's X0 row (coverage 0.915, false alarms 0.085) and the grid's V2 (0.894, 0.105).
They cannot be measured from these data. The report names them for every pair. For the primary pair the
evaluation dates are the same, but the same date is not the same run, so A5 is not ruled out there either.

## Wording rules for any write-up

- Name submissions, not models ("submission A vs C on these 50 tasks"). Say the runs were made by Sierra, and
  put the confounds in the same sentence.
- Not detected: "not detected at this scale; interval [lo, hi]", with the dependence statement above. Never
  "no difference" or "no improvement".
- Detected: "the interval excludes 0", in the same sentence as the A5 caveat with its false-alarm rates
  (0.085 to 0.105). Never "A is better than C".
- No ranking language ("better", "wins", "beats").
- The metadata disagreements of B and D are "metadata fields disagree", never "mislabelled" or "error".
- No claim about any vendor's announcement.

## Before any outward publication (blog post, site write-up, issue on another repository)

- Check the tau2-bench leaderboard and its submission guidelines for terms on reuse of the published data,
  and record the result here as an amendment.
- Clean room: in the working session of 2026-11-16, asked whether tau2-bench (Sierra) and these vendors are
  related to the owner's past internship, the owner answered in chat: "那些厂商与我无关" ("those vendors have
  nothing to do with me"). The owner re-confirms before any outward step.
- Pushing this study's run output to the public repository is an outward step too: it waits for the terms
  check and the owner's approval.
- Each outward step needs the owner's explicit approval.

## Disclosure

Pass rates of all four submissions are public on the leaderboard, so the direction of each pair could be
known to the analyst in advance. During the data survey the analyst saw:
- A's aggregate airline pass count (168 of 200, matching its published 84.0);
- the trial-level files of the tau2 paper's original results (other models).
No per-task outcome of B, C or D was read before this protocol was committed.

## Runs

`analyze.py` runs once. It:
- refuses to overwrite its outputs;
- refuses to run outside a clean git tree, with realdelta other than 0.1.1 from this repository's `src/`, or
  on files that do not match `manifest.json`;
- records the commit, the realdelta version and the manifest's fetch time.
A bug found after the run is fixed in a new run with a new output name; the earlier output stays.
