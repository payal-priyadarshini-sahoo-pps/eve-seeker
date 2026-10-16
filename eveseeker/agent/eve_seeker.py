"""EVE-Seeker: Bayesian belief + expected-information-gain action selection + resource-aware planning.

Each step (receding horizon, replanned from the current belief):
  1. Fold the latest observation into the belief (Bayes).
  2. Resource rule: head to / stay at a recharge station if battery slack is low.
  3. Enumerate candidate *destinations*, each with two variants: "visit" (just walk there; seeing
     the surroundings on arrival) and "visit + scan". Keep only feasible ones: reachable by
     Dijkstra, within time/action budgets, and leaving enough energy to return to a station.
  4. Score each by  EIG(bits) / cost, with cost = energy + time_weight * time. In the endgame
     (little time left) information is only useful if it can still be acted on, so score by the
     probability of directly finding EVE instead.
  5. Execute the first step of the best plan (with hysteresis to avoid dithering).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..environment.actions import Action
from ..environment.env import Observation, PublicInfo
from .base import BeliefAgent
from .info_gain import batch_eig
from .resources import ResourcePolicy


@dataclass
class SeekerConfig:
    use_eig: bool = True               # False -> ablation: no information-gain-based selection
    time_weight: float = 0.5           # cost = energy + time_weight * time
    endgame_frac: float = 0.15         # below this remaining budget fraction, hunt for contact only
    min_utility: float = 1e-6
    hysteresis: float = 0.85           # keep the previous plan if it scores >= this * best
    repeat_scan_discount: float = 0.5  # discount per earlier scan at the same cell (model-mismatch guard)
    assumed_reliability: Optional[float] = None
    scan_interval: int = 4             # only used by the no-EIG ablation (scan on a fixed schedule)
    resource: ResourcePolicy = field(default_factory=ResourcePolicy)


class EveSeekerAgent(BeliefAgent):
    def __init__(self, info: PublicInfo, config: Optional[SeekerConfig] = None):
        self.cfg = config or SeekerConfig()
        super().__init__(info, self.cfg.assumed_reliability, self.cfg.resource)
        self.name = "eve_seeker" if self.cfg.use_eig else "eve_seeker_no_eig"
        self._plan: Optional[tuple[int, bool]] = None   # (index into sensor.cells, scan?)
        self._tabu: set[int] = set()
        self._tabu_until = -1
        self.loop_breaks = 0

    # ------------------------------------------------------------------ main entry
    def act(self, obs: Observation) -> Action:
        self.ingest(obs)
        action, why, info = self._decide(obs)
        h = self.belief.entropy()
        est, conf = self.belief.map_estimate()
        self.explanation = {"step": obs.step, "action": str(action), "reason": why, "entropy_bits": h,
                            "map_estimate": est, "map_prob": conf, **info}
        self.recent.append((obs.position, action.type.value))
        return action

    # ------------------------------------------------------------------ decision logic
    def _decide(self, obs: Observation) -> tuple[Action, str, dict]:
        pos = obs.position
        dist, parent = self.planner.dijkstra(pos)
        self._update_loop_guard(obs)

        rec = self.resources.decide(obs, dist, parent)
        if rec is not None:
            return rec[0], rec[1], {"mode": "resource"}

        endgame = self._in_endgame(obs)
        if not self.cfg.use_eig and not endgame and self._scan_due(obs):
            return Action.scan(), f"scheduled scan (every {self.cfg.scan_interval} steps; no EIG in this ablation)", \
                {"mode": "scheduled-scan"}

        choice = self._best_candidate(obs, dist, endgame)
        if choice is None:
            forced = self.resources.decide(obs, dist, parent, force=True, reason="no productive action feasible")
            if forced is not None:
                return forced[0], forced[1], {"mode": "resource"}
            est, conf = self.belief.map_estimate()
            return Action.stop(), (f"no feasible action improves the belief; stopping and reporting "
                                   f"MAP estimate {est} (p={conf:.2f}) as uncertain"), {"mode": "stop"}

        target, scan = choice["target"], choice["scan"]
        mode = "endgame" if endgame else ("info-gain" if self.cfg.use_eig else "mass")
        info = {"mode": mode, **{k: v for k, v in choice.items() if k != "idx"}}
        if target == pos and scan:
            return Action.scan(), self._explain(choice, mode, "scan here"), info
        path = self.planner.path_from_parents(parent, pos, target)
        if not path or len(path) < 2:  # should not happen; fail safe
            return Action.wait(), "path vanished; waiting one tick", info
        return self.step_towards(pos, path[1]), self._explain(choice, mode, f"go to {target}" + (" and scan" if scan else "")), info

    def _explain(self, c: dict, mode: str, what: str) -> str:
        metric = {"info-gain": f"expected info gain {c['eig_bits']:.2f} bits",
                  "mass": f"belief mass in view {c['p_contact']:.2f}",
                  "endgame": f"P(find EVE) {c['p_contact']:.2f}"}[mode]
        return (f"[{mode}] {what}: {metric}, cost {c['cost']:.1f}, score {c['utility']:.3f}; "
                f"best of {c['n_options']} feasible options, entropy {self.belief.entropy():.2f} bits")

    def _in_endgame(self, obs: Observation) -> bool:
        b = self.info.budget
        frac = min(obs.time_remaining / b.max_time, obs.actions_remaining / b.max_actions)
        return frac < self.cfg.endgame_frac

    def _scan_due(self, obs: Observation) -> bool:
        if self.steps_since_scan < self.cfg.scan_interval or self.scan_counts.get(obs.position, 0) > 0:
            return False
        bat, bud = self.info.battery, self.info.budget
        need = self.resources.reserve_needed(self.resources.return_energy(obs.position))
        return (obs.battery - bat.scan_cost >= need and obs.time_remaining >= bud.scan_time
                and obs.actions_remaining >= 1)

    def _best_candidate(self, obs: Observation, dist: np.ndarray, endgame: bool) -> Optional[dict]:
        cfg, s = self.cfg, self.sensor
        bat, bud = self.info.battery, self.info.budget
        cells = s.cells
        d = dist.ravel()[cells]
        reach = np.isfinite(d)
        d0 = np.where(reach, d, 0.0)
        ret = self.resources.return_energy_map.ravel()[cells] if self.resources.has_stations else np.zeros(len(cells))
        need = self.resources.reserve_needed(ret)
        e_move = d0 * bat.move_cost
        left_v = obs.battery - e_move
        feas_v = reach & (d0 > 0) & (left_v >= need) & (d0 <= obs.actions_remaining) & (d0 <= obs.time_remaining)
        feas_s = (reach & (left_v - bat.scan_cost >= need) & (d0 + 1 <= obs.actions_remaining)
                  & (d0 + bud.scan_time <= obs.time_remaining))
        if endgame or not cfg.use_eig:
            feas_s[:] = False
        if obs.step < self._tabu_until and self._tabu:
            tabu = np.zeros(len(cells), dtype=bool)
            tabu[[i for i, c in enumerate(cells) if int(c) in self._tabu]] = True
            feas_v &= ~tabu
            feas_s &= ~(tabu & (d0 > 0))
        sub = np.flatnonzero(feas_v | feas_s)
        if sub.size == 0:
            return None

        lik, vis = s.stacks()
        eig_v, eig_s, p_c = batch_eig(self.belief.prob.ravel(), lik[sub], vis[sub])
        cost_v = np.maximum(e_move[sub] + cfg.time_weight * d0[sub], 0.5)
        cost_s = e_move[sub] + bat.scan_cost + cfg.time_weight * (d0[sub] + bud.scan_time)
        fv, fs = feas_v[sub], feas_s[sub]
        neg = -np.inf
        if endgame:
            util_v, val_v = p_c - 1e-6 * cost_v, p_c
            util_s = np.full(sub.size, neg)
        elif cfg.use_eig:
            util_v, val_v = eig_v / cost_v, eig_v
            counts = np.array([self.scan_counts.get(self._cell_xy(cells[i]), 0) for i in sub])
            util_s = eig_s * cfg.repeat_scan_discount ** counts / cost_s
        else:
            util_v, val_v = p_c / cost_v, p_c
            util_s = np.full(sub.size, neg)
        util_v = np.where(fv, util_v, neg)
        util_s = np.where(fs, util_s, neg)

        both = np.concatenate([util_v, util_s])
        j = int(np.argmax(both))
        if both[j] <= cfg.min_utility:
            return None
        # hysteresis: stick with the previous plan if it is still nearly as good
        if self._plan is not None:
            pi, pscan = self._plan
            where = np.flatnonzero(sub == pi)
            if where.size:
                jp = int(where[0]) + (sub.size if pscan else 0)
                if both[jp] > cfg.min_utility and both[jp] >= cfg.hysteresis * both[j]:
                    j = jp
        scan = j >= sub.size
        k = j - sub.size if scan else j
        self._plan = (int(sub[k]), scan)
        top = np.argsort(both)[::-1][:4]
        alts = [{"cell": self._cell_xy(cells[sub[t % sub.size]]), "scan": bool(t >= sub.size),
                 "utility": float(both[t])} for t in top if both[t] > neg]
        return {
            "target": self._cell_xy(cells[sub[k]]), "scan": scan,
            "eig_bits": float(eig_s[k] if scan else eig_v[k]), "p_contact": float(p_c[k]),
            "cost": float(cost_s[k] if scan else cost_v[k]), "utility": float(both[j]),
            "n_options": int(np.isfinite(both).sum()), "alternatives": alts,
        }

    def _cell_xy(self, flat: int) -> tuple[int, int]:
        return int(flat % self.info.width), int(flat // self.info.width)

    # ------------------------------------------------------------------ loop watchdog
    def _update_loop_guard(self, obs: Observation) -> None:
        if len(self.recent) < self.recent.maxlen or self.resources.mode is not None:
            return
        positions = {p for p, _ in self.recent}
        stalled = len(self.entropy_trace) > 20 and self.entropy_trace[-1] >= self.entropy_trace[-20] - 0.01
        if len(positions) <= 4 and stalled:
            self.loop_breaks += 1
            self._tabu = {y * self.info.width + x for x, y in positions}
            self._tabu_until = obs.step + 12
            self._plan = None
            self.recent.clear()
