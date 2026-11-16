"""Frozen calibration grid for realdelta (see docs/calibration_protocol.md).

Usage:
    python scripts/calibration_grid.py            # final run: 2000 reps, seed base 20261117
    python scripts/calibration_grid.py --smoke    # 50 reps, seed base 1, not evidence

Amendment 1 (docs/calibration_protocol.md): seed base 20261117; the population-scope delta is not
shipped in v0.1 (width rule, final at seed base 20261116), so delta settings drop that scope and
settings left without a scope are skipped. The 20261116 run is reproducible from commit da182ba.

Imports only the public API of realdelta.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from realdelta import delta_interval, pass_rate_interval

SEED_BASE = 20261117
REPS = 2000
GATE = 0.93
TRUTH_SEED = 20261116
TRUTH_DRAWS = 2_000_000


# ---------------------------------------------------------------- case-rate generators

def beta_rates(a: float, b: float) -> Callable[[np.random.Generator, int], np.ndarray]:
    return lambda rng, m: rng.beta(a, b, size=m)


def mixture_rates(values: dict[float, float]) -> Callable[[np.random.Generator, int], np.ndarray]:
    vals = np.array(list(values.keys()))
    probs = np.array(list(values.values()))
    if not math.isclose(probs.sum(), 1.0):
        raise ValueError("mixture weights must sum to 1")
    return lambda rng, m: rng.choice(vals, size=m, p=probs)


def fixed_rates(p: float) -> Callable[[np.random.Generator, int], np.ndarray]:
    return lambda rng, m: np.full(m, p)


def mixture_mean(values: dict[float, float]) -> float:
    return float(sum(v * w for v, w in values.items()))


# ---------------------------------------------------------------- trial simulation

def simulate_trials(
    rng: np.random.Generator,
    rates: np.ndarray,
    trials: np.ndarray,
    sticky: float = 0.0,
    shocks: np.ndarray | None = None,
) -> dict[str, list[bool]]:
    """Outcomes per case.

    sticky: trial t > 0 copies trial t-1 with probability ``sticky``, otherwise it is a fresh
    draw, so every trial's marginal pass probability is still the case rate.
    shocks: one logit shock per trial index, shared by all cases of this arm.
    """
    out = {}
    for i, (p, n) in enumerate(zip(rates, trials)):
        runs: list[bool] = []
        for t in range(int(n)):
            if t > 0 and sticky > 0 and rng.random() < sticky:
                runs.append(runs[-1])
                continue
            q = p
            if shocks is not None and 0.0 < p < 1.0:
                q = 1.0 / (1.0 + math.exp(-(math.log(p / (1.0 - p)) + shocks[t])))
            runs.append(bool(rng.random() < q))
        out[f"c{i:03d}"] = runs
    return out


def trial_counts(rng: np.random.Generator, m: int, n: int | tuple[int, ...]) -> np.ndarray:
    if isinstance(n, int):
        return np.full(m, n)
    return rng.choice(np.array(n), size=m)


# ---------------------------------------------------------------- candidate transforms

def break_share(g: float, base_pass: float):
    """Turn a share g of ALL cases from 1 to 0 (each passing case w.p. g / base_pass)."""
    return lambda rng, pa: np.where((pa == 1.0) & (rng.random(len(pa)) < g / base_pass), 0.0, pa)


def fix_share(g: float, base_fail: float):
    """Turn a share g of ALL cases from 0 to 1 (each failing case w.p. g / base_fail)."""
    return lambda rng, pa: np.where((pa == 0.0) & (rng.random(len(pa)) < g / base_fail), 1.0, pa)


def shift(delta: float):
    return lambda rng, pa: np.clip(pa + delta, 0.0, 1.0)


def same():
    return lambda rng, pa: pa.copy()


def churn(fix_p: float, break_p: float):
    def f(rng, pa):
        u = rng.random(len(pa))
        out = pa.copy()
        out[(pa == 0.0) & (u < fix_p)] = 1.0
        out[(pa == 1.0) & (u < break_p)] = 0.0
        return out
    return f


def shift_truth(a: float, b: float, delta: float) -> float:
    """Population E[clip(q + delta) - q] for q ~ Beta(a, b), fixed-seed Monte Carlo."""
    q = np.random.default_rng(TRUTH_SEED).beta(a, b, size=TRUTH_DRAWS)
    return float(np.mean(np.clip(q + delta, 0.0, 1.0) - q))


# ---------------------------------------------------------------- settings

@dataclass
class Setting:
    id: str
    kind: str                      # "rate" or "delta"
    m: int
    n: int | tuple[int, ...]
    rates: Callable
    pop_truth: float
    scopes: tuple[str, ...]
    gated: dict[str, bool] = field(default_factory=dict)
    candidate: Callable | None = None
    sticky: float = 0.0
    shock_sd: float = 0.0
    note: str = ""


def build_settings() -> list[Setting]:
    S: list[Setting] = []
    both = ("suite", "population")

    def add(s: Setting) -> None:
        if not s.gated:
            s.gated = {sc: True for sc in s.scopes}
        S.append(s)

    for a, b in [(0.5, 0.5), (2, 2), (4, 2), (20, 1), (50, 1)]:
        for m in (5, 20, 50):
            for n in (1, 5):
                add(Setting(f"G2 Beta({a},{b}) m={m} n={n}", "rate", m, n, beta_rates(a, b), a / (a + b), both))
    mix1 = {1.0: 0.8, 0.7: 0.1, 0.0: 0.1}
    add(Setting("G3 {1:.8,.7:.1,0:.1} m=30 n=5", "rate", 30, 5, mixture_rates(mix1), mixture_mean(mix1), both,
                note="dev overlap: H2"))
    mix2 = {1.0: 0.9, 0.5: 0.1}
    add(Setting("G3 {1:.9,.5:.1} m=20 n=10", "rate", 20, 10, mixture_rates(mix2), mixture_mean(mix2), both))
    mix3 = {1.0: 0.95, 0.0: 0.05}
    for m in (5, 20):
        add(Setting(f"G3 {{1:.95,0:.05}} m={m} n=3", "rate", m, 3, mixture_rates(mix3), 0.95, ("population",)))
    for p in (0.5, 0.9):
        add(Setting(f"G4 homogeneous p={p} m=30 n=5", "rate", 30, 5, fixed_rates(p), p, both))
    for a, b in [(4, 2), (20, 1)]:
        add(Setting(f"G5 unequal n Beta({a},{b}) m=30", "rate", 30, (1, 3, 10), beta_rates(a, b), a / (a + b), both))

    for g in (0.05, 0.10):
        for m in (10, 20, 50):
            for n in (3, 10):
                note = "dev overlap: H6" if (g, m, n) == (0.05, 20, 10) else ""
                add(Setting(f"D1 break g={g} m={m} n={n}", "delta", m, n, mixture_rates({1.0: 0.95, 0.0: 0.05}),
                            -g, ("population",), candidate=break_share(g, 0.95), note=note))
    for g in (0.05, 0.10):
        for m in (10, 20, 50):
            for n in (3, 10):
                add(Setting(f"D2 fix g={g} m={m} n={n}", "delta", m, n, mixture_rates({1.0: 0.85, 0.0: 0.15}),
                            +g, ("population",), candidate=fix_share(g, 0.15)))
    null_bases = [("Beta(4,2)", beta_rates(4, 2), both), ("Beta(20,1)", beta_rates(20, 1), both),
                  ("{1:.95,0:.05}", mixture_rates({1.0: 0.95, 0.0: 0.05}), ("population",))]
    for name, gen, scopes in null_bases:
        for m in (10, 30):
            for n in (3, 10):
                add(Setting(f"D3 null {name} m={m} n={n}", "delta", m, n, gen, 0.0, scopes, candidate=same()))
    for delta in (0.05, 0.10):
        for a, b in [(4, 2), (20, 1)]:
            truth = shift_truth(a, b, delta)
            for m in (20, 50):
                for n in (5, 10):
                    add(Setting(f"D4 shift +{delta} Beta({a},{b}) m={m} n={n}", "delta", m, n, beta_rates(a, b),
                                truth, both, candidate=shift(delta)))
    for m in (20, 50):
        add(Setting(f"D5 two-way churn m={m} n=5", "delta", m, 5, mixture_rates({1.0: 0.8, 0.0: 0.2}), 0.0,
                    ("population",), candidate=churn(0.5, 0.125)))
    add(Setting("D6 unequal n shift +0.1 Beta(4,2) m=30", "delta", 30, (1, 3, 10), beta_rates(4, 2),
                shift_truth(4, 2, 0.10), both, candidate=shift(0.10)))
    for r in (0.5, 0.8):
        add(Setting(f"V1 sticky r={r} Beta(4,2) m=30 n=5", "rate", 30, 5, beta_rates(4, 2), 4 / 6, both,
                    gated={"suite": False, "population": True}, sticky=r))
    add(Setting("V2 batch shock sd=0.3 null Beta(4,2) m=30 n=5", "delta", 30, 5, beta_rates(4, 2), 0.0, both,
                gated={"suite": False, "population": False}, candidate=same(), shock_sd=0.3))
    return _drop_population_delta(S)


def _drop_population_delta(settings: list[Setting]) -> list[Setting]:
    """Amendment 1: the population-scope delta is not shipped, so it is not re-run."""
    kept = []
    for s in settings:
        if s.kind == "delta":
            s.scopes = tuple(sc for sc in s.scopes if sc != "population")
            s.gated = {sc: g for sc, g in s.gated.items() if sc != "population"}
        if s.scopes:
            kept.append(s)
    return kept


# ---------------------------------------------------------------- runner

def run_setting(s: Setting, reps: int, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    acc = {sc: {"cover": 0, "miss_low": 0, "miss_high": 0, "width": 0.0, "excl0": 0} for sc in s.scopes}
    for _ in range(reps):
        pa = s.rates(rng, s.m)
        trials = trial_counts(rng, s.m, s.n)
        max_n = int(np.max(trials))
        shocks_a = rng.normal(0.0, s.shock_sd, size=max_n) if s.shock_sd > 0 else None
        oa = simulate_trials(rng, pa, trials, s.sticky, shocks_a)
        if s.kind == "delta":
            pb = s.candidate(rng, pa)
            shocks_b = rng.normal(0.0, s.shock_sd, size=max_n) if s.shock_sd > 0 else None
            ob = simulate_trials(rng, pb, trials, s.sticky, shocks_b)
        for sc in s.scopes:
            if s.kind == "rate":
                iv = pass_rate_interval(oa, scope=sc)
                truth = float(pa.mean()) if sc == "suite" else s.pop_truth
            else:
                iv = delta_interval(oa, ob, scope=sc)
                truth = float(np.mean(pb - pa)) if sc == "suite" else s.pop_truth
            a = acc[sc]
            if truth < iv.low:
                a["miss_low"] += 1
            elif truth > iv.high:
                a["miss_high"] += 1
            else:
                a["cover"] += 1
            a["width"] += iv.high - iv.low
            a["excl0"] += not iv.contains(0.0)
    rows = []
    for sc, a in acc.items():
        cov = a["cover"] / reps
        gated = s.gated[sc]
        rows.append({
            "setting": s.id, "scope": sc, "kind": s.kind, "gated": gated, "note": s.note,
            "pop_truth": s.pop_truth, "coverage": cov,
            "miss_low": a["miss_low"] / reps, "miss_high": a["miss_high"] / reps,
            "mean_width": a["width"] / reps, "excludes_zero": a["excl0"] / reps,
            "passes_gate": (cov >= GATE) if gated else None,
        })
    return rows


def to_markdown(rows: list[dict], meta: dict) -> str:
    lines = [f"# Calibration grid, seed base {meta['seed_base']}, {meta['reps']} reps", "",
             f"Gate: coverage >= {GATE} on gated rows. Gated rows failing: {meta['gated_failures']}. "
             "Population delta: not shipped in v0.1, width rule final at seed base 20261116.", "",
             "| setting | scope | gated | coverage | miss low | miss high | mean width | excludes 0 | note |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        flag = "yes" if r["gated"] else "no"
        if r["gated"] and not r["passes_gate"]:
            flag = "**FAIL**"
        lines.append(f"| {r['setting']} | {r['scope']} | {flag} | {r['coverage']:.3f} | {r['miss_low']:.3f} | "
                     f"{r['miss_high']:.3f} | {r['mean_width']:.3f} | {r['excludes_zero']:.3f} | {r['note']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="50 reps, seed base 1, output not evidence")
    ap.add_argument("--out", type=Path, default=None, help="output directory (default results/ or a temp dir for smoke)")
    args = ap.parse_args(argv)
    reps, base = (50, 1) if args.smoke else (REPS, SEED_BASE)
    out_dir = args.out or (Path("results") if not args.smoke else Path("smoke_results"))
    stem = f"calibration_grid_{base}"
    if not args.smoke and any((out_dir / f"{stem}{ext}").exists() for ext in (".json", ".md")):
        print(f"refusing to overwrite {out_dir / stem}.*", file=sys.stderr)
        return 1
    settings = build_settings()
    rows: list[dict] = []
    t0 = time.time()
    for i, s in enumerate(settings):
        rows.extend(run_setting(s, reps, base + i))
        print(f"[{i + 1}/{len(settings)}] {s.id} ({time.time() - t0:.0f}s)", file=sys.stderr)
    failures = [f"{r['setting']} [{r['scope']}]" for r in rows if r["gated"] and not r["passes_gate"]]
    meta = {"seed_base": base, "reps": reps, "smoke": args.smoke, "n_settings": len(settings),
            "gated_failures": len(failures), "failures": failures}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=1), encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(to_markdown(rows, meta), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
