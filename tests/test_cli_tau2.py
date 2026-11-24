"""CLI on tau2-bench result files (fixtures written by upstream tau2 code; see tests/fixtures/tau2)."""

import json
from pathlib import Path

import pytest

from realdelta import compare, load_tau2_results, pass_rate_interval
from realdelta.cli import main

FIX = Path(__file__).parent / "fixtures" / "tau2"


def run_json(capsys, argv):
    code = main(argv + ["--json"])
    return code, json.loads(capsys.readouterr().out)


def test_interval_reads_tau2_json_and_reports_dropped_infra(capsys):
    code, out = run_json(capsys, ["interval", str(FIX / "main.json")])
    assert code == 0
    iv = pass_rate_interval(load_tau2_results(FIX / "main.json").outcomes)
    assert (out["estimate"], out["low"], out["high"]) == pytest.approx((iv.estimate, iv.low, iv.high))
    meta = out["summary"]["tau2"]
    assert meta["domain"] == "mock" and meta["infra_dropped"] == 1 and meta["unscored_failures"] == 1
    assert any("infrastructure error were dropped" in w for w in out["warnings"])
    assert any("without a reward" in w for w in out["warnings"])
    assert any("--errors fail" in n for n in out["notes"])


def test_dropping_infra_errors_keeps_the_unequal_trials_warnings(tmp_path, capsys):
    # t3 keeps 3 of 4 trials after the drop: the gate must see unequal trials, not be relaxed.
    from realdelta.cli import WARN_ARMS
    # This 5-case fixture is below the gated range, so it cannot pin the unequal-trials region itself; that
    # needs a fixture with at least 10 cases (not done in this step).
    data = json.loads((FIX / "main.json").read_text())
    for s in data["simulations"]:
        if s["termination_reason"] == "infrastructure_error":
            s["termination_reason"], s["reward_info"] = "user_stop", {"reward": 1.0}
    full = tmp_path / "full.json"
    full.write_text(json.dumps(data))
    _, out = run_json(capsys, ["compare", str(FIX / "main.json"), str(full)])
    assert WARN_ARMS in out["warnings"]  # t3 has 3 trials in the baseline, 4 in the candidate


def test_interval_on_a_dir_format_folder(capsys):
    code, out = run_json(capsys, ["interval", str(FIX / "main_dir")])
    assert code == 0 and out["summary"]["tau2"]["infra_dropped"] == 1


def test_compare_two_tau2_files_matches_the_api(capsys):
    code, out = run_json(capsys, ["compare", str(FIX / "main.json"), str(FIX / "main_dir")])
    assert code == 0
    a = load_tau2_results(FIX / "main.json").outcomes
    b = load_tau2_results(FIX / "main_dir").outcomes
    d = compare(a, b).delta
    assert out["delta"]["estimate"] == pytest.approx(d.estimate) == 0
    assert out["baseline"]["tau2"]["infra_dropped"] == out["candidate"]["tau2"]["infra_dropped"] == 1
    assert sum("infrastructure error were dropped" in w for w in out["warnings"]) == 2  # one per arm


def test_compare_refuses_different_domains(capsys):
    code = main(["compare", str(FIX / "main.json"), str(FIX / "other_domain.json"), "--json"])
    assert code != 0
    assert "different tau2-bench domains" in json.loads(capsys.readouterr().out)["error"]


def test_infra_errors_fail_mode_is_passed_through(capsys):
    code, out = run_json(capsys, ["interval", str(FIX / "all_infra.json"), "--errors", "fail"])
    assert code == 0 and out["summary"]["tau2"]["errors"] == "fail"
    assert out["summary"]["tau2"]["infra_dropped"] == 0


def test_all_infra_task_is_an_error_by_default(capsys):
    code = main(["interval", str(FIX / "all_infra.json"), "--json"])
    assert code != 0
    assert "--errors fail" in json.loads(capsys.readouterr().out)["error"]


def test_jsonl_output_has_no_tau2_block(tmp_path, capsys):
    f = tmp_path / "r.jsonl"
    f.write_text('{"case_id": "a", "passed": true}\n{"case_id": "a", "passed": false}\n', encoding="utf-8")
    _, out = run_json(capsys, ["interval", str(f)])
    assert "tau2" not in out["summary"]


def _with_info(tmp_path, name, **changes):
    data = json.loads((FIX / "main.json").read_text())
    for key, value in changes.items():
        if key == "user_llm":
            data["info"]["user_info"]["llm"] = value
        else:
            data["info"][key] = value
    out = tmp_path / name
    out.write_text(json.dumps(data))
    return out


def test_compare_warns_on_different_trial_counts_and_user_simulators(tmp_path, capsys):
    other = _with_info(tmp_path, "other.json", num_trials=8, user_llm="some-other-simulator")
    code, out = run_json(capsys, ["compare", str(FIX / "main.json"), str(other)])
    assert code == 0
    assert any("different numbers of trials" in w for w in out["warnings"])
    assert any("different user simulators" in w for w in out["warnings"])
    _, same = run_json(capsys, ["compare", str(FIX / "main.json"), str(FIX / "main_dir")])
    assert not any("different numbers of trials" in w or "different user simulators" in w for w in same["warnings"])
