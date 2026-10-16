"""The agent's *assumed* sensor model (may differ from the true one -> model mismatch)."""
from __future__ import annotations

import numpy as np

from ..environment.env import PublicInfo
from ..environment.signals import N_BANDS, clue_likelihood, scan_likelihood


class SensorModel:
    """Caches likelihood tables derived from public information only."""

    def __init__(self, info: PublicInfo, reliability: float | None = None,
                 clue_reliability: float | None = None):
        self.info = info
        self.shape = (info.height, info.width)
        rel = info.signal.reliability if reliability is None else reliability
        crel = info.clue_reliability if clue_reliability is None else clue_reliability
        # Clip away from {0, 1}: a "perfect" sensor would make any contradiction fatal (zero posterior).
        self.reliability = float(np.clip(rel, 0.01, 0.99))
        self.clue_reliability = float(np.clip(crel, 0.01, 0.99))
        self.free = np.ones(self.shape, dtype=bool)
        for x, y in info.obstacles:
            self.free[y, x] = False
        self.cells = np.flatnonzero(self.free.ravel())       # flat indices of free cells
        self._row = {int(c): i for i, c in enumerate(self.cells)}
        ys, xs = np.mgrid[0:info.height, 0:info.width]
        self._xs, self._ys = xs, ys
        self._lik: dict[tuple[int, int], np.ndarray] = {}
        self._vis: dict[tuple[int, int], np.ndarray] = {}
        self._stack: tuple[np.ndarray, np.ndarray] | None = None

    def scan_lik(self, pos: tuple[int, int]) -> np.ndarray:
        """L[k, y, x] = P(reading k | EVE at (x, y), scan at pos)."""
        if pos not in self._lik:
            s = self.info.signal
            self._lik[pos] = scan_likelihood(self.shape, pos, s.strong_radius, s.weak_radius, self.reliability)
        return self._lik[pos]

    def vision_mask(self, pos: tuple[int, int]) -> np.ndarray:
        """Free cells within visual range of pos (EVE there would be noticed)."""
        if pos not in self._vis:
            d = np.abs(self._xs - pos[0]) + np.abs(self._ys - pos[1])
            self._vis[pos] = (d <= self.info.vision_range) & self.free
        return self._vis[pos]

    def clue_lik(self, clue: tuple[int, int], hint: str) -> np.ndarray:
        return clue_likelihood(self.shape, clue, hint, self.clue_reliability)

    def stacks(self) -> tuple[np.ndarray, np.ndarray]:
        """Batch tensors over all free cells: L (N, K, E) and V (N, E) with E = H*W."""
        if self._stack is None:
            e = self.shape[0] * self.shape[1]
            lik = np.empty((len(self.cells), N_BANDS, e))
            vis = np.empty((len(self.cells), e), dtype=bool)
            for i, c in enumerate(self.cells):
                pos = (int(c % self.info.width), int(c // self.info.width))
                lik[i] = self.scan_lik(pos).reshape(N_BANDS, e)
                vis[i] = self.vision_mask(pos).ravel()
            self._stack = (lik, vis)
        return self._stack

    def rows(self, flat_cells: np.ndarray) -> np.ndarray:
        return np.fromiter((self._row[int(c)] for c in flat_cells), dtype=int, count=len(flat_cells))
