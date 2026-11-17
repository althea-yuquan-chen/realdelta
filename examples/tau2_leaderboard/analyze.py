"""Run the pre-registered analysis in PROTOCOL.md once and write its outputs.

Reads the files written by fetch_data.py and checks them against the committed manifest.json. Writes
examples/tau2_leaderboard/run_<seed>/ (summary.md, summary.json). Refuses to overwrite them, to run on a
dirty tree or outside git, to run with a realdelta other than 0.1.1 from this repository's src/, or to
run on files that do not match the manifest.

Usage: python examples/tau2_leaderboard/analyze.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

import realdelta
from realdelta import compare, pass_rate_interval

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = HERE / "data"
REALDELTA_VERSION = "0.1.1"
PERM_SEED = 20261123
N_PERM = 10_000
LABELS = {
    "A": "claude-opus-4-5_sierra_2026-02-26",
    "B": "claude-sonnet-4-5_sierra_2026-02-26",
    "C": "gpt-5-2_sierra_2026-02-26",
    "D": "gpt-5-2-none_sierra_2026-02-26",
}
PRIMARY = ("A", "C")
NOTES = {  # asserted against the metadata by fetch_data.py (RECORDED)
    "A": "evaluated 2026-05-05",
    "B": "evaluated 2026-02-24; metadata fields disagree (label reasoning 'enabled', run arguments give "
         "temperature 0.0 and no reasoning setting)",
    "C": "evaluated 2026-05-05",
    "D": "evaluated 2026-05-26; metadata fields disagree (label reasoning 'none', run arguments say 'medium')",
}
NEWLINE = chr(10)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def load(label: str, manifest: dict) -> dict[str, list[bool]]:
    name = f"{LABELS[label]}.airline.results.json"
    raw = (DATA / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"].get(name):
        raise SystemExit(f"{name} does not match manifest.json")
    out: dict[str, list] = {}
    for x in json.loads(raw)["simulation_index"]:
        if x["reward"] not in (0.0, 1.0):
            raise SystemExit(f"{label}: reward {x['reward']!r} is not 0 or 1")
        row = out.setdefault(str(x["task_id"]), [None] * 4)
        if row[x["trial"]] is not None:
            raise SystemExit(f"{label}: repeated (task, trial)")
        row[x["trial"]] = x["reward"] == 1.0
    if any(None in v for v in out.values()) or len(out) != 50:
        raise SystemExit(f"{label}: not 50 tasks with trials 0-3")
    return out


def residual_correlation(a: np.ndarray, b: np.ndarray) -> float | None:
    ra, rb = a - a.mean(axis=1, keepdims=True), b - b.mean(axis=1, keepdims=True)
    denom = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else None


def dependence_check(oa: dict, ob: dict) -> dict:
    tasks = sorted(oa)
    a = np.array([oa[t] for t in tasks], dtype=float)
    b = np.array([ob[t] for t in tasks], dtype=float)
    informative = int(np.sum((a.std(axis=1) > 0) & (b.std(axis=1) > 0)))
    observed = residual_correlation(a, b)
    if informative == 0 or observed is None:
        return {"computable": False, "informative_tasks": informative, "above_range": None}
    rng = np.random.default_rng(PERM_SEED)
    perm = []
    for _ in range(N_PERM):
        value = residual_correlation(a, np.array([row[rng.permutation(4)] for row in b]))
        if value is not None:
            perm.append(value)
    perm = np.array(perm)
    return {"computable": True, "informative_tasks": informative, "observed": observed,
            "perm_2.5": float(np.percentile(perm, 2.5)), "perm_97.5": float(np.percentile(perm, 97.5)),
            "p_one_sided": float((1 + np.sum(perm >= observed)) / (1 + len(perm))), "n_perm": int(len(perm)),
            "above_range": bool(observed > np.percentile(perm, 97.5))}


def main() -> int:
    out_dir = HERE / f"run_{PERM_SEED}"
    if out_dir.exists():
        print(f"refusing to overwrite {out_dir}", file=sys.stderr)
        return 1
    if realdelta.__version__ != REALDELTA_VERSION:
        print(f"refusing to run: realdelta {realdelta.__version__}, protocol fixes {REALDELTA_VERSION}", file=sys.stderr)
        return 1
    if Path(realdelta.__file__).resolve().parent != (REPO / "src" / "realdelta").resolve():
        print(f"refusing to run: realdelta imported from {realdelta.__file__}, not {REPO / 'src' / 'realdelta'}",
              file=sys.stderr)
        return 1
    if git("status", "--porcelain"):
        print("refusing to run: the working tree is not clean", file=sys.stderr)
        return 1
    commit = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        print(f"refusing to run: commit {commit!r} is not a full hash", file=sys.stderr)
        return 1
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    data = {label: load(label, manifest) for label in LABELS}
    if len({frozenset(d) for d in data.values()}) != 1:
        raise SystemExit("the submissions do not share one task set")
    per_sub = {}
    for label in LABELS:
        iv = pass_rate_interval(data[label], scope="suite")
        per_sub[label] = {"estimate": iv.estimate, "low": iv.low, "high": iv.high}
    pairs = [PRIMARY] + [p for p in combinations(LABELS, 2) if p != PRIMARY]
    comps = []
    for x, y in pairs:
        r = compare(data[x], data[y], seed=0)
        comps.append({"pair": f"{x} vs {y}", "role": "primary" if (x, y) == PRIMARY else "descriptive",
                      "delta": r.delta.estimate, "low": r.delta.low, "high": r.delta.high,
                      "detected": bool(r.detected), "p_value": r.p_value})
    dep = dependence_check(data[PRIMARY[0]], data[PRIMARY[1]])
    meta = {"commit": commit, "realdelta_version": realdelta.__version__, "manifest_fetched_at": manifest["fetched_at_utc"],
            "submissions": LABELS, "notes": NOTES, "perm_seed": PERM_SEED}
    lines = ["# tau2-bench airline leaderboard gaps (pre-registered in PROTOCOL.md)", "",
             f"Run at commit {commit}, realdelta {realdelta.__version__}; data fetched {manifest['fetched_at_utc']} "
             "(manifest.json). Suite scope, 95%. Submissions run by Sierra, not models: each row includes "
             "everything that differed in the runs.", "",
             "| submission | notes | pass rate | 95% interval |", "|---|---|---|---|"]
    for label in LABELS:
        s = per_sub[label]
        lines.append(f"| {label} {LABELS[label]} | {NOTES[label]} | {s['estimate']:.3f} | "
                     f"[{s['low']:.3f}, {s['high']:.3f}] |")
    lines += ["", "| pair (baseline vs candidate) | role | change | 95% interval | detected | sign-flip p |",
              "|---|---|---|---|---|---|"]
    for c in comps:
        lines.append(f"| {c['pair']} | {c['role']} | {c['delta']:+.3f} | [{c['low']:+.3f}, {c['high']:+.3f}] | "
                     f"{'yes' if c['detected'] else 'no'} | {c['p_value']:.4f} |")
    if dep["computable"]:
        lines += ["", f"Dependence check, primary pair {PRIMARY[0]} vs {PRIMARY[1]} (descriptive): residual correlation "
                  f"{dep['observed']:.3f}; permutation 2.5-97.5% range [{dep['perm_2.5']:.3f}, {dep['perm_97.5']:.3f}]; "
                  f"one-sided p {dep['p_one_sided']:.4f} ({dep['n_perm']} permutations); "
                  f"{dep['informative_tasks']} of 50 tasks vary in both arms."]
    else:
        lines += ["", f"Dependence check, primary pair {PRIMARY[0]} vs {PRIMARY[1]}: not computable "
                  f"({dep['informative_tasks']} of 50 tasks vary in both arms)."]
    if dep["computable"] and dep["above_range"]:
        dep_sentence = ("A positive correlation between the arms is visible in the primary pair; under positive "
                        "coupling the interval is expected to be conservative and low in power (Diagnostic AD).")
    elif dep["computable"]:
        dep_sentence = (f"No correlation between the arms was visible at this size ({dep['informative_tasks']} "
                        "informative tasks); if shared seeds couple the arms positively, the interval is conservative "
                        "and low in power; a negative coupling would make it too narrow (Diagnostic AD).")
    else:
        dep_sentence = ("The dependence check was not computable; if shared seeds couple the arms positively, the "
                        "interval is conservative and low in power; a negative coupling would make it too narrow "
                        "(Diagnostic AD).")
    lines += ["", "## How to read these numbers (fixed in PROTOCOL.md before the run)", "",
              "- Only the primary pair (A vs C) can give a finding; the five other pairs are descriptive.",
              "- 'detected' means the interval excludes 0. A run-level shock within one submission's run (assumption "
              "A5) cannot be measured here and raises a single pair's false-alarm rate to 0.085 (Diagnostic AD, X0) "
              "to 0.105 (grid V2); the primary pair shares an evaluation date, which does not rule it out.",
              f"- Dependence between the arms: {dep_sentence}",
              "- 'not detected' means not detected at this scale, not 'no difference'. Rows compare submissions run "
              "by Sierra, not models in general; no row ranks one submission above another."]
    md = NEWLINE.join(lines) + NEWLINE
    js = json.dumps({"meta": meta, "per_submission": per_sub, "comparisons": comps, "dependence": dep}, indent=1)
    out_dir.mkdir()
    (out_dir / "summary.md").write_text(md, encoding="utf-8")
    (out_dir / "summary.json").write_text(js, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
