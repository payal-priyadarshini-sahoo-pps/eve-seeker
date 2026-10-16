"""Uninformed baseline: random walk with occasional scans (readings are ignored).

It shares the safety/recharge rules with the other agents so that it does not simply strand itself.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..agent.base import Agent
from ..agent.planning import GridPlanner
from ..agent.resources import ResourceManager, ResourcePolicy
from ..environment.actions import Action
from ..environment.env import Observation, PublicInfo


class RandomAgent(Agent):
    name = "random"

    def __init__(self, info: PublicInfo, seed: int = 0, p_scan: float = 0.15,
                 resource: Optional[ResourcePolicy] = None):
        self.info = info
        self.rng = np.random.default_rng([seed, 2])
        self.p_scan = p_scan
        self.planner = GridPlanner(info)
        self.resources = ResourceManager(info, self.planner, resource)
        self.explanation = {}
        self._free = [(x, y) for y in range(info.height) for x in range(info.width)
                      if (x, y) not in info.obstacles]

    def act(self, obs: Observation) -> Action:
        action, why = self._decide(obs)
        self.explanation = {"step": obs.step, "action": str(action), "reason": why, "mode": "random"}
        return action

    def _decide(self, obs: Observation) -> tuple[Action, str]:
        pos, bat, bud = obs.position, self.info.battery, self.info.budget
        dist, parent = self.planner.dijkstra(pos)
        rec = self.resources.decide(obs, dist, parent)
        if rec is not None:
            return rec
        need_here = self.resources.reserve_needed(self.resources.return_energy(pos))
        if (self.rng.random() < self.p_scan and obs.battery - bat.scan_cost >= need_here
                and obs.time_remaining >= bud.scan_time):
            return Action.scan(), "random scan (reading ignored)"
        options = []
        for nb in self.planner.neighbors(pos):
            need = self.resources.reserve_needed(self.resources.return_energy(nb))
            if obs.battery - bat.move_cost >= need:
                options.append(nb)
        if not options:
            forced = self.resources.decide(obs, dist, parent, force=True, reason="no safe random move")
            if forced is not None:
                return forced
            return Action.stop(), "no safe move left; stopping"
        nb = options[int(self.rng.integers(len(options)))]
        return self.step_towards(pos, nb), f"random step to {nb}"

    @staticmethod
    def step_towards(pos, nxt) -> Action:
        return Action.move(nxt[0] - pos[0], nxt[1] - pos[1])

    def estimate(self) -> tuple[Optional[tuple[int, int]], float]:
        """No belief: the final 'guess' is a uniformly random free cell (chance level)."""
        cell = self._free[int(self.rng.integers(len(self._free)))]
        return cell, 1.0 / len(self._free)
