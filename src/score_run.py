"""Score saved model replies. Plain Python, no model involved.

Run with:
    uv run src/score_run.py smoke     # scores raw/smoke/, prints only
    uv run src/score_run.py full      # scores raw/, also writes results/scores.csv
"""

import csv
import json
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from fetch_papers import load_papers
from score import classify, exact_match, f1, find_all, is_verbatim, made_up_kind, place_score, tidy

# Dollars per million tokens, from each provider's pricing page (15 Nov 2026).
HAIKU_IN, HAIKU_OUT = 0.10, 0.50  # for prompts of 100K tokens or fewer
HAIKU_IN_LONG, HAIKU_OUT_LONG = 0.50, 2.50
LOCATE_IN = {"pplx-decider-flash-v1.3": 0.01, "pplx-decider-v1.3": 0.02}

LABELS = ["exact", "right_place", "elsewhere", "made_up", "miss", "parse_error"]


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def haiku_json(row: dict, text_key: str, flag_key: str) -> tuple[str | None, bool]:
    """(answer, parsed_ok). A reply we cannot read is a parse error, never 'made up'."""
    try:
        data = json.loads(row["reply_text"])
        text, flag = data[text_key], data[flag_key]
        if not isinstance(text, str) or not isinstance(flag, bool):
            return None, False
        return (text if flag else ""), True
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, False


def haiku_cost(row: dict) -> float:
    u = row["usage"]
    long_prompt = u["input_tokens"] > 100_000
    return (
        u["input_tokens"] / 1e6 * (HAIKU_IN_LONG if long_prompt else HAIKU_IN)
        + u["output_tokens"] / 1e6 * (HAIKU_OUT_LONG if long_prompt else HAIKU_OUT)
    )


def score_arm(name: str, rows: list[dict], questions: dict, papers: dict, kind: str) -> list[dict]:
    out = []
    for row in rows:
        q = questions[row["id"]]
        doc = papers[q["paper"]]["text"]
        ref = q["reference"]
        extra, positions = {}, None
        if kind == "haiku":
            quote, ok = haiku_json(row, "quote", "found")
            cost = haiku_cost(row)
            extra["thinking_tokens"] = (row["usage"].get("output_tokens_details") or {}).get("thinking_tokens", 0)
        else:
            # Locate returns positions. The quote we judge is its most confident
            # span; for "is it in the right place" all its spans count together.
            answer = row.get("answer")
            ok = isinstance(answer, dict) and isinstance(answer.get("spans"), list)
            spans = sorted(answer["spans"], key=lambda s: -s["score"]) if ok else []
            quote = spans[0]["text"] if spans else ""
            positions = [(s["start"], s["end"]) for s in spans]
            cost = row["usage"]["input_tokens"] / 1e6 * LOCATE_IN[row["model"]]
            extra["spans"] = len(spans)
            extra["offsets_ok"] = all(doc[s["start"]:s["end"]] == s["text"] for s in spans)
            extra["any_span_exact"] = any(exact_match(s["text"], ref) for s in spans)
            extra["top_score"] = round(spans[0]["score"], 3) if spans else None
            extra["top_span_covered"] = round(place_score("", doc, ref, positions[:1]), 3) if spans else 0.0

        label = classify(quote, doc, ref, parse_ok=ok, spans=positions)
        in_doc = label in ("exact", "right_place", "elsewhere")
        covered = place_score(quote, doc, ref, positions) if in_doc else 0.0
        out.append(
            {
                "arm": name,
                "id": row["id"],
                "label": label,
                "made_up_kind": made_up_kind(quote, doc) if label == "made_up" else "",
                "right_place": covered > 0,
                "covered": round(covered, 3),  # share of the reference answer the quote includes
                "quote_words": len(tidy(quote or "").split()),
                "f1": round(f1(quote or "", ref), 3),
                "seconds": row["seconds"],
                "cost": cost,
                "input_tokens": row["usage"]["input_tokens"],
                "output_tokens": row["usage"]["output_tokens"],
                "quote": quote,
                "reference": ref,
                "question": q["question"],
                **extra,
            }
        )
    return out


def with_check(haiku_scored: list[dict], name: str) -> list[dict]:
    """Arm C: the same Haiku answers, but any quote that fails the substring
    check is thrown away and treated as 'no answer'. No extra API calls."""
    out = []
    for r in haiku_scored:
        r = dict(r, arm=name)
        if r["label"] == "made_up":
            r.update(label="miss", made_up_kind="", right_place=False, covered=0.0, f1=0.0, quote="", quote_words=0)
        out.append(r)
    return out


def score_memory(rows: list[dict], questions: dict, papers: dict) -> list[dict]:
    """Haiku with no paper attached. There is no document to check a quote
    against, so we only ask: did it answer, and does the answer match?"""
    out = []
    for row in rows:
        q = questions[row["id"]]
        answer, ok = haiku_json(row, "answer", "known")
        answer = answer or ""
        out.append(
            {
                "id": row["id"],
                "parse_ok": ok,
                "answered": bool(tidy(answer)),
                "exact": bool(tidy(answer)) and exact_match(answer, q["reference"]),
                "f1": round(f1(answer, q["reference"]), 3),
                "in_paper": is_verbatim(answer, papers[q["paper"]]["text"]),
                "cost": haiku_cost(row),
                "answer": answer,
                "reference": q["reference"],
                "question": q["question"],
            }
        )
    return out


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    counts = Counter(r["label"] for r in rows)
    answered = n - counts["miss"] - counts["parse_error"]
    answers = [r for r in rows if r["quote_words"]]
    return {
        "arm": rows[0]["arm"],
        "n": n,
        "answered": answered,
        **{label: counts[label] for label in LABELS},
        "punctuation_only": sum(r["made_up_kind"] == "punctuation_only" for r in rows),
        "words_changed": sum(r["made_up_kind"] == "words_changed" for r in rows),
        "made_up_rate": counts["made_up"] / answered if answered else 0.0,
        "right_place_n": sum(r["right_place"] for r in rows),
        "whole_reference_n": sum(r["covered"] == 1 for r in rows),
        "mean_covered": statistics.mean(r["covered"] for r in rows),
        "median_words": statistics.median(r["quote_words"] for r in answers) if answers else 0,
        "mean_f1": statistics.mean(r["f1"] for r in rows),
        "median_seconds": statistics.median(r["seconds"] for r in rows),
        "cost_per_1000": sum(r["cost"] for r in rows) / n * 1000,
        "total_cost": sum(r["cost"] for r in rows),
    }


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("smoke", "full"):
        raise SystemExit("Say which run to score: smoke or full")

    papers = {p["paper"]: p for p in load_papers()}
    questions = {q["id"]: q for q in read(Path("data/questions.jsonl"))}
    for p in papers.values():
        # Locate's positions and ours must be counted on the very same string.
        assert p["text"] == unicodedata.normalize("NFC", p["text"]), p["paper"]
    for q in questions.values():
        assert len(find_all(q["reference"], papers[q["paper"]]["text"])) == 1, q["id"]

    if mode == "smoke":
        folder = Path("raw/smoke")
        files = [
            ("Haiku (thinking default)", folder / "llm_thinking_default.jsonl", "haiku"),
            ("Haiku (thinking off)", folder / "llm_thinking_off.jsonl", "haiku"),
            ("Locate", folder / "locate.jsonl", "locate"),
        ]
    else:
        folder = Path("raw")
        files = [
            ("Haiku", folder / "llm.jsonl", "haiku"),
            ("Locate", folder / "locate.jsonl", "locate"),  # Decider Flash
            ("Locate (Decider)", folder / "locate_decider.jsonl", "locate"),  # the larger model, added later
        ]
        files = [f for f in files if f[1].exists()]

    arms = []
    for name, path, kind in files:
        scored = score_arm(name, read(path), questions, papers, kind)
        arms.append(scored)
        if kind == "haiku":
            arms.append(with_check(scored, name + " + check"))
    stats = [summarise(rows) for rows in arms]

    print("1. Is the quote really in the paper?\n")
    print(f"{'':<34}{'asked':>6}{'answered':>10}{'no answer':>11}{'made up':>9}{'  of which:':>12}"
          f"{'words changed':>15}{'punctuation only':>18}{'made-up rate':>14}")
    for s in stats:
        print(f"{s['arm']:<34}{s['n']:>6}{s['answered']:>10}{s['miss']:>11}{s['made_up']:>9}{'':>12}"
              f"{s['words_changed']:>15}{s['punctuation_only']:>18}{s['made_up_rate']:>13.1%}")
    if any(s["parse_error"] for s in stats):
        print("Unreadable replies:", {s["arm"]: s["parse_error"] for s in stats})

    print("\n2. Is it the right part of the paper?\n")
    print(f"{'':<34}{'right place':>12}{'  % of asked':>12}{'whole ref':>11}{'ref covered':>13}"
          f"{'elsewhere':>11}{'exact':>7}{'words':>7}")
    for s in stats:
        print(f"{s['arm']:<34}{s['right_place_n']:>12}{s['right_place_n'] / s['n']:>12.0%}{s['whole_reference_n']:>11}"
              f"{s['mean_covered']:>13.0%}{s['elsewhere']:>11}{s['exact']:>7}{s['median_words']:>7.0f}")
    print("\n  right place = the answer overlaps the spot where our reference answer sits (for Locate, any of its spans).")
    print("  whole ref   = the answer includes our whole reference answer.")
    print("  ref covered = on average, how much of the reference answer was included (no answer counts as 0%).")
    print("  exact       = same words as the reference answer, nothing more or less.")
    print("  words       = typical length of an answer (for Locate, its most confident span).")

    print("\n3. Speed and cost\n")
    print(f"{'':<34}{'median seconds':>15}{'$ per 1,000':>13}{'spent':>9}")
    for s in stats:
        if "check" not in s["arm"]:
            print(f"{s['arm']:<34}{s['median_seconds']:>15.2f}{s['cost_per_1000']:>13.3f}{s['total_cost']:>9.4f}")

    for locate in [rows for rows in arms if rows[0]["arm"].startswith("Locate")]:
        print(f"\n{locate[0]['arm']} details: positions matched the text in {sum(r['offsets_ok'] for r in locate)}/{len(locate)} replies; "
              f"spans per reply {sorted(Counter(r['spans'] for r in locate).items())}; "
              f"top span alone in the right place in {sum(r['top_span_covered'] > 0 for r in locate)}.")
    for rows in arms:
        if rows[0]["arm"].startswith("Haiku") and "check" not in rows[0]["arm"]:
            print(f"{rows[0]['arm']}: chose to think on {sum(r['thinking_tokens'] > 0 for r in rows)}/{len(rows)} questions.")

    memory = []
    if (folder / "memory.jsonl").exists():
        memory = score_memory(read(folder / "memory.jsonl"), questions, papers)
        answered = [m for m in memory if m["answered"]]
        print(f"\n4. Memory check (Haiku given the title and question, no paper)\n")
        print(f"  asked {len(memory)}, said it did not know {len(memory) - len(answered)}, answered {len(answered)}; "
              f"same words as the reference {sum(m['exact'] for m in memory)}; "
              f"at least half the reference's words {sum(m['f1'] >= 0.5 for m in memory)}; "
              f"spent ${sum(m['cost'] for m in memory):.4f}")
        for m in answered:
            print(f"    {m['id']}: answered {m['answer']!r}  |  reference {m['reference']!r}")

    if mode == "full":
        Path("results").mkdir(exist_ok=True)
        for filename, flat in (("scores.csv", [r for rows in arms for r in rows]), ("memory.csv", memory)):
            if not flat:
                continue
            keys = sorted({k for r in flat for k in r})
            with (Path("results") / filename).open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(flat)
            print(f"\nWrote {len(flat)} rows to results/{filename}")


if __name__ == "__main__":
    main()
