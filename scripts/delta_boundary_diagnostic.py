"""Reported-only diagnostic: suite-scope delta near a 100% pass rate with few trials.

Declared in docs/calibration_protocol.md ("Diagnostic DB") before it was run. It does not gate and
does not change any method; its numbers decide what the README discloses about the suite delta.

Random rows: baseline case rates from Beta(a, 1); the candidate keeps them (null), lowers each by
0.05 clipped at 0, or (Beta(20,1) only) raises each by 0.05 clipped at 1.
Adversarial rows: every baseline case has rate 1; every candidate case has the fixed rate
p_b = 1 - z^2 / (N + z^2) - 0.01 with N = m * n, just below the Wilson lower bound for an all-pass
arm of N trials. They are constructed worst cases for MOVER over Wilson arms, not typical suites.
The truth is the suite estimand, mean(p_b - p_a) over this sample's cases, as in
scripts/calibration_grid.py.

Usage:
    python scripts/delta_boundary_diagnostic.py           # results/delta_boundary_diagnostic_<seed>.*
    python scripts/delta_boundary_diagnostic.py --smoke   # 50 reps, seed base 1, temp output, not evidence
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibration_grid as grid  # noqa: E402  (reuses the frozen simulation helpers)

import realdelta  # noqa: E402
from realdelta import delta_interval  # noqa: E402

SEED_BASE = 20261118
REPS = 2000
Z = NormalDist().inv_cdf(0.975)
NEWLINE = chr(10)


def _fixed(value: float):
    return lambda rng, m: np.full(m, value)


def _constant_candidate(value: float):
    return lambda rng, pa: np.full(len(pa), value)


def settings() -> list[dict]:
    rows = []
    for a in (50, 20):
        effects = [("null", grid.same()), ("shift -0.05", grid.shift(-0.05))]
        if a == 20:
            effects.append(("shift +0.05", grid.shift(0.05)))
        for m in (5, 20):
            for n in (1, 3):
                for effect, transform in effects:
                    rows.append({"id": f"DB Beta({a},1) m={m} n={n} {effect}", "m": m, "n": n,
                                 "base": grid.beta_rates(a, 1.0), "transform": transform})
    for m, n in ((5, 1), (20, 1), (5, 3)):
        p_b = 1.0 - Z * Z / (m * n + Z * Z) - 0.01
        rows.append({"id": f"DB adversarial all-pass baseline, p_b={p_b:.3f} m={m} n={n}", "m": m, "n": n,
                     "base": _fixed(1.0), "transform": _constant_candidate(p_b)})
    return rows


def run(s: dict, reps: int, seed_base: int, index: int) -> dict:
    rng = np.random.default_rng([seed_base, index])
    cover = miss_low = miss_high = excl0 = 0
    width = 0.0
    for _ in range(reps):
        pa = s["base"](rng, s["m"])
        pb = s["transform"](rng, pa)
        trials = np.full(s["m"], s["n"])
        oa = grid.simulate_trials(rng, pa, trials)
        ob = grid.simulate_trials(rng, pb, trials)
        iv = delta_interval(oa, ob, scope="suite")
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
    stem = out / f"delta_boundary_diagnostic_{base}"
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
            "realdelta_file": _realdelta_location()}
    lines = [f"# Suite delta near 100%: reported-only diagnostic, seed base {base}, {reps} reps", "",
             f"Not gated. Lowest coverage: {min(r['coverage'] for r in rows):.3f}. "
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
