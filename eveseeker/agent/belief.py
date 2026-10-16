"""Bayesian belief over EVE's location.

b_t(e) = P(EVE at e | all observations so far), maintained as a normalised H x W array.

Updates (all are  b' ∝ b · likelihood, then renormalise):
  * scan reading r at p:      likelihood P(r | e, p)       (soft evidence, can be wrong)
  * clue hint h at c:         likelihood P(h | e, c)       (soft evidence, can be wrong)
  * no contact at p:          likelihood 0 for cells within visual range of p, 1 elsewhere
                              (hard evidence: those cells are confirmed empty)
  * contact at e*:            belief collapses onto e* (confirmed knowledge)
If evidence is so contradictory that the posterior mass is numerically zero, the belief is reset
to uniform over cells not yet confirmed empty and `contradictions` is incremented.
"""
from __future__ import annotations

import numpy as np

from ..environment.env import PublicInfo
from .info_gain import entropy_bits
from .sensor_model import SensorModel

_TINY = 1e-300


class BeliefState:
    def __init__(self, info: PublicInfo, sensor: SensorModel):
        self.info = info
        self.sensor = sensor
        self.free = sensor.free
        self.cleared = np.zeros(self.free.shape, dtype=bool)  # cells confirmed empty by sight
        self.prob = self.free / self.free.sum()                # uniform prior over free cells
        self.contradictions = 0
        self.confirmed: tuple[int, int] | None = None
        self.clues: list[tuple[tuple[int, int], str]] = []

    # ---------------------------------------------------------------- updates
    def _apply(self, likelihood: np.ndarray) -> None:
        post = self.prob * likelihood
        total = post.sum()
        if not np.isfinite(total) or total <= _TINY:
            self.contradictions += 1
            fallback = self.free & ~self.cleared
            if not fallback.any():
                fallback = self.free
            post = fallback.astype(float)
            total = post.sum()
        self.prob = post / total

    def observe_scan(self, pos: tuple[int, int], reading: int) -> None:
        self._apply(self.sensor.scan_lik(pos)[reading])

    def observe_clue(self, clue: tuple[int, int], hint: str) -> None:
        self.clues.append((clue, hint))
        self._apply(self.sensor.clue_lik(clue, hint))

    def observe_no_contact(self, pos: tuple[int, int]) -> None:
        mask = self.sensor.vision_mask(pos)
        self.cleared |= mask
        self._apply((~mask).astype(float))

    def observe_contact(self, eve: tuple[int, int]) -> None:
        self.confirmed = eve
        post = np.zeros_like(self.prob)
        post[eve[1], eve[0]] = 1.0
        self.prob = post

    # ---------------------------------------------------------------- summaries
    def entropy(self) -> float:
        return entropy_bits(self.prob)

    def max_entropy(self) -> float:
        return float(np.log2(self.free.sum()))

    def map_estimate(self) -> tuple[tuple[int, int], float]:
        idx = int(np.argmax(self.prob))
        y, x = divmod(idx, self.prob.shape[1])
        return (x, y), float(self.prob[y, x])

    def mass_in(self, mask: np.ndarray) -> float:
        return float(self.prob[mask].sum())

    def top_cells(self, k: int = 3) -> list[tuple[tuple[int, int], float]]:
        order = np.argsort(self.prob.ravel())[::-1][:k]
        w = self.prob.shape[1]
        return [((int(i % w), int(i // w)), float(self.prob.ravel()[i])) for i in order]
