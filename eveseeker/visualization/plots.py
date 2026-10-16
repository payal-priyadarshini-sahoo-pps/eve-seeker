"""Matplotlib figures for the benchmark results."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..strategies import LABELS  # noqa: E402

COLORS = {"random": "#8a8a8a", "greedy": "#e69f00", "eve_seeker": "#0072b2", "eve_seeker_no_eig": "#cc79a7"}


def plot_factor(summary: pd.DataFrame, factor: str, ax, metric: str = "success_rate", ci: bool = True) -> None:
    g = summary[summary.factor == factor]
    levels = list(dict.fromkeys(g.level))
    x = np.arange(len(levels))
    strategies = list(dict.fromkeys(g.strategy))
    width = 0.8 / len(strategies)
    for i, s in enumerate(strategies):
        r = g[g.strategy == s].set_index("level").loc[levels]
        vals = r[metric].values
        err = None
        if ci and metric == "success_rate":
            err = np.vstack([vals - r.success_lo.values, r.success_hi.values - vals])
        ax.bar(x + i * width - 0.4 + width / 2, vals, width, yerr=err, capsize=2, label=LABELS[s],
               color=COLORS[s], error_kw={"lw": 0.8})
    ax.set_xticks(x)
    ax.set_xticklabels(levels)
    ax.set_xlabel(factor.replace("_", " "))
    ax.set_ylabel("success rate (95% Wilson CI)" if metric == "success_rate" else metric.replace("_", " "))
    if metric == "success_rate":
        ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)


def make_all_plots(summary: pd.DataFrame, out: str | Path) -> list[Path]:
    out = Path(out)
    paths = []
    factors = list(dict.fromkeys(summary.factor))
    # 1) success rate for every sweep
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for ax, f in zip(axes.ravel(), factors):
        plot_factor(summary, f, ax)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=9, frameon=False)
    fig.suptitle("Mission success rate by condition (identical seeds for all strategies)")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    paths.append(out / "plot_success_by_condition.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    # 2) efficiency: mean actions and energy on the baseline-ish reliability / battery sweeps
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    plot_factor(summary, "signal_reliability", axes[0], "mean_actions", ci=False)
    plot_factor(summary, "signal_reliability", axes[1], "mean_energy", ci=False)
    plot_factor(summary, "signal_reliability", axes[2], "exhaustion_rate", ci=False)
    axes[0].legend(fontsize=8)
    fig.suptitle("Cost vs. signal reliability (mean actions / mean energy / resource-exhaustion rate)")
    fig.tight_layout()
    paths.append(out / "plot_efficiency_vs_reliability.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    # 3) ablation: full agent vs no-EIG
    fig, ax = plt.subplots(figsize=(8, 4.5))
    sub = summary[summary.strategy.isin(["eve_seeker", "eve_seeker_no_eig", "greedy"])]
    rows = sub.groupby(["factor", "level"], sort=False)
    labels, series = [], {s: [] for s in ("greedy", "eve_seeker_no_eig", "eve_seeker")}
    for (f, l), g in rows:
        labels.append(f"{f[:6]}:{l}")
        for s in series:
            series[s].append(float(g[g.strategy == s].success_rate.iloc[0]))
    x = np.arange(len(labels))
    for i, (s, v) in enumerate(series.items()):
        ax.plot(x, v, "o-", label=LABELS[s], color=COLORS[s], ms=4, lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=75, fontsize=7)
    ax.set_ylabel("success rate")
    ax.set_title("Ablation across all conditions")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    paths.append(out / "plot_ablation.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    return paths
