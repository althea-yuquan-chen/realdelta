"""Run the pre-registered Haiku demo (examples/haiku/PROTOCOL.md).

    python examples/haiku/run_demo.py --dry-run          # counts, price constants, cost bounds; no API calls
    python examples/haiku/run_demo.py RUN_DIR            # preflight, then the 600-call run

Needs `pip install anthropic` and an API key in the environment (read by the SDK; never passed here).
Writes RUN_DIR/{preflight,responses}.jsonl, a1/a2/b.jsonl (realdelta result files), summary.txt and
provenance.txt. An aborted run writes ABORTED.txt with the reason and keeps everything written so far.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 2048
EFFORT = "low"
TIMEOUT_S = 120
TRIALS = 5
ORDER_SEED = 20261121
USD_PER_M_INPUT, USD_PER_M_OUTPUT = 0.10, 0.50
LIMIT_REISSUES, LIMIT_OUTPUT_TOKENS, LIMIT_USD = 60, 1_400_000, 1.00
BACKOFF_S = (2, 4, 8, 16, 32)

S0 = ("You are solving a short puzzle. Work it out, then give the final answer on the last line in the "
      "form ANSWER: <value>.")
S1 = S0 + " Answer immediately; do not show your working."
ARMS = {"a1": S0, "a2": S0, "b": S1}
PREFLIGHT_USER = "What is 17 + 25?\n\nGive the answer in this form: an integer."

CATEGORIES = ("pass", "wrong_value", "no_answer_line", "empty", "max_tokens", "refusal", "timeout")
_ANSWER = re.compile(r"ANSWER:\s*(.+)")


# ---------------------------------------------------------------- grading

def grade(text: str, stop_reason: str | None, expected: str, family: str) -> str:
    """One category per trial, first match in the protocol's order (PROTOCOL.md, Grading)."""
    if stop_reason == "timeout":
        return "timeout"
    if stop_reason == "refusal":
        return "refusal"
    if stop_reason == "max_tokens":
        return "max_tokens"
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "empty"
    last = lines[-1].replace("*", "").replace("`", "").strip()
    match = _ANSWER.fullmatch(last)  # anchored: the whole line must be "ANSWER: <value>"
    if not match:
        return "no_answer_line"
    value = match.group(1).strip()
    if value.endswith("."):
        value = value[:-1].rstrip()
    if family == "sort":
        value, expected = value.replace(" ", ""), expected.replace(" ", "")
    if family == "weekday":
        value, expected = value.lower(), expected.lower()
    return "pass" if value == expected else "wrong_value"


# ---------------------------------------------------------------- schedule

def build_schedule(tasks: list[dict], seed: int = ORDER_SEED) -> list[tuple[str, str, int]]:
    """Every (case, arm, trial) exactly once, in one seeded random order."""
    calls = [(t["case_id"], arm, trial) for t in tasks for arm in ARMS for trial in range(TRIALS)]
    order = np.random.default_rng(seed).permutation(len(calls))
    return [calls[i] for i in order]


# ---------------------------------------------------------------- running

class Abort(Exception):
    pass


@dataclass
class Totals:
    input_tokens: int = 0
    output_tokens: int = 0
    reissues: int = 0
    calls: int = 0

    @property
    def usd(self) -> float:
        return self.input_tokens / 1e6 * USD_PER_M_INPUT + self.output_tokens / 1e6 * USD_PER_M_OUTPUT


@dataclass
class Runner:
    """``create(system, user) -> response``; ``classify(exc) -> 'retry' | 'timeout' | 'abort'``."""

    create: Callable
    classify: Callable
    sleep: Callable = time.sleep
    totals: Totals = field(default_factory=Totals)
    max_input_per_call: int = 2000

    def _check_limits(self) -> None:
        worst_out = self.totals.output_tokens + MAX_TOKENS
        worst_usd = self.totals.usd + (self.max_input_per_call * USD_PER_M_INPUT + MAX_TOKENS * USD_PER_M_OUTPUT) / 1e6
        if worst_out > LIMIT_OUTPUT_TOKENS:
            raise Abort(f"output-token limit: {self.totals.output_tokens} used, next call could exceed {LIMIT_OUTPUT_TOKENS}")
        if worst_usd > LIMIT_USD:
            raise Abort(f"cost limit: ${self.totals.usd:.4f} used, next call could exceed ${LIMIT_USD:.2f}")

    def call(self, system: str, user: str) -> dict:
        """One trial. Returns a record with text, stop_reason, usage and re-issue count."""
        attempt = 0
        while True:
            self._check_limits()
            try:
                response = self.create(system, user)
            except Exception as exc:  # classified below; nothing about the exception is stored but its class
                kind = self.classify(exc)
                if kind == "timeout":
                    return {"text": "", "stop_reason": "timeout", "input_tokens": 0, "output_tokens": 0,
                            "reissues": attempt, "model": None}
                if kind != "retry":
                    raise Abort(f"non-retryable API error: {_describe(exc)}") from None
                if attempt >= len(BACKOFF_S) or self.totals.reissues >= LIMIT_REISSUES:
                    raise Abort(f"re-issue limit reached ({_describe(exc)})") from None
                self.sleep(BACKOFF_S[attempt])
                attempt += 1
                self.totals.reissues += 1
                continue
            usage = response.usage
            self.totals.input_tokens += usage.input_tokens
            self.totals.output_tokens += usage.output_tokens
            self.totals.calls += 1
            texts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            return {"text": texts[-1] if texts else "", "stop_reason": response.stop_reason,
                    "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                    "reissues": attempt, "model": getattr(response, "model", None)}


def _describe(exc: Exception) -> str:
    """Class name, HTTP status and the API's error type (a fixed enum). Never the message or headers."""
    parts = [type(exc).__name__]
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        parts.append(f"status {status}")
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        kind = body["error"].get("type")
        if isinstance(kind, str) and kind.replace("_", "").isalnum() and len(kind) <= 60:
            parts.append(f"type {kind}")
    return ", ".join(parts)


def _append(path: Path, record: dict) -> None:
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run(tasks: list[dict], runner: Runner, out: Path) -> dict:
    """Preflight, then every scheduled call. Returns per-arm categories and outcomes."""
    out.mkdir(parents=True, exist_ok=False)
    for name in ("s0", "s1"):
        rec = runner.call(S0 if name == "s0" else S1, PREFLIGHT_USER)
        _append(out / "preflight.jsonl", {"system": name, **rec})
        if rec["stop_reason"] == "timeout":
            raise Abort("preflight timed out")
    by_id = {t["case_id"]: t for t in tasks}
    outcomes = {arm: {} for arm in ARMS}
    categories = {arm: {c: 0 for c in CATEGORIES} for arm in ARMS}
    for index, (case_id, arm, trial) in enumerate(build_schedule(tasks)):
        task = by_id[case_id]
        rec = runner.call(ARMS[arm], task["user"])
        category = grade(rec["text"], rec["stop_reason"], task["answer"], task["family"])
        categories[arm][category] += 1
        outcomes[arm].setdefault(case_id, {})[trial] = category == "pass"
        _append(out / "responses.jsonl", {"order": index, "case_id": case_id, "arm": arm, "trial": trial,
                                          "category": category, **rec})
    models = sorted({json.loads(l)["model"] or "" for l in (out / "preflight.jsonl").read_text(encoding="utf-8").splitlines()})
    return {"outcomes": outcomes, "categories": categories, "model_returned": ", ".join(models)}


def write_results(tasks: list[dict], result: dict, out: Path) -> None:
    for arm, per_case in result["outcomes"].items():
        lines = [json.dumps({"case_id": t["case_id"], "passed": per_case[t["case_id"]][trial], "trial": trial})
                 for t in tasks for trial in range(TRIALS)]
        _write(out / f"{arm}.jsonl", "\n".join(lines) + "\n")


def analysis(out: Path) -> str:
    from realdelta.cli import main as cli

    commands = [["interval", "a1.jsonl", "--json"], ["interval", "a2.jsonl", "--json"],
                ["interval", "b.jsonl", "--json"], ["interval", "a1.jsonl", "--scope", "population", "--json"],
                ["compare", "a1.jsonl", "a2.jsonl", "--seed", "0", "--n-perm", "10000", "--conf", "0.95", "--json"],
                ["compare", "a1.jsonl", "b.jsonl", "--seed", "0", "--n-perm", "10000", "--conf", "0.95", "--json"]]
    parts, here = [], Path.cwd()
    import os
    os.chdir(out)
    try:
        for argv in commands:
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = cli(argv)
            text = f"$ python -m realdelta {' '.join(argv)}\n{buf.getvalue()}"
            if err.getvalue():
                text += "[stderr]\n" + err.getvalue()
            parts.append(text + f"(exit {code})\n")
    finally:
        os.chdir(here)
    return "\n".join(parts)


# ---------------------------------------------------------------- real client

def anthropic_runner() -> Runner:
    import anthropic

    client = anthropic.Anthropic(max_retries=0, timeout=TIMEOUT_S)

    def create(system: str, user: str):
        return client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, output_config={"effort": EFFORT},
                                      system=system, messages=[{"role": "user", "content": user}])

    def classify(exc: Exception) -> str:
        if isinstance(exc, anthropic.APITimeoutError):
            return "timeout"
        if isinstance(exc, anthropic.APIConnectionError):
            return "retry"
        if isinstance(exc, anthropic.APIStatusError) and (exc.status_code == 429 or exc.status_code >= 500):
            return "retry"
        return "abort"

    return Runner(create=create, classify=classify)


def load_tasks(path: Path = HERE / "tasks.jsonl") -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    tasks = load_tasks()
    calls = len(build_schedule(tasks))
    if args.dry_run or not args.run_dir:
        print(f"model {MODEL}, effort {EFFORT}, max_tokens {MAX_TOKENS}, timeout {TIMEOUT_S}s")
        print(f"calls: {calls} + 2 preflight; price constants ${USD_PER_M_INPUT}/M input, ${USD_PER_M_OUTPUT}/M output")
        print(f"cost at 300 input / 500 output tokens per call: ${(calls + 2) * (300 * USD_PER_M_INPUT + 500 * USD_PER_M_OUTPUT) / 1e6:.3f}")
        print(f"cost if every call used {MAX_TOKENS} output tokens: ${(calls + 2) * (300 * USD_PER_M_INPUT + MAX_TOKENS * USD_PER_M_OUTPUT) / 1e6:.3f}")
        print(f"limits: {LIMIT_REISSUES} re-issues, {LIMIT_OUTPUT_TOKENS} output tokens, ${LIMIT_USD:.2f}")
        return 0
    out = Path(args.run_dir)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip())
    if dirty:
        print("refusing to run: the working tree is not clean (the commit would not match the code)", file=sys.stderr)
        return 1
    runner = anthropic_runner()
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        result = run(tasks, runner, out)
    except (Abort, KeyboardInterrupt) as exc:
        reason = str(exc) if isinstance(exc, Abort) else "interrupted by the operator"
        _write(out / "ABORTED.txt", f"{reason}\ncalls completed: {runner.totals.calls}, re-issues: {runner.totals.reissues}, "
                                    f"estimated cost ${runner.totals.usd:.4f}\n")
        print(f"aborted: {reason}", file=sys.stderr)
        return 1
    write_results(tasks, result, out)
    import anthropic

    t = runner.totals
    lines = [f"Haiku demo run (examples/haiku/PROTOCOL.md)", "",
             f"calls {t.calls} (incl. 2 preflight), re-issues {t.reissues}, input tokens {t.input_tokens}, "
             f"output tokens {t.output_tokens}, estimated cost ${t.usd:.4f}", "",
             "Categories per arm: " + ", ".join(CATEGORIES)]
    for arm, cats in result["categories"].items():
        lines.append(f"  {arm}: " + ", ".join(str(cats[c]) for c in CATEGORIES))
    _write(out / "summary.txt", "\n".join(lines) + "\n\n" + analysis(out))
    _write(out / "provenance.txt", "\n".join([
        f"commit: {commit}", f"started: {started}", f"finished: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"model requested: {MODEL}", f"model returned: {result['model_returned']}",
        f"anthropic SDK: {anthropic.__version__}", f"python: {platform.python_version()}",
        f"numpy: {np.__version__}"]) + "\n")
    print((out / "summary.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
