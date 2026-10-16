"""Obstacle-aware path planning (Dijkstra for distance fields, A* for point-to-point)."""
from __future__ import annotations

import heapq

import numpy as np

from ..environment.env import PublicInfo

Cell = tuple[int, int]


class GridPlanner:
    """4-connected grid planner over the (known) static map. Distances are in steps."""

    def __init__(self, info: PublicInfo):
        self.w, self.h = info.width, info.height
        self.blocked = np.zeros((self.h, self.w), dtype=bool)
        for x, y in info.obstacles:
            self.blocked[y, x] = True
        self._stations = info.stations
        self.station_dist = self._multi_source(info.stations)

    def neighbors(self, cell: Cell):
        x, y = cell
        for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
            if 0 <= nx < self.w and 0 <= ny < self.h and not self.blocked[ny, nx]:
                yield nx, ny

    def dijkstra(self, source: Cell) -> tuple[np.ndarray, np.ndarray]:
        """Return (dist[H,W] float with inf for unreachable, parent[H*W] flat index, -1 for none)."""
        dist, parent = self._search([source])
        return dist, parent

    def _multi_source(self, sources) -> np.ndarray:
        if not sources:
            return np.full((self.h, self.w), np.inf)
        return self._search(list(sources))[0]

    def _search(self, sources: list[Cell]) -> tuple[np.ndarray, np.ndarray]:
        dist = np.full((self.h, self.w), np.inf)
        parent = np.full(self.h * self.w, -1, dtype=int)
        heap: list[tuple[float, Cell]] = []
        for s in sources:
            dist[s[1], s[0]] = 0.0
            heap.append((0.0, s))
        heapq.heapify(heap)
        while heap:
            d, cell = heapq.heappop(heap)
            if d > dist[cell[1], cell[0]]:
                continue
            for nx, ny in self.neighbors(cell):
                nd = d + 1.0
                if nd < dist[ny, nx]:
                    dist[ny, nx] = nd
                    parent[ny * self.w + nx] = cell[1] * self.w + cell[0]
                    heapq.heappush(heap, (nd, (nx, ny)))
        return dist, parent

    def path_from_parents(self, parent: np.ndarray, source: Cell, target: Cell) -> list[Cell] | None:
        """Reconstruct source -> target from a Dijkstra parent array (None if unreachable)."""
        src = source[1] * self.w + source[0]
        cur = target[1] * self.w + target[0]
        out = [target]
        while cur != src:
            cur = int(parent[cur])
            if cur < 0:
                return None
            out.append((cur % self.w, cur // self.w))
        return out[::-1]

    def astar(self, start: Cell, goal: Cell) -> list[Cell] | None:
        """Shortest path with Manhattan heuristic; None when no route exists."""
        if self.blocked[start[1], start[0]] or self.blocked[goal[1], goal[0]]:
            return None
        g = {start: 0.0}
        came: dict[Cell, Cell] = {}
        heap = [(abs(start[0] - goal[0]) + abs(start[1] - goal[1]), 0.0, start)]
        while heap:
            _, cost, cell = heapq.heappop(heap)
            if cell == goal:
                path = [cell]
                while cell in came:
                    cell = came[cell]
                    path.append(cell)
                return path[::-1]
            if cost > g.get(cell, np.inf):
                continue
            for nb in self.neighbors(cell):
                nc = cost + 1.0
                if nc < g.get(nb, np.inf):
                    g[nb] = nc
                    came[nb] = cell
                    heapq.heappush(heap, (nc + abs(nb[0] - goal[0]) + abs(nb[1] - goal[1]), nc, nb))
        return None
