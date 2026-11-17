# tau2-bench airline leaderboard gaps (pre-registered in PROTOCOL.md)

Run at commit f2449b1c0af12534ec8adc28c3fe185bb70548ee, realdelta 0.1.1; data fetched 2026-11-17T05:18:11+00:00 (manifest.json). Suite scope, 95%. Submissions run by Sierra, not models: each row includes everything that differed in the runs.

| submission | notes | pass rate | 95% interval |
|---|---|---|---|
| A claude-opus-4-5_sierra_2026-02-26 | evaluated 2026-05-05 | 0.840 | [0.782, 0.888] |
| B claude-sonnet-4-5_sierra_2026-02-26 | evaluated 2026-02-24; metadata fields disagree (label reasoning 'enabled', run arguments give temperature 0.0 and no reasoning setting) | 0.720 | [0.652, 0.781] |
| C gpt-5-2_sierra_2026-02-26 | evaluated 2026-05-05 | 0.830 | [0.771, 0.879] |
| D gpt-5-2-none_sierra_2026-02-26 | evaluated 2026-05-26; metadata fields disagree (label reasoning 'none', run arguments say 'medium') | 0.805 | [0.743, 0.858] |

| pair (baseline vs candidate) | role | change | 95% interval | detected | sign-flip p |
|---|---|---|---|---|---|
| A vs C | primary | -0.010 | [-0.079, +0.059] | no | 0.8623 |
| A vs B | descriptive | -0.120 | [-0.194, -0.044] | yes | 0.0071 |
| A vs D | descriptive | -0.035 | [-0.106, +0.036] | no | 0.2142 |
| B vs C | descriptive | +0.110 | [+0.034, +0.185] | yes | 0.0322 |
| B vs D | descriptive | +0.085 | [+0.007, +0.162] | yes | 0.0321 |
| C vs D | descriptive | -0.025 | [-0.097, +0.046] | no | 0.5439 |

Dependence check, primary pair A vs C (descriptive): residual correlation -0.031; permutation 2.5-97.5% range [-0.153, 0.215]; one-sided p 0.7936 (10000 permutations); 4 of 50 tasks vary in both arms.

## How to read these numbers (fixed in PROTOCOL.md before the run)

- Only the primary pair (A vs C) can give a finding; the five other pairs are descriptive.
- 'detected' means the interval excludes 0. A run-level shock within one submission's run (assumption A5) cannot be measured here and raises a single pair's false-alarm rate to 0.085 (Diagnostic AD, X0) to 0.105 (grid V2); the primary pair shares an evaluation date, which does not rule it out.
- Dependence between the arms: No correlation between the arms was visible at this size (4 informative tasks); if shared seeds couple the arms positively, the interval is conservative and low in power; a negative coupling would make it too narrow (Diagnostic AD).
- 'not detected' means not detected at this scale, not 'no difference'. Rows compare submissions run by Sierra, not models in general; no row ranks one submission above another.
