"""Reproducible benchmark: all strategies on identical seeds across one-factor-at-a-time sweeps.

Usage:  python -m eveseeker.experiments.run_experiments --trials 60 --out results
Evaluation seeds are 0..trials-1 (tuning during development used seeds >= 1000).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ..environment import MissionConfig
from ..strategies import LABELS
from .runner import run_mission
from .stats import mean_ci, paired_bootstrap_diff, wilson_ci

STRATEGY_SET = ("random", "greedy", "eve_seeker", "eve_seeker_no_eig")

BASE = MissionConfig(name="benchmark", width=20, height=20, obstacle_density=0.10).override(
    **{"budget.max_actions": 100, "budget.max_time": 150, "battery.capacity": 40.0})

# factor -> list of (level label, overrides)
SWEEPS: dict[str, list[tuple[str, dict]]] = {
    "map_size": [(f"{n}x{n}", {"width": n, "height": n}) for n in (12, 20, 28)],
    "obstacle_density": [(str(d), {"obstacle_density": d}) for d in (0.0, 0.10, 0.25)],
    "signal_reliability": [(str(r), {"signal.reliability": r}) for r in (0.95, 0.8, 0.6, 0.4)],
    "misleading_prob": [(str(p), {"decoys.count": 2, "decoys.probability": p}) for p in (0.0, 0.3, 0.6)],
    "battery_capacity": [(str(c), {"battery.capacity": float(c)}) for c in (25, 40, 80)],
    "clue_distribution": [(d, {"clues.distribution": d}) for d in ("none", "uniform", "near_target", "far_target")],
}


def _job(args):
    cfg_dict, strategy, seed, factor, level = args
    res = run_mission(MissionConfig.from_dict(cfg_dict), strategy, seed).as_dict()
    res.update(factor=factor, level=level)
    return res


def run_all(trials: int, workers: int | None = None, strategies=STRATEGY_SET) -> pd.DataFrame:
    jobs = []
    for factor, levels in SWEEPS.items():
        for level, overrides in levels:
            cfg = BASE.override(**overrides).to_dict()
            for strategy in strategies:
                for seed in range(trials):
                    jobs.append((cfg, strategy, seed, factor, level))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(_job, jobs, chunksize=16))
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (factor, level, strat), g in df.groupby(["factor", "level", "strategy"], sort=False):
        n, k = len(g), int(g.success.sum())
        lo, hi = wilson_ci(k, n)
        acts, a_lo, a_hi = mean_ci(g.actions)
        ok = g[g.success]
        rows.append(dict(
            factor=factor, level=level, strategy=strat, trials=n, success_rate=k / n, success_lo=lo, success_hi=hi,
            mean_actions=acts, actions_ci_lo=a_lo, actions_ci_hi=a_hi,
            mean_actions_success=ok.actions.mean() if len(ok) else np.nan,
            mean_energy=g.energy_used.mean(), mean_scans=g.scans.mean(), mean_recharges=g.recharges.mean(),
            exhaustion_rate=g.resource_exhausted.mean(), stopped_rate=(g.status == "stopped_uncertain").mean(),
            mean_final_error=g.final_error.mean(), within2_rate=g.localized_within2.mean(),
            mean_final_entropy=g.final_entropy.mean(), invalid_action_rate=g.invalid_actions.mean()))
    return pd.DataFrame(rows)


def paired_table(df: pd.DataFrame) -> pd.DataFrame:
    """EVE-Seeker vs each other strategy: paired success-rate difference with bootstrap CI."""
    rows = []
    for (factor, level), g in df.groupby(["factor", "level"], sort=False):
        piv = g.pivot(index="seed", columns="strategy", values="success").astype(float)
        for other in ("random", "greedy", "eve_seeker_no_eig"):
            d, lo, hi = paired_bootstrap_diff(piv["eve_seeker"], piv[other])
            rows.append(dict(factor=factor, level=level, vs=other, diff=d, ci_lo=lo, ci_hi=hi,
                             significant=(lo > 0 or hi < 0)))
    return pd.DataFrame(rows)


def to_markdown(summary: pd.DataFrame) -> str:
    out = []
    for factor, g in summary.groupby("factor", sort=False):
        out.append(f"\n### {factor}\n")
        out.append("| level | strategy | success (95% CI) | actions (mean) | energy | scans | exhaustion | final err |")
        out.append("|---|---|---|---|---|---|---|---|")
        for _, r in g.iterrows():
            out.append(f"| {r.level} | {LABELS[r.strategy]} | {r.success_rate:.2f} [{r.success_lo:.2f}, {r.success_hi:.2f}] "
                       f"| {r.mean_actions:.1f} | {r.mean_energy:.1f} | {r.mean_scans:.1f} | {r.exhaustion_rate:.2f} "
                       f"| {r.mean_final_error:.1f} |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--out", default="results")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    df = run_all(args.trials, args.workers)
    df.to_csv(out / "experiment_results.csv", index=False)
    summary = summarize(df)
    summary.to_csv(out / "summary.csv", index=False)
    paired = paired_table(df)
    paired.to_csv(out / "paired_comparisons.csv", index=False)
    (out / "results_table.md").write_text(to_markdown(summary), encoding="utf-8")
    (out / "run_metadata.json").write_text(json.dumps({
        "trials_per_condition": args.trials, "seeds": f"0..{args.trials - 1}", "strategies": STRATEGY_SET,
        "base_config": BASE.to_dict(), "sweeps": {k: [l for l, _ in v] for k, v in SWEEPS.items()},
        "missions": len(df), "seconds": round(time.time() - t0, 1)}, indent=2), encoding="utf-8")
    from ..visualization.plots import make_all_plots
    make_all_plots(summary, out)
    print(f"{len(df)} missions in {time.time() - t0:.0f}s -> {out}/")


if __name__ == "__main__":
    main()
