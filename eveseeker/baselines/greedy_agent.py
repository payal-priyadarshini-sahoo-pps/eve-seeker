"""Greedy baseline: same Bayesian belief and safety rules, but no information-gain reasoning.

It scans on a fixed cadence (every `scan_interval` steps at a new spot) and always walks to the
currently most probable cell (ties -> nearest).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..agent.base import BeliefAgent
from ..agent.resources import ResourcePolicy
from ..environment.actions import Action
from ..environment.env import Observation, PublicInfo


class GreedyAgent(BeliefAgent):
    name = "greedy"

    def __init__(self, info: PublicInfo, scan_interval: int = 4, assumed_reliability: Optional[float] = None,
                 resource: Optional[ResourcePolicy] = None):
        super().__init__(info, assumed_reliability, resource)
        self.scan_interval = scan_interval

    def act(self, obs: Observation) -> Action:
        self.ingest(obs)
        action, why = self._decide(obs)
        est, conf = self.belief.map_estimate()
        self.explanation = {"step": obs.step, "action": str(action), "reason": why, "mode": "greedy",
                            "entropy_bits": self.belief.entropy(), "map_estimate": est, "map_prob": conf}
        return action

    def _decide(self, obs: Observation) -> tuple[Action, str]:
        pos, bat, bud = obs.position, self.info.battery, self.info.budget
        dist, parent = self.planner.dijkstra(pos)
        rec = self.resources.decide(obs, dist, parent)
        if rec is not None:
            return rec

        need_here = self.resources.reserve_needed(self.resources.return_energy(pos))
        if (self.steps_since_scan >= self.scan_interval and self.scan_counts.get(pos, 0) == 0
                and obs.battery - bat.scan_cost >= need_here and obs.time_remaining >= bud.scan_time):
            return Action.scan(), f"periodic scan (every {self.scan_interval} steps)"

        cells = self.sensor.cells
        d = dist.ravel()[cells]
        reach = np.isfinite(d)
        d0 = np.where(reach, d, 0.0)
        ret = (self.resources.return_energy_map.ravel()[cells] if self.resources.has_stations
               else np.zeros(len(cells)))
        need = self.resources.reserve_needed(ret)
        feas = (reach & (d0 > 0) & (obs.battery - d0 * bat.move_cost >= need)
                & (d0 <= obs.actions_remaining) & (d0 <= obs.time_remaining))
        if not feas.any():
            forced = self.resources.decide(obs, dist, parent, force=True, reason="no reachable target")
            if forced is not None:
                return forced
            est, conf = self.belief.map_estimate()
            return Action.stop(), f"no feasible target; stopping with MAP {est} (p={conf:.2f})"
        score = np.where(feas, self.belief.prob.ravel()[cells] - 1e-9 * d0, -np.inf)
        i = int(np.argmax(score))
        target = (int(cells[i] % self.info.width), int(cells[i] // self.info.width))
        path = self.planner.path_from_parents(parent, pos, target)
        return (self.step_towards(pos, path[1]),
                f"go to most probable reachable cell {target} (p={self.belief.prob[target[1], target[0]]:.3f})")
