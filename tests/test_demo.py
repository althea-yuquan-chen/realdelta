"""The synthetic demo reproduces its committed transcript (README numbers come from it).

numpy does not promise identical random streams across versions for every distribution, so the
byte comparison runs only when the installed numpy matches the version recorded in the transcript.
With REALDELTA_REQUIRE_BYTE_TEST set (CI does this where numpy is pinned), a version mismatch fails
instead of skipping, so the test cannot silently stop running.
"""

import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "examples" / "synthetic"


def test_demo_reproduces_committed_transcript(tmp_path, capsys):
    header = (COMMITTED / "transcript.txt").read_text(encoding="utf-8").splitlines()[0]
    recorded = header.rsplit("numpy ", 1)[1]
    if recorded != np.__version__:
        message = f"transcript recorded with numpy {recorded}, running {np.__version__}"
        if os.environ.get("REALDELTA_REQUIRE_BYTE_TEST"):
            pytest.fail(message + " (REALDELTA_REQUIRE_BYTE_TEST is set)")
        pytest.skip(message)
    spec = importlib.util.spec_from_file_location("synthetic_demo", REPO / "examples" / "synthetic_demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    assert demo.main([str(tmp_path)]) == 0
    capsys.readouterr()
    for name in ("transcript.txt", "baseline.jsonl", "rerun.jsonl", "regression.jsonl"):
        assert (tmp_path / name).read_bytes() == (COMMITTED / name).read_bytes(), name


def test_readme_demo_numbers_match_the_transcript():
    """Independent of numpy: every count the README quotes is the one in the committed transcript."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    transcript = (COMMITTED / "transcript.txt").read_text(encoding="utf-8")
    pairs = [
        ("True pass rate: 0.95507", "true pass rate 0.95507"),
        ("true change -0.07261", "true change -0.073"),
        ("2 points or more: 184/500", "in 184 pairs (36.8%)"),
        ("4 points or more: 35/500", "or more in 35 (7.0%)"),
        ("95th percentile of the move: 4.0 points", "95th percentile of the move is 4.0 points"),
        ("compare flagged a change:            23/500", "in 23 of the 500 (4.6%)"),
        ("sign-flip p-value below 0.05:        14/500", "14 (2.8%)"),
        ("interval excludes 0 (detected): 423/500", "in 423 of 500 pairs of runs (84.6%)"),
        ("sign-flip p-value below 0.05:   76/500", "below 0.05 in 76 (15.2%)"),
        ("     1  0.133+-0.020", "0.13 +- 0.02 with 1 trial"),
        ("     3  0.543+-0.029", "0.54 +- 0.03 with 3"),
        ("     5  0.847+-0.021", "0.85 +- 0.02 with 5"),
        ("    10  0.990+-0.006", "0.99 +- 0.01 with 10"),
    ]
    flat = " ".join(readme.split())
    for in_transcript, in_readme in pairs:
        assert in_transcript in transcript, in_transcript
        assert in_readme in flat, in_readme
