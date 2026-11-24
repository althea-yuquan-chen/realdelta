# Planning from one result file: not shipped

Question. Given one baseline result file (m cases, 3 to 5 trials each), can realdelta estimate the power that
this fixed suite would have for a planned comparison (k cases break, or every case shifts by -0.05), well enough
to answer "how many trials do I need"? A `plan --from FILE` option was proposed for this. Two simulation rounds,
each run against a protocol fixed before it, found no method that met the criteria. Nothing shipped, and the
option is shelved. The planner that ships (`realdelta plan`, rates drawn from an assumed Beta distribution) is
unchanged.

How "fixed before the run" can be checked. Neither protocol was committed or publicly timestamped before its
run. Each protocol's SHA-256 was recorded locally before the truth phase and again before the methods phase
(values below), and the protocol files here have those hashes.

## Round 1 (2026-11-23)
Protocol: `round1/protocol_20261123.md`. Script: `scripts/plan_from_validation.py` at commit 7f56072
(`scripts/plan_from_validation_summary.py` applies the rule). `round1/plan_from_fit_diagnostic_20261123.txt` is
the earlier diagnostic the protocol cites.
Methods: per-case posteriors with a Jeffreys prior, a uniform prior, and a prior centred on the file's pooled
pass rate (P-pooled, c = 2). Controls: the observed rates (Plug-in) and the true rates (Oracle).
Result (`round1/summary.txt`): Oracle passed, and no candidate met the criteria. P-pooled failed 4 bias and 3 MAE
decision cells (5 distinct cells, all Beta(20,1) with 10 cases; the summary prints only the first few, the full
list was read from the methods output). The Jeffreys and uniform priors underestimated power by 0.14 and 0.19 on
average over the decision cells.

## Round 2 (post-hoc, 2026-11-24)
Designed after seeing round 1, so it is post-hoc. It used new seeds, five distributions not simulated in round 1,
and a stopping rule fixed in advance: if it failed, there would be no round 3. Protocol:
`round2/protocol_20261124.md` (reviewed before the run).
Script: commit 2eddd00 (`scripts/plan_from_validation_summary_r2.py` applies the rule).
Candidate: P-pooled only, with a gate that refuses files with fewer than F_min failed trials in cases with at
least one pass. Controls: Oracle (positive), the uniform prior (negative), Plug-in (reported).
Result (`round2/summary.txt`):
- Oracle passed (0 cells with |mean error| > 0.03). The uniform prior failed (262 bias cells at F_min 3), so the
  criteria reject a method known to be poor.
- P-pooled failed at both eligible gates: F_min 3 (346 decision cells: 39 bias, 9 MAE, 24 single-file p90
  failures) and F_min 6 (275 decision cells: 30, 9, 12). F_min 10 was not eligible (no near-100% decision cell
  with 3 trials per case at m = 20).
- The largest failures were Tri (30% of cases at 0, 40% at 1) with a -0.05 shift: P-pooled overestimated power by
  0.12 to 0.21. At F_min 3, Plug-in did not fail any of these cells. One explanation, not tested: posterior draws
  move the always-failing cases above 0, where the shift has room to act, while in the true suite the shift is
  clipped at 0.
- Near 100%, errors went both ways. Beta(50,1) with 20 cases: -0.10 to -0.18 (21 to 31 files per cell). Mix90Z
  with 120 cases and 3 broken cases: +0.07 to +0.09 at 5 planned trials, -0.10 to -0.12 at 10.
- Plug-in also failed (46 bias cells at F_min 3). Averaged over the gated suite-cells of the decision cells at
  F_min 3 (which are not independent), the two methods had nearly the same absolute error (paired difference
  +0.0008), but they failed in different cells.

Reading: none of the estimators tried here predicted a fixed suite's power within the criteria in these
settings. The observed failures depended on the shape of the pass-rate distribution (cases at exactly 0, how
close to 100%), which the gate's observable count did not capture. That pattern is an observation from these
runs, not a tested explanation.

## Files
- `round1/`, `round2/`: protocols, summaries, decision-cell lists and run logs, copied unchanged from the working
  notes where they were produced (paths inside them point there).
- `round2_prep/`: outputs of checks run before round 2. They cover the reproduction of round 1 with the
  refactored script, the consistency check with an injected defect, exploratory diagnostics on round-1 data
  (`diag_*`, which motivated round 2's gate) and a unit check of the error bands. The scripts that produced them
  read local working-note paths and are not included.
- The full truth and methods outputs (up to 33 MB) are not committed. All seeds are fixed, so the scripts
  regenerate them.

SHA-256 recorded locally during the runs (file names shortened):

| Recorded | File | SHA-256 |
|---|---|---|
| R1, before truth and before methods | protocol_20261123.md | `70c4cb60c1bee72a4969f8d912de9dfdae94d45588b1abd993f45b0ac323e667` |
| R1, before truth and before methods | scripts/plan_from_validation.py (= 7f56072) | `0ba927efe01fe21eed84fb8975bd78f202fb220bc0b017fb5cdd7e3820bca384` |
| R1, before methods | scripts/plan_from_validation_summary.py (= 7f56072) | `976c6640e36c4bbf6a835086b2ec3ab3131228df17bc757c81ba0bf291d6cada` |
| R1, before methods | decision_cells.json | `0b44e078f2300b93ff242797cc6f5ef64f6d7d8f4a3f8ad4849d4a021297c04f` |
| R2, before truth and before methods | protocol_20261124.md | `9f672914c5b57f06246ca9458418d93614551879045f4fb68fc22d176aeb7c99` |
| R2, before truth and before methods | scripts/plan_from_validation.py (= 2eddd00) | `2a4c204a52bacafc32cd39f746d32c6fee3536a841c070060b10c9a7c91e6ede` |
| R2, before truth and before methods | scripts/plan_from_validation_summary_r2.py (= 2eddd00) | `5f91ef62b5e2808dd0502fc9b2fcf789559bcec948c73d5fc9bb04228e683ea7` |
| R2, before methods | decision_cells.json | `76f515532b6ced18404ef467bd9a19ec080b47368c7062ee166e7220116cc6a5` |
| R2, before and after methods | truth.json | `8ca37aae7ba1eb7b141d2d486f15e30dde7ce32adb033b8897c09a2a736d0c31` |
| R2, after methods | methods.json | `3b7e592faf837ad358eceb14f61925f19d914759ddba1fe8b795d6d2264c7f54` |
| R2, after methods | summary.txt | `1d55cf90c31cb75fe749e7033fb8805a845378c716b6b5ef5ce25a70cab215d7` |

Round 1's truth.json and methods.json were hashed after the run (2026-11-24): `5dead727...e6e7` and
`bd6dffac...4bea`.

## Reproduce
```
python scripts/plan_from_validation.py 1 truth OUT1
python scripts/plan_from_validation.py 1 methods OUT1 results/plan_from_validation/round1/protocol_20261123.md
python scripts/plan_from_validation_summary.py OUT1
python scripts/plan_from_validation.py 2 consistency OUT2
python scripts/plan_from_validation.py 2 truth OUT2
python scripts/plan_from_validation.py 2 methods OUT2 results/plan_from_validation/round2/protocol_20261124.md
python scripts/plan_from_validation_summary_r2.py OUT2
```
With the current script, round 1's rows reproduce exactly (`round2_prep/round1_reproduction.txt`). The files are
not byte-identical to the originals, because the refactored script adds a `round` field. Runs used numpy 2.4.4
on macOS arm64. Round 2 took about 31 minutes on 10 worker processes.
