"""Download the frozen papers and check they match the fingerprints.

Run with:  uv run src/fetch_papers.py

For each paper in data/papers.jsonl this downloads arXiv's web-page
version, cleans it to plain text with the rules in src/papers.py, and
compares the result with the recorded fingerprint. Matching text is saved
under data/papers_text/, which git ignores.

If a fingerprint does not match, arXiv has probably regenerated that web
page since the sample was frozen. The script says so and does not save
the text, so a run can never silently use a different document.
"""

import json
from pathlib import Path

from papers import clean_text, fetch_html, fingerprint

MANIFEST = Path("data/papers.jsonl")
TEXT_DIR = Path("data/papers_text")


def load_papers() -> list[dict]:
    """The frozen papers with their text. Used by the other scripts."""
    papers = [json.loads(line) for line in MANIFEST.read_text().splitlines()]
    for p in papers:
        path = TEXT_DIR / f"{p['paper']}.txt"
        if not path.exists():
            raise SystemExit(f"{path} is missing. Run: uv run src/fetch_papers.py")
        p["text"] = path.read_text()
        assert fingerprint(p["text"]) == p["sha256"], f"{p['paper']} text does not match its fingerprint"
    return papers


def main() -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    papers = [json.loads(line) for line in MANIFEST.read_text().splitlines()]
    good = 0
    for p in papers:
        html = fetch_html(p["arxiv_id"], p["version"])
        if html is None:
            print(f"{p['paper']}  MISSING   arXiv has no web page for {p['arxiv_id']}v{p['version']}")
            continue
        text, _ = clean_text(html)
        if fingerprint(text) != p["sha256"]:
            print(f"{p['paper']}  MISMATCH  text differs from the frozen fingerprint")
            continue
        (TEXT_DIR / f"{p['paper']}.txt").write_text(text)
        good += 1
        print(f"{p['paper']}  ok        {len(text):>7,} characters  {p['title'][:60]}")
    print(f"\n{good} of {len(papers)} papers downloaded and verified.")


if __name__ == "__main__":
    main()
