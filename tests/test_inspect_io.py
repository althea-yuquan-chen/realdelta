"""The Inspect AI reader, checked against logs written by inspect_ai itself (tests/inspect_logs.py).

Two independent references: the per-sample pass counts fixed in the generator (PASSES), and Inspect's own
accuracy metric on each log, which must equal the mean over samples of realdelta's per-sample pass rates.
"""

from __future__ import annotations

import dataclasses
import math
import os
from pathlib import Path

import pytest

if os.environ.get("REALDELTA_REQUIRE_INSPECT") != "1":
    pytest.importorskip("inspect_ai")

import inspect_logs as gen  # noqa: E402
from inspect_ai.scorer import value_to_float  # noqa: E402

from realdelta import InspectOutcomes, ResultFileError, check_inspect_pairing, load_inspect_log  # noqa: E402
from realdelta.io import _inspect_value  # noqa: E402

COMMITTED = Path(__file__).parent / "fixtures" / "inspect"


@pytest.fixture(scope="session")
def logs(tmp_path_factory):
    return gen.write_logs(tmp_path_factory.mktemp("inspect_logs"))


def per_sample_mean(res: InspectOutcomes) -> float:
    return sum(sum(v) / len(v) for v in res.outcomes.values()) / len(res.outcomes)


def test_outcomes_match_the_generator_table(logs):
    res = load_inspect_log(logs["main"])
    assert res.outcomes == {k: [e <= n for e in range(1, gen.EPOCHS + 1)] for k, n in gen.PASSES.items()}
    assert (res.task, res.scorer, res.epochs, res.errors) == ("pairs", "det", gen.EPOCHS, "drop")
    assert (res.errored, res.unscored, res.retried) == (0, 0, 0)


@pytest.mark.parametrize("name", ["main", "errors", "errors_json", "retried"])
def test_per_sample_mean_equals_inspects_own_accuracy(logs, name):
    res = load_inspect_log(logs[name])
    assert math.isclose(per_sample_mean(res), gen.inspect_accuracy(logs[name]), abs_tol=1e-12)


def test_errored_and_unscored_epochs_are_dropped_by_default(logs):
    res = load_inspect_log(logs["errors"])
    err_case, err_epoch = gen.ERROR_AT
    nan_case, nan_epoch = gen.NAN_AT
    assert (res.errored, res.errored_cases, res.unscored, res.unscored_cases) == (1, 1, 1, 1)
    assert len(res.outcomes[err_case]) == len(res.outcomes[nan_case]) == gen.EPOCHS - 1
    kept = [e for e in range(1, gen.EPOCHS + 1) if e != err_epoch]
    assert res.outcomes[err_case] == [e <= gen.PASSES[err_case] for e in kept]


def test_fail_mode_counts_errored_and_unscored_epochs_as_failures(logs):
    res = load_inspect_log(logs["errors"], errors="fail")
    err_case, err_epoch = gen.ERROR_AT
    nan_case, nan_epoch = gen.NAN_AT
    assert res.outcomes[err_case][err_epoch - 1] is False and res.outcomes[nan_case][nan_epoch - 1] is False
    assert all(len(v) == gen.EPOCHS for v in res.outcomes.values())


def test_error_mode_refuses_a_log_with_errors(logs):
    with pytest.raises(ResultFileError, match="--errors drop or fail"):
        load_inspect_log(logs["errors"], errors="error")


def test_unknown_errors_mode_is_refused(logs):
    with pytest.raises(ValueError, match="errors must be one of"):
        load_inspect_log(logs["main"], errors="ignore")


def test_json_log_reads_the_same_as_eval(logs):
    assert load_inspect_log(logs["errors_json"]).outcomes == load_inspect_log(logs["errors"]).outcomes


def test_unfinished_run_is_refused_with_a_way_out(logs):
    with pytest.raises(ResultFileError, match="status is 'error'.*eval-retry.*fail_on_error=False"):
        load_inspect_log(logs["status_error"])


def test_sample_with_every_epoch_errored_is_refused_under_drop(logs):
    with pytest.raises(ResultFileError, match=r"'d'.*every epoch errored"):
        load_inspect_log(logs["all_errored"])
    assert load_inspect_log(logs["all_errored"], errors="fail").outcomes["d"] == [False] * gen.EPOCHS


def test_several_scorers_need_a_choice(logs):
    with pytest.raises(ResultFileError, match="2 scorers.*'det'.*--scorer"):
        load_inspect_log(logs["two_scorers"])
    assert load_inspect_log(logs["two_scorers"], scorer="det").outcomes == load_inspect_log(logs["main"]).outcomes
    with pytest.raises(ResultFileError, match="no scorer named"):
        load_inspect_log(logs["two_scorers"], scorer="nope")


@pytest.mark.parametrize("name,kind", [("partial", "str"), ("half", "float"), ("lowercase_c", "str"),
                                       ("dict_value", "dict")])
def test_values_that_are_not_pass_fail_are_refused(logs, name, kind):
    with pytest.raises(ResultFileError, match=f"gave a {kind} value that is not pass/fail"):
        load_inspect_log(logs[name])


def test_value_whitelist_agrees_with_inspects_value_to_float():
    to_float = value_to_float()
    for value in ["C", "I", "N", True, False, 1, 0, 1.0, 0.0, "1", "0", "1.0", "0.0", "yes", "no", "true", "false",
                  "Yes", "TRUE", "No", "False"]:
        assert to_float(value) == (1.0 if _inspect_value(value) else 0.0), value
    assert _inspect_value(float("nan")) is None


@pytest.mark.parametrize("value", ["P", "nan", "2", "-1", "c", "PASS", "", 2, -1, 0.5, [1], {"x": 1}, None])
def test_value_whitelist_refuses_everything_else(value):
    with pytest.raises(Exception) as info:
        _inspect_value(value)
    assert type(info.value).__name__ == "_NotPassFail"


def test_message_does_not_echo_the_value(logs):
    with pytest.raises(ResultFileError) as info:
        load_inspect_log(logs["lowercase_c"])
    assert "'c'" not in str(info.value)


def test_retries_are_counted(logs):
    res = load_inspect_log(logs["retried"])
    assert res.retried == gen.EPOCHS and res.errored == 0
    assert res.outcomes == load_inspect_log(logs["main"]).outcomes


def test_a_retry_that_still_errors_counts_as_an_error_not_a_retry(logs):
    res = load_inspect_log(logs["retry_then_error"], errors="fail")
    assert res.errored == gen.EPOCHS and res.retried == 0


def test_non_mean_reducer_is_flagged(logs):
    assert load_inspect_log(logs["max_reducer"]).reducer_not_mean
    assert not load_inspect_log(logs["main"]).reducer_not_mean


def test_log_missing_a_sample_epoch_is_refused(logs):
    with pytest.raises(ResultFileError, match=f"lists {len(gen.PASSES) * gen.EPOCHS} sample-epochs but holds"):
        load_inspect_log(logs["truncated"])


@pytest.mark.parametrize("name,message", [
    ("invalidated", "were invalidated"),
    ("no_results", "has no results"),
    ("no_samples", "no samples"),
    ("repeat_epoch", "repeats the same sample and epoch"),
    ("mixed_inputs", "epochs of this sample have different inputs"),
    ("missing_score", "no score from 'det' and no error"),
    ("colliding_ids", "of different types .* collide"),
])
def test_inconsistent_logs_are_refused(logs, name, message):
    with pytest.raises(ResultFileError, match=message):
        load_inspect_log(logs[name])


def test_not_an_inspect_log(tmp_path):
    bad = tmp_path / "x.eval"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ResultFileError, match=r"not a readable Inspect AI log .*\(\w+\)"):
        load_inspect_log(bad)
    with pytest.raises(FileNotFoundError):
        load_inspect_log(tmp_path / "missing.eval")


# ---- pairing two logs ----

def test_same_task_same_samples_pairs_without_warnings(logs):
    assert check_inspect_pairing(load_inspect_log(logs["main"]), load_inspect_log(logs["main_again"])) == []


def test_different_tasks_are_refused(logs):
    with pytest.raises(ValueError, match="different Inspect tasks"):
        check_inspect_pairing(load_inspect_log(logs["main"]), load_inspect_log(logs["other_task"]))


def test_reordered_dataset_without_ids_is_refused(logs):
    with pytest.raises(ResultFileError, match="under different ids"):
        check_inspect_pairing(load_inspect_log(logs["noid_plain"]), load_inspect_log(logs["noid_reordered"]))


def test_reordered_and_limited_dataset_without_ids_is_refused(logs):
    with pytest.raises(ResultFileError, match="under different ids"):
        check_inspect_pairing(load_inspect_log(logs["noid_plain_limit"]),
                              load_inspect_log(logs["noid_reordered_limit"]))


def test_shuffled_subset_with_no_moved_sample_only_warns(logs):
    # The one shared sample kept its id by chance; the other ids hold different samples. Nothing moved between
    # ids, so the check cannot tell this from changed prompts: it warns, naming both readings and the shuffle.
    a, b = load_inspect_log(logs["noid_plain_limit"]), load_inspect_log(logs["noid_shuffled_limit_unlucky"])
    shared = set(a.fingerprints.values()) & set(b.fingerprints.values())
    assert len(shared) == 1  # precondition: one shared sample, at the same id in both
    assert [c for c, f in a.fingerprints.items() if f in shared] == [c for c, f in b.fingerprints.items() if f in shared]
    warnings = check_inspect_pairing(a, b)
    assert len(warnings) == 1 and "different subsets" in warnings[0] and "shuffled dataset" in warnings[0]


@pytest.mark.parametrize("field,value,message", [
    ("task_version", "2", "different versions of the task"),
    ("task_args_digest", "0" * 64, "different arguments"),
    ("dataset_name", "other", "different datasets"),
    ("dataset_samples", 99, "different datasets"),
    ("epochs", 3, "different numbers of epochs"),
    ("scorer", "other", "different scorers"),
])
def test_setup_differences_give_warnings(logs, field, value, message):
    a = load_inspect_log(logs["main"])
    warnings = check_inspect_pairing(a, dataclasses.replace(a, **{field: value}))
    assert len(warnings) == 1 and message in warnings[0]


def test_changed_prompts_give_a_warning_only(logs):
    warnings = check_inspect_pairing(load_inspect_log(logs["main"]), load_inspect_log(logs["new_prompts"]))
    assert len(warnings) == 1 and f"{len(gen.PASSES)} case(s) have a different input" in warnings[0]


def test_chat_inputs_pair_across_runs(logs):
    a, b = load_inspect_log(logs["chat"]), load_inspect_log(logs["chat_again"])
    assert a.fingerprints == b.fingerprints and check_inspect_pairing(a, b) == []


def test_duplicate_inputs_do_not_trip_the_check(logs):
    assert check_inspect_pairing(load_inspect_log(logs["noid_dupes"]), load_inspect_log(logs["noid_dupes_again"])) == []


def test_fingerprints_hold_no_prompt_text(logs):
    res = load_inspect_log(logs["main"])
    assert all(len(v) == 64 and "question" not in v for v in res.fingerprints.values())


# ---- a log written by the oldest tested inspect_ai, read by the installed one ----

def test_committed_log_from_the_oldest_tested_version():
    res = load_inspect_log(COMMITTED / "pairs_0.3.218.eval")
    assert res.outcomes == {k: [e <= n for e in range(1, gen.EPOCHS + 1)] for k, n in gen.PASSES.items()}
