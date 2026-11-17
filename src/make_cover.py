"""Cover image for the post: Haiku alone against the combo, nothing else.

Run with:
    uv run src/make_cover.py

Writes results/charts/cover.png at 2400 x 1260 pixels (the 1200 x 630
link-preview shape, doubled for sharp screens). Every number is counted
from the second run's scored replies (results/handoff/scores.csv).
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

from make_combo_charts import COLOUR, load
from make_report import INK, LOGOS, MUTED, SURFACE, outcome


def main() -> None:
    plt.rcParams.update({"font.family": "Helvetica Neue"})
    rows = load()
    haiku, combo = rows[0], rows[3]

    def right(group):
        return sum(outcome(r) == "right" for r in group)

    def cost(row):  # dollars per 1,000 questions
        return sum(float(r["cost"]) for _, g in row["parts"] for r in g) / 200 * 1000

    combo_right = sum(right(g) for _, g in combo["parts"])

    fig = plt.figure(figsize=(12, 6.3), dpi=200, facecolor=SURFACE)
    ax = fig.add_axes([0.06, 0.07, 0.88, 0.52])
    ax.set_facecolor(SURFACE)
    ax.axis("off")
    ax.set_xlim(0, 200)
    ax.set_ylim(-0.45, 1.75)

    headline = {"fontsize": 46, "fontweight": "bold", "fontfamily": "Avenir Next", "color": INK, "ha": "left", "va": "center"}
    fig.text(0.06, 0.845, "Answer Retrieval with", **headline)
    side = 0.60  # logo size in inches, about the height of the headline's capitals
    logo_ax = fig.add_axes([0.06, 0.705 - side / 6.3 / 2, side / 12, side / 6.3])
    logo_ax.imshow(plt.imread(LOGOS / "perplexity.png"))
    logo_ax.axis("off")
    fig.text(0.06 + side / 12 + 0.014, 0.70, "Decider Flash v1.3 Locate", **headline)

    layout = [
        (1, haiku, "Claude Haiku 5.5 alone", lambda company, n: f"{n} correct"),
        (0, combo, "Decider Flash first, then Haiku on its blanks",
         lambda company, n: f"{n} from " + {"flash": "Decider Flash", "anthropic": "Haiku"}[company]),
    ]
    for y, row, name, words in layout:
        left = 0
        for company, group in row["parts"]:
            n = right(group)
            ax.barh(y, n, left=left, height=0.46, color=COLOUR[company], edgecolor=SURFACE, linewidth=3)
            ax.text(left + n / 2, y, words(company, n), ha="center", va="center", fontsize=21, color="white", fontweight="bold", fontfamily="Arial")
            left += n
        shift = 0
        for company in row["logos"]:
            picture = plt.imread(LOGOS / f"{company}.png")
            box = OffsetImage(picture, zoom=26 / picture.shape[0])
            ax.add_artist(AnnotationBbox(box, (0, y + 0.31), xybox=(shift + 13, 13), boxcoords="offset points",
                                         frameon=False, pad=0, box_alignment=(0.5, 0.5)))
            shift += 34
        ax.annotate(name, (0, y + 0.31), xytext=(shift + 4, 0), textcoords="offset points",
                    ha="left", va="bottom", fontsize=19, color=INK)
        ax.annotate(f"${cost(row):.2f} per 1,000 questions", (200, y + 0.31), xytext=(0, 0), textcoords="offset points",
                    ha="right", va="bottom", fontsize=19, color=INK, fontweight="bold", fontfamily="Arial")

    fig.savefig("results/charts/cover.png", facecolor=SURFACE)
    print(f"Wrote results/charts/cover.png ({combo_right} of 200, ${cost(combo):.2f} against ${cost(haiku):.2f})")


if __name__ == "__main__":
    main()
