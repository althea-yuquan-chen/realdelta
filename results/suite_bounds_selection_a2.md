# Suite pass-rate bounds: pre-registered selection (Amendment 2)

Criterion: min exact coverage >= 0.947 on every configuration. Survivors, narrowest first: ['C1 clopper_pearson_capped']. First choice: C1 clopper_pearson_capped.

| method | config | min coverage | mean width |
|---|---|---|---|
| C1 clopper_pearson_capped | S1 m=5 | 0.9750 | 0.6501 |
| C1 clopper_pearson_capped | S1 m=10 | 0.9610 | 0.4729 |
| C1 clopper_pearson_capped | S1 m=20 | 0.9580 | 0.3312 |
| C1 clopper_pearson_capped | S1 m=50 | 0.9508 | 0.2028 |
| C1 clopper_pearson_capped | S1 m=100 | 0.9503 | 0.1400 |
| C1 clopper_pearson_capped | S2 m=5 n=5 | 0.9505 | 0.3275 |
| C1 clopper_pearson_capped | S2 m=10 n=5 | 0.9508 | 0.2304 |
| C1 clopper_pearson_capped | S3 m=5 k=2 | 0.9750 | 0.6392 |
| C1 clopper_pearson_capped | S3 m=5 k=4 | 0.9747 | 0.5692 |
| C1 clopper_pearson_capped | S3 m=20 k=10 | 0.9750 | 0.3049 |
| C1 clopper_pearson_capped | S3 m=20 k=16 | 0.9749 | 0.2374 |
| C1 clopper_pearson_capped | **all** | **0.9503** | **0.3732** |
| reference wilson (current) | S1 m=5 | 0.8284 | 0.5324 |
| reference wilson (current) | S1 m=10 | 0.8332 | 0.4034 |
| reference wilson (current) | S1 m=20 | 0.8357 | 0.2928 |
| reference wilson (current) | S1 m=50 | 0.8372 | 0.1856 |
| reference wilson (current) | S1 m=100 | 0.8377 | 0.1305 |
| reference wilson (current) | S2 m=5 n=5 | 0.8357 | 0.2886 |
| reference wilson (current) | S2 m=10 n=5 | 0.8369 | 0.2080 |
| reference wilson (current) | S3 m=5 k=2 | 0.8264 | 0.5246 |
| reference wilson (current) | S3 m=5 k=4 | 0.8152 | 0.4715 |
| reference wilson (current) | S3 m=20 k=10 | 0.8350 | 0.2714 |
| reference wilson (current) | S3 m=20 k=16 | 0.8329 | 0.2171 |
| reference wilson (current) | **all** | **0.8152** | **0.3205** |

Reported, not gated (Amendment 2): unequal trials, homogeneous p.

| method | config | min coverage | mean width |
|---|---|---|---|
| C1 clopper_pearson_capped | S4 m=5 n_i=(1,1,3,3,10) | 0.9583 | 0.5318 |
| reference wilson (current) | S4 m=5 n_i=(1,1,3,3,10) | 0.8940 | 0.4535 |
