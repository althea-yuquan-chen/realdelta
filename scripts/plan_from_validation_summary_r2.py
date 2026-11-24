"""Apply the round-2 decision rule (plan_from_validation_round2_protocol_20261124; post-hoc) to methods.json.

    python scripts/plan_from_validation_summary_r2.py OUT_DIR
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

POWER_ERR = (-0.10, 0.05)
MAE_MAX = 0.15
P90_MAX = 0.20
FA_ERR = 0.03
ORACLE_ERR = 0.03
MIN_GATED = 20
MIN_GATED_P90 = 50  # the p90 criterion applies to decision cells with at least this many gated suites
F_MIN_CANDIDATES = [3, 6, 10]
METHODS = ["P-pooled", "P-uniform", "Plug-in"]


def setting_of(cell):
    return "|".join(cell.split("|")[:3])


def errors(rows, meth, key, f_min):
    return np.array([r["est"][meth][key] - r["true"][key] for r in rows if r["true"]["fails_star"] >= f_min])


def check(rec, meth, f_min, decision):
    """Failures of one method at one gate: lists of (cell, value) per criterion, and the pooled |errors|."""
    bad = {"bias": [], "mae": [], "p90": [], "fa": []}
    pooled = []
    for c in decision:
        e = errors(rec["cells"][c], meth, "power", f_min)
        pooled += list(np.abs(e))
        if not POWER_ERR[0] <= e.mean() <= POWER_ERR[1]:
            bad["bias"].append((c, float(e.mean())))
        if np.abs(e).mean() > MAE_MAX:
            bad["mae"].append((c, float(np.abs(e).mean())))
        if len(e) >= MIN_GATED_P90 and np.quantile(np.abs(e), 0.9) > P90_MAX:
            bad["p90"].append((c, float(np.quantile(np.abs(e), 0.9))))
    fa = defaultdict(list)  # (setting, n_plan) -> errors; the null does not depend on the change
    seen = set()
    for c, rows in rec["cells"].items():
        key = (setting_of(c), c.split("|")[-1])
        if key in seen:
            continue
        seen.add(key)
        fa[key] = errors(rows, meth, "false_alarm", f_min)
    for key, e in fa.items():
        if len(e) >= MIN_GATED and abs(e.mean()) > FA_ERR:
            bad["fa"].append(("|".join(key), float(e.mean())))
    return bad, pooled


def error_bands(rec, f_min, decision, min_n=100):
    """p90 of P-pooled's |error| by the file's F* band; a band with fewer than min_n suite-cells merges into the
    band below it (the lowest band merges upward)."""
    edges = sorted({f_min, 10, 20})
    edges = [e for e in edges if e >= f_min] + [10**9]
    bands = [[edges[i], edges[i + 1], []] for i in range(len(edges) - 1)]
    for c in decision:
        for r in rec["cells"][c]:
            f = r["true"]["fails_star"]
            for b in bands:
                if b[0] <= f < b[1]:
                    b[2].append(abs(r["est"]["P-pooled"]["power"] - r["true"]["power"]))
    while len(bands) > 1:
        small = [i for i, b in enumerate(bands) if len(b[2]) < min_n]
        if not small:
            break
        i = small[-1]  # highest small band first
        j = i - 1 if i > 0 else 1
        lo, hi = min(bands[i][0], bands[j][0]), max(bands[i][1], bands[j][1])
        bands[j] = [lo, hi, bands[j][2] + bands[i][2]]
        del bands[i]
    assert len(bands) == 1 or all(len(b[2]) >= min_n for b in bands)
    return {f"[{lo}, {'inf' if hi == 10**9 else hi})": (float(np.quantile(e, 0.9)), len(e)) for lo, hi, e in bands if e}


def main(out: Path) -> None:
    rec = json.loads((out / "methods.json").read_text())
    gates = json.loads((out / "decision_cells.json").read_text())["gates"]
    lines = [f"round {rec['round']} (post-hoc); protocol sha256: {rec['protocol_sha256']}", ""]

    oracle_bad = []
    for c, rows in rec["cells"].items():
        e = np.array([r["est"]["Oracle"]["power"] - r["true"]["power"] for r in rows])
        if abs(e.mean()) > ORACLE_ERR:
            oracle_bad.append((c, float(e.mean())))
    lines.append(f"Oracle control: {'PASS' if not oracle_bad else 'FAIL'} "
                 f"(cells with |mean error| > {ORACLE_ERR}, all suites: {len(oracle_bad)})")
    for c, e in oracle_bad[:5]:
        lines.append(f"  {c}: {e:+.3f}")

    chosen = None
    results = {}
    for f_min in F_MIN_CANDIDATES:
        g = gates[str(f_min)]
        decision = sorted(g["decision_cells"])
        lines += ["", f"== F_min {f_min}: eligible {g['eligible']}; {len(decision)} decision cells; "
                      f"coverage by m {g['coverage_by_m']}"]
        if not g["eligible"]:
            continue
        for meth in METHODS:
            bad, pooled = check(rec, meth, f_min, decision)
            ok = not any(bad.values())
            results[(f_min, meth)] = (ok, bad, pooled)
            lines.append(f"  {meth}: {'MEETS ALL' if ok else 'FAILS'}; pooled p90 |error| "
                         f"{np.quantile(pooled, 0.9):.3f}; cells failing bias {len(bad['bias'])}, MAE "
                         f"{len(bad['mae'])}, p90 {len(bad['p90'])}; false-alarm cells {len(bad['fa'])}")
            for crit in ("bias", "mae", "p90", "fa"):
                for c, val in bad[crit]:
                    lines.append(f"    {crit}: {c}: {val:+.3f}" if crit in ("bias", "fa") else f"    {crit}: {c}: {val:.3f}")
        if chosen is None and results[(f_min, "P-pooled")][0]:
            chosen = f_min

    lines.append("")
    if oracle_bad:
        lines.append("Decision: void (Oracle control failed); nothing ships")
    elif chosen is None:
        lines.append("Decision: no eligible F_min at which P-pooled meets every criterion; nothing ships; "
                     "plan --from is shelved (no round 3)")
    elif results[(chosen, "P-uniform")][0]:
        lines.append(f"Decision: void (negative control P-uniform meets every criterion at F_min {chosen}); "
                     "nothing ships")
    else:
        lines.append(f"Decision: F_min = {chosen}; P-pooled ships within the validated range")
        if results[(chosen, "Plug-in")][0]:
            lines.append("  Plug-in also meets every criterion at this F_min: the criteria did not separate P-pooled "
                         "from Plug-in; no advantage is claimed for P-pooled.")
        lines.append("  validated single-file error, p90 of |error| by F* band (printed by the tool):")
        for band, (p90, n) in error_bands(rec, chosen, sorted(gates[str(chosen)]["decision_cells"])).items():
            lines.append(f"    F* in {band}: {p90:.3f} ({n} suite-cells)")
        lines.append("  validated distributions x m (decision cells): " +
                     ", ".join(f"{k}: {v}" for k, v in sorted(gates[str(chosen)]["cells_by_dist_m"].items())))

    f_rep = chosen if chosen is not None else F_MIN_CANDIDATES[0]
    lines += ["", f"Reported (not decisive), at F_min {f_rep}:"]
    g = gates[str(f_rep)]
    decision = sorted(g["decision_cells"])
    lines.append(f"  per decision cell: gated suites, p90 criterion applies (>= {MIN_GATED_P90}), p90 |error| per method")
    for c in decision:
        rows = rec["cells"][c]
        n = sum(r["true"]["fails_star"] >= f_rep for r in rows)
        p90s = "  ".join(f"{m} {np.quantile(np.abs(errors(rows, m, 'power', f_rep)), 0.9):.3f}"
                         for m in METHODS + ["Oracle"])
        lines.append(f"    {c:58s} n={n:3d} {'yes' if n >= MIN_GATED_P90 else 'no '}  {p90s}")
    tally = defaultdict(lambda: [0, 0])
    for c in decision:
        dm = "|".join(c.split("|")[:2])
        tally[dm][1] += 1
        tally[dm][0] += sum(r["true"]["fails_star"] >= f_rep for r in rec["cells"][c]) >= MIN_GATED_P90
    lines.append("  p90-constrained cells / decision cells, by distribution x m: " +
                 ", ".join(f"{k}: {a}/{b}" for k, (a, b) in sorted(tally.items())))
    pp = [(c, float(np.quantile(np.abs(errors(rec["cells"][c], "P-pooled", "power", f_rep)), 0.9))) for c in decision]
    if pp:
        worst = max(pp, key=lambda x: x[1])
        lines.append(f"  worst decision-cell p90 |error| of P-pooled (upper bound for the printed bands): "
                     f"{worst[1]:.3f} ({worst[0]})")
    any_rows = {}
    for c, rows in rec["cells"].items():
        any_rows.setdefault(setting_of(c), rows)
    lines.append("  refusal rate (files with F* < F_min) by setting:")
    for s, rows in sorted(any_rows.items()):
        lines.append(f"    {s}: {np.mean([r['true']['fails_star'] < f_rep for r in rows]):.2f}")
    diffs = []
    for c in decision:
        for r in rec["cells"][c]:
            if r["true"]["fails_star"] >= f_rep:
                diffs.append(abs(r["est"]["P-pooled"]["power"] - r["true"]["power"])
                             - abs(r["est"]["Plug-in"]["power"] - r["true"]["power"]))
    if diffs:
        lines.append(f"  paired |error| P-pooled minus Plug-in over decision cells: mean {np.mean(diffs):+.4f}, "
                     f"P-pooled smaller in {np.mean(np.array(diffs) < 0):.1%}, equal in "
                     f"{np.mean(np.array(diffs) == 0):.1%} of {len(diffs)} suite-cells")
    groups = defaultdict(dict)
    for c, rows in rec["cells"].items():
        groups["|".join(c.split("|")[:-1])][int(c.split("=")[-1])] = rows
    agree = defaultdict(lambda: [0, 0])
    for by_n in groups.values():
        ns = sorted(by_n)
        for j in range(len(by_n[ns[0]])):
            if by_n[ns[0]][j]["true"]["fails_star"] < f_rep:
                continue
            first = lambda get: next((n for n in ns if get(by_n[n][j]) >= 0.8), None)  # noqa: E731
            truth = first(lambda r: r["true"]["power"])
            for meth in METHODS + ["Oracle"]:
                agree[meth][0] += first(lambda r: r["est"][meth]["power"]) == truth
                agree[meth][1] += 1
    for meth, (a, n) in agree.items():
        lines.append(f"  first n_plan reaching 0.8 agrees with truth: {meth} {a}/{n} ({a / n:.1%})")
    text = "\n".join(lines) + "\n"
    (out / "summary.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
