"""Command line: ``realdelta interval | compare | plan`` (also ``python -m realdelta``).

Text output by default; ``--json`` prints one JSON object. Notes (always-on caveats) are part of the
report on stdout; warnings (conditions found in your data or options) go to stderr in text mode.
Exit code 0 on success, 2 on a usage or input error. With ``--json`` an input error is printed as
``{"error": ...}`` on stdout; argparse's own usage errors (unknown option, missing argument) are
still plain text on stderr.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Sequence

from .io import (INFRA_MODES, ResultFileError, check_inspect_pairing, load_inspect_log, load_outcomes,
                 load_tau2_results)
from .planner import estimate_cost, plan_trials
from .stats import compare, pass_rate_interval

README = "README, Limitations"

NOTE_ASSUMPTIONS = (
    "Assumptions A1, A3 and A5 cannot be checked from result files. In the tested settings: a case's trials "
    "that repeat each other (A1), or a run-level shock shared by one arm's cases such as an outage during one "
    "run (A5), made intervals too narrow; positive coupling between the arms (A3), modelled as a latent "
    "correlation, did not narrow them but cut power; negative coupling narrowed them; sharing run-level "
    f"shocks between the arms offset the A5 effect, fully only when both runs saw the same shock ({README})."
)
NOTE_P_VALUE = (
    "The p-value tests the sharp null 'the two versions behave identically on every case' and has not "
    "been calibration-checked. 'detected' uses the interval, not the p-value; the two can disagree."
)
NOTE_POPULATION = "The population scope assumes your cases are a random draw from the cases you care about (A2)."
NOTE_PLAN = (
    "Power and false-alarm rates are simulated for a synthetic suite with Beta(alpha, beta) case pass "
    "rates; they are not coverage claims. Standard errors are Monte Carlo."
)
NOTE_BREAK = (
    "The region column refers to cases and trials only. The gated delta rows are shifts of every case; "
    f"none has a few cases breaking outright, so break plans have no gated calibration evidence ({README})."
)
REGION_UNEQUAL = "unequal trials (one gated setting)"
NOTE_CASES = (
    "Per-case changes are descriptive: with a few trials per case a case's rate moves by chance, and no per-case "
    "test or multiple-comparison correction is applied."
)
CASE_GROUPS = (("now_fails_every_trial", "now fail every trial"), ("now_passes_every_trial", "now pass every trial"),
               ("other", "other changes"))
SHOW_CASES = 10


def _case_lines(changes) -> list[str]:
    lines = [f"Cases whose pass rate changed: {len(changes)} (descriptive; see the note below)"]
    for key, title in CASE_GROUPS:
        group = [c for c in changes if c.group == key]
        if not group:
            continue
        shown = f" (showing {SHOW_CASES} of {len(group)})" if len(group) > SHOW_CASES else ""
        lines.append(f"  {title}: {len(group)}{shown}")
        for c in group[:SHOW_CASES]:
            lines.append(f"    {ascii(_short(c.case_id))} {c.baseline_passes}/{c.baseline_trials} -> "
                         f"{c.candidate_passes}/{c.candidate_trials}")
    return lines
WARN_CONF = "Only the 95% level was checked; other levels are untested."
NOTE_TAU2_INFRA = (
    "tau2-bench files: simulations ended by an infrastructure error were dropped, as tau2's metrics are written to "
    "do (under pandas 3.1.1, tau2 at commit 768f3d8 counted them as failures instead; README, Result files). This "
    "keeps assumption A4 only if those errors do not depend on how the trial would have gone; use "
    "--errors fail to count them as failures instead."
)
NOTE_INSPECT_ERRORS = (
    "Inspect logs: samples that raised an error or were left unscored were dropped, as Inspect's own metrics do. "
    "An Inspect sample error can be any exception, including one caused by the agent's own actions, so dropping "
    "them keeps assumption A4 only if they do not depend on how the trial would have gone; use --errors fail to "
    "count them as failures instead."
)
NOTE_INSPECT_RETRIES = (
    "Inspect logs: some samples were scored only after a retry; their earlier attempts raised an error and are not "
    "counted as trials. This keeps assumption A4 only if whether a sample needed a retry does not depend on how it "
    "would have gone."
)
WARN_ARMS = (
    "Some cases have different trial counts in the two arms: the p-value is not exact and the grid "
    "has no evidence for unequal arms."
)


def _summary(outcomes) -> dict:
    counts = [len(v) for v in outcomes.values()]
    return {"cases": len(counts), "trials_min": min(counts), "trials_median": float(statistics.median(counts)),
            "trials_max": max(counts), "trials_total": sum(counts)}


def _unequal(summary: dict) -> bool:
    return summary["trials_min"] != summary["trials_max"]


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _rate_warnings(s: dict) -> list[str]:
    out = []
    if s["cases"] < 5:
        out.append(f"Fewer than 5 cases: no evidence for the pass-rate intervals (gated range 5-50 cases) ({README}).")
    if s["cases"] > 50 or s["trials_max"] > 10:
        out.append("More than 50 cases or more than 10 trials per case: untested range for the pass-rate "
                   f"intervals (gated range 5-50 cases, 1-10 trials) ({README}).")
    if _unequal(s):
        out.append("Trial counts differ between cases: two grid settings cover this for the pass rate; "
                   f"retries or dropped runs that depend on outcomes violate A4 ({README}).")
    return out


def _delta_region(cases: int, trials_min: int, trials_max: int, unequal: bool) -> tuple[str, list[str]]:
    out = []
    low = cases < 10 or (trials_min < 3 and not unequal)
    if cases < 10:
        out.append("Fewer than 10 cases: no gated evidence for the suite delta (gated range 10-50 cases, "
                   f"3-10 trials); Wilson bounds are known to under-cover with few trials near 100% ({README}).")
    if trials_min < 3 and not unequal:
        out.append("Fewer than 3 trials per case: no gated evidence for the suite delta (gated range 10-50 "
                   "cases, 3-10 trials); Wilson bounds are known to under-cover with few trials near 100% "
                   f"({README}; diagnostic DB covers part of this).")
    high = cases > 50 or trials_max > 10
    if high:
        out.append("More than 50 cases or more than 10 trials per case: untested range for the suite delta "
                   f"(gated range 10-50 cases, 3-10 trials) ({README}).")
    if unequal:
        out.append("Trial counts differ between cases: one grid setting covers this for the suite delta "
                   f"(30 cases, 1/3/10 trials); retries or dropped runs that depend on outcomes violate A4 ({README}).")
    if low:
        region = "below gated range"
    elif high:
        region = "above gated range"
    elif unequal:
        region = REGION_UNEQUAL
    else:
        region = "inside gated range"
    return region, out


def _emit(args, payload: dict, text_lines: list[str]) -> int:
    if args.json:
        print(json.dumps(payload, indent=1))
    else:
        print("\n".join(text_lines + [f"Note: {n}" for n in payload["notes"]]))
        for w in payload["warnings"]:
            print(f"Warning: {w}", file=sys.stderr)
    return 0


def _p_method(base, cand, args) -> str:
    if all(sum(cand[c]) / len(cand[c]) == sum(base[c]) / len(base[c]) for c in base):
        return "no case changed, so no permutation is needed"
    if len(base) <= 16:
        return "exact enumeration"
    return f"{args.n_perm} random sign flips, seed {args.seed}"


def _label(name: str, meta: dict | None) -> str:
    if meta and meta["format"] == "inspect":
        return f"{name} (model {ascii(_short(meta['model'], 60))}, scorer {ascii(_short(meta['scorer']))})"
    return name


def _fmt_summary(label: str, s: dict) -> str:
    return (f"{label}: {s['cases']} cases, trials per case min {s['trials_min']} / median "
            f"{s['trials_median']:g} / max {s['trials_max']}, {s['trials_total']} trials in total")


def _is_inspect_json(p: Path) -> bool:
    """An Inspect AI log saved as JSON has a top-level ``version`` and an ``eval`` object naming its task;
    tau2-bench results files have neither."""
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return False
    return (isinstance(data, dict) and "version" in data and isinstance(data.get("eval"), dict)
            and "task" in data["eval"])


def _format(path: str) -> str:
    p = Path(path)
    if p.is_dir():
        return "tau2"
    suffix = p.suffix.lower()
    if suffix == ".eval":
        return "inspect"
    if suffix == ".json":
        return "inspect" if p.is_file() and _is_inspect_json(p) else "tau2"
    return "plain"


def _read_inspect(path: str, args, label: str) -> tuple[dict, dict, list[str]]:
    res = load_inspect_log(path, scorer=args.scorer, errors=args.errors)
    meta = {"format": "inspect", "task": res.task, "model": res.model, "scorer": res.scorer, "epochs": res.epochs,
            "errors": res.errors, "errored": res.errored, "unscored": res.unscored, "retried": res.retried,
            "dropped": (res.errored + res.unscored) if res.errors == "drop" else 0, "_res": res}
    verb = "dropped" if res.errors == "drop" else "counted as failures"
    warnings = []
    if res.errored:
        warnings.append(f"{label}: {res.errored} sample-epoch(s) that raised an error ({res.errored_cases} sample(s)) "
                        f"were {verb}.")
    if res.unscored:
        warnings.append(f"{label}: {res.unscored} unscored sample-epoch(s) ({res.unscored_cases} sample(s)) were "
                        f"{verb}.")
    if res.retried:
        warnings.append(f"{label}: {res.retried} sample-epoch(s) were scored only after a retry.")
    if res.reducer_not_mean:
        warnings.append(f"{label}: the log reduces epochs with something other than the mean, so its headline score "
                        "is a different quantity from the pass rate here.")
    return res.outcomes, meta, warnings


def _read(path: str, args, label: str) -> tuple[dict, dict | None, list[str]]:
    """Outcomes, format metadata (None for .jsonl/.csv) and warnings for one input file."""
    kind = _format(path)
    if kind != "inspect" and args.scorer is not None:
        raise ValueError(f"--scorer applies to Inspect AI logs only; {Path(path).name} is not one")
    if kind == "plain":
        return load_outcomes(path), None, []
    if kind == "inspect":
        return _read_inspect(path, args, label)
    res = load_tau2_results(path, infra_errors=args.errors)
    meta = {"format": "tau2", "domain": res.domain, "num_trials": res.num_trials, "user_llm": res.user_llm,
            "errors": args.errors, "infra_dropped": res.infra_dropped,
            "unscored_failures": res.unscored_failures, "trials_from_file_order": res.trials_from_file_order}
    warnings = []
    if res.infra_dropped:
        warnings.append(f"{label}: {res.infra_dropped} simulation(s) ended by an infrastructure error were dropped.")
    if res.unscored_failures:
        warnings.append(f"{label}: {res.unscored_failures} simulation(s) without a reward were counted as failures.")
    if res.trials_from_file_order:
        warnings.append(f"{label}: no trial numbers in the file; trials were numbered in file order, so repeated "
                        "trials could not be detected.")
    if res.domain is None:
        warnings.append(f"{label}: the file does not name its domain.")
    return res.outcomes, meta, warnings


def _public(meta: dict | None) -> dict:
    """The format metadata for the JSON payload, under its format's key (no internal fields)."""
    if not meta:
        return {}
    return {meta["format"]: {k: v for k, v in meta.items() if not k.startswith("_")}}


def _format_notes(*metas) -> list[str]:
    notes = []
    if any(m and m["format"] == "tau2" and m["infra_dropped"] for m in metas):
        notes.append(NOTE_TAU2_INFRA)
    if any(m and m["format"] == "inspect" and m["dropped"] for m in metas):
        notes.append(NOTE_INSPECT_ERRORS)
    if any(m and m["format"] == "inspect" and m["retried"] for m in metas):
        notes.append(NOTE_INSPECT_RETRIES)
    return notes


def _cmd_interval(args) -> int:
    outcomes, meta, read_warnings = _read(args.file, args, Path(args.file).name)
    s = _summary(outcomes)
    iv = pass_rate_interval(outcomes, scope=args.scope, conf=args.conf)
    notes = ([NOTE_POPULATION] if args.scope == "population" else []) + _format_notes(meta)
    warnings = ([WARN_CONF] if args.conf != 0.95 else []) + read_warnings + _rate_warnings(s)
    summary = {**s, **_public(meta)}
    payload = {"command": "interval", "file": Path(args.file).name, "scope": args.scope, "conf": args.conf,
               "estimate": iv.estimate, "low": iv.low, "high": iv.high, "summary": summary,
               "notes": notes, "warnings": warnings}
    lines = [_fmt_summary(_label(Path(args.file).name, meta), s),
             f"Pass rate ({args.scope} scope): {iv.estimate:.4f}, {args.conf:.0%} interval [{iv.low:.4f}, {iv.high:.4f}]"]
    return _emit(args, payload, lines)


def _cmd_compare(args) -> int:
    base, mb, wb = _read(args.baseline, args, "baseline")
    cand, mc, wc = _read(args.candidate, args, "candidate")
    if mb and mc and mb["format"] == mc["format"] == "inspect":
        wc.extend(check_inspect_pairing(mb["_res"], mc["_res"]))
    if mb and mc and mb["format"] == mc["format"] == "tau2":
        if mb["domain"] and mc["domain"] and mb["domain"] != mc["domain"]:
            raise ValueError(f"baseline and candidate are different tau2-bench domains ({_short(mb['domain'])!a} and "
                             f"{_short(mc['domain'])!a}); a paired comparison needs the same tasks")
        if mb["num_trials"] != mc["num_trials"]:
            wc.append("baseline and candidate tau2-bench runs were set up with different numbers of trials.")
        if mb["user_llm"] != mc["user_llm"]:
            wc.append("baseline and candidate tau2-bench runs used different user simulators; the change includes "
                      "that difference.")
    only_base, only_cand = set(base) - set(cand), set(cand) - set(base)
    if only_base or only_cand:
        sample = sorted(only_base | only_cand)[:3]
        raise ValueError(f"baseline and candidate cover different cases: {len(only_base)} only in baseline, "
                         f"{len(only_cand)} only in candidate (for example {', '.join(map(ascii, map(_short, sample)))})")
    sb, sc = _summary(base), _summary(cand)
    result = compare(base, cand, scope=args.scope, conf=args.conf, n_perm=args.n_perm, seed=args.seed)
    unequal = _unequal(sb) or _unequal(sc)
    region, region_warnings = _delta_region(sb["cases"], min(sb["trials_min"], sc["trials_min"]),
                                            max(sb["trials_max"], sc["trials_max"]), unequal)
    warnings = ([WARN_CONF] if args.conf != 0.95 else []) + wb + wc + region_warnings
    if any(len(base[c]) != len(cand[c]) for c in base):
        warnings.append(WARN_ARMS)
    d = result.delta
    notes = [NOTE_ASSUMPTIONS, NOTE_P_VALUE, NOTE_CASES] + _format_notes(mb, mc)
    payload = {"command": "compare", "baseline": {"file": Path(args.baseline).name, **sb, **_public(mb)},
               "candidate": {"file": Path(args.candidate).name, **sc, **_public(mc)},
               "scope": args.scope, "conf": args.conf,
               "delta": {"estimate": d.estimate, "low": d.low, "high": d.high}, "detected": result.detected,
               "p_value": result.p_value, "n_perm": args.n_perm, "seed": args.seed, "region": region,
               "case_changes": {"note": NOTE_CASES, "cases": [
                   {"case_id": c.case_id, "baseline": {"passes": c.baseline_passes, "trials": c.baseline_trials},
                    "candidate": {"passes": c.candidate_passes, "trials": c.candidate_trials},
                    "change": c.change, "group": c.group} for c in result.case_changes]},
               "notes": notes, "warnings": warnings}
    lines = [_fmt_summary(f"Baseline {_label(Path(args.baseline).name, mb)}", sb),
             _fmt_summary(f"Candidate {_label(Path(args.candidate).name, mc)}", sc),
             f"Change in pass rate (candidate - baseline, suite scope): {d.estimate:+.4f}, "
             f"{args.conf:.0%} interval [{d.low:+.4f}, {d.high:+.4f}]",
             f"Detected: {'yes' if result.detected else 'no'} (interval {'excludes' if result.detected else 'contains'} 0)",
             f"p-value: {result.p_value:.4g} (sign-flip permutation, " + _p_method(base, cand, args) + ")",
             f"Region: {region}"] + _case_lines(result.case_changes)
    return _emit(args, payload, lines)


def _cmd_plan(args) -> int:
    cost_flags = [args.input_tokens, args.output_tokens, args.usd_per_m_input, args.usd_per_m_output]
    if any(f is not None for f in cost_flags) and not all(f is not None for f in cost_flags):
        raise ValueError("cost flags are all-or-none: give --input-tokens, --output-tokens, "
                         "--usd-per-m-input and --usd-per-m-output together")
    change = "break" if args.break_cases is not None else "shift"
    rows = plan_trials(args.cases, delta=args.delta, trials_options=args.trials, alpha=args.alpha, beta=args.beta,
                       conf=args.conf, n_sim=args.n_sim, seed=args.seed, change=change, k=args.break_cases)
    out_rows, lines, warnings = [], [], ([WARN_CONF] if args.conf != 0.95 else [])
    header = f"{'trials':>6} {'power':>13} {'false alarms':>14} {'realised change':>16} {'runs':>7}"
    if all(f is not None for f in cost_flags):
        header += f" {'cost USD':>9}"
    header += "  region"
    lines += [f"Plan for {args.cases} cases, " + (f"shift {args.delta:+g}" if change == "shift"
                                                   else f"{args.break_cases} cases broken"),
              header]
    flagged = False
    for r in rows:
        region, _ = _delta_region(args.cases, r.trials, r.trials, False)
        flagged |= region != "inside gated range"
        row = {"trials": r.trials, "power": r.power, "power_se": r.power_se,
               "false_alarm_rate": r.false_alarm_rate, "false_alarm_se": r.false_alarm_se,
               "realised_change": r.realised_change, "total_runs": r.total_runs, "region": region}
        line = (f"{r.trials:>6} {r.power:>6.3f}+-{r.power_se:.3f} {r.false_alarm_rate:>7.3f}+-{r.false_alarm_se:.3f}"
                f" {r.realised_change:>+16.4f} {r.total_runs:>7}")
        if all(f is not None for f in cost_flags):
            cost = estimate_cost(args.cases, r.trials, 2, args.input_tokens, args.output_tokens,
                                 args.usd_per_m_input, args.usd_per_m_output)
            row["cost_usd"] = cost.usd
            line += f" {cost.usd:>9.2f}"
        out_rows.append(row)
        lines.append(f"{line}  {region}")
    if flagged:
        warnings.append("Some rows fall outside the suite delta's gated range (10-50 cases, 3-10 trials); "
                        f"their intervals have no gated calibration evidence ({README}).")
    payload = {"command": "plan", "change": change, "cases": args.cases, "delta": args.delta,
               "break_cases": args.break_cases, "alpha": args.alpha, "beta": args.beta, "conf": args.conf,
               "n_sim": args.n_sim, "seed": args.seed, "rows": out_rows,
               "notes": [NOTE_PLAN] + ([NOTE_BREAK] if change == "break" else []), "warnings": warnings}
    return _emit(args, payload, lines)


def _trials_list(text: str) -> list[int]:
    try:
        values = [int(t) for t in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("trials must be comma-separated whole numbers, e.g. 1,3,5") from None
    if not values or any(v < 1 for v in values):
        raise argparse.ArgumentTypeError("trials must be positive")
    return values


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a whole number") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return value


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    common.add_argument("--conf", type=float, default=0.95, help="confidence level (only 0.95 was checked)")
    files = argparse.ArgumentParser(add_help=False)
    files.add_argument("--errors", choices=INFRA_MODES, default="drop",
                       help="tau2-bench files: simulations ended by an infrastructure error; Inspect logs: samples "
                            "that raised an error or are unscored. drop them (as each tool's own metrics do), count "
                            "them as failures, or refuse the file")
    files.add_argument("--scorer", help="Inspect logs with several scorers: the scorer to read")
    parser = argparse.ArgumentParser(prog="realdelta", description="Is that change in your agent eval real, or noise?")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("interval", parents=[common, files], help="pass-rate interval for one result file")
    p.add_argument("file")
    p.add_argument("--scope", choices=("suite", "population"), default="suite")
    p.set_defaults(func=_cmd_interval)

    p = sub.add_parser("compare", parents=[common, files], help="paired comparison of two result files")
    p.add_argument("baseline")
    p.add_argument("candidate")
    p.add_argument("--scope", choices=("suite", "population"), default="suite",
                   help="population is not available in v0.1")
    p.add_argument("--n-perm", type=_positive, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=_cmd_compare)

    p = sub.add_parser("plan", parents=[common], help="simulated power and false alarms per trials option")
    p.add_argument("--cases", type=_positive, required=True)
    change = p.add_mutually_exclusive_group(required=True)
    change.add_argument("--delta", type=float, help="shift every case's pass rate by this amount")
    change.add_argument("--break-cases", type=_positive, help="set this many cases' pass rate to 0")
    p.add_argument("--trials", type=_trials_list, default=[1, 3, 5, 10, 20])
    p.add_argument("--alpha", type=float, default=8.0)
    p.add_argument("--beta", type=float, default=2.0)
    p.add_argument("--n-sim", type=_positive, default=300)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--input-tokens", type=_non_negative)
    p.add_argument("--output-tokens", type=_non_negative)
    p.add_argument("--usd-per-m-input", type=float)
    p.add_argument("--usd-per-m-output", type=float)
    p.set_defaults(func=_cmd_plan)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ResultFileError, ValueError, NotImplementedError, OSError, ImportError) as exc:
        if isinstance(exc, OSError):
            where = Path(exc.filename).name if exc.filename else "file"
            message = f"cannot read {where}: {exc.strerror}"
        else:
            message = str(exc)
        if args.json:
            print(json.dumps({"error": message}))
        else:
            print(f"Error: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
