"""Follow-up, run AFTER the main results were scored. Exploratory only.

In the main run, locate returned nothing on 49 of 200 questions. This
asks: was that down to how we worded the request?

Run with:
    uv run src/followup_locate.py

It re-asks locate in four ways and saves every reply under raw/followup/:
  same        the 49 silent questions, worded exactly as before
              (does it give the same empty reply twice?)
  find        the 49 silent questions as "Find the passage that answers ..."
  sentence    the 49 silent questions as "The sentence that answers ..."
  find_check  49 questions it DID answer, picked with seed 14, in the
              "find" wording (does the new wording lose answers it had?)

The main results in results/ are not changed by this script.
"""

import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from fetch_papers import load_papers
from run_arms import SEED, ask_locate, done_ids, save
from score import classify

WORDINGS = {
    "same": "{q}",
    "find": "Find the passage in the text that answers this question: {q}",
    "sentence": "The sentence in the text that answers this question: {q}",
}
OUT = Path("raw/followup")


def main() -> None:
    papers = {p["paper"]: p for p in load_papers()}
    questions = {}
    for line in Path("data/questions.jsonl").read_text().splitlines():
        q = json.loads(line)
        questions[q["id"]] = q
    main_run = [r for r in csv.DictReader(Path("results/scores.csv").open()) if r["arm"] == "Locate"]
    silent = [r["id"] for r in main_run if r["label"] == "miss"]
    answered = [r["id"] for r in main_run if r["label"] != "miss"]
    control = random.Random(SEED).sample(answered, len(silent))

    load_dotenv(".env")
    key = os.environ["PERPLEXITY_API_KEY"]
    runs = [("same", "same", silent), ("find", "find", silent), ("sentence", "sentence", silent), ("find_check", "find", control)]

    for name, wording, ids in runs:
        path = OUT / f"locate_{name}.jsonl"
        todo = [i for i in ids if i not in done_ids(path)]
        print(f"\n{name}: {len(todo)} to ask, {len(ids) - len(todo)} already saved -> {path}", flush=True)
        for n, i in enumerate(todo, 1):
            q = questions[i]
            instructions = WORDINGS[wording].format(q=q["question"])
            row = ask_locate(key, papers[q["paper"]]["text"], instructions)
            save(path, {"id": i, "instructions": instructions, **row})
            print(f"  {n}/{len(todo)} {i} {row['seconds']}s", flush=True)

    print("\nResults (exploratory, not part of the main table)\n")
    print(f"{'':<12}{'asked':>6}{'answered':>10}{'right place':>13}{'elsewhere':>11}{'not in paper':>14}{'still silent':>14}{'cost':>9}")
    for name, _, ids in runs:
        rows = [json.loads(line) for line in (OUT / f"locate_{name}.jsonl").read_text().splitlines()]
        assert sorted(r["id"] for r in rows) == sorted(ids), name
        labels = Counter()
        for r in rows:
            q = questions[r["id"]]
            spans = sorted(r["answer"]["spans"], key=lambda s: -s["score"])
            quote = spans[0]["text"] if spans else ""
            labels[classify(quote, papers[q["paper"]]["text"], q["reference"], spans=[(s["start"], s["end"]) for s in spans])] += 1
        cost = sum(r["usage"]["input_tokens"] for r in rows) / 1e6 * 0.01
        print(f"{name:<12}{len(rows):>6}{len(rows) - labels['miss']:>10}{labels['exact'] + labels['right_place']:>13}"
              f"{labels['elsewhere']:>11}{labels['made_up']:>14}{labels['miss']:>14}{cost:>9.4f}")


if __name__ == "__main__":
    main()
