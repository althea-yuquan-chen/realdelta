"""CLI on Inspect AI logs written by inspect_ai itself (tests/inspect_logs.py)."""

from __future__ import annotations

import builtins
import json
import os

import pytest

if os.environ.get("REALDELTA_REQUIRE_INSPECT") != "1":
    pytest.importorskip("inspect_ai")

import inspect_logs as gen  # noqa: E402

from realdelta.cli import NOTE_INSPECT_ERRORS, NOTE_INSPECT_RETRIES, main  # noqa: E402


@pytest.fixture(scope="session")
def logs(tmp_path_factory):
    return gen.write_logs(tmp_path_factory.mktemp("inspect_cli_logs"))


def run_json(capsys, argv):
    code = main(argv + ["--json"])
    return code, json.loads(capsys.readouterr().out)


def test_interval_reads_an_eval_log(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["main"])])
    assert code == 0
    meta = out["summary"]["inspect"]
    assert (meta["task"], meta["scorer"], meta["epochs"], meta["errors"]) == ("pairs", "det", gen.EPOCHS, "drop")
    assert out["summary"]["cases"] == len(gen.PASSES) and out["summary"]["trials_total"] == len(gen.PASSES) * gen.EPOCHS
    assert NOTE_INSPECT_ERRORS not in out["notes"] and NOTE_INSPECT_RETRIES not in out["notes"]
    assert "fingerprints" not in json.dumps(out) and "_res" not in json.dumps(out)


def test_dropped_errors_are_reported(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["errors"])])
    assert code == 0 and out["summary"]["inspect"]["dropped"] == 2
    assert NOTE_INSPECT_ERRORS in out["notes"]
    assert any("raised an error (1 sample(s)) were dropped" in w for w in out["warnings"])
    assert any("unscored sample-epoch(s) (1 sample(s)) were dropped" in w for w in out["warnings"])


def test_retries_alone_give_the_retry_note_only(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["retried"])])
    assert code == 0 and NOTE_INSPECT_RETRIES in out["notes"] and NOTE_INSPECT_ERRORS not in out["notes"]
    assert any("scored only after a retry" in w for w in out["warnings"])


def test_scorer_option_on_other_files_is_refused(tmp_path, capsys):
    f = tmp_path / "r.jsonl"
    f.write_text('{"case_id": "a", "passed": true}\n')
    code, out = run_json(capsys, ["interval", str(f), "--scorer", "det"])
    assert code == 2 and "Inspect AI logs only" in out["error"]


def test_errors_fail_is_passed_through(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["errors"]), "--errors", "fail"])
    assert code == 0 and out["summary"]["inspect"]["errors"] == "fail" and out["summary"]["inspect"]["dropped"] == 0
    assert NOTE_INSPECT_ERRORS not in out["notes"]
    assert out["summary"]["trials_total"] == len(gen.PASSES) * gen.EPOCHS
    assert any("were counted as failures" in w for w in out["warnings"])


def test_json_log_is_detected_as_inspect(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["errors_json"])])
    assert code == 0 and "inspect" in out["summary"]


def test_scorer_option(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["two_scorers"])])
    assert code == 2 and "--scorer" in out["error"]
    code, out = run_json(capsys, ["interval", str(logs["two_scorers"]), "--scorer", "det"])
    assert code == 0 and out["summary"]["inspect"]["scorer"] == "det"


def test_compare_two_logs_names_model_and_scorer(logs, capsys):
    code = main(["compare", str(logs["main"]), str(logs["new_prompts"])])
    captured = capsys.readouterr()
    assert code == 0
    assert "Baseline main.eval (model 'mockllm/model', scorer 'det')" in captured.out
    assert "have a different input or target" in captured.err


def test_compare_refuses_different_tasks(logs, capsys):
    code, out = run_json(capsys, ["compare", str(logs["main"]), str(logs["other_task"])])
    assert code == 2 and "different Inspect tasks" in out["error"]


def test_compare_refuses_reshuffled_samples(logs, capsys):
    code, out = run_json(capsys, ["compare", str(logs["noid_plain"]), str(logs["noid_reordered"])])
    assert code == 2 and "under different ids" in out["error"]


def test_unfinished_run_exits_2(logs, capsys):
    code, out = run_json(capsys, ["interval", str(logs["status_error"])])
    assert code == 2 and "eval-retry" in out["error"]


def test_missing_inspect_ai_exits_2_with_install_hint(logs, capsys, monkeypatch):
    real_import = builtins.__import__

    def no_inspect(name, *args, **kwargs):
        if name.startswith("inspect_ai"):
            raise ImportError("blocked for the test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_inspect)
    code, out = run_json(capsys, ["interval", str(logs["main"])])
    assert code == 2 and "realdelta[inspect]" in out["error"]


def test_json_with_version_but_no_eval_object_is_not_inspect(tmp_path, capsys):
    f = tmp_path / "results.json"
    f.write_text(json.dumps({"version": 2, "eval": ["task"]}))  # holds "task", but is not an object
    code, out = run_json(capsys, ["interval", str(f)])
    assert code == 2 and "no simulations" in out["error"]  # read as tau2, which refuses it
