"""Strategy registry: every strategy is built from PublicInfo only."""
from __future__ import annotations

from typing import Callable

from .agent.base import Agent
from .agent.eve_seeker import EveSeekerAgent, SeekerConfig
from .baselines import GreedyAgent, RandomAgent
from .environment.env import PublicInfo

STRATEGIES: dict[str, Callable[[PublicInfo, int], Agent]] = {
    "random": lambda info, seed: RandomAgent(info, seed=seed),
    "greedy": lambda info, seed: GreedyAgent(info),
    "eve_seeker": lambda info, seed: EveSeekerAgent(info, SeekerConfig(use_eig=True)),
    "eve_seeker_no_eig": lambda info, seed: EveSeekerAgent(info, SeekerConfig(use_eig=False)),
}
MAIN_STRATEGIES = ("random", "greedy", "eve_seeker")
LABELS = {"random": "Random walk", "greedy": "Greedy (MAP target)", "eve_seeker": "EVE-Seeker (EIG)",
          "eve_seeker_no_eig": "EVE-Seeker w/o EIG (ablation)"}


def make_agent(name: str, info: PublicInfo, seed: int = 0) -> Agent:
    if name not in STRATEGIES:
        raise KeyError(f"unknown strategy '{name}'; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name](info, seed)
