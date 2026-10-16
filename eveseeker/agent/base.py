"""Common agent plumbing. Agents depend only on PublicInfo / Observation / Action (never on the env)."""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np

from ..environment.actions import Action
from ..environment.env import Observation, PublicInfo
from .belief import BeliefState
from .planning import GridPlanner
from .resources import ResourceManager, ResourcePolicy
from .sensor_model import SensorModel

Cell = tuple[int, int]


class Agent:
    """Interface every strategy implements."""
    name = "agent"

    def act(self, obs: Observation) -> Action:
        raise NotImplementedError

    # optional introspection used by the runner / dashboard
    explanation: dict = {}

    def estimate(self) -> tuple[Optional[Cell], float]:
        return None, 0.0

    def belief_map(self) -> Optional[np.ndarray]:
        return None

    def entropy(self) -> Optional[float]:
        return None


class BeliefAgent(Agent):
    """Agent that keeps a Bayesian belief and shares resource management logic."""

    def __init__(self, info: PublicInfo, assumed_reliability: Optional[float] = None,
                 resource: Optional[ResourcePolicy] = None):
        self.info = info
        self.sensor = SensorModel(info, reliability=assumed_reliability)
        self.belief = BeliefState(info, self.sensor)
        self.planner = GridPlanner(info)
        self.resources = ResourceManager(info, self.planner, resource)
        self.trail: list[Cell] = []
        self.scan_counts: dict[Cell, int] = {}
        self.steps_since_scan = 10 ** 6
        self.entropy_trace: list[float] = []
        self.explanation = {}
        self.recent: deque = deque(maxlen=20)

    def ingest(self, obs: Observation) -> None:
        """Fold one observation into the belief (the only way information enters the agent)."""
        self.trail.append(obs.position)
        if obs.contact is not None:
            self.belief.observe_contact(obs.contact)
        else:
            self.belief.observe_no_contact(obs.position)
            if obs.scan_reading is not None and obs.scan_position is not None:
                self.belief.observe_scan(obs.scan_position, obs.scan_reading)
                self.scan_counts[obs.scan_position] = self.scan_counts.get(obs.scan_position, 0) + 1
                self.steps_since_scan = 0
            else:
                self.steps_since_scan += 1
            for clue in obs.new_clues:
                self.belief.observe_clue(clue.pos, clue.hint)
        self.entropy_trace.append(self.belief.entropy())

    def estimate(self) -> tuple[Optional[Cell], float]:
        return self.belief.map_estimate()

    def belief_map(self) -> np.ndarray:
        return self.belief.prob

    def entropy(self) -> float:
        return self.belief.entropy()

    @staticmethod
    def step_towards(pos: Cell, nxt: Cell) -> Action:
        return Action.move(nxt[0] - pos[0], nxt[1] - pos[1])
