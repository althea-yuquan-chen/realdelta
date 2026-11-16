# realdelta

Is that change in your agent eval real, or noise?

You changed a prompt, a tool description or the model, re-ran your eval suite, and
the pass rate moved from 82% to 86%. `realdelta` tells you whether that move is
larger than the run-to-run noise of your agent, and how many repeated trials you
need before it can tell.

**Status:** early development. The statistics core is in place and tested; the CLI,
runner adapters and demo are not.

## What it does

- **Intervals for repeated trials.** Treats the case as the unit, so correlated
  trials of one case do not masquerade as independent evidence. Two scopes:
  `suite` (this fixed set of cases) and `population` (cases like these).
- **Paired comparisons.** Baseline and candidate run on the same cases; the
  change gets an interval and a permutation p-value.
- **Trial planning.** Simulates your comparison to report the power and false-alarm
  rate for 1, 3, 5, 10 or 20 trials per case, plus a cost estimate from prices you
  supply.

```python
from realdelta import compare, pass_rate_interval

baseline = {"case-1": [True, True, False, True, True], "case-2": [...], ...}
candidate = {"case-1": [True, True, True, True, True], "case-2": [...], ...}

print(pass_rate_interval(candidate, scope="suite"))
result = compare(baseline, candidate)
print(result.delta, result.detected, result.p_value)
```

## Why you can trust the intervals

`tests/test_calibration.py` simulates suites with known pass rates and checks that
each interval covers the truth close to its nominal 95%, including suites near a
100% pass rate, a single trial per case, ten cases and unequal trial counts. The
same tests reject the common shortcut of pooling every trial into one binomial.

## License

Apache-2.0
