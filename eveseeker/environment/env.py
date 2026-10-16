"""MissionEnv: the simulator. Agents see only `PublicInfo` and `Observation`.

Hidden state (EVE, clues, decoys) lives in a private attribute and is exposed only through
`evaluator_view()`, which is meant for the evaluation harness / dashboard "ground truth" tab.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .actions import Action, ActionType
from .config import BatteryConfig, BudgetConfig, Cell, MissionConfig, SignalConfig
from .signals import DIRECTIONS, N_BANDS, band_of_distance, true_direction
from .world import HiddenState, World, generate_world, manhattan

RUNNING = "running"
SUCCESS = "success"                      # EVE within visual range
BATTERY_EXHAUSTED = "battery_exhausted"  # stranded away from a station
TIMEOUT = "timeout"
ACTION_BUDGET = "action_budget_exhausted"
STOPPED = "stopped_uncertain"            # agent stopped and reported its uncertainty
RESOURCE_EXHAUSTION = (BATTERY_EXHAUSTED, TIMEOUT, ACTION_BUDGET)


@dataclass(frozen=True)
class PublicInfo:
    """Everything the agent is told up front. Contains NO hidden information."""
    width: int
    height: int
    obstacles: frozenset[Cell]
    start: Cell
    stations: tuple[Cell, ...]
    battery: BatteryConfig
    budget: BudgetConfig
    signal: SignalConfig          # nominal sensor specification
    clue_reliability: float       # nominal clue reliability
    clue_radius: int
    vision_range: int


@dataclass(frozen=True)
class ClueObservation:
    pos: Cell
    hint: str  # one of N/E/S/W: noisy compass direction towards EVE


@dataclass(frozen=True)
class Observation:
    step: int
    position: Cell
    battery: float
    time_remaining: int
    actions_remaining: int
    at_station: bool
    action_valid: bool = True
    message: str = "ok"
    scan_reading: Optional[int] = None
    scan_position: Optional[Cell] = None
    new_clues: tuple[ClueObservation, ...] = ()
    contact: Optional[Cell] = None   # EVE's position, only when within visual range
    done: bool = False
    status: str = RUNNING


@dataclass
class EnvStats:
    actions: int = 0
    scans: int = 0
    recharges: int = 0
    invalid_actions: int = 0
    energy_used: float = 0.0
    time_used: int = 0


class MissionEnv:
    def __init__(self, config: MissionConfig, seed: Optional[int] = None):
        self.config = config
        self.seed = config.seed if seed is None else seed
        self._world, self._hidden = generate_world(config, self.seed)
        self._noise = np.random.default_rng([self.seed, 1])
        self._blocked = self._world.obstacles
        self.info = PublicInfo(
            width=self._world.width, height=self._world.height, obstacles=self._world.obstacles,
            start=self._world.start, stations=self._world.stations, battery=config.battery,
            budget=config.budget, signal=config.signal, clue_reliability=config.clues.reliability,
            clue_radius=config.clues.radius, vision_range=config.vision_range)
        self._reset_runtime()

    # ------------------------------------------------------------------ public interface
    def reset(self) -> Observation:
        """Restart the same mission (same world, same noise stream)."""
        self._noise = np.random.default_rng([self.seed, 1])
        self._reset_runtime()
        return self._observe(Action.wait(), True, "mission start", None)

    @property
    def done(self) -> bool:
        return self._status != RUNNING

    @property
    def status(self) -> str:
        return self._status

    @property
    def position(self) -> Cell:
        return self._pos

    @property
    def battery(self) -> float:
        return self._battery

    def evaluator_view(self) -> HiddenState:
        """EVALUATION ONLY: ground truth. Agents must never be given this object."""
        return self._hidden

    def step(self, action: Action) -> Observation:
        if self.done:
            raise RuntimeError("mission already finished; call reset()")
        cfg, bat = self.config, self.config.battery
        valid, msg = True, "ok"
        energy, ticks = 0.0, 1
        scan_reading: Optional[int] = None
        scan_pos: Optional[Cell] = None
        x, y = self._pos

        if action.type is ActionType.MOVE:
            nx, ny = x + action.dx, y + action.dy
            if abs(action.dx) + abs(action.dy) != 1:
                valid, msg = False, "moves must be a single orthogonal step"
            elif not (0 <= nx < cfg.width and 0 <= ny < cfg.height) or (nx, ny) in self._blocked:
                valid, msg = False, "blocked: obstacle or map edge"
            elif self._battery < bat.move_cost:
                valid, msg = False, "insufficient energy to move"
            else:
                self._pos, energy = (nx, ny), bat.move_cost
        elif action.type is ActionType.SCAN:
            if self._battery < bat.scan_cost:
                valid, msg = False, "insufficient energy to scan"
            else:
                energy, ticks = bat.scan_cost, cfg.budget.scan_time
                scan_reading, scan_pos = self._sample_scan(), self._pos
                self.stats.scans += 1
        elif action.type is ActionType.WAIT:
            if self._battery < bat.wait_cost:
                valid, msg = False, "insufficient energy to wait"
            else:
                energy = bat.wait_cost
        elif action.type is ActionType.RECHARGE:
            if self._pos not in self._world.stations:
                valid, msg = False, "not on a recharge station"
            else:
                self._battery = min(bat.capacity, self._battery + bat.recharge_rate)
                self.stats.recharges += 1
        elif action.type is ActionType.STOP:
            ticks = 0

        self._battery -= energy
        self.stats.actions += 1
        self.stats.energy_used += energy
        self.stats.time_used += ticks
        if not valid:
            self.stats.invalid_actions += 1
        self._time_left -= ticks

        contact = self._hidden.eve if manhattan(self._pos, self._hidden.eve) <= cfg.vision_range else None
        if action.type is ActionType.STOP:
            self._status = STOPPED
        elif contact is not None:
            self._status = SUCCESS
        elif self._battery < bat.move_cost - 1e-9 and self._pos not in self._world.stations:
            self._status = BATTERY_EXHAUSTED
        elif self._time_left <= 0:
            self._status = TIMEOUT
        elif self.stats.actions >= cfg.budget.max_actions:
            self._status = ACTION_BUDGET
        return self._observe(action, valid, msg, (scan_reading, scan_pos), contact)

    # ------------------------------------------------------------------ internals
    def _reset_runtime(self) -> None:
        self._pos = self._world.start
        self._battery = float(self.config.battery.capacity)
        self._time_left = self.config.budget.max_time
        self._status = RUNNING
        self._found_clues: dict[Cell, str] = {}
        self.stats = EnvStats()

    def _sample_scan(self) -> int:
        """Draw a noisy reading; a decoy may impersonate EVE (misleading evidence)."""
        cfg, sig = self.config, self.config.signal
        source = self._hidden.eve
        if self._hidden.decoys and self._noise.random() < cfg.decoys.probability:
            source = self._hidden.decoys[int(self._noise.integers(len(self._hidden.decoys)))]
        true_band = int(band_of_distance(manhattan(self._pos, source), sig.strong_radius, sig.weak_radius))
        if self._noise.random() < sig.reliability:
            return true_band
        others = [b for b in range(N_BANDS) if b != true_band]
        return int(others[int(self._noise.integers(len(others)))])

    def _discover_clues(self) -> tuple[ClueObservation, ...]:
        found = []
        cfg = self.config
        for clue in self._hidden.clues:
            if clue in self._found_clues or manhattan(self._pos, clue) > cfg.clues.radius:
                continue
            truth = true_direction(clue, self._hidden.eve) or DIRECTIONS[int(self._noise.integers(4))]
            if self._noise.random() < cfg.clues.reliability:
                hint = truth
            else:
                wrong = [d for d in DIRECTIONS if d != truth]
                hint = wrong[int(self._noise.integers(len(wrong)))]
            self._found_clues[clue] = hint
            found.append(ClueObservation(clue, hint))
        return tuple(found)

    def _observe(self, action, valid, msg, scan, contact=None) -> Observation:
        if contact is None and manhattan(self._pos, self._hidden.eve) <= self.config.vision_range:
            contact = self._hidden.eve
            self._status = SUCCESS
        reading, spos = scan if scan else (None, None)
        return Observation(
            step=self.stats.actions, position=self._pos, battery=round(self._battery, 6),
            time_remaining=max(0, self._time_left),
            actions_remaining=max(0, self.config.budget.max_actions - self.stats.actions),
            at_station=self._pos in self._world.stations, action_valid=valid, message=msg,
            scan_reading=reading, scan_position=spos, new_clues=self._discover_clues(),
            contact=contact, done=self.done, status=self._status)
