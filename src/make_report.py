"""Turn results/scores.csv into one table and one chart. No model involved.

Run with:
    uv run src/make_report.py

Writes results/table.md and results/charts/outcomes.png. Every number is
counted from the scored replies; nothing is typed in by hand.
"""

import csv
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

ARMS = [
    ("Haiku", "Haiku 5.5"),
    ("Haiku + check", "Haiku 5.5 + one-line check"),
    ("Locate (Decider)", "Decider locate"),
    ("Locate", "Decider Flash locate"),
]
# The chart leaves out "Haiku + check": it differs from plain Haiku on one
# question in 200, so the two bars would look the same.
# Each row: results key, label, company (for the logo file), company colour.
ANTHROPIC_ORANGE = "#d97757"
PERPLEXITY_GREEN = "#18353b"
CHART_ROWS = [
    ("Haiku", "Anthropic Claude Haiku 5.5", "anthropic", ANTHROPIC_ORANGE),
    ("Locate (Decider)", "Perplexity Decider locate", "perplexity", PERPLEXITY_GREEN),
    ("Locate", "Perplexity Decider Flash locate", "perplexity", PERPLEXITY_GREEN),
]
LOGOS = Path("assets/logos")  # optional: anthropic.png and perplexity.png, square
NO_ANSWER, WRONG = "#d5d4cd", "#0b0b0b"  # no answer; a quote from the wrong place or not in the paper
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def outcome(row: dict) -> str:
    return "right" if row["label"] in ("exact", "right_place") else row["label"]


def main() -> None:
    rows = list(csv.DictReader(Path("results/scores.csv").open()))
    memory = list(csv.DictReader(Path("results/memory.csv").open()))
    by_arm = {key: [r for r in rows if r["arm"] == key] for key, _ in ARMS}
    for key, group in by_arm.items():
        assert group and not any(r["label"] == "parse_error" for r in group), key

    # ---- table ----
    def line(title, fn):
        return f"| {title} | " + " | ".join(fn(by_arm[key]) for key, _ in ARMS) + " |"

    def count(label):
        return lambda g: str(sum(outcome(r) == label for r in g))

    def answered(g):
        return [r for r in g if r["label"] != "miss"]

    table = [
        "| | " + " | ".join(name for _, name in ARMS) + " |",
        "|---|" + "---|" * len(ARMS),
        line("Questions asked", lambda g: str(len(g))),
        line("Gave an answer", lambda g: str(len(answered(g)))),
        line("Quote not in the paper (made up)", count("made_up")),
        line("Made-up rate, of answers given", lambda g: f"{sum(r['label'] == 'made_up' for r in g) / len(answered(g)):.1%}"),
        line("... words changed", lambda g: str(sum(r["made_up_kind"] == "words_changed" for r in g))),
        line("... punctuation style only", lambda g: str(sum(r["made_up_kind"] == "punctuation_only" for r in g))),
        line("Quote from the right place", lambda g: f"{sum(outcome(r) == 'right' for r in g)} ({sum(outcome(r) == 'right' for r in g) / len(g):.1%})"),
        line("Quote from a different place", count("elsewhere")),
        line("No answer", lambda g: f"{sum(r['label'] == 'miss' for r in g)} ({sum(r['label'] == 'miss' for r in g) / len(g):.1%})"),
        line("Included the whole reference answer", lambda g: str(sum(float(r["covered"]) == 1 for r in g))),
        line("Typical answer length, words", lambda g: f"{statistics.median(int(r['quote_words']) for r in answered(g)):.0f}"),
        line("Typical time per question, seconds", lambda g: f"{statistics.median(float(r['seconds']) for r in g):.2f}"),
        line("Cost per 1,000 questions", lambda g: f"${sum(float(r['cost']) for r in g) / len(g) * 1000:.2f}"),
    ]
    knew = [m for m in memory if m["answered"] == "True"]
    note = (
        f"\nMemory check: asked the same {len(memory)} questions with only the paper's title and no text, "
        f"Haiku said it did not know {len(memory) - len(knew)} times and attempted {len(knew)}. "
        f"{sum(float(m['f1']) >= 0.5 for m in knew)} of those attempts shared at least half their words with the reference answer.\n"
    )
    Path("results/table.md").write_text("\n".join(table) + "\n" + note)
    print("\n".join(table) + "\n" + note)

    # ---- chart ----
    plt.rcParams.update({"font.family": "Helvetica Neue", "font.size": 11})
    fig, ax = plt.subplots(figsize=(9, 3.9), dpi=200, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    total = len(by_arm[ARMS[0][0]])
    for i, (key, name, company, colour) in enumerate(CHART_ROWS):
        y, left = len(CHART_ROWS) - 1 - i, 0
        for label in ("right", "elsewhere", "made_up", "miss"):
            n = sum(outcome(r) == label for r in by_arm[key])
            if not n:
                continue
            fill = {"right": colour, "miss": NO_ANSWER}.get(label, WRONG)
            ax.barh(y, n, left=left, height=0.5, color=fill, edgecolor=SURFACE, linewidth=1.5)
            if n >= 12:
                words = "from the right place" if label == "right" else "no answer"
                ax.text(left + n / 2, y, f"{n} {words}", ha="center", va="center", fontsize=10.5,
                        color="white" if label == "right" else INK, fontweight="bold")
            else:  # too thin to hold a label: write it above the bar, ending at the segment
                words = {"made_up": "not in the paper", "elsewhere": "from a different place", "miss": "no answer"}[label]
                ax.text(left + n, y + 0.3, f"{n} {words}", ha="right", va="bottom", fontsize=9.5, color=INK)
            left += n
        # Company logo, if the author has put one in assets/logos/. Logos are not kept in the repo.
        logo, shift = LOGOS / f"{company}.png", 0
        if logo.exists():
            picture = plt.imread(logo)
            box = OffsetImage(picture, zoom=14 / picture.shape[0])  # about 14 points tall
            ax.add_artist(AnnotationBbox(box, (0, y + 0.32), xybox=(7, 7.5), boxcoords="offset points",
                                         frameon=False, pad=0, box_alignment=(0.5, 0.5)))
            shift = 20  # points: make room for the logo
        ax.annotate(name, (0, y + 0.32), xytext=(shift, 0), textcoords="offset points",
                    ha="left", va="bottom", fontsize=11.5, color=INK, fontweight="bold")
    ax.set_xlim(0, total)
    ax.set_ylim(-0.6, len(CHART_ROWS) - 0.2)
    ax.set_yticks([])
    ax.set_xticks([0, 50, 100, 150, 200])
    ax.tick_params(axis="x", colors=MUTED, length=0, labelsize=9.5)
    ax.set_xlabel(f"Questions (out of {total})", color=MUTED, fontsize=10)
    for side in ax.spines.values():
        side.set_visible(False)
    fig.suptitle(f"What happened to {total} questions about 25 new research papers",
                 x=0.035, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.subplots_adjust(left=0.035, right=0.965, top=0.86, bottom=0.16)
    Path("results/charts").mkdir(parents=True, exist_ok=True)
    fig.savefig("results/charts/outcomes.png", facecolor=SURFACE)
    print("Wrote results/table.md and results/charts/outcomes.png")


if __name__ == "__main__":
    main()
