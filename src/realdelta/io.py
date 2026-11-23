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
from dataclasses import dataclass
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
        raise ResultFileError(f"{path.name}: unknown file type; use .jsonl or .csv (or a tau2-bench .json results "
                              "file, read with load_tau2_results)")
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


# ---- tau2-bench result files ----

_TAU2_SUCCESS_TOL = 1e-6  # tau2.metrics.agent_metrics.is_successful: (1 - 1e-6) <= reward <= (1 + 1e-6)
_INFRA = "infrastructure_error"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,40}")
INFRA_MODES = ("drop", "fail", "error")


@dataclass(frozen=True)
class Tau2Outcomes:
    """Outcomes read from one tau2-bench results file, with what the reader did to get them."""

    outcomes: dict[str, list[bool]]
    domain: str | None
    num_trials: int | None
    user_llm: str | None
    infra_dropped: int
    unscored_failures: int
    trials_from_file_order: bool


def _task(tid) -> str:
    s = str(tid)
    return repr(s) if _ID.fullmatch(s) else "a task (id not shown)"


def _reason(value) -> str | None:
    """Termination reason as tau2's enum value. Saved files hold the value ("infrastructure_error"); the
    "TerminationReason.X" form is what str() of the enum gives, accepted defensively."""
    if value is None:
        return None
    s = str(value)
    return s.split(".", 1)[1].lower() if s.startswith("TerminationReason.") else s


def _entry_task(name: str, entry) -> str:
    if not isinstance(entry, dict):
        raise ResultFileError(f"{name}: a simulation entry is not a JSON object")
    tid = entry.get("task_id")
    if tid is None or isinstance(tid, (bool, dict, list)) or str(tid) == "":
        raise ResultFileError(f"{name}: a simulation has no task_id")
    return str(tid)


def _check_trials(name: str, entries) -> None:
    for tid, trial, _, _ in entries:
        if trial is not None and (not isinstance(trial, int) or isinstance(trial, bool) or trial < 0):
            raise ResultFileError(f"{name}: {_task(tid)}: trial must be a non-negative whole number")


def _tau2_entries(name: str, data: dict) -> list[tuple[str, object, object, str | None]]:
    """(task_id, trial, reward, termination_reason) per simulation, from the index or the simulations."""
    index, sims = data.get("simulation_index"), data.get("simulations")
    from_index = from_sims = None
    if isinstance(index, list) and index:
        from_index = [(_entry_task(name, e), e.get("trial"), e.get("reward"), _reason(e.get("termination_reason")))
                      for e in index]
        _check_trials(name, from_index)
    if isinstance(sims, list) and sims:
        from_sims = []
        for s in sims:
            tid = _entry_task(name, s)
            info = s.get("reward_info")
            reward = info.get("reward") if isinstance(info, dict) else None
            from_sims.append((tid, s.get("trial"), reward, _reason(s.get("termination_reason"))))
        _check_trials(name, from_sims)
    if from_index is None and from_sims is None:
        raise ResultFileError(f"{name}: no simulations (neither a simulation_index nor a simulations list); "
                              "a metadata-only results.json cannot be scored")
    if from_index is not None and from_sims is not None:
        key = lambda e: (e[0], -1 if e[1] is None else e[1])  # noqa: E731
        if sorted(from_index, key=key) != sorted(from_sims, key=key):
            raise ResultFileError(f"{name}: simulation_index and simulations disagree; the index may be stale")
    return from_index if from_index is not None else from_sims


def load_tau2_results(path, *, infra_errors: str = "drop") -> Tau2Outcomes:
    """Read a tau2-bench results file (``json`` or ``dir`` format) into per-task pass/fail outcomes.

    ``path`` is a results JSON file or a ``dir``-format folder holding ``results.json``; only the index is read
    there, so the ``simulations/`` folder is not needed. A trial passes when tau2's ``is_successful`` holds for
    its reward. A simulation without a reward (no ``reward_info``) that is not an infrastructure error counts as
    a failure, as in tau2's metrics, and is counted in ``unscored_failures``. (If every reward in a file is
    missing, tau2's own metrics raise; this reader reports 0%.)

    ``infra_errors``: ``"drop"`` removes simulations whose termination reason is ``infrastructure_error``, as
    tau2's metrics are written to do (under pandas 3, tau2 at commit 768f3d8 counted them as failures; see the
    README, Result files); a task left with no simulation raises, because dropping it would change the suite.
    ``"fail"`` counts them as failures. ``"error"`` refuses a file that has any. Dropping by termination reason
    keeps assumption A4 only if infrastructure errors do not depend on how the trial would have gone.
    """
    if infra_errors not in INFRA_MODES:
        raise ValueError(f"infra_errors must be one of {INFRA_MODES}, got {infra_errors!r}")
    path = Path(path)
    if path.is_dir():
        path = path / "results.json"
    name = path.name
    try:
        data = json.loads(_decode(path), object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ResultFileError(f"{name}: not valid JSON (line {exc.lineno})") from None
    if not isinstance(data, dict):
        raise ResultFileError(f"{name}: expected a JSON object (a tau2-bench results file)")
    entries = _tau2_entries(name, data)

    trials = [e[1] for e in entries]
    null = [t is None for t in trials]
    if any(null) and not all(null):
        raise ResultFileError(f"{name}: trial is missing on some simulations but present on others")
    from_order = all(null)
    if not from_order:
        if any(not isinstance(t, int) or isinstance(t, bool) or t < 0 for t in trials):
            raise ResultFileError(f"{name}: trial must be a non-negative whole number")
        seen = set()
        for tid, trial, _, _ in entries:
            if (tid, trial) in seen:
                raise ResultFileError(f"{name}: {_task(tid)} trial {trial}: simulations repeat the same task and trial")
            seen.add((tid, trial))

    listed = [str(t.get("id")) for t in data.get("tasks") or [] if isinstance(t, dict)]
    present = {e[0] for e in entries}
    missing = [t for t in listed if t not in present]
    if missing:
        raise ResultFileError(f"{name}: {_task(missing[0])} ({len(missing)} task(s) in all) has no simulation in the "
                              "file; the run may be unfinished")

    per_task: dict[str, list[tuple[int, bool]]] = {}
    infra_tasks: dict[str, int] = {}
    dropped = unscored = 0
    for order, (tid, trial, reward, reason) in enumerate(entries):
        pos = order if from_order else trial
        if reason == _INFRA:
            if infra_errors == "error":
                raise ResultFileError(f"{name}: {_task(tid)} trial {trial}: infrastructure error; "
                                      "use --infra-errors drop or fail to read this file")
            infra_tasks[tid] = infra_tasks.get(tid, 0) + 1
            if infra_errors == "drop":
                dropped += 1
                continue
            per_task.setdefault(tid, []).append((pos, False))
            continue
        if reward is None:
            if reason is None:
                raise ResultFileError(f"{name}: {_task(tid)} trial {trial}: no reward and no termination_reason; "
                                      "cannot tell an infrastructure error from a failure")
            unscored += 1
            per_task.setdefault(tid, []).append((pos, False))
            continue
        if isinstance(reward, bool) or not isinstance(reward, (int, float)) or not (
                -_TAU2_SUCCESS_TOL <= reward <= 1 + _TAU2_SUCCESS_TOL):
            raise ResultFileError(f"{name}: {_task(tid)} trial {trial}: reward must be a number in [0, 1]")
        per_task.setdefault(tid, []).append((pos, (1 - _TAU2_SUCCESS_TOL) <= reward <= (1 + _TAU2_SUCCESS_TOL)))

    emptied = [t for t in infra_tasks if t not in per_task]
    if emptied:
        raise ResultFileError(f"{name}: {_task(emptied[0])} ({len(emptied)} task(s) in all): every simulation is an "
                              "infrastructure error, so dropping them would remove the task; use --infra-errors fail "
                              "to count them as failures")

    order_ids = [t for t in dict.fromkeys(e[0] for e in entries) if t in per_task]
    outcomes = {t: [ok for _, ok in sorted(per_task[t])] for t in order_ids}
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    env = info.get("environment_info") if isinstance(info.get("environment_info"), dict) else {}
    domain = env.get("domain_name")
    if domain is not None and not isinstance(domain, str):
        raise ResultFileError(f"{name}: info.environment_info.domain_name is not a string")
    user = info.get("user_info") if isinstance(info.get("user_info"), dict) else {}
    return Tau2Outcomes(outcomes=outcomes, domain=domain, num_trials=info.get("num_trials"),
                        user_llm=user.get("llm"), infra_dropped=dropped, unscored_failures=unscored,
                        trials_from_file_order=from_order)
