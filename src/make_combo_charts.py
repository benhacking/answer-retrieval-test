"""Two charts that add the combo (Decider Flash first, Haiku on its blanks).

Run with:
    uv run src/make_combo_charts.py

Writes outcomes_second_run.png (the three models on their own),
outcomes_combo.png (the same plus the combo), cost_time.png and
answer_length.png, all in results/charts/.
All four rows come from the second run (results/handoff/scores.csv), so
they are compared like for like. The main run's chart is outcomes.png.
Every number is counted from the scored replies; nothing is typed in.
"""

import csv
from pathlib import Path

import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from make_report import ANTHROPIC_ORANGE, INK, LOGOS, MUTED, NO_ANSWER, PERPLEXITY_GREEN, SURFACE, WRONG, outcome

COMBO = "Fresh: Flash, then Haiku on blanks"
FLASH_GREEN = "#5f8f96"  # lighter green, so Decider Flash reads apart from the larger Decider
COLOUR = {"anthropic": ANTHROPIC_ORANGE, "perplexity": PERPLEXITY_GREEN, "flash": FLASH_GREEN}


def load() -> list[dict]:
    """Four rows, each a list of parts: (company that answered, scored replies)."""
    fresh = list(csv.DictReader(Path("results/handoff/scores.csv").open()))
    combo = [r for r in fresh if r["arm"] == COMBO]

    def arm(key):
        return [r for r in fresh if r["arm"] == key]

    def flash_alone():
        """Decider Flash's own answer to every question in the second run, re-scored."""
        import json

        from fetch_papers import load_papers
        from score_run import read, score_arm

        papers = {p["paper"]: p for p in load_papers()}
        questions = {q["id"]: q for q in read(Path("data/questions.jsonl"))}
        rows = score_arm("Fresh: Flash", read(Path("results/handoff/raw/flash.jsonl")), questions, papers, "locate")
        return [{k: str(v) for k, v in r.items()} for r in rows]

    rows = [
        {"name": "Anthropic Claude Haiku 5.5", "logos": ["anthropic"], "parts": [("anthropic", arm("Fresh: Haiku"))]},
        {"name": "Perplexity Decider v1.3 locate", "logos": ["perplexity"], "parts": [("perplexity", arm("Fresh: Decider"))]},
        {"name": "Perplexity Decider Flash v1.3 locate", "logos": ["perplexity"], "parts": [("flash", flash_alone())]},
        {
            "name": "Combo: Decider Flash v1.3 first, then Haiku on its blanks",
            "logos": ["perplexity", "anthropic"],
            "parts": [
                ("flash", [r for r in combo if r["sent_to_haiku"] == "False"]),
                ("anthropic", [r for r in combo if r["sent_to_haiku"] == "True"]),
            ],
        },
    ]
    for row in rows:
        assert sum(len(g) for _, g in row["parts"]) == 200, row["name"]
    return rows


def flash_share_of_combo() -> tuple[float, float]:
    """(cost, seconds) that Decider Flash itself used in the fresh run, summed over all 200."""
    import json

    cost = seconds = 0.0
    for line in Path("results/handoff/raw/flash.jsonl").read_text().splitlines():
        r = json.loads(line)
        cost += r["usage"]["input_tokens"] / 1e6 * 0.01
        seconds += r["seconds"]
    return cost, seconds


def name_and_logos(ax, row, y, size=11.5):
    shift = 0
    for company in row["logos"]:
        logo = LOGOS / f"{company}.png"
        if logo.exists():
            picture = plt.imread(logo)
            box = OffsetImage(picture, zoom=14 / picture.shape[0])
            ax.add_artist(AnnotationBbox(box, (0, y), xybox=(shift + 7, 7.5), boxcoords="offset points",
                                         frameon=False, pad=0, box_alignment=(0.5, 0.5)))
            shift += 18
    ax.annotate(row["name"], (0, y), xytext=(shift + (2 if shift else 0), 0), textcoords="offset points",
                ha="left", va="bottom", fontsize=size, color=INK, fontweight="bold")


def clean(ax):
    ax.set_facecolor(SURFACE)
    ax.set_yticks([])
    ax.tick_params(axis="x", colors=MUTED, length=0, labelsize=9.5)
    for side in ax.spines.values():
        side.set_visible(False)


def mono(text, bold=False):
    """Put every number in the text in a mono font (Menlo), leaving the words alone."""
    command = "mathsf" if bold else "mathtt"  # main() points these at Menlo bold and Menlo
    def wrap(match):
        inner = match.group().replace("$", r"\$").replace("%", r"\%").replace(",", "{,}")
        return "$\\%s{%s}$" % (command, inner)
    return re.sub(r"\$?\d+(?:[.,]\d+)*%?", wrap, text)


def outcomes_chart(rows, path, title, height=5.0, top=0.89, bottom=0.13):
    fig, ax = plt.subplots(figsize=(9, height), dpi=200, facecolor=SURFACE)
    for i, row in enumerate(rows):
        y, left, thin = len(rows) - 1 - i, 0, []
        is_combo = len(row["parts"]) > 1
        for company, group in row["parts"]:  # correct answers first, in company colour
            n = sum(outcome(r) == "right" for r in group)
            if not n:
                continue
            ax.barh(y, n, left=left, height=0.5, color=COLOUR[company], edgecolor=SURFACE, linewidth=1.5)
            who = {"flash": "from Decider Flash", "anthropic": "from Haiku"}[company] if is_combo else "from the right place"
            ax.text(left + n / 2, y, mono(f"{n} {who}", bold=True), ha="center", va="center", fontsize=10.5, color="white", fontweight="bold")
            left += n
        everyone = [r for _, g in row["parts"] for r in g]
        for label, words in (("elsewhere", "from a different place"), ("made_up", "not in the paper"), ("miss", "no answer")):
            n = sum(outcome(r) == label for r in everyone)
            if not n:
                continue
            ax.barh(y, n, left=left, height=0.5, color=NO_ANSWER if label == "miss" else WRONG, edgecolor=SURFACE, linewidth=1.5)
            if n >= 12:
                ax.text(left + n / 2, y, mono(f"{n} {words}", bold=True), ha="center", va="center", fontsize=10.5, color=INK, fontweight="bold")
            else:
                thin.append((left + n, f"{n} {words}"))
            left += n
        if thin:  # too thin to hold a label: write above the bar, ending at the last thin segment
            ax.text(thin[-1][0], y + 0.3, mono(", ".join(t for _, t in thin)), ha="right", va="bottom", fontsize=9.5, color=INK)
        name_and_logos(ax, row, y + 0.32)
    clean(ax)
    ax.set_xlim(0, 200)
    ax.set_ylim(-0.6, len(rows) - 0.2)
    ax.set_xticks([0, 50, 100, 150, 200])
    ax.set_xticklabels([mono(str(v)) for v in (0, 50, 100, 150, 200)])
    ax.set_xlabel(mono("Questions (out of 200)"), color=MUTED, fontsize=10)
    fig.suptitle(mono(title, bold=True),
                 x=0.035, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.035, right=0.965, top=top, bottom=bottom)
    fig.savefig(path, facecolor=SURFACE)


def cost_time_chart(rows):
    flash_cost, flash_seconds = flash_share_of_combo()
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6), dpi=200, facecolor=SURFACE)
    panels = [
        ("Cost", "cost", 1000 / 200, lambda v: f"${v:.2f}", "US dollars"),
        ("Total time, one question at a time", "seconds", 1000 / 200 / 60, lambda v: f"{v:.0f} min", "Minutes"),
    ]
    printed = {}
    for ax, (title, field, scale, show, unit) in zip(axes, panels):
        biggest = 0
        for i, row in enumerate(rows):
            y = len(rows) - 1 - i
            total = sum(float(r[field]) for _, g in row["parts"] for r in g) * scale
            if len(row["parts"]) > 1:  # combo: split into what each model used
                flash = (flash_cost if field == "cost" else flash_seconds) * scale
                pieces = [("flash", flash), ("anthropic", total - flash)]
            else:
                pieces = [(row["parts"][0][0], total)]
            left = 0
            for company, value in pieces:
                ax.barh(y, value, left=left, height=0.42, color=COLOUR[company], edgecolor=SURFACE, linewidth=1.5)
                left += value
            ax.annotate(mono(show(total), bold=True), (total, y), xytext=(5, 0), textcoords="offset points",
                        ha="left", va="center", fontsize=10.5, color=INK, fontweight="bold")
            name_and_logos(ax, dict(row, name=row["name"].replace("Combo: Decider Flash v1.3 first, then Haiku on its blanks", "Combo: Decider Flash v1.3, then Haiku")), y + 0.27, size=10)
            biggest = max(biggest, total)
            printed.setdefault(row["name"], []).append(show(total))
        clean(ax)
        ax.set_xlim(0, biggest * 1.22)
        ax.set_ylim(-0.5, len(rows) - 0.15)
        ax.set_xticks([])
        ax.set_title(title, loc="left", fontsize=11, color=MUTED, pad=8)
    fig.suptitle(mono("Cost and time to answer 1,000 questions", bold=True),
                 x=0.035, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.text(0.035, 0.03, mono("Scaled up from 200 questions. In the combo bar, the green part is Decider Flash's share and the orange part is Haiku's."),
             fontsize=9, color=MUTED)
    fig.subplots_adjust(left=0.035, right=0.975, top=0.82, bottom=0.1, wspace=0.12)
    fig.savefig("results/charts/cost_time.png", facecolor=SURFACE)
    for name, values in printed.items():
        print(f"{name}: {' | '.join(values)}")


def length_chart(rows):
    """One line per model across the three answer-length groups. Y starts at 0."""
    groups = [("5 words or fewer", 0, 5), ("6 to 15 words", 6, 15), ("16 words or more", 16, 10**6)]
    styles = [("Claude Haiku 5.5", ANTHROPIC_ORANGE, "-", "o"), ("Decider v1.3", PERPLEXITY_GREEN, "-", "o"),
              ("Decider Flash v1.3", FLASH_GREEN, "--", "s")]
    fig, ax = plt.subplots(figsize=(9, 5.0), dpi=200, facecolor=SURFACE)
    sizes = []
    for row, (name, colour, dash, marker) in zip(rows[:3], styles):
        group = row["parts"][0][1]
        ys, sizes = [], []
        for title, lo, hi in groups:
            mine = [r for r in group if lo <= len(r["reference"].split()) <= hi]
            found = sum(outcome(r) == "right" for r in mine)
            ys.append(found / len(mine) * 100)
            sizes.append(len(mine))
            print(f"{title}: {name} {found} of {len(mine)} ({found / len(mine) * 100:.0f}%)")
        ax.plot(range(3), ys, color=colour, linestyle=dash, linewidth=2, marker=marker, markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=1.5, clip_on=False, zorder=3)
        ax.annotate(name + "  " + mono(f"{ys[-1]:.0f}%", bold=True), (2, ys[-1]), xytext=(12, 0), textcoords="offset points", ha="left",
                    va="center", fontsize=10.5, color=INK, fontweight="bold", annotation_clip=False)
    ax.set_facecolor(SURFACE)
    ax.set_xlim(-0.15, 2.05)
    ax.set_ylim(0, 105)
    ax.set_xticks(range(3))
    ax.set_xticklabels([mono(f"{title}\n{n} questions") for (title, _, _), n in zip(groups, sizes)])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_yticklabels([mono(t) for t in ("0", "25%", "50%", "75%", "100%")])
    ax.tick_params(colors=MUTED, length=0, labelsize=9.5)
    ax.tick_params(axis="x", labelsize=10.5, pad=8)
    ax.grid(axis="y", color=NO_ANSWER, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.set_xlabel("Length of the correct answer", color=MUTED, fontsize=10, labelpad=10)
    ax.set_ylabel("Answers found", color=MUTED, fontsize=10)
    fig.suptitle("Longer answers, fewer found by locate",
                 x=0.035, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.09, right=0.76, top=0.88, bottom=0.2)
    fig.savefig("results/charts/answer_length.png", facecolor=SURFACE)


def main() -> None:
    plt.rcParams.update({"font.family": "Helvetica Neue", "font.size": 11,
                         "mathtext.fontset": "custom", "mathtext.tt": "Menlo", "mathtext.sf": "Menlo:bold"})
    rows = load()
    Path("results/charts").mkdir(parents=True, exist_ok=True)
    title = "What happened to 200 questions about 25 new research papers"
    outcomes_chart(rows[:3], "results/charts/outcomes_second_run.png", title, height=4.0, top=0.87, bottom=0.16)
    outcomes_chart(rows, "results/charts/outcomes_combo.png", "How each approach answered the same 200 questions")
    cost_time_chart(rows)
    length_chart(rows)
    print("Wrote outcomes_second_run.png, outcomes_combo.png, cost_time.png and answer_length.png in results/charts/")


if __name__ == "__main__":
    main()
