"""Handoff test: ask Decider Flash locate first, send its blanks to Haiku.

The plan is in results/handoff/PLAN.md and was committed before any
model was called for this test.

Run with:
    uv run src/handoff.py run       # the fresh run (calls both models)
    uv run src/handoff.py baseline  # added later: Haiku alone and Decider alone, fresh
    uv run src/handoff.py report    # score everything, no model calls

Request wording and scoring are reused from the main run, unchanged.
Everything new is written under results/handoff/.
"""

import csv
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fetch_papers import load_papers
from run_arms import DECIDER, DECIDER_LARGE, ask_haiku, ask_locate, done_ids, save
from score_run import read, score_arm, with_check

OUT = Path("results/handoff")
FRESH_FLASH = OUT / "raw" / "flash.jsonl"
FRESH_HAIKU = OUT / "raw" / "haiku_on_blanks.jsonl"
FRESH_HAIKU_ALL = OUT / "raw" / "haiku_all.jsonl"
FRESH_DECIDER = OUT / "raw" / "decider.jsonl"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_blank(row: dict) -> bool:
    """A blank is a Flash reply with no span in it."""
    return not ((row.get("answer") or {}).get("spans"))


def run() -> None:
    import anthropic
    from dotenv import load_dotenv

    papers = {p["paper"]: p for p in load_papers()}
    questions = read(Path("data/questions.jsonl"))
    load_dotenv(".env")
    key = os.environ["PERPLEXITY_API_KEY"]
    haiku = anthropic.Anthropic()

    todo = [q for q in questions if q["id"] not in done_ids(FRESH_FLASH)]
    print(f"Flash: {len(todo)} to ask -> {FRESH_FLASH}", flush=True)
    for n, q in enumerate(todo, 1):
        asked = now()
        row = ask_locate(key, papers[q["paper"]]["text"], q["question"], DECIDER)
        save(FRESH_FLASH, {"id": q["id"], "asked_at": asked, **row})
        print(f"  {n}/{len(todo)} {q['id']} {row['seconds']}s", flush=True)

    blanks = {r["id"] for r in read(FRESH_FLASH) if is_blank(r)}
    todo = [q for q in questions if q["id"] in blanks and q["id"] not in done_ids(FRESH_HAIKU)]
    print(f"\nFlash left {len(blanks)} blank. Haiku: {len(todo)} to ask -> {FRESH_HAIKU}", flush=True)
    for n, q in enumerate(todo, 1):
        asked = now()
        row = ask_haiku(haiku, papers[q["paper"]]["text"], q["question"], "default")
        save(FRESH_HAIKU, {"id": q["id"], "asked_at": asked, **row})
        print(f"  {n}/{len(todo)} {q['id']} {row['seconds']}s", flush=True)
    print("\nDone.")


def baseline() -> None:
    """Added later (see PLAN.md): Haiku alone and the larger Decider alone, all 200 again."""
    import anthropic
    from dotenv import load_dotenv

    papers = {p["paper"]: p for p in load_papers()}
    questions = read(Path("data/questions.jsonl"))
    load_dotenv(".env")
    key = os.environ["PERPLEXITY_API_KEY"]
    haiku = anthropic.Anthropic()
    jobs = [
        ("Haiku", FRESH_HAIKU_ALL, lambda q: ask_haiku(haiku, papers[q["paper"]]["text"], q["question"], "default")),
        ("Decider", FRESH_DECIDER, lambda q: ask_locate(key, papers[q["paper"]]["text"], q["question"], DECIDER_LARGE)),
    ]
    for name, path, ask in jobs:
        todo = [q for q in questions if q["id"] not in done_ids(path)]
        print(f"{name}: {len(todo)} to ask -> {path}", flush=True)
        for n, q in enumerate(todo, 1):
            asked = now()
            row = ask(q)
            save(path, {"id": q["id"], "asked_at": asked, **row})
            print(f"  {n}/{len(todo)} {q['id']} {row['seconds']}s", flush=True)
    print("\nDone.")


def pct90(values: list[float]) -> float:
    xs = sorted(values)
    k = (len(xs) - 1) * 0.9
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def combine(name: str, first: dict, fallback: dict, send: set[str]) -> list[dict]:
    """One row per question. Questions in `send` take the fallback's answer,
    and pay for and wait for both models."""
    out = []
    for i, f in first.items():
        if i in send:
            h = fallback[i]
            row = dict(h, arm=name, cost=f["cost"] + h["cost"], seconds=round(f["seconds"] + h["seconds"], 2), sent_to_haiku=True)
        else:
            row = dict(f, arm=name, sent_to_haiku=False)
        out.append(row)
    return out


def line(name: str, rows: list[dict]) -> dict:
    c = Counter(r["label"] for r in rows)
    secs = [r["seconds"] for r in rows]
    return {
        "arm": name,
        "right": c["exact"] + c["right_place"],
        "not_in_paper": c["made_up"],
        "elsewhere": c["elsewhere"],
        "no_answer": c["miss"] + c["parse_error"],
        "to_haiku": sum(bool(r.get("sent_to_haiku")) for r in rows),
        "cost_1000": sum(r["cost"] for r in rows) / len(rows) * 1000,
        "total_cost": sum(r["cost"] for r in rows),
        "median": statistics.median(secs),
        "p90": pct90(secs),
        "mean": statistics.mean(secs),
    }


def show(lines: list[dict]) -> str:
    head = f"{'':<44}{'right':>6}{'not in paper':>14}{'elsewhere':>11}{'no answer':>11}{'to Haiku':>10}{'$/1,000':>9}{'median s':>10}{'p90 s':>8}{'mean s':>8}"
    body = [
        f"{s['arm']:<44}{s['right']:>6}{s['not_in_paper']:>14}{s['elsewhere']:>11}{s['no_answer']:>11}{s['to_haiku']:>10}"
        f"{s['cost_1000']:>9.3f}{s['median']:>10.2f}{s['p90']:>8.2f}{s['mean']:>8.2f}"
        for s in lines
    ]
    return "\n".join([head, *body])


def report() -> None:
    papers = {p["paper"]: p for p in load_papers()}
    questions = {q["id"]: q for q in read(Path("data/questions.jsonl"))}

    def scored(name, path, kind):
        return {r["id"]: r for r in score_arm(name, read(path), questions, papers, kind)}

    def checked(rows: dict) -> dict:
        return {r["id"]: r for r in with_check(list(rows.values()), "checked")}

    main_haiku = scored("Haiku", Path("raw/llm.jsonl"), "haiku")
    main_flash = scored("Flash", Path("raw/locate.jsonl"), "locate")
    main_decider = scored("Decider", Path("raw/locate_decider.jsonl"), "locate")
    main_blanks = {i for i, r in main_flash.items() if r["label"] == "miss"}

    for r in main_haiku.values():
        r["sent_to_haiku"] = True
    lines = [line("Haiku only (main run)", list(main_haiku.values())), line("Flash only (main run)", list(main_flash.values()))]
    replay = combine("Replay: Flash, then Haiku on blanks", main_flash, main_haiku, main_blanks)
    lines.append(line(replay[0]["arm"], replay))
    lines.append(line("  the same, after the one-line check", combine("x", main_flash, checked(main_haiku), main_blanks)))

    text = ["Handoff test results", ""]
    all_rows = list(replay)
    if FRESH_FLASH.exists() and FRESH_HAIKU.exists():
        fresh_flash = scored("Flash (fresh)", FRESH_FLASH, "locate")
        fresh_haiku = scored("Haiku (fresh, blanks only)", FRESH_HAIKU, "haiku")
        fresh_blanks = {r["id"] for r in read(FRESH_FLASH) if is_blank(r)}
        assert len(fresh_flash) == 200 and set(fresh_haiku) == fresh_blanks
        fresh = combine("Fresh: Flash, then Haiku on blanks", fresh_flash, fresh_haiku, fresh_blanks)
        lines.insert(2, line("Flash only (fresh run)", list(fresh_flash.values())))
        lines.append(line(fresh[0]["arm"], fresh))
        lines.append(line("  the same, after the one-line check", combine("x", fresh_flash, checked(fresh_haiku), fresh_blanks)))
        all_rows += fresh
        if FRESH_HAIKU_ALL.exists() and FRESH_DECIDER.exists():
            haiku_all = scored("Fresh: Haiku", FRESH_HAIKU_ALL, "haiku")
            decider_all = scored("Fresh: Decider", FRESH_DECIDER, "locate")
            assert len(haiku_all) == 200 and len(decider_all) == 200
            for r in haiku_all.values():
                r["sent_to_haiku"] = True
            lines.insert(1, line("Haiku only (fresh run)", list(haiku_all.values())))
            lines.insert(2, line("Decider only (main run)", list(main_decider.values())))
            lines.insert(3, line("Decider only (fresh run)", list(decider_all.values())))
            all_rows += list(haiku_all.values()) + list(decider_all.values())
            d_blanks = {i for i, r in decider_all.items() if r["label"] == "miss"}
            m_blanks = {i for i, r in main_decider.items() if r["label"] == "miss"}
            lines.append(line("Fresh answers: Decider, then Haiku on blanks", combine("x", decider_all, haiku_all, d_blanks)))
            text += [
                f"Haiku gave the same outcome as the main run on {sum(haiku_all[i]['label'] == main_haiku[i]['label'] for i in main_haiku)}/200 questions.",
                f"Decider blanks: main run {len(m_blanks)}, fresh run {len(d_blanks)}, the same questions in both {len(m_blanks & d_blanks)}.",
                f"Spent on the added runs: Haiku ${sum(r['cost'] for r in haiku_all.values()):.4f}, Decider ${sum(r['cost'] for r in decider_all.values()):.4f}",
                "",
            ]
        same_label = sum(fresh_flash[i]["label"] == main_flash[i]["label"] for i in main_flash)
        same_quote = sum(fresh_flash[i]["quote"] == main_flash[i]["quote"] for i in main_flash)
        text += [
            f"Blanks: main run {len(main_blanks)}, fresh run {len(fresh_blanks)}, the same questions in both {len(main_blanks & fresh_blanks)}.",
            f"Flash gave the same outcome as the main run on {same_label}/200 questions and the same top quote on {same_quote}/200.",
            f"Haiku on the fresh blanks: {dict(Counter(r['label'] for r in fresh_haiku.values()))}",
            f"Spent on the fresh run: ${sum(r['cost'] for r in fresh_flash.values()) + sum(r['cost'] for r in fresh_haiku.values()):.4f} "
            f"(Flash ${sum(r['cost'] for r in fresh_flash.values()):.4f}, Haiku ${sum(r['cost'] for r in fresh_haiku.values()):.4f})",
            "",
        ]
    text += [show(lines), "", "Cost per 1,000 = total cost of the 200 questions / 200 x 1,000.", ""]

    # Exploratory, replay only.
    text += ["Exploratory (replay from the main run only)", ""]
    extra = [line("Decider, then Haiku on blanks", combine("x", main_decider, main_haiku, {i for i, r in main_decider.items() if r["label"] == "miss"}))]
    for cut in (0.6, 0.7, 0.8, 0.9):
        low = {i for i, r in main_flash.items() if r["label"] != "miss" and float(r["top_score"]) < cut}
        extra.append(line(f"Flash, Haiku on blanks or confidence < {cut}", combine("x", main_flash, main_haiku, main_blanks | low)))
    text += [show(extra), ""]
    wrong = {i: r["top_score"] for i, r in main_flash.items() if r["label"] == "elsewhere"}
    text.append(f"Confidence of Flash's wrong-place answers in the main run: {wrong}")

    out = "\n".join(text)
    print(out)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.txt").write_text(out + "\n")
    keys = sorted({k for r in all_rows for k in r})
    with (OUT / "scores.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWrote {OUT / 'summary.txt'} and {OUT / 'scores.csv'}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "run":
        run()
    elif mode == "baseline":
        baseline()
    elif mode == "report":
        report()
    else:
        raise SystemExit("Say which: run, baseline or report")
