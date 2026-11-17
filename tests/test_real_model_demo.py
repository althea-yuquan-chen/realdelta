"""The real-model demo runner (examples/real_model/PROTOCOL.md, Amendment 1: GPT-5.6 Luna), tested without
network or the openai package."""

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
    spec = importlib.util.spec_from_file_location(name, REPO / "examples" / "real_model" / f"{name}.py")
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
    ("ANSWER: 42", "incomplete_other", "42", "arithmetic", "incomplete_other"),
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


# ---------------------------------------------------------------- parsing a Responses API response

def responses_obj(texts=("ANSWER: 1",), status="completed", reason=None, refusal=False, model="gpt-5.6-luna",
                  inp=200, out=100):
    content = [NS(type="output_text", text=t) for t in texts]
    if refusal:
        content.append(NS(type="refusal", refusal="SECRET-REFUSAL"))
    output = [NS(type="reasoning", summary=[NS(text="SECRET-THINKING")]),
              NS(type="message", role="assistant", content=content)]
    return NS(output=output, status=status, model=model, usage=NS(input_tokens=inp, output_tokens=out),
              incomplete_details=NS(reason=reason) if reason else None)


@pytest.mark.parametrize("kwargs, stop", [
    (dict(), "end_turn"),
    (dict(status="incomplete", reason="max_output_tokens"), "max_tokens"),
    (dict(status="incomplete", reason="content_filter"), "refusal"),
    (dict(refusal=True), "refusal"),
    (dict(status="incomplete", reason="steered"), "incomplete_other"),
])
def test_parse_response_stop_reasons(kwargs, stop):
    assert demo.parse_response(responses_obj(**kwargs))["stop_reason"] == stop


def test_parse_response_keeps_message_text_only():
    rec = demo.parse_response(responses_obj(texts=("Working", "ANSWER: 7")))
    assert rec["text"] == "Working\nANSWER: 7"  # parts joined by a newline, so the answer keeps its own line
    assert "SECRET" not in json.dumps(rec)
    assert (rec["input_tokens"], rec["output_tokens"], rec["model"]) == (200, 100, "gpt-5.6-luna")


# ---------------------------------------------------------------- real-client wiring with a fake openai module

class FakeConnectionError(Exception):
    pass


class FakeTimeoutError(FakeConnectionError):  # worst case for ordering: timeout as a connection-error subclass
    pass


class FakeStatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def test_openai_runner_request_shape_and_error_classes(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.responses = NS(create=lambda **kw: calls.setdefault("create", kw) and responses_obj())

    fake = types.SimpleNamespace(OpenAI=FakeClient, APITimeoutError=FakeTimeoutError,
                                 APIConnectionError=FakeConnectionError, APIStatusError=FakeStatusError)
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key-for-test")
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://fake-resource.openai.azure.com/openai/v1/")
    runner = demo.openai_runner()
    rec = runner.create("SYS", "USER")
    assert rec["stop_reason"] == "end_turn"
    assert calls["client"] == {"api_key": "fake-key-for-test",
                               "base_url": "https://fake-resource.openai.azure.com/openai/v1/",
                               "max_retries": 0, "timeout": 120}
    sent = calls["create"]
    assert sent == {"model": "gpt-5.6-luna", "instructions": "SYS", "input": "USER", "max_output_tokens": 2048,
                    "reasoning": {"effort": "low"}, "store": False}
    assert runner.classify(FakeTimeoutError()) == "timeout"
    assert runner.classify(FakeConnectionError()) == "retry"
    for code, kind in [(429, "retry"), (500, "retry"), (503, "retry"), (400, "abort"), (401, "abort"), (403, "abort")]:
        assert runner.classify(FakeStatusError(code)) == kind


def test_real_sdk_error_classes_when_installed():
    openai = pytest.importorskip("openai")
    for name in ("APITimeoutError", "APIConnectionError", "APIStatusError"):
        assert hasattr(openai, name), name
    import inspect
    params = inspect.signature(openai.OpenAI(api_key="x").responses.create).parameters
    for name in ("model", "instructions", "input", "max_output_tokens", "reasoning"):
        assert name in params, name


# ---------------------------------------------------------------- runner behaviour

def record(text="ANSWER: 1", stop="end_turn", out_tokens=100, inp=200):
    return {"text": text, "stop_reason": stop, "input_tokens": inp, "output_tokens": out_tokens, "model": "m"}


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
        return record()

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


def test_abort_message_has_status_and_error_type_but_not_the_message():
    class Status(Exception):
        status_code = 400
        body = {"error": {"type": "invalid_request_error", "message": "SECRET-DETAIL"}}

    def bad(system, user):
        raise Status("SECRET-DETAIL")

    with pytest.raises(demo.Abort) as info:
        demo.Runner(create=bad, classify=lambda e: "abort", sleep=lambda s: None).call("s", "u")
    text = str(info.value)
    assert "status 400" in text and "type invalid_request_error" in text and "SECRET" not in text


def test_full_run_at_worst_case_output_fits_under_the_cost_cap():
    # 602 calls at 300 input and 2048 output tokens cost $7.58 at $1/$6 per million: inside $8.00.
    runner = demo.Runner(create=lambda s, u: record(out_tokens=2048, inp=300), classify=classify)
    for _ in range(602):
        runner.call("s", "u")
    assert runner.totals.usd < demo.LIMIT_USD


def test_cost_limit_binds_with_endless_full_length_outputs():
    # At $6/M the cost cap ($8.00) binds before 1.4M output tokens ($8.40).
    runner = demo.Runner(create=lambda s, u: record(out_tokens=2048), classify=classify)
    with pytest.raises(demo.Abort, match="cost limit"):
        for _ in range(10_000):
            runner.call("s", "u")
    assert runner.totals.output_tokens <= demo.LIMIT_OUTPUT_TOKENS and runner.totals.usd <= demo.LIMIT_USD


def test_output_token_limit_binds_when_output_is_cheap(monkeypatch):
    monkeypatch.setattr(demo, "USD_PER_M_OUTPUT", 0.01)
    runner = demo.Runner(create=lambda s, u: record(out_tokens=2048), classify=classify)
    with pytest.raises(demo.Abort, match="output-token limit"):
        for _ in range(10_000):
            runner.call("s", "u")
    assert runner.totals.output_tokens <= demo.LIMIT_OUTPUT_TOKENS


def test_cost_limit_binds_with_large_inputs():
    runner = demo.Runner(create=lambda s, u: record(out_tokens=10, inp=200_000), classify=classify)
    with pytest.raises(demo.Abort, match="cost limit"):
        for _ in range(10_000):
            runner.call("s", "u")
    assert runner.totals.usd <= demo.LIMIT_USD + 200_000 * demo.USD_PER_M_INPUT / 1e6


def test_full_run_with_a_fake_model(tmp_path):
    answers = {t["user"]: t["answer"] for t in TASKS}

    def create(system, user):
        if user == demo.PREFLIGHT_USER:
            return record("ANSWER: 42")
        if system == demo.S1 and user.startswith("How many times"):
            return record("I think 2")  # arm B loses the answer line on the letter family
        return record("Working...\nANSWER: " + answers[user])

    out = tmp_path / "run"
    result = demo.run(TASKS, demo.Runner(create=create, classify=classify, sleep=lambda s: None), out)
    demo.write_results(TASKS, result, out)
    assert len((out / "preflight.jsonl").read_text().splitlines()) == 2
    assert len((out / "responses.jsonl").read_text().splitlines()) == 600
    assert result["categories"]["a1"]["pass"] == 200 and result["categories"]["a2"]["pass"] == 200
    assert result["categories"]["b"] == {**{c: 0 for c in demo.CATEGORIES}, "pass": 150, "no_answer_line": 50}
    b = load_outcomes(out / "b.jsonl")
    assert len(b) == 40 and all(len(v) == 5 for v in b.values())
    assert sum(sum(v) for v in b.values()) == 150
    assert demo.analysis(out).count("(exit 0)") == 6
    with pytest.raises(FileExistsError):
        demo.run(TASKS, demo.Runner(create=create, classify=classify), out)


def test_analysis_keeps_cli_warnings(tmp_path, monkeypatch):
    import realdelta.cli

    def fake_cli(argv):
        print("report")
        print("Warning: STDERR-MARKER", file=sys.stderr)
        return 0

    monkeypatch.setattr(realdelta.cli, "main", fake_cli)
    assert demo.analysis(tmp_path).count("[stderr]\nWarning: STDERR-MARKER") == 6


def test_only_message_items_contribute_text():
    resp = responses_obj(texts=("ANSWER: 7",))
    resp.output.insert(0, NS(type="reasoning", content=[NS(type="output_text", text="SECRET-REASONING")]))
    rec = demo.parse_response(resp)
    assert rec["text"] == "ANSWER: 7" and "SECRET" not in json.dumps(rec)


def test_protocol_constants():
    """Amendment 1 values; a change here needs a new amendment."""
    assert (demo.MODEL, demo.EFFORT, demo.MAX_OUTPUT_TOKENS, demo.TIMEOUT_S, demo.TRIALS) == (
        "gpt-5.6-luna", "low", 2048, 120, 5)
    assert (demo.USD_PER_M_INPUT, demo.USD_PER_M_OUTPUT) == (1.00, 6.00)
    assert (demo.LIMIT_REISSUES, demo.LIMIT_OUTPUT_TOKENS, demo.LIMIT_USD) == (60, 1_400_000, 8.00)
    assert demo.ORDER_SEED == 20261121
    assert (demo.ENV_KEY, demo.ENV_BASE_URL) == ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL")


def test_missing_environment_is_reported_by_name_only(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **kw: None))
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://SECRET-RESOURCE.openai.azure.com/openai/v1/")
    with pytest.raises(demo.MissingConfig) as info:
        demo.openai_runner()
    assert "AZURE_OPENAI_API_KEY" in str(info.value) and "SECRET" not in str(info.value)


def test_azure_input_content_filter_is_a_refusal_not_an_abort():
    class Filtered(FakeStatusError):
        def __init__(self):
            super().__init__(400)
            self.code = "content_filter"

    fake = types.SimpleNamespace(APITimeoutError=FakeTimeoutError, APIConnectionError=FakeConnectionError,
                                 APIStatusError=FakeStatusError)
    assert demo.classify_openai(Filtered(), fake) == "refusal"
    assert demo.classify_openai(FakeStatusError(400), fake) == "abort"

    def create(system, user):
        raise Filtered()

    rec = demo.Runner(create=create, classify=lambda e: demo.classify_openai(e, fake), sleep=lambda s: None).call("s", "u")
    assert rec["stop_reason"] == "refusal" and rec["reissues"] == 0
    assert demo.grade(rec["text"], rec["stop_reason"], "1", "arithmetic") == "refusal"


@pytest.mark.parametrize("filters, stop", [
    ([{"blocked": True, "source_type": "completion"}], "refusal"),
    ([NS(blocked=True, source_type="completion")], "refusal"),
    ([{"blocked": False, "source_type": "completion"}], "end_turn"),
    ([{"blocked": True, "source_type": "prompt"}], "end_turn"),
    (None, "end_turn"),
])
def test_azure_completion_filter_is_a_refusal(filters, stop):
    resp = responses_obj()
    resp.content_filters = filters
    assert demo.parse_response(resp)["stop_reason"] == stop


def test_two_text_parts_keep_the_answer_line_separate():
    rec = demo.parse_response(responses_obj(texts=("I worked it out.", "ANSWER: 7")))
    assert demo.grade(rec["text"], rec["stop_reason"], "7", "arithmetic") == "pass"


@pytest.mark.parametrize("status", ["failed", "cancelled", "queued", "in_progress", None])
def test_non_answer_statuses_raise_a_server_side_failure(status):
    resp = responses_obj(status="completed")
    resp.status = status
    resp.error = NS(code="server_error", message="SECRET-DETAIL")
    with pytest.raises(demo.ServerSideFailure) as info:
        demo.parse_response(resp)
    assert "SECRET" not in demo._describe(info.value)


def test_missing_usage_is_a_server_side_failure():
    resp = responses_obj()
    resp.usage = None
    with pytest.raises(demo.ServerSideFailure):
        demo.parse_response(resp)


class FakeQuotaError(FakeStatusError):
    def __init__(self, code):
        super().__init__(429)
        self.code, self.type = code, code


def test_classify_openai_rules():
    fake = types.SimpleNamespace(APITimeoutError=FakeTimeoutError, APIConnectionError=FakeConnectionError,
                                 APIStatusError=FakeStatusError)
    assert demo.classify_openai(demo.ServerSideFailure("failed", "server_error"), fake) == "retry"
    assert demo.classify_openai(FakeTimeoutError(), fake) == "timeout"
    assert demo.classify_openai(FakeQuotaError("insufficient_quota"), fake) == "abort"
    assert demo.classify_openai(FakeQuotaError("rate_limit_exceeded"), fake) == "retry"
    assert demo.classify_openai(ValueError(), fake) == "abort"


def test_server_side_failures_are_reissued_and_count_toward_the_limit():
    attempts = []

    def create(system, user):
        attempts.append(1)
        if len(attempts) == 1:
            raise demo.ServerSideFailure("failed", "server_error")
        return record()

    runner = demo.Runner(create=create, classify=lambda e: "retry" if isinstance(e, demo.ServerSideFailure) else "abort",
                         sleep=lambda s: None)
    rec = runner.call("s", "u")
    assert rec["reissues"] == 1 and runner.totals.reissues == 1 and rec["stop_reason"] == "end_turn"


def test_preflight_refusal_aborts_before_any_task_call(tmp_path):
    calls = []

    def create(system, user):
        calls.append(user)
        if user == demo.PREFLIGHT_USER:
            return record("", stop="refusal")
        return record("ANSWER: 1")

    with pytest.raises(demo.Abort, match="preflight refused"):
        demo.run(TASKS, demo.Runner(create=create, classify=classify, sleep=lambda s: None), tmp_path / "run")
    assert calls == [demo.PREFLIGHT_USER]
    assert len((tmp_path / "run" / "preflight.jsonl").read_text().splitlines()) == 1


def test_records_note_whether_azure_content_filters_were_present():
    resp = responses_obj()
    assert demo.parse_response(resp)["content_filters_present"] is False
    resp.content_filters = []
    assert demo.parse_response(resp)["content_filters_present"] is True
