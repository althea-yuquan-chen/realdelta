"""Write real Inspect AI eval logs with inspect_ai itself and its offline mock model (no API, no network).

Used by tests/test_inspect_io.py and tests/test_cli_inspect.py at test time, so the logs come from whatever
inspect_ai version is installed; also used by tests/fixtures/inspect/make_fixture.py for the committed log.
The expected outcomes are fixed here (PASSES), not read back from the logs.
"""

from __future__ import annotations

import glob
import math
from pathlib import Path

from inspect_ai import Epochs, Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.model import ChatMessageSystem, ChatMessageUser
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, mean, scorer
from inspect_ai.solver import solver

EPOCHS = 4
# passes out of EPOCHS per sample id; epoch e (1-based) passes when e <= passes
PASSES = {"a": 4, "b": 3, "c": 2, "d": 0, "e": 1, "f": 4}
ERROR_AT = ("e", 2)  # this sample-epoch raises in the "errors" log
NAN_AT = ("b", 4)  # this sample-epoch is unscored (NaN) in the "errors" log


def _passes(sample_id, epoch) -> bool:
    return epoch <= PASSES[str(sample_id)]


@scorer(metrics=[accuracy()])
def det(nan_at=None):
    async def score(state, target):
        if nan_at and (str(state.sample_id), state.epoch) == nan_at:
            return Score(value=float("nan"))
        return Score(value=CORRECT if _passes(state.sample_id, state.epoch) else INCORRECT)
    return score


@scorer(metrics=[mean()])
def valued(value):
    """Gives every sample the same value, for the value-mapping tests."""
    async def score(state, target):
        return Score(value=value)
    return score


@scorer(metrics={"x": [mean()]})
def dict_valued():
    """A dict-valued score with per-key metrics, the form Inspect uses for dict scores."""
    async def score(state, target):
        return Score(value={"x": 1})
    return score


@solver
def maybe_raise(error_at=None, always=None):
    async def solve(state, generate):
        if error_at and (str(state.sample_id), state.epoch) == error_at:
            raise RuntimeError("planned failure")
        if always and str(state.sample_id) == always:
            raise RuntimeError("planned failure")
        return state
    return solve


_TRIED: set = set()


@solver
def fails_once(sample):
    async def solve(state, generate):
        key = (str(state.sample_id), state.epoch)
        if str(state.sample_id) == sample and key not in _TRIED:
            _TRIED.add(key)
            raise RuntimeError("transient failure")
        return state
    return solve


def _samples(prompt="question {}"):
    return [Sample(id=k, input=prompt.format(k), target="x") for k in PASSES]


def _run(out: Path, task: Task, **kwargs) -> Path:
    before = set(glob.glob(str(out / "*.eval")))
    eval(task, model="mockllm/model", log_dir=str(out), display="none", **kwargs)
    (new,) = set(glob.glob(str(out / "*.eval"))) - before
    return Path(new)


def _named(out: Path, path: Path, name: str) -> Path:
    target = out / f"{name}.eval"
    path.rename(target)
    return target


def write_logs(out: Path) -> dict[str, Path]:
    """Write every log the tests use into ``out``; returns name -> path."""
    out.mkdir(parents=True, exist_ok=True)
    _TRIED.clear()  # the "retried" log needs each first attempt to fail again on every call
    logs: dict[str, Path] = {}

    def add(name, task, **kw):
        logs[name] = _named(out, _run(out, task, **kw), name)

    add("main", Task(dataset=_samples(), solver=[maybe_raise()], scorer=det(), name="pairs"), epochs=EPOCHS)
    add("main_again", Task(dataset=_samples(), solver=[maybe_raise()], scorer=det(), name="pairs"), epochs=EPOCHS)
    add("errors", Task(dataset=_samples(), solver=[maybe_raise(error_at=ERROR_AT)], scorer=det(nan_at=NAN_AT),
                       name="pairs"), epochs=EPOCHS, fail_on_error=False)
    add("status_error", Task(dataset=_samples(), solver=[maybe_raise(error_at=ERROR_AT)], scorer=det(),
                             name="pairs"), epochs=EPOCHS)
    add("all_errored", Task(dataset=_samples(), solver=[maybe_raise(always="d")], scorer=det(), name="pairs"),
        epochs=EPOCHS, fail_on_error=False)
    add("two_scorers", Task(dataset=_samples(), solver=[maybe_raise()], scorer=[det(), valued(1.0)],
                            name="pairs"), epochs=EPOCHS)
    add("partial", Task(dataset=_samples(), solver=[maybe_raise()], scorer=valued("P"), name="pairs"), epochs=2)
    add("half", Task(dataset=_samples(), solver=[maybe_raise()], scorer=valued(0.5), name="pairs"), epochs=2)
    add("lowercase_c", Task(dataset=_samples(), solver=[maybe_raise()], scorer=valued("c"), name="pairs"), epochs=2)
    add("dict_value", Task(dataset=_samples(), solver=[maybe_raise()], scorer=dict_valued(), name="pairs"),
        epochs=2)
    add("retried", Task(dataset=_samples(), solver=[fails_once("c")], scorer=det(), name="pairs"), epochs=EPOCHS,
        retry_on_error=2)
    add("retry_then_error", Task(dataset=_samples(), solver=[maybe_raise(always="d")], scorer=det(), name="pairs"),
        epochs=EPOCHS, retry_on_error=1, fail_on_error=False)
    add("max_reducer", Task(dataset=_samples(), solver=[maybe_raise()], scorer=det(), name="pairs"),
        epochs=Epochs(EPOCHS, "max"))
    add("other_task", Task(dataset=_samples(), solver=[maybe_raise()], scorer=det(), name="other"), epochs=EPOCHS)
    add("new_prompts", Task(dataset=_samples("reworded question {}"), solver=[maybe_raise()], scorer=det(),
                            name="pairs"), epochs=EPOCHS)

    # Chat-form inputs: Inspect gives each message a new id on every run, so pairing must ignore message ids.
    def chat():
        return Task(dataset=[Sample(id=k, input=[ChatMessageSystem(content="be brief"),
                                                 ChatMessageUser(content=f"question {k}")], target="x")
                             for k in PASSES], solver=[maybe_raise()], scorer=det(), name="chat")

    add("chat", chat(), epochs=2)
    add("chat_again", chat(), epochs=2)

    # Datasets without ids: Inspect numbers the samples, after shuffling.
    def noid(seed=None, prompts=None):
        ds = MemoryDataset([Sample(input=p, target="x") for p in (prompts or [f"q{i}" for i in range(8)])])
        if seed is not None:
            ds.shuffle(seed=seed)
        return Task(dataset=ds, solver=[maybe_raise()], scorer=valued("C"), name="noid")

    reordered = [f"q{i}" for i in (3, 2, 7, 6, 5, 4, 1, 0)]  # a fixed reordering, independent of any seed
    add("noid_plain", noid(), epochs=2)
    add("noid_reordered", noid(prompts=reordered), epochs=2)
    # first four: q0-q3 vs q3, q2, q7, q6, so q3 and q2 sit at other ids in the two runs
    add("noid_reordered_limit", noid(prompts=reordered), epochs=2, limit=4)
    # seed 7 keeps only q2 in the first four, at the same id 3 as in the unshuffled run (the test asserts this),
    # so no sample moved between ids and only a warning is possible
    add("noid_shuffled_limit_unlucky", noid(seed=7), epochs=2, limit=4)
    add("noid_plain_limit", noid(), epochs=2, limit=4)
    add("noid_dupes", noid(prompts=["same", "same", "other", "x"]), epochs=2)
    add("noid_dupes_again", noid(prompts=["same", "same", "other", "x"]), epochs=2)

    # A log missing one sample-epoch (an incomplete file); Inspect's total_samples still counts it.
    log = read_eval_log(str(logs["main"]))
    log.samples = log.samples[1:]
    write_eval_log(log, str(out / "truncated.eval"))
    logs["truncated"] = out / "truncated.eval"
    # Logs Inspect would not write, edited with its own API, for the reader's consistency checks.
    def edited(name, change, suffix=".eval"):
        log = read_eval_log(str(logs["main"]))
        change(log)
        write_eval_log(log, str(out / f"{name}{suffix}"))
        logs[name] = out / f"{name}{suffix}"

    def repeat_epoch(log):
        log.samples.append(log.samples[0].model_copy())
        log.results.total_samples += 1

    def mixed_inputs(log):
        log.samples[0].input = "a different question"

    def missing_score(log):
        log.samples[0].scores = {}

    def colliding_ids(log):
        first = log.samples[0].id
        for s in log.samples:
            if s.id == first and s.epoch == 1:
                s.id, s.input = 7, "seven"
        for s in log.samples:
            if s.id == log.samples[1].id and s.epoch == 1:
                s.id, s.input = "7", "seven"

    # .eval stores one entry per (id, epoch), so a repeat or an id collision can only occur in a .json log
    edited("repeat_epoch", repeat_epoch, ".json")
    edited("mixed_inputs", mixed_inputs)
    edited("missing_score", missing_score)
    edited("colliding_ids", colliding_ids, ".json")

    def invalidated(log):
        log.invalidated = True

    def no_results(log):
        log.results = None

    def no_samples(log):
        log.samples = []
        log.results.total_samples = 0

    edited("invalidated", invalidated)
    edited("no_results", no_results)
    edited("no_samples", no_samples, ".json")
    # The same log saved as JSON.
    write_eval_log(read_eval_log(str(logs["errors"])), str(out / "errors.json"))
    logs["errors_json"] = out / "errors.json"
    return logs


def inspect_accuracy(path: Path, scorer_name: str = "det") -> float:
    """Inspect's own accuracy for the log (the upstream computation)."""
    log = read_eval_log(str(path), header_only=True)
    (s,) = [s for s in log.results.scores if s.name == scorer_name]
    value = s.metrics["accuracy"].value
    assert not math.isnan(value)
    return value
