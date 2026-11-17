"""Download and check the tau2-bench leaderboard files named in PROTOCOL.md, and pin them in a manifest.

Writes, under examples/tau2_leaderboard/data/ (git-ignored, not redistributed):
  <submission>.submission.json, <submission>.airline.results.json, <submission>.airline.seeds.json
The seeds file holds only (task_id, trial, seed) read from each simulation file; trajectories are not kept.
Writes examples/tau2_leaderboard/manifest.json (committed before the analysis): full SHA-256 of every file
above and the fetch time. Asserts every filter and every recorded difference in PROTOCOL.md and exits
non-zero if any fails. Prints no reward.

Usage: python examples/tau2_leaderboard/fetch_data.py
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

BUCKET = "https://sierra-tau-bench-public.s3.us-west-2.amazonaws.com/submissions"
SUBMISSIONS = {
    "A": "claude-opus-4-5_sierra_2026-02-26",
    "B": "claude-sonnet-4-5_sierra_2026-02-26",
    "C": "gpt-5-2_sierra_2026-02-26",
    "D": "gpt-5-2-none_sierra_2026-02-26",
}
COMMON = {"tau2_version": "1.0.1", "git_commit": "7324fb57cb6819e77937c79964db916f5b068e31",
          "user_llm": "gpt-5.2", "user_reasoning_effort": "low", "seed": 300, "num_trials": 4}
N_TASKS = 50
# Recorded differences (PROTOCOL.md, Data); a change in any of them stops the script.
RECORDED = {
    "A": {"evaluation_date": "2026-05-05", "label_reasoning": "high", "agent_reasoning_effort": "high",
          "agent_temperature": None},
    "B": {"evaluation_date": "2026-02-24", "label_reasoning": "enabled", "agent_reasoning_effort": None,
          "agent_temperature": 0.0},
    "C": {"evaluation_date": "2026-05-05", "label_reasoning": "high", "agent_reasoning_effort": "high",
          "agent_temperature": None},
    "D": {"evaluation_date": "2026-05-26", "label_reasoning": "none", "agent_reasoning_effort": "medium",
          "agent_temperature": None},
}
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
MANIFEST = HERE / "manifest.json"


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        body = r.read()
        return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body


def fail(msg: str) -> None:
    print(f"check failed: {msg}", file=sys.stderr)
    raise SystemExit(1)


def task_key(t: str):
    return (0, int(t), "") if str(t).isdigit() else (1, 0, str(t))


def main() -> int:
    if MANIFEST.exists():
        fail(f"{MANIFEST.name} exists; the data were already fetched and pinned")
    DATA.mkdir(exist_ok=True)
    task_sets, seed_maps, files = {}, {}, {}
    for label, sub in SUBMISSIONS.items():
        meta_raw = get(f"{BUCKET}/{sub}/submission.json")
        res_raw = get(f"{BUCKET}/{sub}/trajectories/airline/results.json")
        meta, res = json.loads(meta_raw), json.loads(res_raw)
        info = res.get("info", {})
        user = info.get("user_info", {}) or {}
        agent_args = ((info.get("agent_info", {}) or {}).get("llm_args") or {})
        found = {
            "tau2_version": (meta.get("methodology") or {}).get("tau2_bench_version"),
            "git_commit": info.get("git_commit"),
            "user_llm": user.get("llm"),
            "user_reasoning_effort": (user.get("llm_args") or {}).get("reasoning_effort"),
            "seed": info.get("seed"),
            "num_trials": info.get("num_trials"),
        }
        for key, value in found.items():
            if value != COMMON[key]:
                fail(f"{label} {key} = {value!r}, expected {COMMON[key]!r}")
        recorded = {
            "evaluation_date": (meta.get("methodology") or {}).get("evaluation_date"),
            "label_reasoning": meta.get("reasoning_effort"),
            "agent_reasoning_effort": agent_args.get("reasoning_effort"),
            "agent_temperature": agent_args.get("temperature"),
        }
        for key, value in recorded.items():
            if value != RECORDED[label][key]:
                fail(f"{label} recorded difference {key} = {value!r}, expected {RECORDED[label][key]!r}")
        idx = res["simulation_index"]
        pairs = [(str(x["task_id"]), x["trial"]) for x in idx]
        if len(pairs) != len(set(pairs)):
            fail(f"{label} has a repeated (task, trial)")
        tasks = {t for t, _ in pairs}
        if len(tasks) != N_TASKS or any(sorted(tr for t2, tr in pairs if t2 == t) != [0, 1, 2, 3] for t in tasks):
            fail(f"{label} does not have trials 0-3 for exactly {N_TASKS} tasks")
        seeds = []
        for x in idx:
            sim = json.loads(get(f"{BUCKET}/{sub}/trajectories/airline/simulations/{x['id']}.json"))
            if str(sim.get("task_id")) != str(x["task_id"]) or sim.get("trial") != x["trial"]:
                fail(f"{label} simulation {x['id']} does not match its index entry")
            seed = sim.get("seed")
            if not isinstance(seed, int) or isinstance(seed, bool):
                fail(f"{label} simulation {x['id']} has seed {seed!r}, not an integer")
            seeds.append([str(x["task_id"]), x["trial"], seed])
        seeds.sort(key=lambda r: (task_key(r[0]), r[1]))
        seeds_raw = json.dumps(seeds).encode("utf-8")
        task_sets[label], seed_maps[label] = frozenset(tasks), seeds_raw
        out = {"submission": f"{sub}.submission.json", "results": f"{sub}.airline.results.json",
               "seeds": f"{sub}.airline.seeds.json"}
        for kind, raw in (("submission", meta_raw), ("results", res_raw), ("seeds", seeds_raw)):
            (DATA / out[kind]).write_bytes(raw)
            files[out[kind]] = hashlib.sha256(raw).hexdigest()
        print(f"{label} {sub}: checks passed, {len(tasks)} tasks x 4 trials")
    if len(set(task_sets.values())) != 1:
        fail("the submissions do not share one task set")
    if len(set(seed_maps.values())) != 1:
        fail("the submissions do not share one per-(task, trial) seed map")
    manifest = {"fetched_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "bucket": BUCKET, "submissions": SUBMISSIONS, "sha256": files}
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"all checks passed; manifest written to {MANIFEST.name} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
