"""Apply the pre-specified decision rule (plan_from_validation_protocol_20261123, Revisions 1-2) to methods.json.

    python scripts/plan_from_validation_summary.py OUT_DIR
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

CANDIDATES = ["P-Jeffreys", "P-uniform", "P-pooled"]
ALL = CANDIDATES + ["Plug-in", "Oracle"]
SIMPLICITY = {m: i for i, m in enumerate(CANDIDATES)}
POWER_ERR = (-0.10, 0.05)
MAE_MAX = 0.15
FA_ERR = 0.03
ORACLE_ERR = 0.03
TIE = 0.02


def main(out: Path) -> None:
    rec = json.loads((out / "methods.json").read_text())
    decision = set(rec["decision_cells"])
    power = {}  # (cell, method) -> (mean err, mae, p90)
    fa_err = defaultdict(list)  # ((setting, n_plan), method) -> errors
    for cell, rows in rec["cells"].items():
        setting = "|".join(cell.split("|")[:3])
        n_plan = cell.split("|")[-1]
        for meth in ALL:
            e = np.array([r["est"][meth]["power"] - r["true"]["power"] for r in rows])
            power[(cell, meth)] = (float(e.mean()), float(np.abs(e).mean()), float(np.quantile(np.abs(e), 0.9)))
            fa_err[((setting, n_plan), meth)] += [r["est"][meth]["false_alarm"] - r["true"]["false_alarm"] for r in rows]
    fa_mean = {k: float(np.mean(v)) for k, v in fa_err.items()}
    lines = [f"protocol sha256: {rec['protocol_sha256']}", f"decision cells: {len(decision)}", ""]

    oracle_bad = [(c, power[(c, "Oracle")][0]) for c in rec["cells"] if abs(power[(c, "Oracle")][0]) > ORACLE_ERR]
    lines.append(f"Oracle control: {'PASS' if not oracle_bad else 'FAIL'} "
                 f"(cells with |mean error| > {ORACLE_ERR}: {len(oracle_bad)})")
    for c, e in oracle_bad[:5]:
        lines.append(f"  {c}: {e:+.3f}")

    verdict = {}
    for meth in CANDIDATES + ["Plug-in"]:
        cells = sorted(decision)
        errs = [power[(c, meth)] for c in cells]
        bad_bias = [c for c, (me, _, _) in zip(cells, errs) if not POWER_ERR[0] <= me <= POWER_ERR[1]]
        bad_mae = [c for c, (_, mae, _) in zip(cells, errs) if mae > MAE_MAX]
        bad_fa = [k for (k, m), v in fa_mean.items() if m == meth and abs(v) > FA_ERR]
        worst_mae = max(mae for _, mae, _ in errs)
        mean_err = float(np.mean([me for me, _, _ in errs]))
        ok = not bad_bias and not bad_mae and not bad_fa
        verdict[meth] = (ok, worst_mae, mean_err)
        lines += ["", f"{meth}: {'ACCEPTABLE' if ok else 'NOT ACCEPTABLE'}; worst decision-cell MAE {worst_mae:.3f}; "
                  f"mean error over decision cells {mean_err:+.3f}",
                  f"  decision cells outside the bias band [{POWER_ERR[0]}, {POWER_ERR[1]}]: {len(bad_bias)}",
                  f"  decision cells with MAE > {MAE_MAX}: {len(bad_mae)}",
                  f"  false-alarm cells with |mean error| > {FA_ERR}: {len(bad_fa)}"]
        for c in (bad_bias + bad_mae)[:6]:
            me, mae, p90 = power[(c, meth)]
            lines.append(f"    {c}: mean error {me:+.3f}, MAE {mae:.3f}, p90 {p90:.3f}")

    acceptable = [m for m in CANDIDATES if verdict[m][0]]
    lines.append("")
    if not oracle_bad and acceptable:
        best = min(verdict[m][1] for m in acceptable)
        tied = [m for m in acceptable if verdict[m][1] - best < TIE]
        chosen = sorted(tied, key=lambda m: (verdict[m][2], SIMPLICITY[m]))[0]
        lines.append(f"Chosen: {chosen} (acceptable: {acceptable}; tied within {TIE}: {tied})")
    else:
        lines.append("Chosen: none (" + ("Oracle control failed" if oracle_bad else "no acceptable method") +
                     "); nothing ships this round")
    if verdict["Plug-in"][0]:
        lines.append("Negative control: Plug-in also passed every criterion; the criteria's power to discriminate is "
                     "in question.")

    # Secondary: first n_plan on {n_obs, 5, 10} reaching 0.8, estimate vs truth.
    lines.append("")
    agree = defaultdict(lambda: [0, 0])
    groups = defaultdict(dict)
    for cell, rows in rec["cells"].items():
        head, n_plan = "|".join(cell.split("|")[:-1]), int(cell.split("=")[-1])
        groups[head][n_plan] = rows
    for head, by_n in groups.items():
        ns = sorted(by_n)
        for j in range(len(by_n[ns[0]])):
            def first(get):
                return next((n for n in ns if get(by_n[n][j]) >= 0.8), None)
            truth = first(lambda r: r["true"]["power"])
            for meth in CANDIDATES + ["Plug-in", "Oracle"]:
                agree[meth][0] += first(lambda r: r["est"][meth]["power"]) == truth
                agree[meth][1] += 1
    for meth, (a, n) in agree.items():
        lines.append(f"Secondary, first n_plan reaching 0.8 agrees with truth: {meth} {a}/{n} ({a / n:.1%})")
    text = "\n".join(lines) + "\n"
    (out / "summary.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
