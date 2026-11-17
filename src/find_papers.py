"""Milestone 2, step 1: find candidate research papers.

Run with:  uv run src/find_papers.py

Uses only arXiv's free public services. Writes data/paper_candidates.jsonl
(no paper text) and, for inspection only, the cleaned text of each
candidate under .cache/arxiv_text/. Nothing is frozen by this script.

A candidate must:
  1. be first submitted to arXiv between START and END (after the models'
     training cutoffs),
  2. have one of CATEGORIES as its main subject area (prose-heavy fields),
  3. have a web-page version on arXiv,
  4. clean up to between MIN_CHARS and MAX_CHARS of text,
  5. be mostly prose (MIN_PROSE_SHARE) with little maths (MAX_MATH_PER_1000).
     Numbers such as "95%" are often typed as maths, so the limit is a
     rate, not zero.

Papers are tried in a random order fixed by SEED, until WANT of them pass.
"""

import json
import random
from pathlib import Path

from papers import clean_text, fetch_html, fingerprint, list_papers, prose_share

START, END = "20261001", "20261110"
CATEGORIES = ["cs.HC", "cs.CY", "cs.SE", "econ.GN", "physics.soc-ph"]
SEED = 14
WANT = 40  # 25 plus reserves
MIN_CHARS, MAX_CHARS = 20_000, 80_000
MIN_PROSE_SHARE = 0.75
MAX_MATH_PER_1000 = 0.5  # inline maths expressions allowed per 1,000 characters

OUT = Path("data/paper_candidates.jsonl")
LIST_CACHE = Path(".cache/arxiv_listing.json")
TEXT_DIR = Path(".cache/arxiv_text")


def say(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    Path(".cache").mkdir(exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    say("Step 1 of 2: listing recent papers ...")
    if LIST_CACHE.exists():
        pool = json.loads(LIST_CACHE.read_text())
        say(f"Using saved listing of {len(pool):,} papers.")
    else:
        seen = {}
        for cat in CATEGORIES:
            found = list_papers(cat, START, END)
            mine = [p for p in found if p["primary"] == cat]
            for p in mine:
                seen[p["arxiv_id"]] = p
            say(f"  {cat}: {len(found):,} listed, {len(mine):,} with it as main subject")
        pool = list(seen.values())
        LIST_CACHE.write_text(json.dumps(pool, ensure_ascii=False))

    # The identifier starts with year and month of FIRST submission (2610 = Oct 2026).
    pool = [p for p in pool if p["arxiv_id"][:4] in ("2610", "2611")]
    pool.sort(key=lambda p: p["arxiv_id"])
    random.Random(SEED).shuffle(pool)
    say(f"{len(pool):,} papers in the pool, shuffled with seed {SEED}.")

    say(f"Step 2 of 2: reading papers in that order until {WANT} pass ...")
    rows, passed = [], 0
    for order, p in enumerate(pool, 1):
        html = fetch_html(p["arxiv_id"], p["version"])
        row = {k: p[k] for k in ("arxiv_id", "version", "title", "primary", "published")}
        row["order"] = order
        if html is None:
            row["status"] = "no web-page version"
        else:
            text, counts = clean_text(html)
            row.update(
                chars=len(text),
                words=len(text.split()),
                math=counts["math"],
                prose_share=round(prose_share(text), 2),
                sha256=fingerprint(text),
            )
            if not MIN_CHARS <= len(text) <= MAX_CHARS:
                row["status"] = "wrong length"
            elif counts["math"] / len(text) * 1000 > MAX_MATH_PER_1000:
                row["status"] = "too much maths"
            elif row["prose_share"] < MIN_PROSE_SHARE:
                row["status"] = "not mostly prose"
            else:
                row["status"] = "ok"
                passed += 1
                (TEXT_DIR / f"{p['arxiv_id']}v{p['version']}.txt").write_text(text)
        rows.append(row)
        OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        if order % 5 == 0 or passed == WANT:
            say(f"  tried {order}, {passed} passed so far")
        if passed == WANT:
            break

    say(f"\nDone. Tried {len(rows)} papers, {passed} passed. Written to {OUT}")


if __name__ == "__main__":
    main()
