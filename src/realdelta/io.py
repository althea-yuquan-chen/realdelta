"""Read eval results from disk: one record per trial, as JSON Lines or CSV.

Each record has ``case_id`` (a non-empty string), ``passed`` (a boolean) and, optionally, ``trial``
(a whole number). No other fields are accepted. ``trial`` is all-or-none within a file; when present,
each (case_id, trial) pair must be unique.

JSON Lines (``.jsonl``)::

    {"case_id": "case-001", "passed": true}
    {"case_id": "case-001", "passed": false}

CSV (``.csv``), header required, columns in any order::

    case_id,passed
    case-001,true
    case-001,false

``passed`` in CSV is one of true, false, 1, 0 (any case; Excel writes TRUE and FALSE). Files must be
UTF-8; a UTF-8 byte-order mark is fine. Error messages name the file, line and field, never the value,
so a wrong file (for example one holding prompts or keys) does not end up in logs.

Record failed, crashed or timed-out runs as ``passed: false`` unless you have a reason to drop them;
dropping runs because of their outcome breaks assumption A4 (README, Limitations).
"""

from __future__ import annotations

import csv
import io as _io
import json
import re
from pathlib import Path

REQUIRED = ("case_id", "passed")
OPTIONAL = ("trial",)
ALLOWED = REQUIRED + OPTIONAL
_TRUE = {"true", "1"}
_FALSE = {"false", "0"}
_WHOLE = re.compile(r"\d+")


class ResultFileError(ValueError):
    """A result file does not follow the format. The message never contains field values."""


_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_ .-]{0,39}")


def _names(names) -> str:
    """Field or column names for an error message. Names that do not look like identifiers (for
    example a data row read as a header) are counted, not shown."""
    names = [str(n) for n in names]
    shown = [repr(n) for n in names if _IDENTIFIER.fullmatch(n)][:5]
    hidden = len(names) - len(shown)
    parts = ", ".join(shown)
    if hidden:
        parts += (" " if parts else "") + f"({hidden} not shown)"
    return parts


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise ResultFileError(
            f"{path.name}: the file is UTF-16; expected UTF-8 (Windows PowerShell 5.1 '>' writes UTF-16; "
            "re-save the file as UTF-8)"
        )
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ResultFileError(f"{path.name}: not valid UTF-8 (byte offset {exc.start}); expected UTF-8") from None


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise ResultFileError(f"duplicate key {_names([key])}")
        seen.add(key)
    return dict(pairs)


def _jsonl_records(name: str, text: str):
    # split on "\n" only: str.splitlines() also breaks at U+2028 and friends, which are legal in JSON strings
    for lineno, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        where = f"{name}: line {lineno}"
        try:
            obj = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except ResultFileError as exc:
            raise ResultFileError(f"{where}: {exc}") from None
        except json.JSONDecodeError as exc:
            raise ResultFileError(f"{where}: not valid JSON ({exc.msg}, column {exc.colno})") from None
        if not isinstance(obj, dict):
            raise ResultFileError(f"{where}: expected a JSON object, got {type(obj).__name__}")
        extra = [k for k in obj if k not in ALLOWED]
        if extra:
            raise ResultFileError(f"{where}: unexpected field(s) {_names(extra)}; allowed: {', '.join(ALLOWED)}")
        missing = [k for k in REQUIRED if k not in obj]
        if missing:
            raise ResultFileError(f"{where}: missing field(s) {', '.join(missing)}")
        case_id, passed = obj["case_id"], obj["passed"]
        if type(case_id) is not str or not case_id.strip():
            raise ResultFileError(f"{where}: case_id must be a non-empty string, got {type(case_id).__name__}"
                                  " (write numeric ids as strings)")
        if type(passed) is not bool:
            raise ResultFileError(f"{where}: passed must be a JSON boolean, got {type(passed).__name__}")
        trial = obj.get("trial")
        if "trial" in obj and type(trial) is not int:
            raise ResultFileError(f"{where}: trial must be a whole number, got {type(trial).__name__}")
        if "trial" in obj and trial < 0:
            raise ResultFileError(f"{where}: trial must not be negative")
        yield lineno, case_id, passed, ("trial" in obj), trial


def _csv_records(name: str, text: str):
    rows = csv.reader(_io.StringIO(text, newline=""))
    header = None
    while True:
        try:
            row = next(rows)
        except StopIteration:
            return
        except csv.Error as exc:
            raise ResultFileError(f"{name}: line {rows.line_num}: not valid CSV (a field is too long or quoting "
                                  "is malformed)") from None
        lineno = rows.line_num  # physical line, correct after quoted multi-line fields
        if not any(field.strip() for field in row):
            continue
        where = f"{name}: line {lineno}"
        if header is None:
            header = [h.strip() for h in row]
            if len(header) == 1 and ";" in header[0]:
                raise ResultFileError(f"{where}: the file looks semicolon-separated; use commas")
            if not any(k in header for k in REQUIRED):
                # Probably a data row: say so without showing any of it.
                raise ResultFileError(f"{where}: no header row found; the first line must be case_id,passed[,trial]")
            extra = [h for h in header if h not in ALLOWED]
            if extra:
                raise ResultFileError(f"{where}: unexpected column(s) {_names(extra)}; allowed: {', '.join(ALLOWED)}")
            if len(set(header)) != len(header):
                raise ResultFileError(f"{where}: a column name appears twice")
            missing = [k for k in REQUIRED if k not in header]
            if missing:
                raise ResultFileError(f"{where}: missing column(s) {', '.join(missing)}")
            col = {h: i for i, h in enumerate(header)}
            continue
        if len(row) != len(header):
            raise ResultFileError(f"{where}: expected {len(header)} fields, found {len(row)}")
        case_id = row[col["case_id"]]
        if not case_id.strip():
            raise ResultFileError(f"{where}: case_id is empty")
        flag = row[col["passed"]].strip().lower()
        if flag in _TRUE:
            passed = True
        elif flag in _FALSE:
            passed = False
        else:
            raise ResultFileError(f"{where}: passed must be one of true, false, 1, 0")
        has_trial, trial = "trial" in col, None
        if has_trial:
            raw = row[col["trial"]].strip()
            if not _WHOLE.fullmatch(raw):
                raise ResultFileError(f"{where}: trial must be a non-negative whole number (Excel may write 1.0)")
            trial = int(raw)
        yield lineno, case_id, passed, has_trial, trial


def load_outcomes(path) -> dict[str, list[bool]]:
    """Read a ``.jsonl`` or ``.csv`` result file into ``{case_id: [passed, ...]}`` in file order."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".jsonl", ".csv"):
        raise ResultFileError(f"{path.name}: unknown file type; use .jsonl or .csv")
    text = _decode(path)
    records = list((_jsonl_records if suffix == ".jsonl" else _csv_records)(path.name, text))
    if not records:
        raise ResultFileError(f"{path.name}: no records")
    with_trial = [r for r in records if r[3]]
    if with_trial and len(with_trial) != len(records):
        first_without = next(r[0] for r in records if not r[3])
        raise ResultFileError(f"{path.name}: line {first_without}: trial is missing here but present on other lines;"
                              " give it on every line or on none")
    if with_trial:
        seen: dict[tuple[str, int], int] = {}
        for lineno, case_id, _, _, trial in records:
            key = (case_id, trial)
            if key in seen:
                raise ResultFileError(f"{path.name}: lines {seen[key]} and {lineno} repeat the same case and trial")
            seen[key] = lineno
    outcomes: dict[str, list[bool]] = {}
    for _, case_id, passed, _, _ in records:
        outcomes.setdefault(case_id, []).append(passed)
    return outcomes
