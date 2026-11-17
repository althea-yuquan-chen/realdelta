"""CLI (Phase 2 plan v2 section 2).

Numbers are checked against independent values where possible: the compare test uses arms where
every case has the same count, so the expected interval follows from the public wilson_interval and
Newcombe's hybrid score formula (as in tests/test_stats.py), and a candidate that is clearly better
must give a positive change (catches swapped arms).
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from realdelta import load_outcomes, pass_rate_interval, wilson_interval
from realdelta.cli import main

DATA = Path(__file__).parent / "data"
REPO = Path(__file__).resolve().parents[1]


def write_jsonl(path: Path, counts: dict[str, tuple[int, int]]) -> Path:
    """counts: case -> (passes, trials)."""
    lines = []
    for case, (passes, trials) in counts.items():
        for t in range(trials):
            lines.append(json.dumps({"case_id": case, "passed": t < passes}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def suite(tmp_path, name, m, n, passes):
    return write_jsonl(tmp_path / name, {f"c{i:03d}": (passes, n) for i in range(m)})


def run_json(capsys, argv):
    code = main(argv + ["--json"])
    out = capsys.readouterr().out
    return code, json.loads(out)


# ---------------------------------------------------------------- interval

def test_interval_matches_library_and_reports_summary(capsys):
    code, out = run_json(capsys, ["interval", str(DATA / "ok.jsonl")])
    assert code == 0
    assert set(out) == {"command", "file", "scope", "conf", "estimate", "low", "high", "summary", "notes", "warnings"}
    iv = pass_rate_interval(load_outcomes(DATA / "ok.jsonl"))
    assert (out["estimate"], out["low"], out["high"]) == (iv.estimate, iv.low, iv.high)
    assert out["summary"] == {"cases": 2, "trials_min": 1, "trials_median": 1.5, "trials_max": 2, "trials_total": 3}


@pytest.mark.parametrize("m, n, few, untested", [(4, 3, True, False), (5, 3, False, False),
                                                 (50, 10, False, False), (51, 3, False, True), (20, 11, False, True)])
def test_interval_region_warnings_at_boundaries(tmp_path, capsys, m, n, few, untested):
    f = suite(tmp_path, "a.jsonl", m, n, n - 1)
    _, out = run_json(capsys, ["interval", str(f)])
    text = " ".join(out["warnings"])
    assert ("Fewer than 5 cases" in text) == few
    assert ("untested range for the pass-rate" in text) == untested
    assert "Trial counts differ" not in text


def test_interval_population_note(tmp_path, capsys):
    f = suite(tmp_path, "a.jsonl", 10, 3, 2)
    _, out = run_json(capsys, ["interval", str(f), "--scope", "population"])
    assert any("(A2)" in n for n in out["notes"])
    _, out = run_json(capsys, ["interval", str(f)])
    assert out["notes"] == []


# ---------------------------------------------------------------- compare

def test_compare_matches_independent_wilson_mover(tmp_path, capsys):
    m, n, k_a, k_b = 12, 5, 2, 4
    base = suite(tmp_path, "base.jsonl", m, n, k_a)
    cand = suite(tmp_path, "cand.jsonl", m, n, k_b)
    code, out = run_json(capsys, ["compare", str(base), str(cand)])
    assert code == 0
    assert set(out) == {"command", "baseline", "candidate", "scope", "conf", "delta", "detected", "p_value",
                        "n_perm", "seed", "region", "notes", "warnings"}
    a, b = wilson_interval(m * k_a, m * n), wilson_interval(m * k_b, m * n)
    d = b.estimate - a.estimate
    assert d > 0
    assert out["delta"]["estimate"] == pytest.approx(d, abs=1e-12)
    assert out["delta"]["low"] == pytest.approx(d - math.hypot(b.estimate - b.low, a.high - a.estimate), abs=1e-12)
    assert out["delta"]["high"] == pytest.approx(d + math.hypot(b.high - b.estimate, a.estimate - a.low), abs=1e-12)
    assert out["detected"] is True
    assert out["seed"] == 0
    assert out["region"] == "inside gated range"
    assert out["warnings"] == []
    assert len(out["notes"]) == 2


@pytest.mark.parametrize("m, n, low, high", [(9, 3, True, False), (10, 3, False, False), (10, 2, True, False),
                                             (50, 10, False, False), (51, 3, False, True), (10, 11, False, True)])
def test_compare_region_warnings_at_boundaries(tmp_path, capsys, m, n, low, high):
    base = suite(tmp_path, "b.jsonl", m, n, n - 1)
    cand = suite(tmp_path, "c.jsonl", m, n, n - 1)
    _, out = run_json(capsys, ["compare", str(base), str(cand)])
    text = " ".join(out["warnings"])
    assert ("no gated evidence for the suite delta" in text) == low
    assert ("untested range for the suite delta" in text) == high
    expected = "below gated range" if low else "above gated range" if high else "inside gated range"
    assert out["region"] == expected


def test_compare_unequal_trials_within_and_between_arms(tmp_path, capsys):
    counts = {f"c{i:02d}": (1, 1 if i % 2 else 10) for i in range(20)}
    base = write_jsonl(tmp_path / "b.jsonl", counts)
    cand = write_jsonl(tmp_path / "c.jsonl", {k: (1, t + 1) for k, (p, t) in counts.items()})
    _, out = run_json(capsys, ["compare", str(base), str(cand)])
    text = " ".join(out["warnings"])
    assert "one grid setting covers this for the suite delta" in text
    assert "Fewer than 3 trials" not in text  # replaced by the unequal-trials warning
    assert "different trial counts in the two arms" in text
    assert out["region"] == "above gated range"  # max trials 11 > 10


def test_compare_notes_on_stdout_warnings_on_stderr(tmp_path, capsys):
    base = suite(tmp_path, "b.jsonl", 5, 3, 2)
    cand = suite(tmp_path, "c.jsonl", 5, 3, 3)
    assert main(["compare", str(base), str(cand)]) == 0
    captured = capsys.readouterr()
    assert "Note: Assumptions A1, A3 and A5" in captured.out
    assert "Note:" not in captured.err
    assert "Warning: Fewer than 10 cases" in captured.err


def test_compare_population_scope_is_refused(tmp_path, capsys):
    base = suite(tmp_path, "b.jsonl", 10, 3, 2)
    code, out = run_json(capsys, ["compare", str(base), str(base), "--scope", "population"])
    assert code == 2
    assert "not in v0.1" in out["error"]


def test_compare_mismatched_cases_truncates_ids(tmp_path, capsys):
    long_id = "x" * 200
    base = write_jsonl(tmp_path / "b.jsonl", {"a": (1, 1), long_id: (1, 1)})
    cand = write_jsonl(tmp_path / "c.jsonl", {"a": (1, 1)})
    code, out = run_json(capsys, ["compare", str(base), str(cand)])
    assert code == 2
    assert "1 only in baseline, 0 only in candidate" in out["error"]
    assert "x" * 41 not in out["error"]


def test_conf_warning(tmp_path, capsys):
    f = suite(tmp_path, "a.jsonl", 10, 3, 2)
    _, out = run_json(capsys, ["interval", str(f), "--conf", "0.9"])
    assert any("Only the 95% level" in w for w in out["warnings"])


def test_bad_file_error_in_text_mode(capsys):
    assert main(["interval", str(DATA / "extra_key.jsonl")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: extra_key.jsonl") and "SECRETPROMPT" not in err


# ---------------------------------------------------------------- plan

def test_plan_json_rows_and_regions(capsys):
    code, out = run_json(capsys, ["plan", "--cases", "20", "--break-cases", "2", "--trials", "1,3,11",
                                  "--n-sim", "20", "--input-tokens", "1000", "--output-tokens", "200",
                                  "--usd-per-m-input", "1", "--usd-per-m-output", "5"])
    assert code == 0
    assert set(out) == {"command", "change", "cases", "delta", "break_cases", "alpha", "beta", "conf", "n_sim",
                        "seed", "rows", "notes", "warnings"}
    assert out["change"] == "break" and out["delta"] is None
    assert [r["region"] for r in out["rows"]] == ["below gated range", "inside gated range", "above gated range"]
    assert set(out["rows"][0]) == {"trials", "power", "power_se", "false_alarm_rate", "false_alarm_se",
                                   "realised_change", "total_runs", "region", "cost_usd"}
    # 20 cases x 3 trials x 2 arms = 120 runs; 120k input tokens at $1/M + 24k output at $5/M
    assert out["rows"][1]["cost_usd"] == pytest.approx(0.12 + 0.12)
    assert out["warnings"]


def test_plan_partial_cost_flags_are_an_error(capsys):
    code, out = run_json(capsys, ["plan", "--cases", "20", "--delta", "0.1", "--n-sim", "5",
                                  "--input-tokens", "1000"])
    assert code == 2 and "all-or-none" in out["error"]


def test_plan_delta_and_break_are_mutually_exclusive():
    with pytest.raises(SystemExit) as info:
        main(["plan", "--cases", "20", "--delta", "0.1", "--break-cases", "2"])
    assert info.value.code == 2


# ---------------------------------------------------------------- entry point

def test_python_dash_m_entry_point():
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    proc = subprocess.run([sys.executable, "-m", "realdelta", "interval", str(DATA / "ok.jsonl"), "--json"],
                          capture_output=True, text=True, env=env, cwd=REPO)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["summary"]["cases"] == 2


def test_compare_region_uses_the_smaller_trial_count_over_both_arms(tmp_path, capsys):
    base = suite(tmp_path, "b.jsonl", 20, 5, 4)
    cand = suite(tmp_path, "c.jsonl", 20, 2, 1)
    _, out = run_json(capsys, ["compare", str(base), str(cand)])
    assert out["region"] == "below gated range"
    assert any("Fewer than 3 trials" in w for w in out["warnings"])


def test_compare_unequal_trials_inside_the_size_range_get_their_own_region(tmp_path, capsys):
    # 20 cases, 19 with 1 trial and one with 2: never "inside gated range" (review of the Phase 2 code)
    counts = {f"c{i:02d}": (1, 2 if i == 0 else 1) for i in range(20)}
    base = write_jsonl(tmp_path / "b.jsonl", counts)
    cand = write_jsonl(tmp_path / "c.jsonl", counts)
    _, out = run_json(capsys, ["compare", str(base), str(cand)])
    assert out["region"] == "unequal trials (one gated setting)"
    assert any("one grid setting covers this for the suite delta" in w for w in out["warnings"])


@pytest.mark.parametrize("argv", [
    ["compare", "{b}", "{b}", "--conf", "0.9"],
    ["plan", "--cases", "20", "--delta", "0.1", "--n-sim", "5", "--trials", "3", "--conf", "0.9"],
])
def test_conf_warning_on_compare_and_plan(tmp_path, capsys, argv):
    b = str(suite(tmp_path, "b.jsonl", 20, 3, 2))
    _, out = run_json(capsys, [a.format(b=b) for a in argv])
    assert any("Only the 95% level" in w for w in out["warnings"])


@pytest.mark.parametrize("argv", [
    ["plan", "--cases", "0", "--delta", "0.1"],
    ["plan", "--cases", "10", "--delta", "0.1", "--n-sim", "0"],
    ["plan", "--cases", "10", "--break-cases", "0"],
    ["compare", "a.jsonl", "b.jsonl", "--n-perm", "0"],
])
def test_non_positive_counts_are_usage_errors(argv):
    with pytest.raises(SystemExit) as info:
        main(argv)
    assert info.value.code == 2


def test_missing_file_error_names_the_file(tmp_path, capsys):
    base = suite(tmp_path, "b.jsonl", 10, 3, 2)
    code, out = run_json(capsys, ["compare", str(base), str(tmp_path / "missing_candidate.jsonl")])
    assert code == 2
    assert "missing_candidate.jsonl" in out["error"]


def test_break_plan_has_its_note_and_shift_plan_does_not(capsys):
    _, out = run_json(capsys, ["plan", "--cases", "20", "--break-cases", "2", "--trials", "3", "--n-sim", "5"])
    assert any("break plans have no gated calibration evidence" in n for n in out["notes"])
    _, out = run_json(capsys, ["plan", "--cases", "20", "--delta", "0.1", "--trials", "3", "--n-sim", "5"])
    assert not any("break plans" in n for n in out["notes"])


def test_p_value_text_says_exact_or_seeded(tmp_path, capsys):
    small = suite(tmp_path, "s.jsonl", 10, 3, 2)
    small_better = suite(tmp_path, "t.jsonl", 10, 3, 3)
    assert main(["compare", str(small), str(small_better)]) == 0
    assert "exact enumeration" in capsys.readouterr().out
    big = suite(tmp_path, "g.jsonl", 20, 3, 2)
    assert main(["compare", str(big), str(big)]) == 0
    assert "no case changed" in capsys.readouterr().out
    better = suite(tmp_path, "h.jsonl", 20, 3, 3)
    assert main(["compare", str(big), str(better)]) == 0
    assert "random sign flips, seed 0" in capsys.readouterr().out


def test_negative_token_counts_are_usage_errors():
    with pytest.raises(SystemExit) as info:
        main(["plan", "--cases", "10", "--delta", "0.1", "--input-tokens", "-1", "--output-tokens", "1",
              "--usd-per-m-input", "1", "--usd-per-m-output", "1"])
    assert info.value.code == 2
