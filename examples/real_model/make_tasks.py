"""Generate the real-model demo task set (examples/real_model/PROTOCOL.md, "Task set"). No model calls.

    python examples/real_model/make_tasks.py   # writes examples/real_model/tasks.jsonl

Determined only by the seed and the rules below; answers are computed here.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

SEED = 20261120
PER_FAMILY = 10
OUT = Path(__file__).resolve().parent / "tasks.jsonl"

FORMS = {
    "arithmetic": "an integer with no units or separators",
    "letters": "an integer",
    "weekday": "the full English weekday name, e.g. Monday",
    "sort": "the numbers separated by commas, no spaces",
}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
FILLERS = ["The report lists", "Someone wrote down", "A note mentions", "The board shows", "A log contains"]


def arithmetic(rng):
    a, b = int(rng.integers(3, 20)), int(rng.integers(4, 30))
    c, d = int(rng.integers(1, a * b)), int(rng.integers(2, 10))
    q = (f"A shop has {a} boxes with {b} items in each box. It sells {c} items and then receives "
         f"{d} more boxes of {b} items. How many items does it have now?")
    return q, str(a * b - c + d * b)


def letters(rng):
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    while True:
        pool = rng.choice(list(alphabet), size=6, replace=False)
        word = "".join(rng.choice(pool, size=int(rng.integers(9, 15))))
        counts = {ch: word.count(ch) for ch in set(word)}
        eligible = sorted(ch for ch, n in counts.items() if 2 <= n <= 5)
        if eligible:
            x = eligible[int(rng.integers(len(eligible)))]
            return f"How many times does the letter '{x}' appear in the word '{word}'?", str(counts[x])


def weekday(rng):
    start, end = dt.date(2026, 1, 1), dt.date(2030, 12, 31)
    day = start + dt.timedelta(days=int(rng.integers(0, (end - start).days + 1)))
    n = int(rng.integers(20, 401))
    answer = WEEKDAYS[(day + dt.timedelta(days=n)).weekday()]
    return f"What day of the week is {n} days after {day.isoformat()}?", answer


def sort_numbers(rng):
    k = int(rng.integers(5, 8))
    nums = [int(v) for v in rng.choice(np.arange(1, 1000), size=k, replace=False)]
    sentence = f"{FILLERS[int(rng.integers(len(FILLERS)))]} " + ", then ".join(map(str, nums)) + "."
    return f"List the numbers in this sentence in ascending order: {sentence}", ",".join(map(str, sorted(nums)))


GENERATORS = {"arithmetic": arithmetic, "letters": letters, "weekday": weekday, "sort": sort_numbers}


def build(seed: int = SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    tasks = []
    for family, gen in GENERATORS.items():
        for i in range(PER_FAMILY):
            question, answer = gen(rng)
            tasks.append({"case_id": f"{family}-{i:02d}", "family": family,
                          "user": f"{question}\n\nGive the answer in this form: {FORMS[family]}",
                          "answer": answer})
    return tasks


def main(argv: list[str] | None = None) -> int:
    out = Path((argv or sys.argv[1:] or [str(OUT)])[0])
    text = "\n".join(json.dumps(t, ensure_ascii=True) for t in build()) + "\n"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {out} ({PER_FAMILY * len(GENERATORS)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
