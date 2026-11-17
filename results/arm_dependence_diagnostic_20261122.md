# Suite delta with dependent arms: reported-only diagnostic, seed base 20261122, 2000 reps

Not gated. m=30 cases, n=5 trials per case. 'excludes 0' is the false-alarm rate on null rows and the power on the other rows. Run at commit 611d257b6d2af364e402978e3f6a3cfa5a57068f, realdelta from src\realdelta\__init__.py.

| setting | coverage | miss low | miss high | mean width | excludes 0 |
|---|---|---|---|---|---|
| X0 within-arm shock sd=0.3, null, Beta(4,2) | 0.915 | 0.042 | 0.043 | 0.201 | 0.085 |
| X1 latent rho=-0.5, null, Beta(4,2) | 0.926 | 0.037 | 0.036 | 0.201 | 0.073 |
| X1 latent rho=0.0, null, Beta(4,2) | 0.961 | 0.019 | 0.020 | 0.200 | 0.040 |
| X1 latent rho=0.5, null, Beta(4,2) | 0.987 | 0.006 | 0.007 | 0.201 | 0.013 |
| X1 latent rho=0.9, null, Beta(4,2) | 1.000 | 0.000 | 0.000 | 0.201 | 0.000 |
| X1 latent rho=1.0, null, Beta(4,2) | 1.000 | 0.000 | 0.000 | 0.201 | 0.000 |
| X1 latent rho=0.0, shift +0.05, Beta(4,2) | 0.959 | 0.018 | 0.024 | 0.197 | 0.162 |
| X1 latent rho=0.9, shift +0.05, Beta(4,2) | 1.000 | 0.000 | 0.000 | 0.197 | 0.038 |
| X1 latent rho=0.9, null, Beta(20,1) | 0.999 | 0.001 | 0.000 | 0.103 | 0.001 |
| X2 arm shocks sd=0.3 correlated 0.5, null, Beta(4,2) | 0.928 | 0.038 | 0.034 | 0.201 | 0.072 |
| X2 arm shocks sd=0.3 correlated 1.0, null, Beta(4,2) | 0.961 | 0.018 | 0.022 | 0.201 | 0.040 |
| X2 arm shocks sd=0.3 correlated 1.0, shift +0.05, Beta(4,2) | 0.948 | 0.024 | 0.029 | 0.197 | 0.153 |
