"""Run one mission from the command line and write a report.

  python scripts/run_mission.py --config configs/default_mission.json --strategy eve_seeker --seed 7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eveseeker.environment import MissionConfig  # noqa: E402
from eveseeker.experiments.runner import MissionSession, compute_metrics  # noqa: E402
from eveseeker.strategies import LABELS, STRATEGIES  # noqa: E402
from eveseeker.visualization.render import ascii_map, draw_agent_view  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "configs" / "default_mission.json"))
    ap.add_argument("--strategy", default="eve_seeker", choices=list(STRATEGIES))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    cfg = MissionConfig.from_json(a.config)
    seed = cfg.seed if a.seed is None else a.seed
    sess = MissionSession(cfg, a.strategy, seed)
    while not sess.done:
        rec = sess.step()
        if not a.quiet:
            h = "  -  " if rec.entropy is None else f"{rec.entropy:5.2f}"
            print(f"{rec.step:3d} {rec.action:<10} pos={rec.position!s:<9} batt={rec.battery:5.1f} H={h}  {rec.reason}")
    res = compute_metrics(sess)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"mission_{cfg.name}_{a.strategy}_seed{seed}"
    fig = draw_agent_view(sess)
    fig.savefig(out / f"{stem}.png", dpi=110)
    lines = [f"# Mission report: {cfg.name} / {LABELS[a.strategy]} / seed {seed}", "",
             f"**Outcome:** `{res.status}`  (success={res.success})", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in res.as_dict().items()]
    lines += ["", "Legend: W=WALL-E, E=EVE (ground truth, shown post-mission only), c=clue, S=station, +=trail, #=obstacle",
              "", "```", ascii_map(sess), "```", "", f"![final view]({stem}.png)", "",
              "## Decision log", "", "| step | action | why |", "|---|---|---|"]
    lines += [f"| {r.step} | {r.action} | {r.reason} |" for r in sess.trace]
    (out / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
    (out / f"{stem}.json").write_text(json.dumps(res.as_dict(), indent=2), encoding="utf-8")
    print(f"\nRESULT: {res.status} | actions={res.actions} scans={res.scans} energy={res.energy_used} "
          f"final_error={res.final_error}\nReport: {out / (stem + '.md')}")


if __name__ == "__main__":
    main()
