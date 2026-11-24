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
import hashlib
import io as _io
import json
import math
import re
import sys
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
                              "file, read with load_tau2_results, or an Inspect AI log, read with load_inspect_log)")
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


def load_tau2_results(path, *, errors: str = "drop") -> Tau2Outcomes:
    """Read a tau2-bench results file (``json`` or ``dir`` format) into per-task pass/fail outcomes.

    ``path`` is a results JSON file or a ``dir``-format folder holding ``results.json``; only the index is read
    there, so the ``simulations/`` folder is not needed. A trial passes when tau2's ``is_successful`` holds for
    its reward. A simulation without a reward (no ``reward_info``) that is not an infrastructure error counts as
    a failure, as in tau2's metrics, and is counted in ``unscored_failures``. (If every reward in a file is
    missing, tau2's own metrics raise; this reader reports 0%.)

    ``errors``: ``"drop"`` removes simulations whose termination reason is ``infrastructure_error``, as
    tau2's metrics are written to do (under pandas 3.1.1, tau2 at commit 768f3d8 counted them as failures; see the
    README, Result files); a task left with no simulation raises, because dropping it would change the suite.
    ``"fail"`` counts them as failures. ``"error"`` refuses a file that has any. Dropping by termination reason
    keeps assumption A4 only if infrastructure errors do not depend on how the trial would have gone.
    """
    if errors not in INFRA_MODES:
        raise ValueError(f"errors must be one of {INFRA_MODES}, got {errors!r}")
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
            if errors == "error":
                raise ResultFileError(f"{name}: {_task(tid)} trial {trial}: infrastructure error; "
                                      "use --errors drop or fail to read this file")
            infra_tasks[tid] = infra_tasks.get(tid, 0) + 1
            if errors == "drop":
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
                              "infrastructure error, so dropping them would remove the task; use --errors fail "
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


# ---- Inspect AI eval logs ----

INSPECT_MIN_VERSION = "0.3.218"  # oldest inspect_ai the tests were run on (README, Result files)
_PASS_WORDS = ("yes", "true")
_FAIL_WORDS = ("no", "false")


@dataclass(frozen=True)
class InspectOutcomes:
    """Outcomes read from one Inspect AI eval log, with what the reader did to get them.

    A case is a sample id and a trial is an epoch. ``fingerprints`` holds, per case, a SHA-256 of the sample's
    input (text and roles only) and target, so two logs can be checked for pairing without keeping prompts.
    """

    outcomes: dict[str, list[bool]]
    task: str
    model: str
    scorer: str
    epochs: int | None
    errors: str
    errored: int
    errored_cases: int
    unscored: int
    unscored_cases: int
    retried: int
    reducer_not_mean: bool
    task_version: str
    task_args_digest: str
    dataset_name: str | None
    dataset_samples: int | None
    dataset_shuffled: bool
    fingerprints: dict[str, str]


class _NotPassFail(Exception):
    pass


def _inspect_value(value) -> bool | None:
    """True or False for a pass/fail score value, None for an unscored (NaN) one; anything else raises."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        if value == 1:
            return True
        if value == 0:
            return False
        raise _NotPassFail
    if isinstance(value, str):
        if value == "C":
            return True
        if value in ("I", "N"):
            return False
        if value.lower() in _PASS_WORDS:
            return True
        if value.lower() in _FAIL_WORDS:
            return False
        try:
            number = float(value)
        except ValueError:
            raise _NotPassFail from None
        if number == 1:
            return True
        if number == 0:
            return False
    raise _NotPassFail


def _fingerprint(inp, target) -> str:
    if isinstance(inp, str):
        parts: list = ["text", inp]
    else:
        parts = ["chat"] + [[getattr(m, "role", None), getattr(m, "text", None)] for m in inp or []]
    blob = json.dumps([parts, target], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _inspect_readers():
    try:
        from inspect_ai.log import read_eval_log, read_eval_log_sample_summaries
    except ImportError:
        if sys.version_info < (3, 11):
            raise ImportError("reading Inspect AI logs needs inspect_ai, which needs Python 3.11 or later") from None
        raise ImportError(f"reading Inspect AI logs needs inspect_ai (>= {INSPECT_MIN_VERSION}): "
                          "pip install 'realdelta[inspect]'") from None
    return read_eval_log, read_eval_log_sample_summaries


_STATUS_HELP = {
    "error": "the run stopped on an error (Inspect's default when a sample errors); finish it with "
             "'inspect eval-retry', or rerun with fail_on_error=False",
    "cancelled": "the run was cancelled; finish it with 'inspect eval-retry'",
    "started": "the run has not finished",
}


def load_inspect_log(path, *, scorer: str | None = None, errors: str = "drop") -> InspectOutcomes:
    """Read an Inspect AI eval log (``.eval`` or ``.json``) into per-sample pass/fail outcomes over epochs.

    Needs the ``inspect`` extra (``pip install 'realdelta[inspect]'``, Python 3.11 or later); the log is read
    with inspect_ai's own sample-summary reader, so messages and events are not loaded from ``.eval`` files.

    Only finished runs are read (status ``success``). A score passes when its value is ``C``, ``True``, 1,
    ``"1"``, ``yes`` or ``true``, and fails when it is ``I``, ``N`` (no answer, a failure as in Inspect's
    accuracy), ``False``, 0, ``"0"``, ``no`` or ``false``; any other value (partial credit such as ``P``,
    other numbers or strings, dicts) raises, because realdelta needs pass/fail. With several scorers in the log,
    ``scorer`` names the one to use.

    ``errors`` applies to samples that raised an error and to unscored samples (value NaN, for example a
    model grader whose output could not be parsed): ``"drop"`` removes them, which is what Inspect's own metrics
    do; ``"fail"`` counts them as failures; ``"error"`` refuses a log that has any. A case left with no epochs
    raises. Dropping keeps assumption A4 only if the errors do not depend on how the trial would have gone; in
    Inspect a sample error can be any exception, including one caused by the agent's own actions.

    Before comparing two logs with ``compare(a.outcomes, b.outcomes)``, call ``check_inspect_pairing(a, b)``: it
    refuses logs whose sample ids do not refer to the same samples. The command line does this for you.
    """
    if errors not in INFRA_MODES:
        raise ValueError(f"errors must be one of {INFRA_MODES}, got {errors!r}")
    read_eval_log, read_summaries = _inspect_readers()
    path = Path(path)
    name = path.name
    if not path.is_file():
        raise FileNotFoundError(2, "No such file", str(path))
    try:
        header = read_eval_log(str(path), header_only=True)
        summaries = read_summaries(str(path))
    except Exception as exc:  # upstream messages may quote file content, so only the exception's class is shown
        raise ResultFileError(f"{name}: not a readable Inspect AI log for the installed inspect_ai "
                              f"({type(exc).__name__})") from None

    if header.status != "success":
        status = header.status if header.status in _STATUS_HELP else "unknown"
        raise ResultFileError(f"{name}: status is {status!r}, not 'success': {_STATUS_HELP.get(status, '')}".rstrip(": "))
    if header.invalidated:
        raise ResultFileError(f"{name}: some samples in this log were invalidated; the log does not say which "
                              "trials to keep")
    if header.results is None:
        raise ResultFileError(f"{name}: the log has no results")
    total = header.results.total_samples
    if total is not None and total != len(summaries):
        raise ResultFileError(f"{name}: the log lists {total} sample-epochs but holds {len(summaries)}")
    if not summaries:
        raise ResultFileError(f"{name}: no samples")

    names = list(dict.fromkeys(k for s in summaries for k in (s.scores or {})))
    if scorer is None:
        if len(names) != 1:
            raise ResultFileError(f"{name}: the log has {len(names)} scorers ({_names(names)}); "
                                  "choose one with --scorer (scorer= in Python)" if names else f"{name}: no scores")
        scorer = names[0]
    elif scorer not in names:
        raise ResultFileError(f"{name}: no scorer named {_names([scorer]) or 'that'}; the log has {_names(names)}")

    seen_ids: dict[str, object] = {}
    seen_trials: set[tuple[str, int]] = set()
    fingerprints: dict[str, str] = {}
    per_case: dict[str, list[tuple[int, bool]]] = {}
    errored_cases: set[str] = set()
    unscored_cases: set[str] = set()
    errored = unscored = retried = 0
    for s in summaries:
        cid = str(s.id)
        shown = _task(cid)
        if cid in seen_ids and seen_ids[cid] != s.id:
            raise ResultFileError(f"{name}: sample ids {shown} of different types (number and text) collide")
        seen_ids[cid] = s.id
        if (cid, s.epoch) in seen_trials:
            raise ResultFileError(f"{name}: {shown} epoch {s.epoch}: the log repeats the same sample and epoch")
        seen_trials.add((cid, s.epoch))
        fp = _fingerprint(s.input, s.target)
        if fingerprints.setdefault(cid, fp) != fp:
            raise ResultFileError(f"{name}: {shown}: the epochs of this sample have different inputs or targets")
        if s.retries and s.error is None:  # succeeded only after a retry
            retried += 1
        if s.error is not None:
            kind = "an error"
            outcome = None
            errored += 1
            errored_cases.add(cid)
        else:
            score = (s.scores or {}).get(scorer)
            if score is None:
                raise ResultFileError(f"{name}: {shown} epoch {s.epoch}: no score from {_names([scorer])} and no error")
            try:
                outcome = _inspect_value(score.value)
            except _NotPassFail:
                raise ResultFileError(
                    f"{name}: {shown} epoch {s.epoch}: scorer {_names([scorer])} gave a {type(score.value).__name__} "
                    "value that is not pass/fail (partial credit and other values are not read)") from None
            if outcome is None:
                kind = "an unscored value (NaN)"
                unscored += 1
                unscored_cases.add(cid)
        if outcome is None:
            if errors == "error":
                raise ResultFileError(f"{name}: {shown} epoch {s.epoch}: {kind}; use --errors drop or fail to read "
                                      "this log")
            if errors == "drop":
                continue
            outcome = False
        per_case.setdefault(cid, []).append((s.epoch, outcome))

    emptied = [c for c in seen_ids if c not in per_case]
    if emptied:
        raise ResultFileError(f"{name}: {_task(emptied[0])} ({len(emptied)} sample(s) in all): every epoch errored or "
                              "is unscored, so dropping them would remove the sample; use --errors fail to count "
                              "them as failures")
    outcomes = {c: [ok for _, ok in sorted(per_case[c])] for c in seen_ids}
    spec = header.eval
    reducers = spec.config.epochs_reducer
    args_blob = json.dumps(spec.task_args, sort_keys=True, default=str)
    return InspectOutcomes(
        outcomes=outcomes, task=spec.task, model=spec.model, scorer=scorer, epochs=spec.config.epochs, errors=errors,
        errored=errored, errored_cases=len(errored_cases), unscored=unscored, unscored_cases=len(unscored_cases),
        retried=retried, reducer_not_mean=bool(reducers) and any(r != "mean" for r in reducers),
        task_version=str(spec.task_version), task_args_digest=hashlib.sha256(args_blob.encode()).hexdigest(),
        dataset_name=spec.dataset.name, dataset_samples=spec.dataset.samples,
        dataset_shuffled=bool(spec.dataset.shuffled), fingerprints=fingerprints)


def check_inspect_pairing(baseline: InspectOutcomes, candidate: InspectOutcomes) -> list[str]:
    """Check that two Inspect logs can be compared case by case; returns warnings, raises when they cannot.

    Raises when the tasks differ, or when a sample (same input and target) appears in both logs under different
    ids, as happens when a dataset without ids is numbered after shuffling. Other differences in a sample's input or
    target, task arguments, task version, dataset, scorer or epochs give warnings.
    """
    if baseline.task != candidate.task:
        raise ValueError(f"baseline and candidate are different Inspect tasks ({_task(baseline.task)} and "
                         f"{_task(candidate.task)}); a paired comparison needs the same samples")
    warnings = []
    ids_a: dict[str, set[str]] = {}
    ids_b: dict[str, set[str]] = {}
    for c, fp in baseline.fingerprints.items():
        ids_a.setdefault(fp, set()).add(c)
    for c, fp in candidate.fingerprints.items():
        ids_b.setdefault(fp, set()).add(c)
    moved = [fp for fp in ids_a.keys() & ids_b.keys() if ids_a[fp] != ids_b[fp]]
    if moved:
        raise ResultFileError(
            f"{len(moved)} sample(s) appear in both logs under different ids, so pairing by id would compare different "
            "samples; this happens when a dataset without ids is shuffled differently. Give the samples ids")
    shared = baseline.fingerprints.keys() & candidate.fingerprints.keys()
    differ = [c for c in shared if baseline.fingerprints[c] != candidate.fingerprints[c]]
    if differ:
        shuffled = " One of the logs comes from a shuffled dataset." if (
            baseline.dataset_shuffled or candidate.dataset_shuffled) else ""
        warnings.append(f"{len(differ)} case(s) have a different input or target in the two logs. This is expected "
                        "if you changed the prompts or targets; otherwise the logs may hold different samples under "
                        f"the same ids (for example different subsets).{shuffled}")
    if baseline.task_version != candidate.task_version:
        warnings.append("baseline and candidate ran different versions of the task.")
    if baseline.task_args_digest != candidate.task_args_digest:
        warnings.append("baseline and candidate ran the task with different arguments; the change includes them.")
    if (baseline.dataset_name, baseline.dataset_samples) != (candidate.dataset_name, candidate.dataset_samples):
        warnings.append("baseline and candidate logs name different datasets or dataset sizes.")
    if baseline.scorer != candidate.scorer:
        warnings.append("baseline and candidate were read with different scorers; the change includes that difference.")
    if baseline.epochs != candidate.epochs:
        warnings.append("baseline and candidate were run with different numbers of epochs.")
    return warnings
