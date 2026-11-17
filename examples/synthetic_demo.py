"""Synthetic demo: no model, no API cost, fixed seeds.

A simulated agent with 40 cases, most of which pass nearly every time (case pass rates drawn from
Beta(20, 1), mean about 0.95), each run 5 times. The script

1. writes three result files: a baseline run, a re-run of the same agent (noise only), and a
   candidate in which 3 cases now fail every time (a regression), then runs `realdelta compare`
   on baseline vs re-run and baseline vs regression, and `realdelta plan` for that regression;
2. repeats the noise-only comparison 500 times: how far the pass rate moves, and how often
   `compare` flags a change;
3. repeats the regression comparison 500 times: how often the interval excludes 0, and how often
   the sign-flip p-value is below 0.05.

Run from the repository root:

    python examples/synthetic_demo.py [OUTPUT_DIR]     # default: examples/synthetic

SEED = 20261119 was the first and only seed used. The three random streams (case pass rates, trial
outcomes, which cases break) are spawned from it independently. Files are written with LF line
endings, so the transcript is byte-identical across platforms for the same numpy version, which is
recorded in the transcript.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from realdelta import SimulatedSuite, compare, macro_pass_rate  # noqa: E402
from realdelta.cli import main as cli  # noqa: E402
from realdelta.planner import break_cases  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent / "synthetic"
CASES, TRIALS, BROKEN, REPEATS = 40, 5, 3, 500
SEED = 20261119


def write_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_jsonl(path: Path, outcomes: dict[str, list[bool]]) -> None:
    lines = [json.dumps({"case_id": case, "passed": bool(p)}) for case, runs in outcomes.items() for p in runs]
    write_text(path, "\n".join(lines) + "\n")


def run_cli(argv: list[str], cwd_label: str) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli(argv)
    if code != 0:
        raise RuntimeError(f"realdelta {' '.join(argv)} exited with {code}: {err.getvalue()}")
    text = f"$ python -m realdelta {' '.join(argv)}    # cwd: {cwd_label}\n{out.getvalue()}"
    if err.getvalue():
        text += "[stderr]\n" + err.getvalue()
    return text


def passes(outcomes: dict[str, list[bool]]) -> int:
    return sum(sum(runs) for runs in outcomes.values())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out_dir = Path(argv[0]) if argv else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    suite_seq, trial_seq, break_seq = np.random.SeedSequence(SEED).spawn(3)
    rng = np.random.default_rng(trial_seq)
    agent = SimulatedSuite.from_beta(CASES, 20.0, 1.0, seed=int(suite_seq.generate_state(1)[0]))
    regressed = break_cases(agent, BROKEN, np.random.default_rng(break_seq))
    total = CASES * TRIALS

    files = {"baseline.jsonl": agent.run(TRIALS, rng), "rerun.jsonl": agent.run(TRIALS, rng),
             "regression.jsonl": regressed.run(TRIALS, rng)}
    for name, outcomes in files.items():
        write_jsonl(out_dir / name, outcomes)

    report = [f"# Synthetic demo, seed {SEED}, numpy {np.__version__}", "",
              "Commands run from the directory holding the result files, with the repository's src on PYTHONPATH.",
              f"Simulated agent: {CASES} cases, {TRIALS} trials each, case pass rates from Beta(20, 1).",
              f"True pass rate: {agent.true_macro_rate:.5f}. Regression: {BROKEN} cases set to rate 0, "
              f"true change {regressed.true_macro_rate - agent.true_macro_rate:+.5f}.", "",
              "Observed pass rates: " + ", ".join(f"{n} {macro_pass_rate(o):.3f}" for n, o in files.items()), ""]
    here = os.getcwd()
    os.chdir(out_dir)  # contextlib.chdir needs Python 3.11; the package supports 3.10
    try:
        report.append(run_cli(["compare", "baseline.jsonl", "rerun.jsonl"], "examples/synthetic"))
        report.append(run_cli(["compare", "baseline.jsonl", "regression.jsonl"], "examples/synthetic"))
    finally:
        os.chdir(here)
    report.append(run_cli(["plan", "--cases", str(CASES), "--break-cases", str(BROKEN), "--trials", "1,3,5,10",
                           "--alpha", "20", "--beta", "1", "--seed", str(SEED)], "any"))

    # Noise only: the same agent run twice. Equal trials, so pass-rate moves are multiples of 1/200;
    # thresholds are compared on pass counts (2 points = 4 passes) to avoid float edges.
    moves, flagged, null_p_low = [], 0, 0
    for _ in range(REPEATS):
        a, b = agent.run(TRIALS, rng), agent.run(TRIALS, rng)
        moves.append(abs(passes(b) - passes(a)))
        result = compare(a, b, seed=0)
        flagged += result.detected
        null_p_low += result.p_value < 0.05
    moves = np.array(moves)
    two, four = int(np.sum(moves >= round(0.02 * total))), int(np.sum(moves >= round(0.04 * total)))
    q95 = float(np.quantile(moves, 0.95)) / total
    report += [f"Noise only, {REPEATS} pairs of runs of the same agent (truth: no change):",
               f"  pass rate moved by 2 points or more: {two}/{REPEATS} = {two / REPEATS:.3f}",
               f"  pass rate moved by 4 points or more: {four}/{REPEATS} = {four / REPEATS:.3f}",
               f"  95th percentile of the move: {q95 * 100:.1f} points",
               f"  compare flagged a change:            {flagged}/{REPEATS} = {flagged / REPEATS:.3f}",
               f"  sign-flip p-value below 0.05:        {null_p_low}/{REPEATS} = {null_p_low / REPEATS:.3f}", ""]

    # Regression: baseline vs candidate with the same 3 cases broken, fresh trials each time.
    detected = p_low = 0
    for _ in range(REPEATS):
        result = compare(agent.run(TRIALS, rng), regressed.run(TRIALS, rng), seed=0)
        detected += result.detected
        p_low += result.p_value < 0.05
    report += [f"Regression ({BROKEN} cases broken), {REPEATS} pairs of runs:",
               f"  interval excludes 0 (detected): {detected}/{REPEATS} = {detected / REPEATS:.3f}",
               f"  sign-flip p-value below 0.05:   {p_low}/{REPEATS} = {p_low / REPEATS:.3f}", ""]

    text = "\n".join(report)
    write_text(out_dir / "transcript.txt", text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
