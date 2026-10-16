"""Mission configuration: typed dataclasses, JSON loading and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Optional

Cell = tuple[int, int]
CLUE_DISTRIBUTIONS = ("none", "uniform", "near_target", "far_target", "clustered")


class ConfigError(ValueError):
    """Raised for any invalid mission configuration."""


@dataclass(frozen=True)
class SignalConfig:
    """Noisy proximity sensor. Reading is one of {0: none, 1: weak, 2: strong}."""
    reliability: float = 0.8   # P(reading == true band); otherwise uniform over the other bands
    strong_radius: int = 3     # Manhattan distance <= this -> strong band
    weak_radius: int = 7       # Manhattan distance <= this -> weak band


@dataclass(frozen=True)
class ClueConfig:
    """Hidden clues. Walking within `radius` reveals a noisy compass hint towards EVE."""
    count: int = 3
    distribution: str = "uniform"
    reliability: float = 0.75
    radius: int = 2
    positions: Optional[tuple[Cell, ...]] = None  # explicit placement (hidden from the agent)


@dataclass(frozen=True)
class DecoyConfig:
    """Hidden decoy emitters. With `probability`, a scan reflects a decoy instead of EVE."""
    count: int = 0
    probability: float = 0.0


@dataclass(frozen=True)
class BatteryConfig:
    capacity: float = 40.0
    move_cost: float = 1.0
    scan_cost: float = 3.0
    wait_cost: float = 0.2
    recharge_rate: float = 10.0  # energy gained per RECHARGE action at a station


@dataclass(frozen=True)
class BudgetConfig:
    max_time: int = 220      # time ticks (moves/waits/recharges cost 1, scans cost scan_time)
    max_actions: int = 160   # total actions, valid or not
    scan_time: int = 2


@dataclass(frozen=True)
class MissionConfig:
    name: str = "mission"
    width: int = 15
    height: int = 15
    obstacle_density: float = 0.10
    obstacles: Optional[tuple[Cell, ...]] = None
    start: Optional[Cell] = None
    eve: Optional[Cell] = None           # hidden; random when None
    stations: Optional[tuple[Cell, ...]] = None
    n_stations: int = 2
    min_eve_distance: int = 6
    vision_range: int = 1                # EVE is "found" when Manhattan distance <= this
    signal: SignalConfig = field(default_factory=SignalConfig)
    clues: ClueConfig = field(default_factory=ClueConfig)
    decoys: DecoyConfig = field(default_factory=DecoyConfig)
    battery: BatteryConfig = field(default_factory=BatteryConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    seed: int = 0

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------------ validation
    def validate(self) -> None:
        def need(cond: bool, msg: str) -> None:
            if not cond:
                raise ConfigError(msg)

        need(self.width >= 3 and self.height >= 3, "map must be at least 3x3")
        need(self.width <= 80 and self.height <= 80, "map larger than 80x80 is not supported")
        need(0.0 <= self.obstacle_density < 0.6, "obstacle_density must be in [0, 0.6)")
        need(self.n_stations >= 0, "n_stations must be >= 0")
        need(self.min_eve_distance >= 0, "min_eve_distance must be >= 0")
        need(self.vision_range >= 0, "vision_range must be >= 0")
        s = self.signal
        need(0.0 <= s.reliability <= 1.0, "signal.reliability must be in [0, 1]")
        need(0 <= s.strong_radius < s.weak_radius, "need 0 <= strong_radius < weak_radius")
        c = self.clues
        need(c.distribution in CLUE_DISTRIBUTIONS, f"clues.distribution must be one of {CLUE_DISTRIBUTIONS}")
        need(c.count >= 0 and c.radius >= 0, "clues.count/radius must be >= 0")
        need(0.0 <= c.reliability <= 1.0, "clues.reliability must be in [0, 1]")
        d = self.decoys
        need(d.count >= 0 and 0.0 <= d.probability <= 1.0, "invalid decoys section")
        b = self.battery
        need(b.capacity > 0, "battery.capacity must be > 0")
        need(b.move_cost > 0, "battery.move_cost must be > 0")
        need(b.scan_cost >= 0 and b.wait_cost >= 0, "battery costs must be >= 0")
        need(b.recharge_rate > 0, "battery.recharge_rate must be > 0")
        g = self.budget
        need(g.max_time > 0 and g.max_actions > 0 and g.scan_time >= 1, "invalid budget section")
        for name, cells in (("obstacles", self.obstacles), ("stations", self.stations),
                            ("clues.positions", c.positions)):
            for cell in cells or ():
                self._check_cell(cell, name)
        for name, cell in (("start", self.start), ("eve", self.eve)):
            if cell is not None:
                self._check_cell(cell, name)

    def _check_cell(self, cell: Cell, name: str) -> None:
        x, y = cell
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ConfigError(f"{name} cell {cell} is outside the {self.width}x{self.height} map")

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionConfig":
        data = dict(data)
        nested = {"signal": SignalConfig, "clues": ClueConfig, "decoys": DecoyConfig,
                  "battery": BatteryConfig, "budget": BudgetConfig}
        for key, klass in nested.items():
            if key in data:
                data[key] = _build(klass, data[key], key)
        for key in ("obstacles", "stations"):
            if data.get(key) is not None:
                data[key] = tuple(_cell(c, key) for c in data[key])
        for key in ("start", "eve"):
            if data.get(key) is not None:
                data[key] = _cell(data[key], key)
        return _build(cls, data, "mission")

    @classmethod
    def from_json(cls, path: str | Path) -> "MissionConfig":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ConfigError(f"config file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a JSON object")
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        def conv(v: Any) -> Any:
            if hasattr(v, "__dataclass_fields__"):
                return {f.name: conv(getattr(v, f.name)) for f in fields(v)}
            if isinstance(v, tuple):
                return [conv(i) for i in v]
            return v
        return conv(self)

    def override(self, **changes: Any) -> "MissionConfig":
        """Return a copy with changes; nested fields use dotted names, e.g. 'signal.reliability'."""
        cfg = self
        for key, value in changes.items():
            if "." in key:
                section, attr = key.split(".", 1)
                if section not in ("signal", "clues", "decoys", "battery", "budget"):
                    raise ConfigError(f"unknown config section '{section}'")
                sub = replace(getattr(cfg, section), **{attr: value})
                cfg = replace(cfg, **{section: sub})
            else:
                cfg = replace(cfg, **{key: value})
        return cfg


def _cell(value: Any, name: str) -> Cell:
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise ConfigError(f"{name}: expected [x, y], got {value!r}")
    return int(value[0]), int(value[1])


def _build(klass: type, data: Any, name: str):
    if not isinstance(data, dict):
        raise ConfigError(f"section '{name}' must be an object")
    allowed = {f.name for f in fields(klass)}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"unknown key(s) in '{name}': {sorted(unknown)}")
    data = dict(data)
    if klass is ClueConfig and data.get("positions") is not None:
        data["positions"] = tuple(_cell(c, "clues.positions") for c in data["positions"])
    try:
        return klass(**data)
    except TypeError as exc:
        raise ConfigError(f"bad value in '{name}': {exc}") from exc
