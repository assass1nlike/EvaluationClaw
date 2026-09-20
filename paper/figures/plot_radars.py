"""Draw radar charts with illustrative values; replace these with measured results."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUTPUT = Path(__file__).resolve().parent
METRICS = ["Correctness", "Faithfulness", "Diversity", "Contamination", "Score"]
COLORS = {
    "EvalClaw": "#0072B2",
    "Expert-curated": "#D55E00",
}
# Arbitrary values on a shared 0--1 display scale, not experimental results.
CHARTS = {
    "conventional_radar": (
        "Conventional demands",
        {
            "EvalClaw": [0.86, 0.82, 0.78, 0.85, 0.48],
            "Expert-curated": [0.90, 0.88, 0.65, 0.70, 0.62],
        },
    ),
    "frontier_radar": (
        "Frontier and custom demands",
        {
            "EvalClaw": [0.81, 0.86, 0.77, 0.83, 0.43],
            "Expert-curated": [0.89, 0.78, 0.65, 0.72, 0.59],
        },
    ),
}


def draw(name, title, values):
    angles = np.linspace(0, 2 * np.pi, len(METRICS), endpoint=False)
    closed_angles = np.append(angles, angles[0])
    fig, ax = plt.subplots(figsize=(4.4, 4.4), subplot_kw={"projection": "polar"})
    fig.subplots_adjust(left=0.20, right=0.80, bottom=0.28, top=0.80)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles, METRICS, fontsize=10)
    ax.tick_params(axis="x", pad=10)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0.25", "0.5", "0.75", "1.0"], color="#7B8490", fontsize=8)
    ax.set_rlabel_position(10)
    ax.grid(color="#DCE1E6", linewidth=0.7)
    ax.spines["polar"].set_color("#CAD1D8")
    for method, scores in values.items():
        closed_scores = scores + scores[:1]
        ax.plot(closed_angles, closed_scores, label=method, color=COLORS[method],
                linewidth=2.1 if method == "EvalClaw" else 1.5,
                linestyle="--" if method == "Expert-curated" else "-", marker="o", markersize=3)
        ax.fill(closed_angles, closed_scores, color=COLORS[method], alpha=0.035)
    fig.suptitle(title, y=0.96, fontsize=11)
    fig.legend(loc="lower center", bbox_to_anchor=(0.5, 0.09), ncol=2,
               frameon=False, fontsize=10, columnspacing=1.2)
    fig.text(0.5, 0.035, "Illustrative values only (0–1)",
             ha="center", color="#777777", fontsize=9)
    fig.savefig(OUTPUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUTPUT / f"{name}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})
    for name, (title, values) in CHARTS.items():
        draw(name, title, values)
