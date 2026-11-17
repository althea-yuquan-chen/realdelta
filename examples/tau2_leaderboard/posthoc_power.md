# Post-hoc power for a 50-task airline comparison (PROTOCOL.md, Amendment 4)

Run at commit dc3703e5dd3309d2a827ece4b3ff11dc4c543715, realdelta 0.1.1; data fetched 2026-11-17T05:18:11+00:00 (manifest.json). realdelta.plan_trials, suite scope, 95%, 1000 simulations per row, seed 20261117. Not part of the pre-registered analysis. Simulation results for synthetic 50-task suites, not a statement about submissions A or C.

Assumptions: realdelta 0.1.1's suite-scope interval; two independent arms (A3 and A5 hold); per-task rates from the fitted Beta. Four trials cannot tell a rate of 1 from 0.97, so rows with many trials depend on the fitted Beta's shape near 0 and 1: they are an extrapolation.

Power target 0.8:
- A 1-point change (a design target, not the observed A vs C difference): power first reaches 0.8 at 256 trials per task, power 0.867 (SE 0.011); the option before it has power 0.563 (SE 0.016).
- At 4 trials per task: power first reaches 0.8 at a shift of -0.12 (realised change -0.1158), power 0.897 (SE 0.010); the option before it has power 0.763 (SE 0.013).
- Power is compared with the target as a point estimate; a row within about 2 SE of it could fall on either side with another seed.

Per-task pass rates: Beta(0.586, 0.120), fitted by beta-binomial maximum likelihood to the per-task pass counts (out of 4) of A and C: 50 tasks observed twice, not 100 independent tasks. Sensitivity, A only: Beta(0.787, 0.153). numpy 2.4.4, scipy 1.18.1.

| passes out of 4 | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| observed tasks (A and C) | 8 | 5 | 3 | 13 | 71 |
| expected under the fit | 7.4 | 5.5 | 6.2 | 9.6 | 71.3 |

## A 1-point change (-0.01), fitted rates

| trials per task | power (SE) | false alarms (SE) | realised change | total runs |
|---|---|---|---|---|
| 4 | 0.004 (0.002) | 0.003 (0.002) | -0.0099 | 400 |
| 16 | 0.050 (0.007) | 0.015 (0.004) | -0.0099 | 1600 |
| 64 | 0.295 (0.014) | 0.030 (0.005) | -0.0099 | 6400 |
| 128 | 0.563 (0.016) | 0.028 (0.005) | -0.0099 | 12800 |
| 256 | 0.867 (0.011) | 0.043 (0.006) | -0.0099 | 25600 |
| 512 | 0.995 (0.002) | 0.045 (0.007) | -0.0099 | 51200 |
| 1024 | 1.000 (0.000) | 0.058 (0.007) | -0.0099 | 102400 |

## Change sizes at 4 trials per task, fitted rates

All rows share one seed and the null run does not depend on the shift, so the false-alarm column repeats one estimate.

| shift | power (SE) | false alarms (SE) | realised change |
|---|---|---|---|
| -0.01 | 0.004 (0.002) | 0.003 (0.002) | -0.0099 |
| -0.02 | 0.026 (0.005) | 0.003 (0.002) | -0.0198 |
| -0.05 | 0.184 (0.012) | 0.003 (0.002) | -0.0490 |
| -0.06 | 0.285 (0.014) | 0.003 (0.002) | -0.0586 |
| -0.07 | 0.396 (0.015) | 0.003 (0.002) | -0.0683 |
| -0.08 | 0.515 (0.016) | 0.003 (0.002) | -0.0778 |
| -0.09 | 0.662 (0.015) | 0.003 (0.002) | -0.0874 |
| -0.10 | 0.763 (0.013) | 0.003 (0.002) | -0.0969 |
| -0.12 | 0.897 (0.010) | 0.003 (0.002) | -0.1158 |
| -0.15 | 0.981 (0.004) | 0.003 (0.002) | -0.1440 |
| -0.20 | 1.000 (0.000) | 0.003 (0.002) | -0.1904 |

## Contrast: a 1-point change with the planner's default Beta(8.0, 2.0)

| trials per task | power (SE) | false alarms (SE) | realised change |
|---|---|---|---|
| 4 | 0.041 (0.006) | 0.051 (0.007) | -0.0100 |
| 16 | 0.075 (0.008) | 0.040 (0.006) | -0.0100 |
| 64 | 0.177 (0.012) | 0.047 (0.007) | -0.0100 |
| 128 | 0.327 (0.015) | 0.055 (0.007) | -0.0100 |
| 256 | 0.560 (0.016) | 0.057 (0.007) | -0.0100 |
| 512 | 0.809 (0.012) | 0.044 (0.006) | -0.0100 |
| 1024 | 0.983 (0.004) | 0.068 (0.008) | -0.0100 |

## Contrast: k tasks break (rate set to 0) at 4 trials per task, fitted rates

The false-alarm column repeats the estimate of the change-size table (same seed, same null runs).

| tasks broken | power (SE) | false alarms (SE) | realised change |
|---|---|---|---|
| 1 | 0.013 (0.004) | 0.003 (0.002) | -0.0167 |
| 2 | 0.071 (0.008) | 0.003 (0.002) | -0.0335 |
| 5 | 0.629 (0.015) | 0.003 (0.002) | -0.0830 |
| 10 | 0.998 (0.001) | 0.003 (0.002) | -0.1658 |

False alarms, read as fixed in Amendment 4 before the run. Only the 4-trial rows are read against the calibration gate: this is the study's setting (50 tasks, 4 trials). Rows with 16 or more trials lie outside the gated range (3-10 trials) and are reported, not judged.
- fitted rates, 4 trials: 0.003 (SE 0.002): below 0.05 by more than 2 SE, so the interval is conservative here
- planner default Beta(8.0, 2.0), 4 trials: 0.051 (SE 0.007): not distinguishable from 0.05-0.07 at this simulation size

The shift model adds the change to every task's rate and clips to [0, 1]; tasks at a rate of 0 cannot fall further, so the realised change can be smaller than the shift. 'power' counts intervals entirely below 0.
