"""Regime-aware joint block-bootstrap portfolio simulation.

This module measures risk; it does not create alpha. It resamples synchronized
historical strategy returns in contiguous blocks, conditions block starts on a
simulated market regime, and applies explicit execution/dependence stresses.
"""
from __future__ import annotations

from dataclasses import dataclass
import multiprocessing as mp
import os

import numpy as np


@dataclass(frozen=True)
class SimulationSpec:
    n_paths: int = 100_000
    horizon_days: int = 756
    mean_block_days: int = 20
    bootstrap_method: str = "regime"
    equity_mode: str = "fixed_notional"
    extra_slippage_ticks: float = 0.0
    slippage_cost_per_trade_return: float = 25.0 / 100_000.0
    missed_trade_probability: float = 0.0
    synchronized_loss_probability: float = 0.0
    gap_shock_probability: float = 0.0
    gap_shock_multiplier: float = 2.0
    starting_equity: float = 1.0
    ruin_level: float = 0.5


_RETURNS: np.ndarray | None = None
_TRADES: np.ndarray | None = None
_REGIMES: np.ndarray | None = None
_STARTS: dict[int, np.ndarray] | None = None
_TRANSITION: np.ndarray | None = None
_LOSS_SCALE: np.ndarray | None = None
_WEIGHTS: np.ndarray | None = None
_SPEC: SimulationSpec | None = None


def _transition_matrix(regimes: np.ndarray) -> np.ndarray:
    n = int(regimes.max()) + 1
    counts = np.ones((n, n), dtype=float)  # light smoothing for unseen transitions
    np.add.at(counts, (regimes[:-1], regimes[1:]), 1.0)
    return counts / counts.sum(axis=1, keepdims=True)


def _init_worker(returns, trades, regimes, starts, transition, loss_scale,
                 weights, spec):
    global _RETURNS, _TRADES, _REGIMES, _STARTS, _TRANSITION
    global _LOSS_SCALE, _WEIGHTS, _SPEC
    _RETURNS = returns
    _TRADES = trades
    _REGIMES = regimes
    _STARTS = starts
    _TRANSITION = transition
    _LOSS_SCALE = loss_scale
    _WEIGHTS = weights
    _SPEC = spec


def _sample_indices(rng: np.random.Generator) -> np.ndarray:
    assert _RETURNS is not None and _REGIMES is not None
    assert _STARTS is not None and _TRANSITION is not None and _SPEC is not None
    n = len(_RETURNS)
    horizon = _SPEC.horizon_days
    indices = np.empty(horizon, dtype=np.int32)
    method = _SPEC.bootstrap_method
    allowed_methods = {"regime", "stationary", "moving", "circular", "crisis_weighted"}
    if method not in allowed_methods:
        raise ValueError(f"unknown bootstrap_method: {method}")
    regime = int(rng.choice(np.unique(_REGIMES)))
    cursor = 0
    probability = 1.0 / max(_SPEC.mean_block_days, 1)
    while cursor < horizon:
        if method == "regime":
            eligible = _STARTS.get(regime)
            if eligible is None or not len(eligible):
                eligible = np.arange(n, dtype=np.int32)
            start = int(rng.choice(eligible))
            requested = int(rng.geometric(probability))
        elif method == "crisis_weighted":
            weights = np.ones(n, dtype=float)
            weights[_REGIMES == _REGIMES.max()] = 3.0
            start = int(rng.choice(n, p=weights / weights.sum()))
            requested = int(rng.geometric(probability))
        else:
            start = int(rng.integers(0, n))
            requested = (_SPEC.mean_block_days if method in ("moving", "circular")
                         else int(rng.geometric(probability)))

        length = min(requested, horizon - cursor)
        if method == "circular":
            block = (start + np.arange(length)) % n
        else:
            length = min(length, n - start)
            block = np.arange(start, start + length)
        if length <= 0:
            continue
        indices[cursor:cursor + length] = block
        regime = int(_REGIMES[int(block[-1])])
        if method == "regime":
            regime = int(rng.choice(len(_TRANSITION), p=_TRANSITION[regime]))
        cursor += length
    return indices


def _max_recovery_days(equity: np.ndarray) -> int:
    peak = np.maximum.accumulate(equity)
    underwater = equity < peak
    longest = current = 0
    for value in underwater:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _one_path(rng: np.random.Generator) -> tuple[float, float, int, bool]:
    assert _RETURNS is not None and _TRADES is not None
    assert _LOSS_SCALE is not None and _WEIGHTS is not None and _SPEC is not None
    idx = _sample_indices(rng)
    returns = _RETURNS[idx].copy()
    trades = _TRADES[idx].copy()

    if _SPEC.missed_trade_probability > 0:
        # With mark-to-market daily returns, removing only an exit day would leave
        # the trade's earlier open-position P&L behind. Apply an expected-exposure
        # haircut to the entire sampled path instead; this is conservative and
        # internally consistent, though it is not a trade-by-trade fill simulator.
        retained = 1.0 - _SPEC.missed_trade_probability
        returns *= retained
        trades *= retained

    if _SPEC.extra_slippage_ticks > 0:
        returns -= (trades * _SPEC.extra_slippage_ticks *
                    _SPEC.slippage_cost_per_trade_return)

    if _SPEC.synchronized_loss_probability > 0:
        active = np.abs(_WEIGHTS) > 0
        any_loss = (returns[:, active] < 0).any(axis=1)
        synchronize = any_loss & (rng.random(len(returns)) <
                                  _SPEC.synchronized_loss_probability)
        if synchronize.any():
            returns[synchronize] = -np.maximum(np.abs(returns[synchronize]),
                                               _LOSS_SCALE[None, :])

    if _SPEC.gap_shock_probability > 0:
        shock = rng.random(len(returns)) < _SPEC.gap_shock_probability
        if shock.any():
            returns[shock] -= _LOSS_SCALE[None, :] * _SPEC.gap_shock_multiplier

    portfolio = returns @ _WEIGHTS
    # A daily loss below -100% is impossible to compound; clipping represents
    # liquidation at near-zero rather than allowing equity to change sign.
    if _SPEC.equity_mode == "fixed_notional":
        equity = _SPEC.starting_equity * (1.0 + np.cumsum(portfolio))
        insolvent = np.flatnonzero(equity <= 0.0)
        if len(insolvent):
            equity[int(insolvent[0]):] = 0.0
    elif _SPEC.equity_mode == "compound":
        portfolio = np.maximum(portfolio, -0.999)
        equity = _SPEC.starting_equity * np.cumprod(1.0 + portfolio)
    else:
        raise ValueError(f"unknown equity_mode: {_SPEC.equity_mode}")
    peak = np.maximum.accumulate(equity)
    drawdown = equity / peak - 1.0
    total = equity[-1] / _SPEC.starting_equity - 1.0
    max_drawdown = float(drawdown.min())
    recovery = _max_recovery_days(equity)
    ruined = bool(equity.min() <= _SPEC.ruin_level * _SPEC.starting_equity)
    return float(total), max_drawdown, recovery, ruined


def _worker(job: tuple[int, int]) -> np.ndarray:
    seed, count = job
    rng = np.random.default_rng(seed)
    out = np.empty((count, 4), dtype=float)
    for i in range(count):
        total, drawdown, recovery, ruined = _one_path(rng)
        out[i] = total, drawdown, recovery, float(ruined)
    return out


def summarize_paths(paths: np.ndarray) -> dict:
    total, drawdown, recovery, ruined = paths.T
    quantiles = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
    return {
        "paths": int(len(paths)),
        "probability_profitable": float(np.mean(total > 0)),
        "probability_ruin_50pct": float(np.mean(ruined > 0)),
        "probability_drawdown_20pct": float(np.mean(drawdown <= -0.20)),
        "probability_drawdown_30pct": float(np.mean(drawdown <= -0.30)),
        "probability_drawdown_50pct": float(np.mean(drawdown <= -0.50)),
        "return_quantiles": {str(q): float(v) for q, v in zip(quantiles, np.quantile(total, quantiles))},
        "max_drawdown_quantiles": {str(q): float(v) for q, v in zip(quantiles, np.quantile(drawdown, quantiles))},
        "recovery_days_quantiles": {str(q): float(v) for q, v in zip(quantiles, np.quantile(recovery, quantiles))},
    }


def simulate(returns: np.ndarray, trades: np.ndarray, regimes: np.ndarray,
             weights: np.ndarray, spec: SimulationSpec, *, seed: int = 20260714,
             workers: int | None = None) -> tuple[np.ndarray, dict]:
    """Run deterministic parallel simulations and return raw paths + summary."""
    returns = np.asarray(returns, dtype=float)
    trades = np.asarray(trades, dtype=float)
    regimes = np.asarray(regimes, dtype=np.int16)
    weights = np.asarray(weights, dtype=float)
    if returns.ndim != 2 or trades.shape != returns.shape:
        raise ValueError("returns and trades must be matching [day, strategy] arrays")
    if len(regimes) != len(returns) or len(weights) != returns.shape[1]:
        raise ValueError("regimes/weights do not match return dimensions")
    if not np.isfinite(returns).all() or not np.isfinite(weights).all():
        raise ValueError("simulation inputs must be finite")

    starts = {int(regime): np.flatnonzero(regimes == regime).astype(np.int32)
              for regime in np.unique(regimes)}
    transition = _transition_matrix(regimes)
    losses = np.where(returns < 0, -returns, np.nan)
    loss_scale = np.nanquantile(losses, 0.90, axis=0)
    loss_scale = np.nan_to_num(loss_scale, nan=0.0)
    workers = min(workers or (os.cpu_count() or 1), spec.n_paths)
    counts = np.full(workers, spec.n_paths // workers, dtype=int)
    counts[:spec.n_paths % workers] += 1
    seeds = np.random.SeedSequence(seed).spawn(workers)
    jobs = [(int(s.generate_state(1)[0]), int(count)) for s, count in zip(seeds, counts)]

    context = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    with context.Pool(
        workers,
        initializer=_init_worker,
        initargs=(returns, trades, regimes, starts, transition, loss_scale,
                  weights, spec),
    ) as pool:
        chunks = pool.map(_worker, jobs)
    paths = np.vstack(chunks)
    return paths, summarize_paths(paths)
