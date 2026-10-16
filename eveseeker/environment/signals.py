"""Public signal-model mathematics shared by the environment (to sample) and the agent (to infer).

Proximity sensor (SCAN at position p, EVE at e, d = Manhattan(p, e)):
    true band  b(d) = 2 (strong) if d <= strong_radius, 1 (weak) if d <= weak_radius, else 0
    reading r  = b(d) with probability rho, otherwise uniform over the other K-1 bands
    =>  P(r | e, p) = rho                if r == b(d(p, e))
                      (1 - rho) / (K-1)  otherwise

Clue hint (a clue at c gives a compass direction towards EVE):
    true direction = dominant axis of (e - c) (ties -> horizontal)
    hint = true direction with probability rho_c, otherwise uniform over the other 3.
"""
from __future__ import annotations

import numpy as np

N_BANDS = 3
BAND_NAMES = ("none", "weak", "strong")
DIRECTIONS = ("N", "E", "S", "W")


def band_of_distance(d: int | np.ndarray, strong_radius: int, weak_radius: int):
    """Noise-free band for a distance (scalar or array)."""
    d = np.asarray(d)
    return np.where(d <= strong_radius, 2, np.where(d <= weak_radius, 1, 0))


def scan_likelihood(shape: tuple[int, int], pos: tuple[int, int], strong_radius: int,
                    weak_radius: int, reliability: float) -> np.ndarray:
    """Array L[k, y, x] = P(reading = k | EVE at (x, y), scan at pos)."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    dist = np.abs(xs - pos[0]) + np.abs(ys - pos[1])
    band = band_of_distance(dist, strong_radius, weak_radius)
    off = (1.0 - reliability) / (N_BANDS - 1)
    lik = np.empty((N_BANDS, h, w))
    for k in range(N_BANDS):
        lik[k] = np.where(band == k, reliability, off)
    return lik


def true_direction(clue: tuple[int, int], target: tuple[int, int]) -> str | None:
    dx, dy = target[0] - clue[0], target[1] - clue[1]
    if dx == 0 and dy == 0:
        return None
    if abs(dx) >= abs(dy):
        return "E" if dx > 0 else "W"
    return "S" if dy > 0 else "N"


def clue_likelihood(shape: tuple[int, int], clue: tuple[int, int], hint: str,
                    reliability: float) -> np.ndarray:
    """Array L[y, x] = P(hint | EVE at (x, y), clue at `clue`). Cell == clue is uninformative."""
    h, w = shape
    ys, xs = np.mgrid[0:h, 0:w]
    dx, dy = xs - clue[0], ys - clue[1]
    horizontal = np.abs(dx) >= np.abs(dy)
    match = {
        "E": horizontal & (dx > 0),
        "W": horizontal & (dx < 0),
        "S": ~horizontal & (dy > 0),
        "N": ~horizontal & (dy < 0),
    }[hint]
    lik = np.where(match, reliability, (1.0 - reliability) / (len(DIRECTIONS) - 1))
    lik[clue[1], clue[0]] = 1.0 / len(DIRECTIONS)
    return lik
