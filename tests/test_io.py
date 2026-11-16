"""Result-file contract (src/realdelta/io.py, Phase 2 plan v2 section 1).

Fixtures in tests/data are committed byte for byte (.gitattributes marks them -text) and the
expected values are written by hand, not produced by a writer that shares the reader's logic.
Every error test also checks that the message does not contain the offending value.
"""

from pathlib import Path

import pytest

from realdelta import load_outcomes
from realdelta.io import ResultFileError

DATA = Path(__file__).parent / "data"
NL = b"\n"


def test_jsonl_with_blank_line():
    assert load_outcomes(DATA / "ok.jsonl") == {"a": [True, False], "b": [True]}


def test_csv_with_bom_crlf_excel_booleans_trial_and_empty_row():
    assert (DATA / "ok_bom_crlf.csv").read_bytes()[:3] == b"\xef\xbb\xbf"
    assert b"\r\n" in (DATA / "ok_bom_crlf.csv").read_bytes()
    assert load_outcomes(DATA / "ok_bom_crlf.csv") == {"a": [True, False], "b": [True]}


def test_csv_columns_in_any_order_with_spaces_in_header():
    assert load_outcomes(DATA / "ok_reordered.csv") == {"x": [False, True]}


@pytest.mark.parametrize(
    "name, expected_fragment",
    [
        ("utf16.csv", "UTF-16"),
        ("latin1.jsonl", "not valid UTF-8"),
        ("semicolon.csv", "semicolon"),
        ("extra_column.csv", "'api_key'"),
        ("headerless.csv", "no header row found"),
        ("extra_key.jsonl", "'prompt'"),
        ("duplicate_key.jsonl", "duplicate key 'passed'"),
        ("bool_trial.jsonl", "trial must be a whole number, got bool"),
        ("numeric_case.jsonl", "case_id must be a non-empty string"),
        ("string_passed.jsonl", "passed must be a JSON boolean, got str"),
        ("int_passed.jsonl", "passed must be a JSON boolean, got int"),
        ("bad_json.jsonl", "not valid JSON"),
        ("mixed_trial.jsonl", "line 2: trial is missing"),
        ("duplicate_trial.csv", "lines 2 and 3 repeat"),
        ("excel_float_trial.csv", "whole number"),
        ("bad_passed.csv", "passed must be one of"),
        ("short_row.csv", "expected 2 fields, found 1"),
        ("empty.jsonl", "no records"),
        ("ok.txt", "unknown file type"),
    ],
)
def test_invalid_files_are_rejected_without_echoing_values(name, expected_fragment):
    """Every fixture that holds a value marks it with SECRET (or the number 12345); none may appear."""
    with pytest.raises(ResultFileError) as info:
        load_outcomes(DATA / name)
    message = str(info.value)
    assert message.startswith(name)
    assert expected_fragment in message
    assert "SECRET" not in message and "12345" not in message


def _write(tmp_path, name, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_csv_line_numbers_count_physical_lines_after_a_quoted_multiline_field(tmp_path):
    data = b"case_id,passed" + NL + b'"two' + NL + b'lines",1' + NL + b"b,SECRETBAD" + NL
    with pytest.raises(ResultFileError, match="line 4: passed must be one of") as info:
        load_outcomes(_write(tmp_path, "m.csv", data))
    assert "SECRET" not in str(info.value)


def test_csv_parser_errors_become_result_file_errors(tmp_path):
    data = b"case_id,passed" + NL + b"S" * 200_000 + b",1" + NL
    with pytest.raises(ResultFileError, match="not valid CSV") as info:
        load_outcomes(_write(tmp_path, "big.csv", data))
    assert "SSSS" not in str(info.value)


@pytest.mark.parametrize("data, fragment", [
    (b'{"case_id": "a", "passed": true, "trial": -1}' + NL, "trial must not be negative"),
    (b'{"case_id": "   ", "passed": true}' + NL, "case_id must be a non-empty string"),
])
def test_jsonl_negative_trial_and_blank_case_id(tmp_path, data, fragment):
    with pytest.raises(ResultFileError, match=fragment):
        load_outcomes(_write(tmp_path, "x.jsonl", data))


def test_csv_blank_case_id(tmp_path):
    with pytest.raises(ResultFileError, match="case_id is empty"):
        load_outcomes(_write(tmp_path, "x.csv", b"case_id,passed" + NL + b"  ,1" + NL))


def test_jsonl_line_separator_inside_a_string_is_not_a_line_break(tmp_path):
    case = "a" + chr(0x2028) + "b"
    data = ('{"case_id": "' + case + '", "passed": true}').encode("utf-8") + NL
    assert load_outcomes(_write(tmp_path, "u.jsonl", data)) == {case: [True]}


def test_error_is_a_value_error():
    assert issubclass(ResultFileError, ValueError)
