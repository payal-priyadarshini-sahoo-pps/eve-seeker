"""Mission execution: the only place where the environment, an agent and the evaluator meet.

The agent is handed `Observation`s and nothing else. Ground truth is read only in `compute_metrics`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np

from ..agent.base import Agent
from ..environment import MissionConfig, MissionEnv, RESOURCE_EXHAUSTION, STOPPED, SUCCESS, manhattan
from ..strategies import make_agent


NEAR_BUDGET = 0.05  # a STOP with <= 5% of actions or time left counts as resource exhaustion


@dataclass
class StepRecord:
    step: int
    action: str
    position: tuple[int, int]
    battery: float
    entropy: Optional[float]
    estimate: Optional[tuple[int, int]]
    reading: Optional[int]
    reason: str
    mode: str
    message: str
    clues: list
    belief: Optional[np.ndarray] = None   # snapshot after the observation (for replay/visuals)


class MissionSession:
    """Step-by-step mission driver (used by the CLI runner and by the dashboard)."""

    def __init__(self, config: MissionConfig, strategy: str, seed: int, snapshots: bool = False):
        self.config, self.strategy, self.seed = config, strategy, seed
        self.snapshots = snapshots
        self.env = MissionEnv(config, seed)
        self.agent: Agent = make_agent(strategy, self.env.info, seed)
        self.obs = self.env.reset()
        self.trace: list[StepRecord] = []
        self.trail = [self.obs.position]
        self.discovered: dict[tuple[int, int], str] = {}

    @property
    def done(self) -> bool:
        return self.env.done

    def step(self) -> StepRecord:
        if self.done:
            raise RuntimeError("mission finished")
        action = self.agent.act(self.obs)
        expl = dict(getattr(self.agent, "explanation", {}) or {})
        obs = self.env.step(action)
        for c in obs.new_clues:
            self.discovered[c.pos] = c.hint
        rec = StepRecord(
            step=obs.step, action=str(action), position=obs.position, battery=obs.battery,
            entropy=self.agent.entropy(), estimate=(self.agent.estimate()[0] if obs.contact is None else obs.contact),
            reading=obs.scan_reading, reason=expl.get("reason", ""), mode=expl.get("mode", ""),
            message=obs.message, clues=[(c.pos, c.hint) for c in obs.new_clues],
            belief=(np.array(self.agent.belief_map(), copy=True) if self.snapshots and self.agent.belief_map() is not None else None))
        self.trace.append(rec)
        self.trail.append(obs.position)
        self.obs = obs
        return rec

    def run(self) -> "MissionResult":
        while not self.done:
            self.step()
        return compute_metrics(self)


@dataclass
class MissionResult:
    strategy: str
    seed: int
    status: str
    success: bool
    actions: int
    scans: int
    recharges: int
    invalid_actions: int
    energy_used: float
    time_used: int
    resource_exhausted: bool
    final_error: float          # Manhattan distance between final estimate and EVE
    localized_exact: bool
    localized_within2: bool
    final_entropy: Optional[float]
    final_confidence: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_metrics(session: MissionSession) -> MissionResult:
    """Evaluation-only: compares the agent's final estimate with ground truth."""
    truth = session.env.evaluator_view().eve
    env, agent = session.env, session.agent
    success = env.status == SUCCESS
    if success:
        est, conf = truth, 1.0   # visual contact is confirmed knowledge
    else:
        est, conf = agent.estimate()
    err = float(manhattan(est, truth)) if est is not None else float("nan")
    st = env.stats
    # A voluntary STOP with (almost) no budget left is effectively exhaustion, so it is counted as such.
    obs, bud = session.obs, session.env.info.budget
    near_budget_stop = env.status == STOPPED and (obs.actions_remaining <= NEAR_BUDGET * bud.max_actions
                                                  or obs.time_remaining <= NEAR_BUDGET * bud.max_time)
    final_entropy = None if agent.entropy() is None else (0.0 if success else agent.entropy())
    return MissionResult(
        strategy=session.strategy, seed=session.seed, status=env.status, success=success,
        actions=st.actions, scans=st.scans, recharges=st.recharges, invalid_actions=st.invalid_actions,
        energy_used=round(st.energy_used, 4), time_used=st.time_used,
        resource_exhausted=env.status in RESOURCE_EXHAUSTION or near_budget_stop, final_error=err,
        localized_exact=err == 0, localized_within2=bool(err <= 2),
        final_entropy=final_entropy, final_confidence=float(conf))


def run_mission(config: MissionConfig, strategy: str, seed: int) -> MissionResult:
    return MissionSession(config, strategy, seed).run()
