"""Run the pre-registered real-model demo (examples/real_model/PROTOCOL.md, Amendment 1: GPT-5.6 Luna on
Azure OpenAI).

    python examples/real_model/run_demo.py --dry-run     # counts, price constants, cost bounds; no API calls
    python examples/real_model/run_demo.py RUN_DIR       # preflight, then the 600-call run

Needs `pip install openai` (or `pip install -e ".[demo]"`) and two environment variables set outside this
program: AZURE_OPENAI_API_KEY and AZURE_OPENAI_BASE_URL (https://<resource>.openai.azure.com/openai/v1/).
Their values are passed to the client and never printed, logged or written. Writes
RUN_DIR/{preflight,responses}.jsonl, a1/a2/b.jsonl (realdelta result files), summary.txt and
provenance.txt. An aborted run writes ABORTED.txt with the reason and keeps everything written so far.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
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

MODEL = "gpt-5.6-luna"  # the Azure deployment name (Global Standard), which the owner named after the model
ENV_KEY, ENV_BASE_URL = "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL"
MAX_OUTPUT_TOKENS = 2048
EFFORT = "low"
TIMEOUT_S = 120
TRIALS = 5
ORDER_SEED = 20261121
# Conservative: the older Azure rate some users report being billed, not the $0.20 / $1.20 announced.
USD_PER_M_INPUT, USD_PER_M_OUTPUT = 1.00, 6.00
LIMIT_REISSUES, LIMIT_OUTPUT_TOKENS, LIMIT_USD = 60, 1_400_000, 8.00
BACKOFF_S = (2, 4, 8, 16, 32)

S0 = ("You are solving a short puzzle. Work it out, then give the final answer on the last line in the "
      "form ANSWER: <value>.")
S1 = S0 + " Answer immediately; do not show your working."
ARMS = {"a1": S0, "a2": S0, "b": S1}
PREFLIGHT_USER = "What is 17 + 25?\n\nGive the answer in this form: an integer."

CATEGORIES = ("pass", "wrong_value", "no_answer_line", "empty", "incomplete_other", "max_tokens", "refusal",
              "timeout")
_ANSWER = re.compile(r"ANSWER:\s*(.+)")


# ---------------------------------------------------------------- grading

def grade(text: str, stop_reason: str | None, expected: str, family: str) -> str:
    """One category per trial, first match in the protocol's order (PROTOCOL.md, Grading; Amendment 1)."""
    for reason in ("timeout", "refusal", "max_tokens", "incomplete_other"):
        if stop_reason == reason:
            return reason
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


# ---------------------------------------------------------------- parsing an OpenAI Responses API response

def _completion_filtered(response) -> bool:
    """Azure adds a `content_filters` list; an entry blocking the completion counts as a refusal."""
    for entry in getattr(response, "content_filters", None) or []:
        get = entry.get if isinstance(entry, dict) else (lambda k, e=entry: getattr(e, k, None))
        if get("blocked") is True and get("source_type") == "completion":
            return True
    return False


class ServerSideFailure(Exception):
    """A response that is not an answer attempt (status failed / cancelled / queued / in_progress, or no
    usage): treated like a server error, i.e. re-issued, never graded (Amendment 1)."""

    def __init__(self, status, code):
        super().__init__(f"status {status}")
        self.status_value = status if isinstance(status, str) else None
        self.code = code if isinstance(code, str) else None


def parse_response(response) -> dict:
    """Text, stop reason and usage. Only message text is kept; reasoning items are ignored."""
    status = getattr(response, "status", None)
    if status not in ("completed", "incomplete") or getattr(response, "usage", None) is None:
        error = getattr(response, "error", None)
        raise ServerSideFailure(status, getattr(error, "code", None))
    texts, refused = [], False
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            kind = getattr(part, "type", None)
            if kind == "output_text":
                texts.append(part.text)
            elif kind == "refusal":
                refused = True
    reason = None
    if getattr(response, "status", None) == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None)
    if refused or reason == "content_filter" or _completion_filtered(response):
        stop = "refusal"
    elif reason == "max_output_tokens":
        stop = "max_tokens"
    elif getattr(response, "status", None) == "incomplete":
        stop = "incomplete_other"
    else:
        stop = "end_turn"
    usage = response.usage
    return {"text": "\n".join(texts), "stop_reason": stop, "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens, "model": getattr(response, "model", None),
            "content_filters_present": getattr(response, "content_filters", None) is not None}


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


def _describe(exc: Exception) -> str:
    """Class name, HTTP status and the API's error type (a fixed enum). Never the message or headers."""
    parts = [type(exc).__name__]
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        parts.append(f"status {status}")
    for attr in ("status_value", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 60:
            parts.append(f"{attr.replace('_value', '')} {value}")
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        kind = err.get("type") or err.get("code")
        if isinstance(kind, str) and kind.replace("_", "").isalnum() and len(kind) <= 60:
            parts.append(f"type {kind}")
    return ", ".join(parts)


@dataclass
class Runner:
    """``create(system, user) -> parsed record``; ``classify(exc) -> 'retry' | 'timeout' | 'abort'``."""

    create: Callable
    classify: Callable
    sleep: Callable = time.sleep
    totals: Totals = field(default_factory=Totals)
    max_input_per_call: int = 2000

    def _check_limits(self) -> None:
        worst_out = self.totals.output_tokens + MAX_OUTPUT_TOKENS
        worst_usd = self.totals.usd + (self.max_input_per_call * USD_PER_M_INPUT
                                       + MAX_OUTPUT_TOKENS * USD_PER_M_OUTPUT) / 1e6
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
                rec = self.create(system, user)
            except Exception as exc:  # only the class, status and error type are ever recorded
                kind = self.classify(exc)
                if kind in ("timeout", "refusal"):  # a graded fail, not re-issued (Amendment 1)
                    return {"text": "", "stop_reason": kind, "input_tokens": 0, "output_tokens": 0,
                            "reissues": attempt, "model": None}
                if kind != "retry":
                    raise Abort(f"non-retryable API error: {_describe(exc)}") from None
                if attempt >= len(BACKOFF_S) or self.totals.reissues >= LIMIT_REISSUES:
                    raise Abort(f"re-issue limit reached ({_describe(exc)})") from None
                self.sleep(BACKOFF_S[attempt])
                attempt += 1
                self.totals.reissues += 1
                continue
            self.totals.input_tokens += rec["input_tokens"]
            self.totals.output_tokens += rec["output_tokens"]
            self.totals.calls += 1
            return {**rec, "reissues": attempt}


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
        if rec["stop_reason"] == "refusal":  # a filter on an out-of-set question: configuration, not a result
            raise Abort("preflight refused (content filter or refusal on the preflight question)")
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
    lines = (out / "preflight.jsonl").read_text(encoding="utf-8").splitlines()
    models = sorted({json.loads(line)["model"] or "" for line in lines})
    return {"outcomes": outcomes, "categories": categories, "model_returned": ", ".join(models)}


def write_results(tasks: list[dict], result: dict, out: Path) -> None:
    for arm, per_case in result["outcomes"].items():
        lines = [json.dumps({"case_id": t["case_id"], "passed": per_case[t["case_id"]][trial], "trial": trial})
                 for t in tasks for trial in range(TRIALS)]
        _write(out / f"{arm}.jsonl", "\n".join(lines) + "\n")


def analysis(out: Path) -> str:
    from realdelta import cli as realdelta_cli

    commands = [["interval", "a1.jsonl", "--json"], ["interval", "a2.jsonl", "--json"],
                ["interval", "b.jsonl", "--json"], ["interval", "a1.jsonl", "--scope", "population", "--json"],
                ["compare", "a1.jsonl", "a2.jsonl", "--seed", "0", "--n-perm", "10000", "--conf", "0.95", "--json"],
                ["compare", "a1.jsonl", "b.jsonl", "--seed", "0", "--n-perm", "10000", "--conf", "0.95", "--json"]]
    parts, here = [], Path.cwd()
    os.chdir(out)
    try:
        for argv in commands:
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = realdelta_cli.main(argv)
            text = f"$ python -m realdelta {' '.join(argv)}\n{buf.getvalue()}"
            if err.getvalue():
                text += "[stderr]\n" + err.getvalue()
            parts.append(text + f"(exit {code})\n")
    finally:
        os.chdir(here)
    return "\n".join(parts)


# ---------------------------------------------------------------- real client

class MissingConfig(Exception):
    pass


def openai_runner() -> Runner:
    """Azure OpenAI v1 endpoint through the standard OpenAI client (Microsoft's documented pattern)."""
    import openai

    missing = [name for name in (ENV_KEY, ENV_BASE_URL) if not os.environ.get(name)]
    if missing:
        raise MissingConfig(f"set {' and '.join(missing)} in the environment (values are never printed)")
    client = openai.OpenAI(api_key=os.environ[ENV_KEY], base_url=os.environ[ENV_BASE_URL], max_retries=0,
                           timeout=TIMEOUT_S)

    def create(system: str, user: str) -> dict:
        response = client.responses.create(model=MODEL, instructions=system, input=user,
                                           max_output_tokens=MAX_OUTPUT_TOKENS, reasoning={"effort": EFFORT},
                                           store=False)
        return parse_response(response)

    return Runner(create=create, classify=lambda exc: classify_openai(exc, openai))


def classify_openai(exc: Exception, openai) -> str:
    """Amendment 1 error rules."""
    if isinstance(exc, ServerSideFailure):
        return "retry"
    if isinstance(exc, openai.APITimeoutError):  # checked first: in the SDK it subclasses APIConnectionError
        return "timeout"
    if isinstance(exc, openai.APIConnectionError):
        return "retry"
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code == 400 and getattr(exc, "code", None) == "content_filter":
            return "refusal"  # Azure input guardrail: a graded fail for this trial, not an abort
        if exc.status_code == 429 and "insufficient_quota" in (getattr(exc, "code", None), getattr(exc, "type", None)):
            return "abort"  # no credit: re-issuing cannot help (an account cause; re-run allowed)
        if exc.status_code == 429 or exc.status_code >= 500:
            return "retry"
    return "abort"


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
        per_call = lambda out_tokens: (300 * USD_PER_M_INPUT + out_tokens * USD_PER_M_OUTPUT) / 1e6  # noqa: E731
        print(f"model {MODEL}, reasoning effort {EFFORT}, max_output_tokens {MAX_OUTPUT_TOKENS}, timeout {TIMEOUT_S}s")
        print(f"calls: {calls} + 2 preflight; price constants ${USD_PER_M_INPUT}/M input, ${USD_PER_M_OUTPUT}/M output")
        print(f"cost at 300 input / 600 output tokens per call: ${(calls + 2) * per_call(600):.3f}")
        print(f"cost if every call used {MAX_OUTPUT_TOKENS} output tokens: ${(calls + 2) * per_call(MAX_OUTPUT_TOKENS):.3f}")
        print(f"limits: {LIMIT_REISSUES} re-issues, {LIMIT_OUTPUT_TOKENS} output tokens, ${LIMIT_USD:.2f}")
        return 0
    out = Path(args.run_dir)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip())
    if dirty:
        print("refusing to run: the working tree is not clean (the commit would not match the code)", file=sys.stderr)
        return 1
    try:
        runner = openai_runner()
    except MissingConfig as exc:
        print(f"not started: {exc}", file=sys.stderr)
        return 1
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
    import openai

    t = runner.totals
    lines = ["Real-model demo run (examples/real_model/PROTOCOL.md, Amendment 1)", "",
             f"calls {t.calls} (incl. 2 preflight), re-issues {t.reissues}, input tokens {t.input_tokens}, "
             f"output tokens {t.output_tokens}, cost upper estimate ${t.usd:.4f} at the conservative "
             f"${USD_PER_M_INPUT}/${USD_PER_M_OUTPUT} per million (the Azure bill is authoritative)", "",
             "Categories per arm: " + ", ".join(CATEGORIES)]
    for arm, cats in result["categories"].items():
        lines.append(f"  {arm}: " + ", ".join(str(cats[c]) for c in CATEGORIES))
    _write(out / "summary.txt", "\n".join(lines) + "\n\n" + analysis(out))
    _write(out / "provenance.txt", "\n".join([
        f"commit: {commit}", f"started: {started}", f"finished: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "provider: Azure OpenAI, owner's personal subscription, Global Standard deployment (endpoint not recorded)",
        f"deployment requested: {MODEL}", f"model returned: {result['model_returned']}",
        f"openai SDK: {openai.__version__}", f"python: {platform.python_version()}", f"numpy: {np.__version__}"]) + "\n")
    print((out / "summary.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
