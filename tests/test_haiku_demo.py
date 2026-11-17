"""The Haiku demo runner, tested without network or the anthropic package (examples/haiku/PROTOCOL.md)."""

import importlib.util
import json
import sys
import types
from collections import Counter
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from realdelta import load_outcomes

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "examples" / "haiku" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses look their module up in sys.modules by spec name
    spec.loader.exec_module(module)
    return module


demo = _load("run_demo")
TASKS = demo.load_tasks()


# ---------------------------------------------------------------- task set

def test_task_set_is_reproducible_from_the_seed():
    make = _load("make_tasks")
    assert make.build() == TASKS
    assert Counter(t["family"] for t in TASKS) == {"arithmetic": 10, "letters": 10, "weekday": 10, "sort": 10}
    assert len({t["case_id"] for t in TASKS}) == 40


# ---------------------------------------------------------------- grading

@pytest.mark.parametrize("text, stop, expected, family, category", [
    ("Work...\nANSWER: 42", "end_turn", "42", "arithmetic", "pass"),
    ("**ANSWER:** 42", "end_turn", "42", "arithmetic", "pass"),
    ("`ANSWER: 42.`", "end_turn", "42", "arithmetic", "pass"),
    ("ANSWER: monday", "end_turn", "Monday", "weekday", "pass"),
    ("ANSWER: 3, 17, 250", "end_turn", "3,17,250", "sort", "pass"),
    ("ANSWER: 41", "end_turn", "42", "arithmetic", "wrong_value"),
    ("The answer is ANSWER: 42", "end_turn", "42", "arithmetic", "no_answer_line"),
    ("ANSWER: 42\nThanks!", "end_turn", "42", "arithmetic", "no_answer_line"),
    ("  \n ", "end_turn", "42", "arithmetic", "empty"),
    ("ANSWER: 42", "max_tokens", "42", "arithmetic", "max_tokens"),
    ("ANSWER: 42", "refusal", "42", "arithmetic", "refusal"),
    ("", "timeout", "42", "arithmetic", "timeout"),
])
def test_grade_categories_and_precedence(text, stop, expected, family, category):
    assert demo.grade(text, stop, expected, family) == category


# ---------------------------------------------------------------- schedule

def test_schedule_covers_each_case_arm_trial_once_and_interleaves_arms():
    schedule = demo.build_schedule(TASKS)
    assert len(schedule) == 600 and len(set(schedule)) == 600
    assert Counter((c, a) for c, a, _ in schedule) == {(t["case_id"], arm): 5 for t in TASKS for arm in demo.ARMS}
    assert schedule == demo.build_schedule(TASKS)
    first_hundred = Counter(a for _, a, _ in schedule[:100])
    assert all(20 <= first_hundred[arm] <= 50 for arm in demo.ARMS)


# ---------------------------------------------------------------- real-client wiring with a fake anthropic module

class FakeConnectionError(Exception):
    pass


class FakeTimeoutError(FakeConnectionError):  # the SDK's timeout is a connection-error subclass
    pass


class FakeStatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def test_anthropic_runner_request_shape_and_error_classes(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.messages = NS(create=lambda **kw: calls.setdefault("create", kw))

    fake = types.SimpleNamespace(Anthropic=FakeClient, APITimeoutError=FakeTimeoutError,
                                 APIConnectionError=FakeConnectionError, APIStatusError=FakeStatusError)
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    runner = demo.anthropic_runner()
    runner.create("SYS", "USER")
    assert calls["client"] == {"max_retries": 0, "timeout": 120}
    sent = calls["create"]
    assert sent["model"] == "claude-haiku-5-5" and sent["max_tokens"] == 2048
    assert sent["output_config"] == {"effort": "low"}
    assert sent["system"] == "SYS" and sent["messages"] == [{"role": "user", "content": "USER"}]
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(sent)
    assert runner.classify(FakeTimeoutError()) == "timeout"
    assert runner.classify(FakeConnectionError()) == "retry"
    for code, kind in [(429, "retry"), (500, "retry"), (529, "retry"), (400, "abort"), (401, "abort"), (403, "abort")]:
        assert runner.classify(FakeStatusError(code)) == kind


# ---------------------------------------------------------------- runner behaviour

def response(text, stop="end_turn", out_tokens=100, thinking="SECRET-THINKING"):
    return NS(content=[NS(type="thinking", thinking=thinking), NS(type="text", text=text)],
              stop_reason=stop, usage=NS(input_tokens=200, output_tokens=out_tokens), model="claude-haiku-5-5")


def classify(exc):
    if isinstance(exc, FakeTimeoutError):
        return "timeout"
    if isinstance(exc, FakeConnectionError):
        return "retry"
    return "abort"


def test_timeout_is_a_fail_and_not_reissued():
    attempts = []

    def create(system, user):
        attempts.append(1)
        raise FakeTimeoutError()

    rec = demo.Runner(create=create, classify=classify, sleep=lambda s: None).call("s", "u")
    assert rec["stop_reason"] == "timeout" and len(attempts) == 1 and rec["reissues"] == 0


def test_retryable_errors_are_reissued_then_abort_after_five():
    attempts, sleeps = [], []

    def flaky(system, user):
        attempts.append(1)
        if len(attempts) < 3:
            raise FakeConnectionError()
        return response("ANSWER: 1")

    runner = demo.Runner(create=flaky, classify=classify, sleep=sleeps.append)
    assert runner.call("s", "u")["reissues"] == 2 and sleeps == [2, 4] and runner.totals.reissues == 2

    def always(system, user):
        raise FakeConnectionError()

    with pytest.raises(demo.Abort, match="re-issue limit"):
        demo.Runner(create=always, classify=classify, sleep=lambda s: None).call("s", "u")


def test_non_retryable_error_aborts():
    def bad(system, user):
        raise FakeStatusError(400)

    with pytest.raises(demo.Abort, match="non-retryable"):
        demo.Runner(create=bad, classify=classify, sleep=lambda s: None).call("s", "u")


def test_limits_stop_before_a_call_that_could_cross_them():
    # With 2048-token outputs the 1.4M output-token limit binds before the $1.00 limit.
    runner = demo.Runner(create=lambda s, u: response("ANSWER: 1", out_tokens=2048), classify=classify)
    with pytest.raises(demo.Abort, match="output-token limit"):
        for _ in range(10_000):
            runner.call("s", "u")
    assert runner.totals.output_tokens <= demo.LIMIT_OUTPUT_TOKENS and runner.totals.usd <= demo.LIMIT_USD


def test_cost_limit_binds_with_large_inputs():
    big = NS(content=[NS(type="text", text="ANSWER: 1")], stop_reason="end_turn",
             usage=NS(input_tokens=200_000, output_tokens=10), model="m")
    runner = demo.Runner(create=lambda s, u: big, classify=classify)
    with pytest.raises(demo.Abort, match="cost limit"):
        for _ in range(10_000):
            runner.call("s", "u")
    assert runner.totals.usd <= demo.LIMIT_USD + 200_000 * demo.USD_PER_M_INPUT / 1e6


def test_full_run_with_a_fake_model(tmp_path):
    answers = {t["user"]: t["answer"] for t in TASKS}

    def create(system, user):
        if user == demo.PREFLIGHT_USER:
            return response("ANSWER: 42")
        if system == demo.S1 and user.startswith("How many times"):
            return response("I think 2")  # arm B loses the answer line on the letter family
        return response("Working...\nANSWER: " + answers[user])

    out = tmp_path / "run"
    result = demo.run(TASKS, demo.Runner(create=create, classify=classify, sleep=lambda s: None), out)
    demo.write_results(TASKS, result, out)
    assert len((out / "preflight.jsonl").read_text().splitlines()) == 2
    records = [json.loads(line) for line in (out / "responses.jsonl").read_text().splitlines()]
    assert len(records) == 600
    assert "SECRET-THINKING" not in (out / "responses.jsonl").read_text()
    assert result["categories"]["a1"]["pass"] == 200 and result["categories"]["a2"]["pass"] == 200
    assert result["categories"]["b"] == {**{c: 0 for c in demo.CATEGORIES}, "pass": 150, "no_answer_line": 50}
    b = load_outcomes(out / "b.jsonl")
    assert len(b) == 40 and all(len(v) == 5 for v in b.values())
    assert sum(sum(v) for v in b.values()) == 150
    with pytest.raises(FileExistsError):
        demo.run(TASKS, demo.Runner(create=create, classify=classify), out)


def test_only_text_blocks_are_kept_whatever_the_block_order():
    resp = NS(content=[NS(type="text", text="ANSWER: 7"), NS(type="thinking", thinking="SECRET-THINKING")],
              stop_reason="end_turn", usage=NS(input_tokens=10, output_tokens=10), model="m")
    rec = demo.Runner(create=lambda s, u: resp, classify=classify).call("s", "u")
    assert rec["text"] == "ANSWER: 7" and "SECRET" not in json.dumps(rec)


def test_abort_message_has_status_and_error_type_but_not_the_message():
    class Status(Exception):
        status_code = 400
        body = {"type": "error", "error": {"type": "invalid_request_error", "message": "SECRET-DETAIL"}}

    def bad(system, user):
        raise Status("SECRET-DETAIL")

    with pytest.raises(demo.Abort) as info:
        demo.Runner(create=bad, classify=lambda e: "abort", sleep=lambda s: None).call("s", "u")
    text = str(info.value)
    assert "status 400" in text and "type invalid_request_error" in text and "SECRET" not in text


def test_analysis_runs_every_command_and_keeps_stderr(tmp_path):
    answers = {t["user"]: t["answer"] for t in TASKS}

    def create(system, user):
        return response("ANSWER: 42" if user == demo.PREFLIGHT_USER else "ANSWER: " + answers[user])

    out = tmp_path / "run"
    result = demo.run(TASKS, demo.Runner(create=create, classify=classify, sleep=lambda s: None), out)
    demo.write_results(TASKS, result, out)
    text = demo.analysis(out)
    assert text.count("$ python -m realdelta") == 6
    assert text.count("(exit 0)") == 6
    assert "[stderr]" not in text or "Warning" in text


def test_real_sdk_error_classes_when_installed():
    anthropic = pytest.importorskip("anthropic")
    assert issubclass(anthropic.APITimeoutError, anthropic.APIConnectionError)
    import inspect
    assert "output_config" in inspect.signature(anthropic.Anthropic(api_key="x").messages.create).parameters


def test_analysis_keeps_cli_warnings(tmp_path, monkeypatch):
    import realdelta.cli

    def fake_cli(argv):
        print("report")
        print("Warning: STDERR-MARKER", file=sys.stderr)
        return 0

    monkeypatch.setattr(realdelta.cli, "main", fake_cli)
    text = demo.analysis(tmp_path)
    assert text.count("[stderr]\nWarning: STDERR-MARKER") == 6
