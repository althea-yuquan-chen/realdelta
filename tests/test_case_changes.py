"""Per-case change list: descriptive, hand-checked expectations."""

import json

import pytest

from realdelta import CaseChange, case_changes, compare
from realdelta.cli import main

T, F = True, False
BASE = {"a": [T, T, T], "b": [F, F, F], "c": [T, F, T], "d": [T, T, T], "e": [T, T, F], "f": [T, T, T, T]}
CAND = {"a": [F, F, F], "b": [T, T, T], "c": [F, T, T], "d": [T, T, F], "e": [F, F, F], "f": [T, T, F]}


def test_only_changed_cases_by_group_then_size_then_id():
    got = case_changes(BASE, CAND)
    # c: 2/3 -> 2/3 unchanged; f: 4/4 -> 2/3 (unequal trials)
    assert [c.case_id for c in got] == ["a", "e", "b", "d", "f"]
    assert [c.change for c in got] == pytest.approx([-1, -2 / 3, 1, -1 / 3, -1 / 3])


def test_equal_changes_tie_by_case_id_even_when_floats_differ():
    # 4/5 -> 3/5 and 5/5 -> 4/5 are both -1/5, but 0.6 - 0.8 != 0.8 - 1.0 in floating point.
    base = {"z": [T, T, T, T, F], "y": [T] * 5, "x": [T, T, T, F, F], "w": [T, T, F, F, F]}
    cand = {"z": [T, T, T, F, F], "y": [T, T, T, T, F], "x": [T, T, F, F, F], "w": [T, F, F, F, F]}
    assert [c.case_id for c in case_changes(base, cand)] == ["w", "x", "y", "z"]


def test_larger_changes_come_first_within_a_group():
    got = case_changes({"p": [T, T, T, F, F], "q": [T, T, T, T, F]}, {"p": [T] * 5, "q": [T] * 5})
    assert [c.case_id for c in got] == ["p", "q"]  # +2/5 before +1/5


def test_groups_and_counts():
    got = {c.case_id: c for c in case_changes(BASE, CAND)}
    assert got["a"].group == "now_fails_every_trial" and got["e"].group == "now_fails_every_trial"
    assert got["b"].group == "now_passes_every_trial"
    assert got["d"].group == "other" and got["f"].group == "other"
    f = got["f"]
    assert (f.baseline_passes, f.baseline_trials, f.candidate_passes, f.candidate_trials) == (4, 4, 2, 3)


def test_a_case_already_failing_every_trial_is_not_newly_failing():
    got = case_changes({"x": [F, F], "y": [T, T]}, {"x": [F, F, F], "y": [T, T, T]})
    assert got == ()  # rates unchanged (0 -> 0, 1 -> 1)


def test_compare_carries_the_list_and_stays_hashable():
    res = compare(BASE, CAND, seed=0)
    assert res.case_changes == case_changes(BASE, CAND)
    assert isinstance(res.case_changes[0], CaseChange)
    hash(res)


def test_cli_text_shows_groups_counts_and_the_descriptive_note(tmp_path, capsys):
    base, cand = tmp_path / "b.jsonl", tmp_path / "c.jsonl"
    rows_b, rows_c = [], []
    for i in range(12):  # 12 cases go from 3/3 to 0/3
        rows_b += [{"case_id": f"k{i:02d}", "passed": True}] * 3
        rows_c += [{"case_id": f"k{i:02d}", "passed": False}] * 3
    base.write_text("\n".join(json.dumps(r) for r in rows_b) + "\n")
    cand.write_text("\n".join(json.dumps(r) for r in rows_c) + "\n")
    assert main(["compare", str(base), str(cand)]) == 0
    out = capsys.readouterr().out
    assert "now fail every trial: 12 (showing 10 of 12)" in out
    assert "'k00' 3/3 -> 0/3" in out and "'k10'" not in out
    assert "descriptive" in out and "multiple-comparison" in out
    assert main(["compare", str(base), str(cand), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    cc = payload["case_changes"]
    assert len(cc["cases"]) == 12 and "descriptive" in cc["note"]
    assert cc["cases"][0] == {"case_id": "k00", "baseline": {"passes": 3, "trials": 3},
                              "candidate": {"passes": 0, "trials": 3}, "change": -1.0,
                              "group": "now_fails_every_trial"}
