"""Action vocabulary shared by the environment and every agent."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    MOVE = "move"
    SCAN = "scan"
    WAIT = "wait"
    RECHARGE = "recharge"
    STOP = "stop"  # agent declares it cannot make further useful progress


# Compass moves on the grid. y grows downward (row index), so "N" is y-1.
COMPASS = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


@dataclass(frozen=True)
class Action:
    type: ActionType
    dx: int = 0
    dy: int = 0

    @staticmethod
    def move(dx: int, dy: int) -> "Action":
        return Action(ActionType.MOVE, dx, dy)

    @staticmethod
    def scan() -> "Action":
        return Action(ActionType.SCAN)

    @staticmethod
    def wait() -> "Action":
        return Action(ActionType.WAIT)

    @staticmethod
    def recharge() -> "Action":
        return Action(ActionType.RECHARGE)

    @staticmethod
    def stop() -> "Action":
        return Action(ActionType.STOP)

    def __str__(self) -> str:
        if self.type is ActionType.MOVE:
            name = {v: k for k, v in COMPASS.items()}.get((self.dx, self.dy), f"{self.dx},{self.dy}")
            return f"MOVE {name}"
        return self.type.value.upper()
