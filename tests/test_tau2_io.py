"""The tau2-bench loader, checked against files and metrics produced by upstream tau2 code.

tests/fixtures/tau2/ was written by tau2's own Results.save, and expected.json holds what tau2's own
get_metrics_df and compute_metrics report for those files (see make_fixtures.py for the upstream commit).
"""

import json
import shutil
from pathlib import Path

import pytest

from realdelta import ResultFileError, load_tau2_results, macro_pass_rate

FIX = Path(__file__).parent / "fixtures" / "tau2"
EXPECTED = json.loads((FIX / "expected.json").read_text())
REPO = Path(__file__).resolve().parents[1]


def upstream_outcomes(view):
    out = {}
    for task, trial, success in view["rows"]:
        out.setdefault(task, {})[trial] = success
    return {t: [v[k] for k in sorted(v)] for t, v in out.items()}


@pytest.mark.parametrize("name", ["main.json", "main_dir/results.json", "main_dir", "main_both.json"])
def test_outcomes_equal_upstream_metrics_rows(name):
    res = load_tau2_results(FIX / name)
    assert res.outcomes == upstream_outcomes(EXPECTED["main"])
    assert res.infra_dropped == 1
    assert macro_pass_rate(res.outcomes) == pytest.approx(EXPECTED["main"]["pass_hat_1"], abs=1e-12)
    assert res.domain == "mock"


def test_success_threshold_matches_upstream():
    # t2: rewards 1 - 5e-7, 1 - 2e-6, 1, 0 -> upstream is_successful gives pass, fail, pass, fail
    assert load_tau2_results(FIX / "main.json").outcomes["t2"] == [True, False, True, False]


def test_unscored_non_infra_simulation_is_a_failure_and_counted():
    res = load_tau2_results(FIX / "main.json")
    assert res.outcomes["t3"] == [False, True, False]  # agent_error (no reward_info), pass, (infra dropped), fail
    assert res.unscored_failures == 1


def test_all_infra_task_raises_in_drop_mode_and_names_the_way_out():
    with pytest.raises(ResultFileError, match=r"t5.*infrastructure.*--errors fail"):
        load_tau2_results(FIX / "all_infra.json")


def test_fail_mode_counts_infra_errors_as_failures():
    res = load_tau2_results(FIX / "all_infra.json", infra_errors="fail")
    assert res.outcomes["t5"] == [False] * 4
    assert res.outcomes["t3"] == [False, True, False, False]
    assert res.infra_dropped == 0


def test_error_mode_refuses_any_infra_error():
    with pytest.raises(ResultFileError, match="infrastructure"):
        load_tau2_results(FIX / "main.json", infra_errors="error")


def test_missing_task_has_its_own_message():
    with pytest.raises(ResultFileError, match=r"t6.*no simulation"):
        load_tau2_results(FIX / "missing_task.json")


def test_other_domain_is_read():
    assert load_tau2_results(FIX / "other_domain.json").domain == "other"


def _edited(tmp_path, name, edit):
    data = json.loads((FIX / name).read_text())
    edit(data)
    out = tmp_path / Path(name).name
    out.write_text(json.dumps(data))
    return out


def test_index_and_simulations_that_disagree_raise(tmp_path):
    def edit(d):
        d["simulation_index"][1]["reward"] = 0.0
    with pytest.raises(ResultFileError, match="disagree"):
        load_tau2_results(_edited(tmp_path, "main_both.json", edit))


def test_index_entry_without_reward_or_reason_raises(tmp_path):
    def edit(d):
        d["simulation_index"][0]["reward"] = None
        d["simulation_index"][0]["termination_reason"] = None
    with pytest.raises(ResultFileError, match="termination_reason"):
        load_tau2_results(_edited(tmp_path, "main_dir/results.json", edit))


@pytest.mark.parametrize("reward", [1.5, -0.1, "1"])
def test_reward_outside_0_1_or_not_a_number_raises(tmp_path, reward):
    def edit(d):
        d["simulations"][0]["reward_info"]["reward"] = reward
    with pytest.raises(ResultFileError, match="reward"):
        load_tau2_results(_edited(tmp_path, "main.json", edit))


def test_all_null_trials_are_numbered_in_file_order(tmp_path):
    def edit(d):
        for s in d["simulations"]:
            s["trial"] = None
    res = load_tau2_results(_edited(tmp_path, "main.json", edit))
    assert res.trials_from_file_order
    assert res.outcomes == load_tau2_results(FIX / "main.json").outcomes


def test_mixed_null_trials_raise(tmp_path):
    def edit(d):
        d["simulations"][0]["trial"] = None
    with pytest.raises(ResultFileError, match="trial"):
        load_tau2_results(_edited(tmp_path, "main.json", edit))


def test_repeated_task_and_trial_raises(tmp_path):
    def edit(d):
        d["simulations"][1]["trial"] = d["simulations"][0]["trial"]
    with pytest.raises(ResultFileError, match="repeat"):
        load_tau2_results(_edited(tmp_path, "main.json", edit))


def test_metadata_only_results_json_raises(tmp_path):
    def edit(d):
        d["simulation_index"] = None
    with pytest.raises(ResultFileError, match="no simulations"):
        load_tau2_results(_edited(tmp_path, "main_dir/results.json", edit))


def test_unknown_infra_mode_is_rejected():
    with pytest.raises(ValueError):
        load_tau2_results(FIX / "main.json", infra_errors="ignore")


def test_error_messages_do_not_echo_values(tmp_path):
    def edit(d):
        d["simulations"][0]["reward_info"]["reward"] = "sk-secret-looking-value"
    with pytest.raises(ResultFileError) as err:
        load_tau2_results(_edited(tmp_path, "main.json", edit))
    assert "sk-secret" not in str(err.value)


# ---- local check on the pinned leaderboard files (not in CI: the raw files are not redistributed) ----

PINNED = REPO / "examples" / "tau2_leaderboard" / "data"
SUBS = {"A": "claude-opus-4-5_sierra_2026-02-26", "B": "claude-sonnet-4-5_sierra_2026-02-26",
        "C": "gpt-5-2_sierra_2026-02-26", "D": "gpt-5-2-none_sierra_2026-02-26"}


@pytest.mark.skipif(not PINNED.exists(), reason="pinned tau2 leaderboard files are not in this checkout")
def test_pinned_leaderboard_files_reproduce_published_pass_1():
    checked = []
    for label, sub in SUBS.items():
        res = load_tau2_results(PINNED / f"{sub}.airline.results.json")
        rate = 100 * macro_pass_rate(res.outcomes)
        if label == "D":
            # D's files do not reproduce its published score (Amendment 2); 80.5 is this study's own figure,
            # so this is a regression check, not an independent one.
            assert rate == pytest.approx(80.5, abs=1e-9)
        else:
            published = json.loads((PINNED / f"{sub}.submission.json").read_text())["results"]["airline"]["pass_1"]
            assert rate == pytest.approx(published, abs=0.005)  # published values carry two decimals at most
        assert res.domain == "airline" and res.infra_dropped == 0 and len(res.outcomes) == 50
        checked.append(label)
    assert checked == ["A", "B", "C", "D"]


def test_enum_style_termination_reason_is_recognised(tmp_path):
    def edit(d):
        for e in d["simulation_index"]:
            if e["termination_reason"] == "infrastructure_error":
                e["termination_reason"] = "TerminationReason.INFRASTRUCTURE_ERROR"
    res = load_tau2_results(_edited(tmp_path, "main_dir/results.json", edit))
    assert res.infra_dropped == 1 and res.outcomes == load_tau2_results(FIX / "main.json").outcomes


@pytest.mark.parametrize("reward, ok", [(0.999999, True), (1.000001, True), (1 - 1.1e-6, False)])
def test_success_rule_is_upstreams_expression(tmp_path, reward, ok):
    def edit(d):
        d["simulations"][0]["reward_info"]["reward"] = reward
    res = load_tau2_results(_edited(tmp_path, "main.json", edit))
    assert res.outcomes["t0"][0] is ok
    assert ((1 - 1e-6) <= reward <= (1 + 1e-6)) is ok  # tau2.metrics.agent_metrics.is_successful, verbatim


@pytest.mark.parametrize("edit, match", [
    (lambda d: d["simulations"].__setitem__(0, "not an object"), "not a JSON object"),
    (lambda d: d["simulations"][0].pop("task_id"), "no task_id"),
    (lambda d: d["simulations"][0].__setitem__("trial", "0"), "trial"),
    (lambda d: d["info"]["environment_info"].__setitem__("domain_name", 3), "domain_name"),
])
def test_malformed_files_raise_result_file_error(tmp_path, edit, match):
    with pytest.raises(ResultFileError, match=match):
        load_tau2_results(_edited(tmp_path, "main.json", edit))
