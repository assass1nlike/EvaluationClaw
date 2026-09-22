"""Plot available measured results and an empty frontier radar."""

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUTPUT = Path(__file__).resolve().parent
METRICS = ["Correctness", "Faithfulness", "Diversity", "Difficulty", "Non-contamination"]
COLORS = {
    "EvalScientist": "#0072B2",
    "Expert-curated": "#D55E00",
}


def draw(name, title, values):
    angles = np.linspace(0, 2 * np.pi, len(METRICS), endpoint=False)
    closed_angles = np.append(angles, angles[0])
    fig, ax = plt.subplots(figsize=(5, 4.5), subplot_kw={"projection": "polar"})
    fig.subplots_adjust(left=0.23, right=0.77, bottom=0.24, top=0.80)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_xticks(angles, [label.replace("Non-contamination", "Non-\ncontamination") for label in METRICS], fontsize=10)
    for angle, label in zip(angles, ax.get_xticklabels()):
        label.set_horizontalalignment("center" if angle == 0 else "left" if angle < np.pi else "right")
    ax.tick_params(axis="x", pad=10)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color="#7B8490", fontsize=8)
    ax.set_rlabel_position(10)
    ax.grid(color="#DCE1E6", linewidth=0.7)
    ax.spines["polar"].set_color("#CAD1D8")
    for method, scores in values.items():
        scores = [np.nan if score is None else score for score in scores]
        closed_scores = scores + scores[:1]
        ax.plot(closed_angles, closed_scores, label=method, color=COLORS[method],
                linewidth=2.1 if method == "EvalScientist" else 1.5,
                linestyle="--" if method == "Expert-curated" else "-", marker="o", markersize=3)
        if np.isfinite(scores).all():
            ax.fill(closed_angles, closed_scores, color=COLORS[method], alpha=0.035)
    fig.suptitle(title, y=0.96, fontsize=11)
    if values:
        fig.legend(loc="lower center", bbox_to_anchor=(0.5, 0.035), ncol=2,
                   frameon=False, fontsize=10, columnspacing=1.2)
    fig.savefig(OUTPUT / f"{name}.pdf")
    fig.savefig(OUTPUT / f"{name}.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42})
    spec = importlib.util.spec_from_file_location("radar_results", OUTPUT.parent/'results/laaj/radar.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.collect()
    values = {method: [metrics[name]['value'] for name in METRICS]
              for method, metrics in data['aggregate'].items()}
    draw('conventional_radar', 'Conventional demands', values)
    draw('frontier_radar', 'Frontier and custom demands', {})
