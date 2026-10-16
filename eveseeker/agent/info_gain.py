"""Expected information gain (mutual information between EVE's location and an observation).

For a candidate destination x the agent will see everything within visual range on arrival
("contact" outcome, which reveals EVE exactly) and may additionally SCAN there. With belief b:

    m      = mass of b inside the visual range of x          (probability of finding EVE outright)
    b'     = b with that visual range zeroed                  (unnormalised, mass 1 - m)
    visit  : EIG = H(b) - (1-m) * H(b' / (1-m))
    scan   : EIG = H(b) - sum_k P_k * H(post_k),  P_k = sum_e b'(e) L_k(e),  post_k ∝ b' · L_k
             (the contact branch contributes 0 residual entropy)

Entropies are in bits. EIG >= 0 always (mutual information), and EIG_scan >= EIG_visit.
"""
from __future__ import annotations

import numpy as np


def entropy_bits(p: np.ndarray) -> float:
    p = np.asarray(p, dtype=float).ravel()
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum()) if p.size else 0.0


def _plogp(q: np.ndarray, axis: int) -> np.ndarray:
    """sum of q*log2(q) over axis, treating 0*log0 = 0."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(q > 0, q * np.log2(np.where(q > 0, q, 1.0)), 0.0)
    return t.sum(axis=axis)


def batch_eig(prob: np.ndarray, lik: np.ndarray, vis: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """EIG for N candidate positions at once.

    prob: (E,) belief; lik: (N, K, E) scan likelihoods; vis: (N, E) visual-range masks.
    Returns (eig_visit (N,), eig_scan (N,), p_contact (N,)).
    """
    prob = np.asarray(prob, dtype=float).ravel()
    h0 = -_plogp(prob, axis=0)
    bprime = prob[None, :] * (~vis)                          # (N, E) unnormalised
    mass = bprime.sum(axis=1)                                # 1 - m
    p_contact = 1.0 - mass

    # visit only: residual entropy = (1-m) * H(b'/(1-m)) = -sum b' log b' + mass log mass
    resid_visit = -_plogp(bprime, axis=1) + np.where(mass > 0, mass * np.log2(np.where(mass > 0, mass, 1.0)), 0.0)
    eig_visit = h0 - resid_visit

    # scan: residual = sum_k P_k H(post_k) = -sum q log q + sum_k P_k log P_k with q = b' * L_k
    q = bprime[:, None, :] * lik                             # (N, K, E)
    pk = q.sum(axis=2)                                       # (N, K)
    resid_scan = -_plogp(q.reshape(q.shape[0], -1), axis=1) + _plogp(pk, axis=1)
    eig_scan = h0 - resid_scan
    return np.maximum(eig_visit, 0.0), np.maximum(eig_scan, 0.0), np.clip(p_contact, 0.0, 1.0)


def eig_single(prob: np.ndarray, lik: np.ndarray, vis: np.ndarray) -> tuple[float, float, float]:
    """Convenience wrapper for one candidate: lik (K, H, W), vis (H, W)."""
    v, s, m = batch_eig(prob.ravel(), lik.reshape(1, lik.shape[0], -1), vis.reshape(1, -1))
    return float(v[0]), float(s[0]), float(m[0])
