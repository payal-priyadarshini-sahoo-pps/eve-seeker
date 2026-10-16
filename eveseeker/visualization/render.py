"""Grid rendering for the dashboard / reports. The agent view never draws ground truth."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..experiments.runner import MissionSession  # noqa: E402

ARROW = {"N": (0, -0.35), "S": (0, 0.35), "E": (0.35, 0), "W": (-0.35, 0)}


def _base(session: MissionSession, ax) -> None:
    info = session.env.info
    ax.set_xlim(-0.5, info.width - 0.5)
    ax.set_ylim(info.height - 0.5, -0.5)
    ax.set_aspect("equal")
    ax.set_xticks(range(0, info.width, 2))
    ax.set_yticks(range(0, info.height, 2))
    ax.tick_params(labelsize=7)
    for x, y in info.obstacles:
        ax.add_patch(plt.Rectangle((x - 0.5, y - 0.5), 1, 1, color="#2b2d42"))
    for x, y in info.stations:
        ax.add_patch(plt.Rectangle((x - 0.5, y - 0.5), 1, 1, fill=False, ec="#2a9d8f", lw=2))
        ax.text(x, y, "⚡", ha="center", va="center", fontsize=8, color="#2a9d8f")


def draw_agent_view(session: MissionSession, show_heatmap: bool = True):
    """Belief heatmap, trail, discovered clues, WALL-E and the estimated EVE position."""
    info = session.env.info
    fig, ax = plt.subplots(figsize=(6.2, 6.2))
    belief = session.agent.belief_map()
    if show_heatmap and belief is not None:
        img = np.ma.masked_where(belief <= 0, belief)
        im = ax.imshow(img, cmap="magma_r", alpha=0.9, vmin=0, vmax=max(float(belief.max()), 1e-9))
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02, label="P(EVE here)")
    _base(session, ax)
    ax.grid(color="#cccccc", lw=0.3)
    if len(session.trail) > 1:
        t = np.array(session.trail)
        ax.plot(t[:, 0], t[:, 1], "-", color="#118ab2", lw=1.5, alpha=0.8, label="trail")
    for (cx, cy), hint in session.discovered.items():
        ax.plot(cx, cy, "D", color="#ffd166", mec="k", ms=7)
        dx, dy = ARROW[hint]
        ax.annotate("", xy=(cx + dx * 2, cy + dy * 2), xytext=(cx, cy), arrowprops=dict(arrowstyle="->", color="#e76f51", lw=1.5))
    est, conf = session.agent.estimate() if session.obs.contact is None else (session.obs.contact, 1.0)
    if est is not None and belief is not None:
        ax.plot(*est, "*", color="#06d6a0", mec="k", ms=17, label=f"EVE estimate (p={conf:.2f})")
    x, y = session.obs.position
    ax.plot(x, y, "o", color="#ef476f", mec="k", ms=12, label="WALL-E")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=3, fontsize=8, frameon=False)
    ax.set_title("Agent's view (belief only)", fontsize=10)
    fig.tight_layout()
    return fig


def draw_truth_view(session: MissionSession):
    """EVALUATION ONLY. Shows hidden EVE / clues / decoys next to the agent's estimate."""
    truth = session.env.evaluator_view()
    fig, ax = plt.subplots(figsize=(5.4, 5.4))
    _base(session, ax)
    ax.grid(color="#cccccc", lw=0.3)
    for cx, cy in truth.clues:
        ax.plot(cx, cy, "D", color="#ffd166", mec="k", ms=6, alpha=0.9)
    for dx, dy in truth.decoys:
        ax.plot(dx, dy, "X", color="#9d4edd", ms=9, label="decoy source")
    ax.plot(*truth.eve, "*", color="#d00000", mec="k", ms=20, label="EVE (ground truth)")
    est = session.agent.estimate()[0]
    if est is not None and session.agent.belief_map() is not None:
        ax.plot(*est, "*", color="#06d6a0", mec="k", ms=12, label="agent estimate")
    ax.plot(*session.obs.position, "o", color="#ef476f", mec="k", ms=10, label="WALL-E")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=3, fontsize=8, frameon=False)
    ax.set_title("EVALUATION-ONLY ground truth", fontsize=10, color="#d00000")
    fig.tight_layout()
    return fig


def ascii_map(session: MissionSession) -> str:
    """Compact text rendering used in mission reports (includes the truth: reports are post-mission)."""
    info, truth = session.env.info, session.env.evaluator_view()
    trail = set(session.trail)
    rows = []
    for y in range(info.height):
        row = []
        for x in range(info.width):
            c = (x, y)
            ch = "#" if c in info.obstacles else "."
            if c in trail:
                ch = "+"
            if c in info.stations:
                ch = "S"
            if c in truth.clues:
                ch = "c"
            if c == truth.eve:
                ch = "E"
            if c == session.obs.position:
                ch = "W"
            row.append(ch)
        rows.append("".join(row))
    return "\n".join(rows)
