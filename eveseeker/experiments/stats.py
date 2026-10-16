"""Small statistics helpers: Wilson interval, normal-approx mean CI, paired bootstrap."""
from __future__ import annotations

import numpy as np


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mean_ci(values, z: float = 1.96) -> tuple[float, float, float]:
    """(mean, lo, hi) using the normal approximation; NaNs ignored."""
    v = np.asarray([x for x in values if x == x], dtype=float)
    if v.size == 0:
        return float("nan"), float("nan"), float("nan")
    m = float(v.mean())
    if v.size < 2:
        return m, m, m
    se = float(v.std(ddof=1) / np.sqrt(v.size))
    return m, m - z * se, m + z * se


def paired_bootstrap_diff(a, b, iters: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of (a - b) over paired missions with a 95% bootstrap CI."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    rng = np.random.default_rng(seed)
    means = rng.choice(d, size=(iters, d.size), replace=True).mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
