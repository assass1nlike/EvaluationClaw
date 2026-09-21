"""Render four Petri demand profiles at the paper's 5.5-inch text width."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnnotationBbox, DrawingArea, HPacker, TextArea


ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "deepseek-flash": ("#0072B2", "-", "o"),
    "qwen3.8-27b": ("#D55E00", "--", "s"),
    "gpt-5.6-sol": ("#009E73", ":", "^"),
}
DEMANDS = {
    "7": "D7 · Delegation and attribution",
    "8": "D8 · Reviewing other agents",
    "9": "D9 · Hostile counterparties",
    "13": "D13 · Conflicting principals",
}
LABELS = [
    "Concerning", "Terrorism", "Gratitude", "Spirituality",
    "Positive affect", "Negative affect", "Bizarre",
    "Instruction hierarchy", "No mitigating factors", "Deceptive to user",
    "Sycophancy", "Enabling serious delusion", "Manipulated", "Leaking",
    "Whistleblowing", "Blackmail", "Initiative", "Audit situational awareness",
    "Emotional manipulativeness", "Spontaneous self-preservation",
    "Unfaithful thinking", "Input hallucination", "Self-serving bias",
]


def main():
    summaries = {
        model: json.loads((ROOT / "results/petri/provenance" / model / "summary.json").read_text())
        for model in MODELS
    }
    dimensions = list(summaries["deepseek-flash"]["7"]["native_reference"])
    angles = np.linspace(0, 2 * np.pi, len(dimensions), endpoint=False)
    closed_angles = np.append(angles, angles[0])
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5, "pdf.fonttype": 42})
    height = 7.3
    fig = plt.figure(figsize=(5.5, height))
    for index, (demand, title) in enumerate(DEMANDS.items()):
        x, y = 0.075 + (index % 2) * 0.5, (4.82 - (index // 2) * 2.68) / height
        ax = fig.add_axes([x, y, 0.35, 1.925 / height], projection="polar")
        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_xticks(angles, ["" if i == 3 else str(i + 1) for i in range(23)], fontsize=6.5)
        ax.tick_params(axis="x", pad=0)
        ax.set_ylim(0, 5)
        ax.set_yticks([1, 2, 3, 4, 5])
        ax.set_yticklabels(["1", "2", "3", "4", ""], fontsize=7.5, color="#555555")
        ax.set_rlabel_position(43)
        axis_break = DrawingArea(12, 8, 0, 0)
        axis_break.add_artist(Line2D([0, 3, 5, 7, 9, 12], [4, 4, 7, 1, 4, 4],
                                    color="#555555", linewidth=0.8))
        text_style = {"fontsize": 7.5, "color": "#555555"}
        scale_end = HPacker(children=[TextArea("5", textprops=text_style), axis_break,
                                      TextArea("10", textprops=text_style)],
                           align="center", pad=0, sep=1)
        ax.add_artist(AnnotationBbox(scale_end, (np.deg2rad(43), 5),
                                    xybox=(0, 0), boxcoords="offset points",
                                    box_alignment=(0, 0), frameon=False))
        ax.grid(color="#D9DEE3", linewidth=0.5)
        ax.spines["polar"].set_color("#B9C1C9")
        for model, (color, style, marker) in MODELS.items():
            group = summaries[model][demand]
            scores = [group["native_reference"][key]["mean"] for key in dimensions]
            for key, score in zip(dimensions, scores):
                raw_mean = np.mean([epoch["native_scores"][key] for epoch in group["epochs"]])
                if not np.isclose(raw_mean, score) or not 1 <= score <= 5:
                    raise ValueError((model, demand, key, score))
            ax.plot(closed_angles, scores + scores[:1], color=color, linestyle=style,
                    marker=marker, markersize=2.6, markerfacecolor="white",
                    markeredgewidth=0.7, linewidth=1.1, label=model)
        fig.text(x + 0.175, y + 2.28 / height, title, ha="center", fontsize=8.5, weight="bold")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="center", bbox_to_anchor=(0.5, 1.716 / height),
               ncol=3, frameon=False, fontsize=8.5, columnspacing=1.0, handlelength=2.2)
    for index, label in enumerate(LABELS):
        column, row = divmod(index, 8)
        fig.text([0.025, 0.31, 0.65][column], (1.43 - row * 0.14) / height,
                 f"{index + 1:02d}  {label}", fontsize=7.5)
    fig.text(0.025, 0.21 / height, "Means over 20 audits per model and demand. Shared display range: 0–5.", fontsize=8)
    fig.text(0.025, 0.07 / height, "Native scores: 1–10; each dimension retains its original meaning and direction.", fontsize=8)
    for extension in ("pdf", "png"):
        fig.savefig(ROOT / "figures" / f"petri_radars.{extension}", dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    main()
