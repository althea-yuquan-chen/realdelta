# Do the pinned airline results reproduce the published scores? (post-hoc, PROTOCOL.md Amendment 2)

pass^k in percent: computed from `<submission>.airline.results.json` (pinned by manifest.json) vs `results.airline.pass_k` in `<submission>.submission.json`. Not part of the pre-registered analysis.

Run at commit 88f0b1bc3d650be7bd2ac093844ceff27936ac53; data fetched 2026-11-17T05:18:11+00:00 (manifest.json).

| submission | k | from results.json | published | reproduced |
|---|---|---|---|---|
| A claude-opus-4-5_sierra_2026-02-26 | 1 | 84.00 | 84.00 | yes |
| A claude-opus-4-5_sierra_2026-02-26 | 2 | 77.67 | 77.67 | yes |
| A claude-opus-4-5_sierra_2026-02-26 | 3 | 73.50 | 73.50 | yes |
| A claude-opus-4-5_sierra_2026-02-26 | 4 | 70.00 | 70.00 | yes |
| B claude-sonnet-4-5_sierra_2026-02-26 | 1 | 72.00 | 72.00 | yes |
| B claude-sonnet-4-5_sierra_2026-02-26 | 2 | 62.00 | 62.00 | yes |
| B claude-sonnet-4-5_sierra_2026-02-26 | 3 | 54.50 | 54.50 | yes |
| B claude-sonnet-4-5_sierra_2026-02-26 | 4 | 48.00 | 48.00 | yes |
| C gpt-5-2_sierra_2026-02-26 | 1 | 83.00 | 83.00 | yes |
| C gpt-5-2_sierra_2026-02-26 | 2 | 78.33 | 78.33 | yes |
| C gpt-5-2_sierra_2026-02-26 | 3 | 75.00 | 75.00 | yes |
| C gpt-5-2_sierra_2026-02-26 | 4 | 72.00 | 72.00 | yes |
| D gpt-5-2-none_sierra_2026-02-26 | 1 | 80.50 | 52.50 | no |
| D gpt-5-2-none_sierra_2026-02-26 | 2 | 71.00 | 35.67 | no |
| D gpt-5-2-none_sierra_2026-02-26 | 3 | 64.50 | 27.00 | no |
| D gpt-5-2-none_sierra_2026-02-26 | 4 | 60.00 | 22.00 | no |
