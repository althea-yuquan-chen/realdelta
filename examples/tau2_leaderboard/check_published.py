"""Post-hoc check, added after the analysis (PROTOCOL.md, Amendment 2): do the pinned airline results reproduce
the scores the leaderboard publishes for each submission?

For each submission, computes pass^k (k = 1..4): the mean over tasks of C(c, k) / C(4, k), as in tau2-bench's
`pass_hat_k` (src/tau2/metrics/agent_metrics.py, read at commit c06b07d; the runs' commit 7324fb57 is not in the
public repository). Success there is a reward within 1e-6 of 1; rewards here are asserted to be exactly 0 or 1.
tau2-bench also drops infrastructure-error simulations before scoring; this script drops nothing.
pass^k is computed from <submission>.airline.results.json and compared with results.airline.pass_<k> in
<submission>.submission.json.
Both files must match manifest.json. Writes examples/tau2_leaderboard/posthoc_published_scores.md and refuses to
overwrite it, to run on a dirty tree, or on files that do not match the manifest. This check is not part of the
pre-registered analysis and changes none of its outputs.

Usage: python examples/tau2_leaderboard/check_published.py
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = HERE / "data"
OUT = HERE / "posthoc_published_scores.md"
LABELS = {
    "A": "claude-opus-4-5_sierra_2026-02-26",
    "B": "claude-sonnet-4-5_sierra_2026-02-26",
    "C": "gpt-5-2_sierra_2026-02-26",
    "D": "gpt-5-2-none_sierra_2026-02-26",
}
# Tolerance in percentage points. Published values are rounded to 2 decimals (error <= 0.005) or given in full;
# the smallest possible difference between two pass^k values here is 1/3 point (pass^2), so 0.01 neither
# misses a one-trial difference nor rejects a rounded value.
TOL = 0.01


def read_pinned(name: str, manifest: dict) -> dict:
    raw = (DATA / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"].get(name):
        raise SystemExit(f"{name} does not match manifest.json")
    return json.loads(raw)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    if OUT.exists():
        print(f"refusing to overwrite {OUT.name}", file=sys.stderr)
        return 1
    if git("status", "--porcelain"):
        print("refusing to run: the working tree is not clean", file=sys.stderr)
        return 1
    commit = git("rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        print(f"refusing to run: commit {commit!r} is not a full hash", file=sys.stderr)
        return 1
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for label, sub in LABELS.items():
        res = read_pinned(f"{sub}.airline.results.json", manifest)
        meta = read_pinned(f"{sub}.submission.json", manifest)
        succ: dict[str, list[bool]] = {}
        for x in res["simulation_index"]:
            if x["reward"] not in (0.0, 1.0):
                raise SystemExit(f"{label}: reward {x['reward']!r} is not 0 or 1")
            succ.setdefault(str(x["task_id"]), []).append(x["reward"] == 1.0)
        if len(succ) != 50 or any(len(v) != 4 for v in succ.values()):
            raise SystemExit(f"{label}: not 50 tasks x 4 trials")
        published = (meta.get("results") or {}).get("airline")
        if not isinstance(published, dict) or any(f"pass_{k}" not in published for k in range(1, 5)):
            raise SystemExit(f"{label}: submission.json has no results.airline.pass_1..pass_4")
        for k in range(1, 5):
            ours = 100 * sum(comb(sum(v), k) / comb(4, k) for v in succ.values()) / len(succ)
            pub = float(published[f"pass_{k}"])
            rows.append((label, sub, k, ours, pub, abs(ours - pub) <= TOL))
    lines = ["# Do the pinned airline results reproduce the published scores? (post-hoc, PROTOCOL.md Amendment 2)", "",
             "pass^k in percent: computed from `<submission>.airline.results.json` (pinned by manifest.json) vs "
             "`results.airline.pass_k` in `<submission>.submission.json`. Not part of the pre-registered analysis.", "",
             f"Run at commit {commit}; data fetched {manifest['fetched_at_utc']} (manifest.json).", "",
             "| submission | k | from results.json | published | reproduced |", "|---|---|---|---|---|"]
    for label, sub, k, ours, pub, ok in rows:
        lines.append(f"| {label} {sub} | {k} | {ours:.2f} | {pub:.2f} | {'yes' if ok else 'no'} |")
    text = "\n".join(lines) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
