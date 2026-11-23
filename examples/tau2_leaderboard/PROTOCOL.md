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

## Amendments

### Amendment 1 (2026-11-17): fetch record and terms check

Fetch. `fetch_data.py` ran twice, unchanged from 7c4ef90, on 2026-11-16 and 2026-11-17 (US Eastern); the
run logs carry no timestamps.
- The first run stopped on a network error (TLS handshake timeout) while downloading submission C's
  simulation files. A and B had passed their per-submission checks; the checks across submissions had not
  run, and no manifest was written.
- The second run passed every check and wrote `manifest.json` (fetched 2026-11-17T05:18:11+00:00),
  committed as produced in 8abbb32. It rewrote every file the first run had written, so all hashes in the
  manifest come from the second run.
- As of this amendment, the content of no file in `data/` has been displayed or parsed outside
  `fetch_data.py`: only file names, sizes and SHA-256 hashes were listed. This is the analyst's statement and
  cannot be checked from the repository. `fetch_data.py` prints no reward.

Terms of use (the check required under "Before any outward publication"), done on 2026-11-16 and
2026-11-17. Sources checked: the tau2-bench repository at commit c06b07dd7c4d4ec61ba6ff9bcdf0b15dd7ef36d4
(`LICENSE`, `README.md`, `docs/leaderboard-submission.md`, the leaderboard maintainer notes, the full file
tree) and the taubench.com page.
- The repository is MIT-licensed ("Copyright (c) 2025 Sierra Research"). Its README asks users to cite the
  paper of the component they use.
- `submission.json` of A, B, C and D is committed in that repository under
  `web/leaderboard/public/submissions/`. Their `results.json` and simulation files are not in the repository;
  they are in the public S3 bucket, which states no licence.
- `docs/leaderboard-submission.md` (the "Submit Results" link on taubench.com) states no terms of use or
  licence for submitted data. The taubench.com page text, read on 2026-11-16 and 2026-11-17, contains no
  terms, licence, copyright or privacy text; the page is rendered by script, so a link added by script may
  not have been seen.
- In the sources checked, no stated term was found that restricts reuse, and none grants it for the bucket
  files. This is a reading, not a legal opinion; the owner decides. The plan above stands: commit only
  derived statistics and the hash manifest, do not redistribute raw files, and cite the source and the
  tau2-bench paper.
- This record does not approve any outward step. Each one still needs the owner's explicit approval and the
  owner's re-confirmation of the clean-room answer.

### Amendment 2 (2026-11-17): D's bucket files do not reproduce D's published scores

Added after `analyze.py` ran. Its output (`run_20261123/`, committed as produced in 0c59ed5) is unchanged, and
so are the roles of the pairs: A vs C stays the only primary pair, and no descriptive pair becomes a finding.
None of the checks below was pre-registered.

Airline. After the run, a one-off check in the analyst's notes (not in the repository) computed pass^1 to
pass^4 (the mean over tasks of C(c, k) / C(4, k), as in tau2-bench's `pass_hat_k`, read at commit c06b07d; the
runs' commit 7324fb57 is not in the public repository) from each pinned airline `results.json` and compared
them with the scores in the pinned `submission.json`.
- A, B and C reproduced all four published values.
- D did not: its results file gives 80.50, 71.00, 64.50 and 60.00; its `submission.json` publishes 52.50,
  35.67, 27.00 and 22.00.
- `check_published.py` re-implements this check in the repository and reads only pinned files. Its output,
  `posthoc_published_scores.md`, is committed as produced. If it differs from the numbers above, a new
  amendment records that, and this one is not edited.

Retail and telecom. On 2026-11-17 the analyst also read the retail and telecom `results.json` of C and D from
the bucket. These files are not pinned by the manifest, and the code for this check is not in the repository.
- C reproduced its published pass^1 in both domains (retail 81.58, telecom 89.69).
- D did not: retail 67.54 against 75.00 published (run arguments: reasoning_effort "medium"), telecom 61.62
  against 57.24 (run arguments: "none").
- SHA-256 of the files read:
  - `gpt-5-2-none_sierra_2026-02-26/trajectories/retail/results.json`:
    60ce2eb2c560f7cb3ec93c0d18369cfd4c6a551cfb7ed6a4f65d4edc64124c41
  - `gpt-5-2-none_sierra_2026-02-26/trajectories/telecom/results.json`:
    1dae7a63a2bebd4357fb9abb3586df18e3c4695705873126ed892320307ef0b0
  - `gpt-5-2_sierra_2026-02-26/trajectories/retail/results.json`:
    2319107cfdb702a2bdd642bc987e5a55bf6dfc3b24553d73488c35aad73f762f
  - `gpt-5-2_sierra_2026-02-26/trajectories/telecom/results.json`:
    e13a01e28beae037d6468653916794498ac2481dea89bccadc90263d2501e320

What these data allow:
- Explanations consistent with this include: D's published scores come from runs other than those in its
  bucket files, or the same runs were scored differently. These data cannot tell which.
- D's published values fit the task counts of the bucket files (50, 114 and 114 tasks, 4 trials each): airline
  52.5 = 105/200, retail 75.0 = 342/456, telecom 57.24 = 261/456. So they do not point to a different task set.
- The top-level `timestamp` of the pinned airline results files is A 2026-02-24T10:30:49, B 2026-02-24T09:40:24,
  C 2026-02-24T10:31:27, D 2026-02-23T13:58:37. Its meaning (start of the run or time the file was written) is
  not documented in the sources checked. These timestamps do not agree with the `evaluation_date` fields
  (A and C 2026-05-05, B 2026-02-24, D 2026-05-26), which `summary.md` quotes as "evaluated ..." and on which
  the choice of the primary pair rests. A and C also differ from their evaluation dates and still reproduce
  their scores, so this gap cannot separate the explanations for D.

How the results are read from now on:
- A and C reproduce their published airline scores. The reason for choosing A vs C as the primary pair (the
  same evaluation date) rests on a metadata field that the files' own timestamps do not match. The choice
  stays as pre-registered.
- The three pairs with D (A-D, B-D, C-D) stay descriptive. They compare the bucket files of D, whose airline
  run arguments say reasoning_effort "medium". They say nothing about D's published scores or about the
  configuration D's label describes.
- Any write-up names D as "the bucket files of submission D, which do not reproduce its published scores",
  and says so next to every D row. This is described as files that do not reproduce the published scores,
  never as an error or a mislabelling by anyone.
- `run_20261123/` is used outside this repository (including a push) only together with
  `posthoc_published_scores.md` and this amendment, so that the D rows, among them B vs D "detected", never
  appear without this note.
- Telling the leaderboard maintainers about this is an outward step and needs the owner's approval.

### Amendment 3 (2026-11-17): correction to Amendment 2, and what `evaluation_date` may describe

Correction. Amendment 2 says the files' timestamps "do not agree with the `evaluation_date` fields". That holds
for A, C and D. It does not hold for B: B's airline results file is timestamped 2026-02-24T09:40:24 and its
`evaluation_date` is 2026-02-24.

`evaluation_date` may describe another domain's evaluation. The pinned `submission.json` of A and of C both carry
the same `methodology.notes`: "Evaluated using AllTools retrieval (BM25 + dense OpenAI text-embedding-3-large +
sandboxed shell). ... Banking_knowledge domain only — other domains intentionally excluded from this
comparison". Their `evaluation_date` (2026-05-05) may therefore refer to a banking_knowledge evaluation rather
than to the airline runs. This is a reading of the notes; no source states it.
- If that reading is right, the reason the primary pair was chosen (A and C are the only pair with the same
  evaluation date) does not separate A-C from A-B or B-C: the airline results files of A, B and C are
  timestamped on 2026-02-24 within about 51 minutes of one another (a fact that does not depend on this
  reading).
- The primary pair stays as pre-registered. A-B and B-C do not become findings.
- A write-up states this next to the primary result.

Other records:
- `analyze.py` and `fetch_data.py` are unchanged since 7c4ef90, and this protocol has only had text appended
  since then (evidence kept with the run logs).
- `analyze.py` was run once. That is the analyst's statement; the repository shows one run directory and the
  script refuses to overwrite it, but cannot show that no other run took place.
- The directory name `run_20261123` is the permutation seed, not a date. The analysis ran on 2026-11-17.
- The retail and telecom checks of Amendment 2 compare pass^1 only. If a write-up or a message to the
  leaderboard maintainers cites them, those four files are first pinned and the check code is committed.

### Amendment 4 (2026-11-17): post-hoc power calculation, fixed before it runs

The primary result is "not detected" with a 95% interval about 7 points wide on each side. This amendment adds
one post-hoc calculation, fixed here with `plan_power.py` before the script runs; the script runs once and its
output is committed as produced. It changes no earlier result and no role of any pair.

Question: with realdelta 0.1.1's suite-scope interval (95%), two independent arms (assumptions A3 and A5 hold) and
per-task pass rates like those observed, how many trials per task does a 50-task comparison need to detect a
1-point change, and which changes does it detect at 4 trials? The 1-point change is a design target (one point
of leaderboard resolution), not the observed A vs C difference.
- Rate distribution: a Beta distribution fitted by beta-binomial maximum likelihood to the per-task pass counts
  (out of 4) of A and C from the pinned files: 50 tasks observed twice, not 100 independent tasks. The output
  shows the observed and fitted count histograms and, as a sensitivity check, the fit on A alone. The fit is
  run from two starting points and must agree; a degenerate fit stops the script.
- Method: `realdelta.planner.plan_trials`, 50 tasks, suite scope, 95%, 1,000 simulations per row, seed 20261117.
  The script refuses to run with a realdelta other than 0.1.1 from this repository's `src/`.
- Criterion: "detects" means power at least 0.8. If no option in a grid reaches it, the output says "not
  reached within the grid" and gives the grid's end.
- Reported:
  1. a shift of -0.01 at 4, 16, 64, 128, 256, 512 and 1024 trials per task, and the first option reaching 0.8;
  2. at 4 trials, shifts of -0.01, -0.02, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.12, -0.15 and -0.20, and the
     first reaching 0.8;
  3. for contrast, (1) with the planner's default Beta(8, 2);
  4. for contrast, at 4 trials, 1, 2, 5 and 10 tasks breaking (rate set to 0), the planner's "break" model, since
     with rates near 0 or 1 a change is more likely a few tasks flipping than every task moving.
  Each row shows power, false-alarm rate, Monte Carlo standard errors and the realised change (the shift model
  clips rates to [0, 1], so the realised change can be smaller than the shift).
- Reading the false-alarm column: only the 4-trial rows are read against the calibration gate, since this is
  the study's setting (50 tasks, 4 trials) and its first simulation. A rate more than 2 Monte Carlo SE below 0.05
  means the interval is conservative here; more than 2 SE above 0.07 means it exceeds the gate here; otherwise it
  is "not distinguishable from 0.05-0.07 at this simulation size". Rows with 16 or more trials lie outside the
  gated range (3-10 trials); their false-alarm rates are reported, not judged. In tables 2 and 4 all rows share
  one seed and the same null runs, so that column repeats one estimate.
- Power is compared with 0.8 as a point estimate. The output gives the first row reaching it with its SE, the
  row before it, and for a shift also the realised change, which a write-up quotes.
- If the sensitivity fit on A alone fails, the output says "not available" with the reason; the main result
  still runs.
- Limits: four trials cannot tell a rate of 1 from 0.97, so rows with many trials depend on the fitted Beta's
  shape near 0 and 1 and are an extrapolation. The results describe the interval under these assumptions, not
  submissions A or C, and a write-up says so next to them.

### Amendment 5 (2026-11-17): upstream records explain D's mismatch

Before opening an issue upstream, the analyst searched the tau2-bench issues on 2026-11-17. The data survey had
not searched them.
- Issue #238 (opened 2026-04-15, closed 2026-06-19) reported that the published GPT-5.2 "none" airline scores
  could not be reproduced with reasoning_effort "none". A contributor replied: "You are correct -- we did run it
  with medium by mistake. I will work on fixing this!"
- Pull request #334, "Update GPT-5.2 none submission" (merged 2026-05-26), changed only D's `submission.json`,
  "with corrected rerun results". D's `evaluation_date`, 2026-05-26, is the merge date.
- The diff of #334 shows the values it replaced. Before #334, D's `submission.json` listed airline pass^1 to
  pass^4 of 80.5, 71.0, 64.5 and 60.0, exactly what the pinned airline results file gives
  (`posthoc_published_scores.md`); retail pass^1 67.54 and telecom pass^1 61.62, exactly what the unpinned files
  of Amendment 2 give.
- A full listing of the bucket under D's prefix on 2026-11-17 shows two airline result files, `airline/results.json`
  and `gpt-5.2_none_airline_gpt-5.2_4trials.json` (the name given in `trajectory_files`), and 200 airline
  simulations. The second file is not pinned; it has the same timestamp (2026-02-23T13:58:37), the same run
  arguments (reasoning_effort "medium") and the same pass^1 to pass^4 as the pinned one.
- So, for airline, the upstream record settles the question Amendment 2 left open: D's published airline
  scores come from the rerun behind #334, and both airline result files in the bucket hold the run whose scores
  #334 replaced. One airline simulation object, read as a sample, started at 2026-02-23T13:58:44, in that same
  run; the other 199 were not read. No airline result file of the rerun is in the bucket.
- Not checked: D's banking_knowledge files and the retail, telecom and banking_knowledge `*_4trials.json` files.
  For retail and telecom only `results.json` pass^1 was compared (Amendment 2). D's banking_knowledge scores were
  changed again after #334 (re-graded on 2026-07-15, according to the submission's notes).
- Server metadata: `airline/results.json` reports Last-Modified 2026-10-27 and the `*_4trials.json` airline file
  2026-03-23. The objects may have been re-uploaded; their content is still the earlier run.
- That D's original airline run does not match its label is not a finding of this study: #238 reported it and
  the maintainers acknowledged it. (D's retail file also gives reasoning_effort "medium"; its telecom file gives
  "none".) This study adds only that the content of D's airline files in the bucket is still the earlier run.
- Before the new issue, the tau2-bench issues were searched again on 2026-11-17 for "gpt-5-2-none", "GPT-5.2 none
  trajectories", "trajectories S3 outdated" and "#334"; only #238 is on this topic.
- A write-up says this and cites #238 and #334. The maintainers' word "mistake" may be quoted as theirs; this
  study does not call anything an error.
- The D rows stay as Amendment 2 describes them. For A and C, Amendment 3's reading of `evaluation_date`
  remains a reading.

### Amendment 6 (2026-11-17): commit hashes changed before the first push

Before the commits listed here were accepted by the remote, their author and committer email was changed to the
account's GitHub no-reply address. Because of that, each commit hash changed, and so did the parent pointer of every
commit after the first. Each new commit has the same tree (the same files, byte for byte), the same message, the
same author and committer names and the same author and committer dates as the old one; the first new commit has
the same parent, 7c4ef90.
- Which hashes this affects: the commits from 8abbb32 to a9d6cec, cited in Amendments 1 to 5, and the commits
  recorded as "Run at commit ..." inside `run_20261123/`, `posthoc_published_scores.md` and `posthoc_power.md`
  (the HEAD when each script ran). To follow one, find it by prefix in the "old commit" column and take the new
  commit on the same row, which has the same tree. 7c4ef90 and earlier commits, and the upstream commits c06b07d
  and 7324fb57, are unchanged and not in the table.
- `git rev-parse <new commit>^{tree}` prints the tree listed here. The old commits were never accepted by the
  remote, so that the old commits had these trees is the analyst's statement and cannot be checked from the
  repository.

| old commit | new commit | tree |
|---|---|---|
| 8abbb32e0b797ccecd92349dbed08ec9b3ae2922 | 55ab070229388c085542f4d3ffb29aa9471e8486 | 464cd4115211049aa5e1db70dab71078d6aa1e21 |
| f2449b1c0af12534ec8adc28c3fe185bb70548ee | 29d978a36ba9daa064c6670ed110f605c5eda93d | 2ebc57fb3679a66b732b550162a44241e4f7d55f |
| 0c59ed588fd2e066277424f72a57e3f0c308fb34 | 111e82290d870e74592f2337fa2f65c5fcd5886b | 95e789b36cca4f499fa4049612bbb11a949f95be |
| 88f0b1bc3d650be7bd2ac093844ceff27936ac53 | 7b2de75cef63d05bcabbaf4053338838fc86eaf6 | 428460a16c4696942577d089a5305c3baa1ff097 |
| 09307293fad34ac214afd657b814c8cb68298fd9 | c795111fda08ab01bd22e1f7b7612157ce545cfe | 58b9515ee764f210947e3f0f764b010179471806 |
| fc6b40c241bb0a2b8e87e8ce7c805da163e0df87 | aac0568d2aa244fe26946fb12976cf9e7157f8ae | a3ccedfbfb0a33ebfde1d90f5eb52fdc57581915 |
| dc3703e5dd3309d2a827ece4b3ff11dc4c543715 | 427ddb5339c996c22ca465c49830280c576ffe3b | 6dd8bf657f62a93a0f959e3ca95545fd045bc8a3 |
| 7819263bebef8289c60a23713f5a7573854ba50a | d6091315326ffb14539fe0c2c3d8a6e2bdf0e174 | feafe99317d7ded560c9312ea7133dedafaad3cb |
| a9d6cec8e190902096e52d28956b14dab654c613 | 3a88a3ebcd6a37cc86f1f8eefcb55a03d30ce1e9 | 1e552b24a88914167c04225fd07fa49e0cb20c4d |

### Amendment 7 (2026-11-17): upstream issue #764; a README section on this study

Upstream issue. On 2026-11-17 at 05:59:54 UTC, with the owner's approval, the owner's GitHub account opened
sierra-research/tau2-bench#764, "S3 airline trajectories for gpt-5-2-none_sierra_2026-02-26 predate the #334
rerun".
- It reports what Amendment 5 records for D's airline files: the two result files, their timestamp and run
  arguments, and their pass^1 to pass^4 against the values D's `submission.json` listed before and after #334.
  It adds that the same computation matches the published airline pass^1 to pass^4 of A, B and C.
- It asks whether the rerun's trajectories could be uploaded, or a note added to D's submission, and offers a
  pull request for the note. It does not mention this study or realdelta.
- It covers airline only. The retail and telecom checks of Amendment 2 are not in it; Amendment 3's condition
  for citing them is unchanged.
- When this amendment was written, the issue was open with no comments (`gh issue view` on 2026-11-17:
  createdAt 2026-11-17T05:59:54Z, state OPEN, 0 comments; the output is kept in the analyst's notes, not in
  this repository). A maintainer reply, or a change to the
  bucket or to D's submission, is recorded in a later amendment; this one is not edited.

README. The repository README gains a section on this study, committed with this amendment. It quotes the
primary result with the dependence statement, the A5 caveat and Amendment 3's reading; the post-hoc power with
Amendment 4's limits and the false-alarm reading of `posthoc_power.md`; and D only as Amendment 2 requires,
citing #238, #334 and #764. It names no model in its text and no descriptive pair as detected. Pushing it is
an outward step and waits for the owner, as does any write-up outside this repository, together with the
owner's re-confirmation of the clean-room answer.

### Amendment 8 (2026-11-23): the outward steps of 2026-11-17; clean room; README wording

Outward steps of 2026-11-17. Push times come from this machine's reflog of `origin/main` ("update by push", local
clock, -0500); they are the analyst's statement and cannot be checked from this repository.
- 00:55: push of 7c4ef90..e5ad8b1 (Amendments 1 to 6). It carried `run_20261123/` (111e822) together with
  `posthoc_published_scores.md` (c795111) and Amendment 2 (7b2de75), as Amendment 2 requires.
- 05:59:54 UTC (00:59 -0500): upstream issue #764 (Amendment 7).
- 10:44: push of c9aad41 (Amendment 7 and the README section on this study).
- 10:51: push of commit cfefe00 of the owner's personal site, which adds a section on this study. Commit 6893b2c
  split its long sentences and reached the site's remote with the push of 6b5c25b at 11:23. The section's text
  is the same in the site's latest pushed commit, e82526d (16:10).
The owner approved the pushes of e5ad8b1, c9aad41 and cfefe00 and the issue in chat (analyst's notes).

The site section, as of e82526d, against "Wording rules for any write-up" and Amendments 2 to 4:
- It names submissions, says Sierra ran them, and puts the confounds in the same sentence. The primary result
  reads "not detected at this scale" with its interval. It gives the run-level shock caveat with false-alarm
  rates of 0.085 to 0.105, the post-hoc power with Amendment 4's limits, and no ranking language. It does not
  mention D. For the descriptive pairs it links the README and this protocol.
- It gives the dependence statement's words in three sentences and leaves out "(Diagnostic AD)".
- It gives Amendment 3's reading at the end of the section, after the post-hoc power paragraph. Amendment 3
  asks for it next to the primary result.
On 2026-11-23 the owner asked for both differences to be corrected on the site. A later amendment records the
corrected site commit.

Clean room. "Before any outward publication" and Amendments 1 and 7 ask the owner to re-confirm the clean-room
answer before each outward step. No re-confirmation was recorded before the steps above. This is a deviation
from that rule. On 2026-11-23 the analyst asked the owner in chat to confirm: "当时没有专门确认，现在补确认：
tau2-bench（Sierra）和这些厂商仍然与你无关。" ("No separate confirmation was made at the time; confirming now:
tau2-bench (Sierra) and these vendors are still unrelated to you.") The owner answered "无关" ("not related"),
then "一直都无关，从来都没关系。。。这是我个人的项目" ("never related, there has never been any connection... this
is my personal project"). The owner's "always" covers the time of the steps above. This answer precedes the push
of this amendment.
- Change to the rule, at the owner's request ("不用每次确认", "no need to confirm each time"): the owner's
  statement of 2026-11-23 is taken as standing. From this amendment on, the owner tells the analyst if it
  changes, and a separate re-confirmation before each outward step is no longer asked. Each outward step still
  needs the owner's explicit approval.

#764. On 2026-11-23, `gh issue view 764` showed the issue open with no comments, last updated
2026-11-17T05:59:54Z (output kept in the analyst's notes). No reply on the issue. The bucket and D's
`submission.json` were not re-checked.

Posts. This amendment does not record social-media posts about this study. A later amendment records them with
their dates.

README wording. Commit 829c89b changes the README section on this study. Its numbers, scopes and caveats are
unchanged, except for one rounding:
- Long sentences are split and semicolons are replaced by periods. The dependence statement keeps the words fixed
  in "Dependence between and within submissions (assumptions A3 and A5)", including "(Diagnostic AD)". Only its
  two semicolons became periods.
- The realized change at a shift of -0.12, -0.1158 in `posthoc_power.md`, is rounded to -0.116, the value the
  site uses.
- "what was read before that" becomes "the protocol's Disclosure section lists what was read before it was
  fixed", closer to the Disclosure section's wording.
- "which weakens the reason for the choice" becomes "If so, the reason for the choice is weaker", closer to
  Amendment 3's conditional.
- Prose uses US spelling ("realized", "labeled"). Identifiers and committed output are unchanged, including the
  column name "realised change" in `posthoc_power.md`.
Commits f17de3b and 79ec3d7 add and revise a Related work section in the README. They do not change the section
on this study. 829c89b, f17de3b, 79ec3d7 and this amendment were not pushed when this amendment was written.
Pushing them waits for the owner.

### Amendment 9 (2026-11-23): the site corrections asked for in Amendment 8

The owner's personal site corrected the two differences recorded in Amendment 8 in commit 69aa528, pushed on
2026-11-23 at 15:51 -0500 with the owner's approval, as the site session reports. The push time comes from this
machine's reflog of the site's `origin/main` and is the analyst's statement. In the tau2 section of 69aa528:
- the dependence statement ends "A negative coupling would make it too narrow (Diagnostic AD)".
- Amendment 3's reading follows the primary-result table directly, before the post-hoc power paragraph, with
  its wording unchanged.
The site commit before it, 3f2c0d6 (pushed at 15:44 -0500), adds a Related work section and does not change the
tau2 section. The tau2 section of 69aa528 does not mention D. This amendment was not pushed when it was written.
