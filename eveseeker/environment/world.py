"""Procedural mission generation. Produces the public map and the hidden ground truth."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .config import Cell, ConfigError, MissionConfig


@dataclass(frozen=True)
class World:
    """Public layout the agent is allowed to know (a known map, unknown target)."""
    width: int
    height: int
    obstacles: frozenset[Cell]
    start: Cell
    stations: tuple[Cell, ...]


@dataclass(frozen=True)
class HiddenState:
    """Ground truth. Only the environment and the evaluator may touch this."""
    eve: Cell
    clues: tuple[Cell, ...]
    decoys: tuple[Cell, ...]


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def reachable_mask(blocked: np.ndarray, start: Cell) -> np.ndarray:
    h, w = blocked.shape
    seen = np.zeros_like(blocked, dtype=bool)
    seen[start[1], start[0]] = True
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not blocked[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((nx, ny))
    return seen


def generate_world(cfg: MissionConfig, seed: int) -> tuple[World, HiddenState]:
    """Deterministically build a mission from (config, seed). Unreachable pockets become walls."""
    rng = np.random.default_rng([seed, 0])
    w, h = cfg.width, cfg.height

    if cfg.obstacles is not None:
        blocked = np.zeros((h, w), dtype=bool)
        for x, y in cfg.obstacles:
            blocked[y, x] = True
    else:
        blocked = rng.random((h, w)) < cfg.obstacle_density

    if cfg.start is not None:
        start = cfg.start
        if cfg.obstacles is not None and blocked[start[1], start[0]]:
            raise ConfigError("start cell is an obstacle")
    else:
        free = np.argwhere(~blocked)
        if len(free) == 0:
            raise ConfigError("no free cell for the start position")
        y, x = free[rng.integers(len(free))]
        start = (int(x), int(y))
    blocked[start[1], start[0]] = False

    reach = reachable_mask(blocked, start)
    blocked = ~reach  # fill unreachable pockets so every free cell is reachable
    cells = [(int(x), int(y)) for y, x in np.argwhere(reach)]

    def need_reachable(cell: Cell, name: str) -> None:
        if not reach[cell[1], cell[0]]:
            raise ConfigError(f"{name} {cell} is an obstacle or unreachable from the start")

    # recharge stations: first at the start (home base), others spread out
    if cfg.stations is not None:
        stations = tuple(cfg.stations)
        for s in stations:
            need_reachable(s, "station")
    else:
        chosen: list[Cell] = [start] if cfg.n_stations >= 1 else []
        min_sep = (w + h) // 4
        while len(chosen) < cfg.n_stations:
            pool = [c for c in cells if c not in chosen and all(manhattan(c, s) >= min_sep for s in chosen)]
            if not pool:
                pool = [c for c in cells if c not in chosen]
            if not pool:
                break
            chosen.append(pool[rng.integers(len(pool))])
        stations = tuple(chosen)

    # EVE
    if cfg.eve is not None:
        need_reachable(cfg.eve, "eve")
        eve = cfg.eve
    else:
        pool = [c for c in cells if manhattan(c, start) >= cfg.min_eve_distance]
        if not pool:
            pool = [max(cells, key=lambda c: manhattan(c, start))]
        eve = pool[rng.integers(len(pool))]

    clues = _place_clues(cfg, rng, cells, eve, start, need_reachable)

    decoys: list[Cell] = []
    if cfg.decoys.count:
        pool = [c for c in cells if manhattan(c, eve) >= 5]
        pool = pool or [c for c in cells if c != eve]
        for _ in range(cfg.decoys.count):
            decoys.append(pool[rng.integers(len(pool))])

    world = World(w, h, frozenset((int(x), int(y)) for y, x in np.argwhere(blocked)), start, stations)
    return world, HiddenState(eve, tuple(clues), tuple(decoys))


def _place_clues(cfg, rng, cells, eve, start, need_reachable) -> list[Cell]:
    c = cfg.clues
    if c.positions is not None:
        for p in c.positions:
            need_reachable(p, "clue")
        return list(c.positions)
    if c.distribution == "none" or c.count == 0:
        return []
    others = [p for p in cells if p != eve and p != start]
    if not others:
        return []
    if c.distribution == "uniform":
        pool = others
    elif c.distribution == "near_target":
        pool = [p for p in others if manhattan(p, eve) <= 4] or others
    elif c.distribution == "far_target":
        pool = [p for p in others if manhattan(p, eve) >= 8]
        pool = pool or sorted(others, key=lambda p: -manhattan(p, eve))[: max(c.count, 1)]
    else:  # clustered: all clues around one random centre
        centre = others[rng.integers(len(others))]
        pool = sorted(others, key=lambda p: (manhattan(p, centre), p))[: max(c.count * 2, 3)]
    idx = rng.choice(len(pool), size=min(c.count, len(pool)), replace=False)
    return [pool[int(i)] for i in idx]
