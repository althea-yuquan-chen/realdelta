"""Every number the README quotes from the real-model run comes from the committed run outputs."""

import collections
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN = REPO / "examples" / "real_model" / "run_20261116"
TASKS = {t["case_id"]: t for t in map(json.loads, (REPO / "examples" / "real_model" / "tasks.jsonl")
                                      .read_text(encoding="utf-8").splitlines())}


def _readme():
    return " ".join((REPO / "README.md").read_text(encoding="utf-8").split())


def _analysis():
    text = (RUN / "summary.txt").read_text(encoding="utf-8")
    out = {}
    for block in text.split("$ python -m realdelta ")[1:]:
        cmd, rest = block.split("\n", 1)
        body = rest.rsplit("(exit", 1)[0].split("[stderr]")[0]
        out[cmd] = json.loads(body)
    return text, out


def _records():
    return [json.loads(line) for line in (RUN / "responses.jsonl").read_text(encoding="utf-8").splitlines()]


def test_readme_real_model_numbers_match_the_run():
    readme = _readme()
    summary, a = _analysis()
    for arm in ("a1", "a2", "b"):
        d = a[f"interval {arm}.jsonl --json"]
        assert f"| {arm.upper()} | {d['estimate']:.3f} | [{d['low']:.3f}, {d['high']:.3f}] |" in readme, arm
    pop = a["interval a1.jsonl --scope population --json"]
    assert f"{pop['estimate']:.3f} with interval [{pop['low']:.3f}, {pop['high']:.3f}]" in readme
    aa = a["compare a1.jsonl a2.jsonl --seed 0 --n-perm 10000 --conf 0.95 --json"]
    ab = a["compare a1.jsonl b.jsonl --seed 0 --n-perm 10000 --conf 0.95 --json"]
    assert not aa["detected"] and not ab["detected"]
    d = aa["delta"]
    assert f"A1 vs A2:** {d['estimate']:+.3f}, interval [{d['low']:+.3f}, {d['high']:+.3f}]. The A/A pair was not flagged." \
        in readme.replace("+-", "-")
    d = ab["delta"]
    assert (f"A1 vs B:** {d['estimate']:+.3f}. No change detected at this scale (40 cases, 5 trials); the interval "
            f"[{d['low']:+.3f}, {d['high']:+.3f}] bounds the change.") in readme.replace("+-", "-")
    assert "re-issues 0" in summary and "input tokens 51213, output tokens 52408" in summary
    assert "51,213 input and 52,408 output tokens" in readme
    for arm, counts in (("a1", "175, 1, 24, 0, 0, 0, 0, 0"), ("a2", "171, 1, 28, 0, 0, 0, 0, 0"),
                        ("b", "164, 2, 34, 0, 0, 0, 0, 0")):
        assert f"  {arm}: {counts}" in summary
    assert "A1 175 / 1 / 24, A2 171 / 1 / 28, B 164 / 2 / 34" in readme
    started = (RUN / "provenance.txt").read_text(encoding="utf-8").split("started: ")[1][:16]
    assert started == "2026-11-17T00:54" and "it started at 2026-11-17T00:54Z" in readme


def _value_correct(record):
    task = TASKS[record["case_id"]]
    lines = [ln for ln in record["text"].splitlines() if ln.strip()]
    if not lines:
        return False
    value = lines[-1].replace("*", "").replace("`", "").strip()
    if value.startswith("ANSWER:"):
        value = value[len("ANSWER:"):].strip()
    if value.endswith("."):
        value = value[:-1].rstrip()
    expected = task["answer"]
    if task["family"] == "sort":
        value, expected = value.replace(" ", ""), expected.replace(" ", "")
    if task["family"] == "weekday":
        value, expected = value.lower(), expected.lower()
    return value == expected


def test_readme_descriptive_numbers_match_the_responses():
    readme = _readme()
    records = _records()
    correct = {arm: sum(_value_correct(r) for r in records if r["arm"] == arm) for arm in ("a1", "a2", "b")}
    assert correct == {"a1": 196, "a2": 199, "b": 197}
    assert "A1 has 196 of 200 trials right, A2 199 and B 197" in readme
    nal = [r for r in records if r["category"] == "no_answer_line"]
    assert (len(nal), sum(map(_value_correct, nal))) == (86, 82)
    assert '82 of the 86 "no `ANSWER:` line" trials carry the right value' in readme
    fails = collections.Counter((r["case_id"].split("-")[0], r["arm"]) for r in records if r["category"] != "pass")
    for family in ("arithmetic", "letters", "weekday", "sort"):
        row = " | ".join(str(fails[(family, arm)]) for arm in ("a1", "a2", "b"))
        assert f"| {family} | {row} |" in readme, family
    per_case = collections.defaultdict(list)
    for r in records:
        per_case[(r["case_id"], r["arm"])].append(r["category"] == "pass")
    flaky = {arm: sum(0 < sum(v) < 5 for (c, a), v in per_case.items() if a == arm) for arm in ("a1", "a2", "b")}
    assert (min(flaky.values()), max(flaky.values())) == (15, 20)
    assert "15 to 20 cases per arm passed on some trials and failed on others" in readme
