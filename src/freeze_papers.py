"""Freeze the paper sample. Run once, before any model is called.

Run with:  uv run src/freeze_papers.py

Takes the first N papers that passed in data/paper_candidates.jsonl (they
are already in seed-14 order) and writes data/papers.jsonl: identifier,
version, title, link and a fingerprint of the cleaned text.

The paper text itself is NOT stored in this repo, because we do not have
the right to republish it. Run src/fetch_papers.py to download it.
"""

import json
from pathlib import Path

N = 25
CANDIDATES = Path("data/paper_candidates.jsonl")
OUT = Path("data/papers.jsonl")


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT} already exists. The sample is frozen; do not overwrite it.")
    rows = [json.loads(line) for line in CANDIDATES.read_text().splitlines()]
    chosen = [r for r in rows if r["status"] == "ok"][:N]
    assert len(chosen) == N, f"only {len(chosen)} papers passed"
    with OUT.open("w") as f:
        for n, r in enumerate(chosen, 1):
            f.write(
                json.dumps(
                    {
                        "paper": f"P{n:02d}",
                        "arxiv_id": r["arxiv_id"],
                        "version": r["version"],
                        "title": r["title"],
                        "url": f"https://arxiv.org/abs/{r['arxiv_id']}v{r['version']}",
                        "first_posted": r["published"][:10],
                        "subject": r["primary"],
                        "chars": r["chars"],
                        "sha256": r["sha256"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"Froze {N} papers to {OUT}")


if __name__ == "__main__":
    main()
