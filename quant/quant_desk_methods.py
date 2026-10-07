"""Small, auditable statistical tools for strategy research and monitoring."""
from __future__ import annotations

import numpy as np
from scipy.special import expit
from scipy.stats import genpareto


def probability_scores(probability, outcome, bins: int = 10) -> dict:
    """Return proper scores and a reliability table for binary forecasts."""
    p = np.clip(np.asarray(probability, dtype=float), 1e-12, 1 - 1e-12)
    y = np.asarray(outcome, dtype=float)
    if p.shape != y.shape or p.ndim != 1 or len(p) == 0:
        raise ValueError("probability and outcome must be nonempty 1D arrays of equal size")
    if np.any((y != 0) & (y != 1)):
        raise ValueError("outcome must be binary")
    edges = np.linspace(0, 1, bins + 1)
    bucket = np.minimum(np.searchsorted(edges, p, side="right") - 1, bins - 1)
    reliability = []
    for i in range(bins):
        mask = bucket == i
        if mask.any():
            reliability.append({"bin": i, "count": int(mask.sum()),
                                "mean_probability": float(p[mask].mean()),
                                "event_rate": float(y[mask].mean())})
    return {
        "observations": int(len(p)),
        "base_rate": float(y.mean()),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "reliability": reliability,
    }


def smooth_logit_state(observations, process_variance: float = 0.01,
                       observation_variance: float = 0.04,
                       prior_probability: float = 0.5) -> np.ndarray:
    """Causal scalar Kalman filter in logit space.

    This deterministic approximation is appropriate for monitoring. A particle
    filter is warranted only when the transition or likelihood is non-Gaussian.
    """
    p = np.clip(np.asarray(observations, dtype=float), 1e-6, 1 - 1e-6)
    if process_variance <= 0 or observation_variance <= 0:
        raise ValueError("variances must be positive")
    state = np.log(prior_probability / (1 - prior_probability))
    variance = 1.0
    out = np.empty(len(p))
    for i, value in enumerate(np.log(p / (1 - p))):
        variance += process_variance
        gain = variance / (variance + observation_variance)
        state += gain * (value - state)
        variance *= 1 - gain
        out[i] = expit(state)
    return out


def peaks_over_threshold(losses, threshold_quantile: float = 0.90,
                         tail_probability: float = 0.99) -> dict:
    """Fit a generalized Pareto tail and estimate a loss quantile and ES."""
    x = np.asarray(losses, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 50 or not 0.5 < threshold_quantile < tail_probability < 1:
        raise ValueError("need >=50 losses and 0.5 < threshold < tail probability < 1")
    threshold = float(np.quantile(x, threshold_quantile))
    excess = x[x > threshold] - threshold
    if len(excess) < 10:
        raise ValueError("too few threshold exceedances")
    shape, _, scale = genpareto.fit(excess, floc=0)
    exceedance_probability = len(excess) / len(x)
    conditional_cdf = 1 - (1 - tail_probability) / exceedance_probability
    var = threshold + genpareto.ppf(conditional_cdf, shape, loc=0, scale=scale)
    if shape >= 1:
        expected_shortfall = float("inf")
    else:
        expected_shortfall = (var + scale - shape * threshold) / (1 - shape)
    return {"observations": int(len(x)), "exceedances": int(len(excess)),
            "threshold": threshold, "shape": float(shape), "scale": float(scale),
            "tail_probability": tail_probability, "value_at_risk": float(var),
            "expected_shortfall": float(expected_shortfall)}


def monte_carlo_standard_error(indicators) -> float:
    """Standard error for a Monte Carlo event-probability estimate."""
    x = np.asarray(indicators, dtype=float)
    if len(x) < 2 or np.any((x != 0) & (x != 1)):
        raise ValueError("indicators must contain at least two binary values")
    return float(np.sqrt(x.mean() * (1 - x.mean()) / len(x)))
