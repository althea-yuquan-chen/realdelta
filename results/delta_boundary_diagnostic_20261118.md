# Suite delta near 100%: reported-only diagnostic, seed base 20261118, 2000 reps

Not gated. Lowest coverage: 0.949. 'excludes 0' is the false-alarm rate on null rows and the power on the other rows. Run at commit 463429f5b06d1cfeb647b4d3e7f1dfc71cdd11cf, realdelta from src\realdelta\__init__.py.

| setting | coverage | miss low | miss high | mean width | excludes 0 |
|---|---|---|---|---|---|
| DB Beta(50,1) m=5 n=1 null | 1.000 | 0.000 | 0.000 | 0.872 | 0.000 |
| DB Beta(50,1) m=5 n=1 shift -0.05 | 1.000 | 0.000 | 0.001 | 0.875 | 0.002 |
| DB Beta(50,1) m=5 n=3 null | 1.000 | 0.000 | 0.001 | 0.427 | 0.001 |
| DB Beta(50,1) m=5 n=3 shift -0.05 | 0.996 | 0.002 | 0.003 | 0.449 | 0.013 |
| DB Beta(50,1) m=20 n=1 null | 1.000 | 0.000 | 0.001 | 0.344 | 0.001 |
| DB Beta(50,1) m=20 n=1 shift -0.05 | 0.996 | 0.002 | 0.003 | 0.368 | 0.044 |
| DB Beta(50,1) m=20 n=3 null | 0.998 | 0.002 | 0.001 | 0.147 | 0.003 |
| DB Beta(50,1) m=20 n=3 shift -0.05 | 0.982 | 0.011 | 0.007 | 0.175 | 0.168 |
| DB Beta(20,1) m=5 n=1 null | 0.998 | 0.002 | 0.001 | 0.875 | 0.002 |
| DB Beta(20,1) m=5 n=1 shift -0.05 | 1.000 | 0.000 | 0.000 | 0.878 | 0.006 |
| DB Beta(20,1) m=5 n=1 shift +0.05 | 1.000 | 0.000 | 0.000 | 0.873 | 0.001 |
| DB Beta(20,1) m=5 n=3 null | 0.994 | 0.001 | 0.005 | 0.447 | 0.006 |
| DB Beta(20,1) m=5 n=3 shift -0.05 | 0.991 | 0.005 | 0.004 | 0.469 | 0.025 |
| DB Beta(20,1) m=5 n=3 shift +0.05 | 1.000 | 0.001 | 0.000 | 0.436 | 0.006 |
| DB Beta(20,1) m=20 n=1 null | 0.991 | 0.006 | 0.004 | 0.373 | 0.009 |
| DB Beta(20,1) m=20 n=1 shift -0.05 | 0.988 | 0.007 | 0.005 | 0.394 | 0.051 |
| DB Beta(20,1) m=20 n=1 shift +0.05 | 0.999 | 0.001 | 0.000 | 0.357 | 0.006 |
| DB Beta(20,1) m=20 n=3 null | 0.978 | 0.009 | 0.013 | 0.179 | 0.022 |
| DB Beta(20,1) m=20 n=3 shift -0.05 | 0.971 | 0.019 | 0.010 | 0.202 | 0.150 |
| DB Beta(20,1) m=20 n=3 shift +0.05 | 0.991 | 0.004 | 0.005 | 0.162 | 0.064 |
| DB adversarial all-pass baseline, p_b=0.556 m=5 n=1 | 0.949 | 0.051 | 0.000 | 0.855 | 0.409 |
| DB adversarial all-pass baseline, p_b=0.829 m=20 n=1 | 0.976 | 0.021 | 0.003 | 0.399 | 0.458 |
| DB adversarial all-pass baseline, p_b=0.786 m=5 n=3 | 0.969 | 0.024 | 0.007 | 0.485 | 0.418 |
