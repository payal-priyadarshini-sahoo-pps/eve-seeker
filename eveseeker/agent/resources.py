"""Battery / time management shared by every strategy so that comparisons are fair.

Rules (all explainable):
  * Safety: an excursion is only allowed if, afterwards, the agent can still walk to a station
    (energy_left >= energy_to_nearest_station + margin).
  * Recharge trips: go to a station when slack (battery - energy to nearest station) falls below
    `low_slack`, when no productive action is feasible, or opportunistically when already standing
    on a station with less than `opportunistic_frac` of the battery.
  * Recharging continues until `target_frac` of capacity unless time/actions are nearly exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..environment.actions import Action
from ..environment.env import Observation, PublicInfo
from .planning import GridPlanner

Cell = tuple[int, int]


@dataclass
class ResourcePolicy:
    reserve_margin: float = 1.0
    low_slack: float = 6.0
    opportunistic_frac: float = 0.5
    target_frac: float = 0.95


class ResourceManager:
    def __init__(self, info: PublicInfo, planner: GridPlanner, policy: Optional[ResourcePolicy] = None):
        self.info = info
        self.planner = planner
        self.policy = policy or ResourcePolicy()
        self.has_stations = len(info.stations) > 0
        self.return_energy_map = planner.station_dist * info.battery.move_cost  # inf when no station
        self.mode: Optional[str] = None  # None | "returning" | "recharging"
        self.last_reason = ""

    # ---------------------------------------------------------------- feasibility
    def return_energy(self, cell: Cell) -> float:
        if not self.has_stations:
            return 0.0
        return float(self.return_energy_map[cell[1], cell[0]])

    def reserve_needed(self, return_energy: np.ndarray | float):
        """Energy that must remain after an excursion ending at cells with the given return cost."""
        if not self.has_stations:
            return np.zeros_like(return_energy, dtype=float) if isinstance(return_energy, np.ndarray) else 0.0
        margin = np.where(np.asarray(return_energy) > 0, self.policy.reserve_margin, 0.0)
        return np.asarray(return_energy) + margin

    # ---------------------------------------------------------------- recharge logic
    def decide(self, obs: Observation, dist: np.ndarray, parent: np.ndarray,
               force: bool = False, reason: str = "") -> Optional[tuple[Action, str]]:
        """Return (action, explanation) if the agent should recharge / head to a station, else None."""
        if not self.has_stations:
            return None
        cap = self.info.battery.capacity
        pol = self.policy
        pos = obs.position
        batt = obs.battery
        at_station = obs.at_station

        if at_station:
            if self.mode == "recharging":
                if batt < pol.target_frac * cap and obs.time_remaining > 2 and obs.actions_remaining > 1:
                    return Action.recharge(), f"recharging ({batt:.0f}/{cap:.0f}) before resuming search"
                self.mode = None
            wants = force or batt < pol.low_slack or batt < pol.opportunistic_frac * cap or self.mode == "returning"
            if wants and batt < cap - 1e-9 and obs.time_remaining > 2 and obs.actions_remaining > 1:
                why = reason or ("arrived at station" if self.mode == "returning" else "battery below policy threshold")
                self.mode = "recharging"
                return Action.recharge(), f"recharging at station: {why}"
            self.mode = None
            return None

        slack = batt - self.return_energy(pos)
        trigger = force or slack < pol.low_slack or self.mode == "returning"
        if not trigger:
            return None
        # nearest reachable station
        best, best_d = None, np.inf
        for s in self.info.stations:
            d = dist[s[1], s[0]]
            if d < best_d:
                best, best_d = s, d
        if best is None or not np.isfinite(best_d):
            return None
        if best_d * self.info.battery.move_cost > batt:
            return None  # cannot even reach it; nothing sensible to do here
        if obs.time_remaining < best_d + 3 or obs.actions_remaining < best_d + 2:
            self.mode = None
            return None  # no time for a recharge round trip; spend what is left
        path = self.planner.path_from_parents(parent, pos, best)
        if not path or len(path) < 2:
            return None
        self.mode = "returning"
        nxt = path[1]
        why = reason or f"slack {slack:.0f} < {pol.low_slack:.0f}"
        return Action.move(nxt[0] - pos[0], nxt[1] - pos[1]), \
            f"heading to recharge station {best} ({int(best_d)} steps away): {why}"
