"""Reported-only diagnostic: the suite delta when the two arms' randomness is not independent.

Declared in docs/calibration_protocol.md ("Diagnostic AD") before it was run. It does not gate and
does not change any method; its numbers decide how the README and the command-line notes describe
assumption A3.

Three structures, all with Beta(4,2) or Beta(20,1) case rates, m=30 cases, n=5 trials per case:
- X0, within-arm shock: for every trial index t each arm draws its own logit shock s ~ N(0, 0.3^2)
  shared by all of that arm's cases (same structure as the grid's V2 row; a different random stream).
- X1, latent coupling per (case, trial): arm a passes when Phi(z_a) < p_a,i and arm b when
  Phi(z_b) < p_b,i, with (z_a, z_b) standard normal and correlation rho. rho = 0 is independent arms
  (reference), rho > 0 models shared seeds (rho = 1: the same random number), rho < 0 opposite coupling.
- X2, correlated run-level shocks: as X0, but the two arms' shocks for trial index t have correlation
  c (c = 1: one outage window hits both runs; c = 0 would be X0).
The truth is the suite estimand, mean(p_b - p_a) over this sample's cases, as in
scripts/calibration_grid.py.

Usage:
    python scripts/arm_dependence_diagnostic.py           # results/arm_dependence_diagnostic_<seed>.*
    python scripts/arm_dependence_diagnostic.py --smoke   # 50 reps, seed base 1, temp output, not evidence
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.special import expit, logit
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibration_grid as grid  # noqa: E402  (reuses the frozen rate generators and transforms)

import realdelta  # noqa: E402
from realdelta import delta_interval  # noqa: E402

SEED_BASE = 20261122
REPS = 2000
M, N = 30, 5
SHOCK_SD = 0.3
NEWLINE = chr(10)


def settings() -> list[dict]:
    b42, b201 = grid.beta_rates(4.0, 2.0), grid.beta_rates(20.0, 1.0)
    null, up = grid.same(), grid.shift(0.05)
    rows = [{"id": "X0 within-arm shock sd=0.3, null, Beta(4,2)", "base": b42, "transform": null, "kind": "shock",
             "shock_corr": 0.0}]
    for rho in (-0.5, 0.0, 0.5, 0.9, 1.0):
        rows.append({"id": f"X1 latent rho={rho}, null, Beta(4,2)", "base": b42, "transform": null,
                     "kind": "latent", "rho": rho})
    for rho in (0.0, 0.9):
        rows.append({"id": f"X1 latent rho={rho}, shift +0.05, Beta(4,2)", "base": b42, "transform": up,
                     "kind": "latent", "rho": rho})
    rows.append({"id": "X1 latent rho=0.9, null, Beta(20,1)", "base": b201, "transform": null,
                 "kind": "latent", "rho": 0.9})
    for c in (0.5, 1.0):
        rows.append({"id": f"X2 arm shocks sd=0.3 correlated {c}, null, Beta(4,2)", "base": b42, "transform": null,
                     "kind": "shock", "shock_corr": c})
    rows.append({"id": "X2 arm shocks sd=0.3 correlated 1.0, shift +0.05, Beta(4,2)", "base": b42, "transform": up,
                 "kind": "shock", "shock_corr": 1.0})
    return rows


def _outcomes(passed: np.ndarray) -> dict[str, list[bool]]:
    return {f"c{i:03d}": [bool(x) for x in row] for i, row in enumerate(passed)}


def simulate_pair(rng: np.random.Generator, pa: np.ndarray, pb: np.ndarray, s: dict):
    """Both arms' outcomes, an m x n boolean array each, under the row's dependence structure."""
    pa_mat, pb_mat = np.repeat(pa[:, None], N, axis=1), np.repeat(pb[:, None], N, axis=1)
    if s["kind"] == "latent":
        rho = s["rho"]
        za = rng.standard_normal((M, N))
        zb = rho * za + np.sqrt(max(0.0, 1.0 - rho * rho)) * rng.standard_normal((M, N))
        return norm.cdf(za) < pa_mat, norm.cdf(zb) < pb_mat
    c = s["shock_corr"]
    shocks_a = rng.normal(0.0, SHOCK_SD, size=N)
    shocks_b = c * shocks_a + np.sqrt(max(0.0, 1.0 - c * c)) * rng.normal(0.0, SHOCK_SD, size=N)

    def shocked(p_mat, shocks):
        inner = (p_mat > 0.0) & (p_mat < 1.0)  # rates of exactly 0 or 1 are not moved, as in the grid
        q = p_mat.copy()
        q[inner] = expit(logit(p_mat[inner]) + np.broadcast_to(shocks, p_mat.shape)[inner])
        return q

    return rng.random((M, N)) < shocked(pa_mat, shocks_a), rng.random((M, N)) < shocked(pb_mat, shocks_b)


def run(s: dict, reps: int, seed_base: int, index: int) -> dict:
    rng = np.random.default_rng([seed_base, index])
    cover = miss_low = miss_high = excl0 = 0
    width = 0.0
    for _ in range(reps):
        pa = s["base"](rng, M)
        pb = s["transform"](rng, pa)
        a, b = simulate_pair(rng, pa, pb, s)
        iv = delta_interval(_outcomes(a), _outcomes(b), scope="suite")
        truth = float(np.mean(pb - pa))
        if truth < iv.low:
            miss_low += 1
        elif truth > iv.high:
            miss_high += 1
        else:
            cover += 1
        width += iv.high - iv.low
        excl0 += not iv.contains(0.0)
    return {"setting": s["id"], "coverage": cover / reps, "miss_low": miss_low / reps,
            "miss_high": miss_high / reps, "mean_width": width / reps, "excludes_zero": excl0 / reps}


def _commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _realdelta_location() -> str:
    here, src = Path.cwd().resolve(), Path(realdelta.__file__).resolve()
    return str(src.relative_to(here)) if src.is_relative_to(here) else "outside the working directory"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="50 reps, seed base 1, temp output, not evidence")
    args = ap.parse_args(argv)
    reps, base = (50, 1) if args.smoke else (REPS, SEED_BASE)
    out = Path(tempfile.mkdtemp()) if args.smoke else Path("results")
    stem = out / f"arm_dependence_diagnostic_{base}"
    if stem.with_suffix(".json").exists() or stem.with_suffix(".md").exists():
        print(f"refusing to overwrite {stem}.*", file=sys.stderr)
        return 1
    if not args.smoke:
        location = _realdelta_location()
        if not Path(location).parts[:2] == ("src", "realdelta"):
            print(f"refusing to run: realdelta imported from {location}, not src/realdelta", file=sys.stderr)
            return 1
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
        if dirty:
            print("refusing to run: the working tree is not clean, so the commit would not match the code",
                  file=sys.stderr)
            return 1
    rows = [run(s, reps, base, i) for i, s in enumerate(settings())]
    meta = {"seed_base": base, "reps": reps, "smoke": args.smoke, "commit": _commit(),
            "realdelta_file": _realdelta_location(), "m": M, "n": N, "shock_sd": SHOCK_SD}
    lines = [f"# Suite delta with dependent arms: reported-only diagnostic, seed base {base}, {reps} reps", "",
             f"Not gated. m={M} cases, n={N} trials per case. "
             "'excludes 0' is the false-alarm rate on null rows and the power on the other rows. "
             f"Run at commit {meta['commit']}, realdelta from {meta['realdelta_file']}.", "",
             "| setting | coverage | miss low | miss high | mean width | excludes 0 |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['setting']} | {r['coverage']:.3f} | {r['miss_low']:.3f} | {r['miss_high']:.3f} | "
                     f"{r['mean_width']:.3f} | {r['excludes_zero']:.3f} |")
    md = NEWLINE.join(lines) + NEWLINE
    js = json.dumps({"meta": meta, "rows": rows}, indent=1)  # both built before any file is written
    out.mkdir(exist_ok=True)
    stem.with_suffix(".json").write_text(js, encoding="utf-8")
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
