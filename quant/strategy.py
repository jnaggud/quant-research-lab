"""strategy.py — causal signal generation for the ES pipeline.

Ports the *signal logic* from Pattern_FindR's `velocity_core.calculate_velocity_signals`
(the reusable rule set — NOT the old engine, NOT its backtest/breakeven path).
Consumes the causal feature frame from `features.py` (which already carries
`composite_smooth`, `velocity`, `acceleration`) and emits a `signal` column
{+1 long, -1 short, 0 flat} on the COMPLETED bar. `backtest.run_backtest` then
enters on the next bar — so there is no same-bar look-ahead.

Causality: every condition uses only values at bar t and t-1 (`.shift(1)`), all of
which are known when bar t closes. Proven by the self-test below.

Includes the v4 "velocity-stability" safety filter: reject marginal zero-crossings
whose |velocity| is within `vel_eps` of zero (the noise band that produced the
82%-premature-exit problem in the audited system).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import polars as pl

MODES = ("velocity_crossover", "velocity_zone", "zone_reversal", "any_reversal")


def make_signal(
    features,
    mode: str = "velocity_zone",
    osc_thr: float = 0.3,
    vel_eps: float = 0.0,
    direction: str = "both",
):
    """Add a causal `signal` column {+1,-1,0} to the feature frame.

    mode:
      velocity_crossover : long when velocity crosses up through +vel_eps; short on down-cross.
      velocity_zone      : crossover, but only when the oscillator is in the
                           oversold (long) / overbought (short) zone (|comp|>osc_thr).
      zone_reversal      : long when composite exits the oversold zone (crosses up
                           through -osc_thr); short when it exits overbought.
      any_reversal       : union of velocity_zone and zone_reversal (the system's default).
    direction: 'both' | 'long' | 'short'.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    pdf = features.to_pandas() if isinstance(features, pl.DataFrame) else features.copy()
    comp = pdf["composite_smooth"]
    vel = pdf["velocity"]

    up_cross = (vel > vel_eps) & (vel.shift(1) <= vel_eps)
    dn_cross = (vel < -vel_eps) & (vel.shift(1) >= -vel_eps)
    oversold = comp < -osc_thr
    overbought = comp > osc_thr

    if mode == "velocity_crossover":
        long, short = up_cross, dn_cross
    elif mode == "velocity_zone":
        long = up_cross & oversold
        short = dn_cross & overbought
    elif mode == "zone_reversal":
        long = (comp.shift(1) < -osc_thr) & (comp >= -osc_thr)
        short = (comp.shift(1) > osc_thr) & (comp <= osc_thr)
    else:  # any_reversal
        long = (up_cross & oversold) | ((comp.shift(1) < -osc_thr) & (comp >= -osc_thr))
        short = (dn_cross & overbought) | ((comp.shift(1) > osc_thr) & (comp <= osc_thr))

    long = long.fillna(False)
    short = short.fillna(False)
    sig = np.where(long & ~short, 1.0, np.where(short & ~long, -1.0, 0.0))
    if direction == "long":
        sig = np.where(sig > 0, 1.0, 0.0)
    elif direction == "short":
        sig = np.where(sig < 0, -1.0, 0.0)

    out = pdf.copy()
    out["signal"] = sig
    return pl.from_pandas(out) if isinstance(features, pl.DataFrame) else out


TREND_MODES = ("ma_state", "ma_cross", "breakout", "momentum", "trend_filtered_reversal")


def make_trend_signal(
    features,
    mode: str = "ma_state",
    fast: int = 20,
    slow: int = 50,
    lookback: int = 20,
    mom_n: int = 20,
    osc_thr: float = 0.3,
    direction: str = "both",
):
    """Trend / breakout / momentum signals (causal, state-based).

    These RIDE the trend rather than fade it (the oscillator reversal faded it and
    failed OOS). Computed from close/high/low present in the feature frame, using
    only `.rolling/.shift` — no future bars.

    Modes:
      ma_state  : +1 while SMA(fast) > SMA(slow), else -1 (pure trend state).
      ma_cross  : event — long on the up-cross, short on the down-cross.
      breakout  : Donchian — long when close breaks the prior `lookback` high,
                  short when it breaks the prior low (state holds between).
      momentum  : +1 while close > close[mom_n bars ago], else -1.
      trend_filtered_reversal : oscillator reversal but ONLY longs in an uptrend
                  (close>SMA200) and shorts in a downtrend (close<SMA200).
    """
    if mode not in TREND_MODES:
        raise ValueError(f"mode must be one of {TREND_MODES}")
    pdf = features.to_pandas() if isinstance(features, pl.DataFrame) else features.copy()
    c, h, l = pdf["close"], pdf["high"], pdf["low"]

    if mode == "ma_state":
        sf, ss = c.rolling(fast).mean(), c.rolling(slow).mean()
        sig = np.where(sf > ss, 1.0, np.where(sf < ss, -1.0, 0.0))
    elif mode == "ma_cross":
        sf, ss = c.rolling(fast).mean(), c.rolling(slow).mean()
        up = (sf > ss) & (sf.shift(1) <= ss.shift(1))
        dn = (sf < ss) & (sf.shift(1) >= ss.shift(1))
        sig = np.where(up.fillna(False), 1.0, np.where(dn.fillna(False), -1.0, 0.0))
    elif mode == "breakout":
        upper = h.rolling(lookback).max().shift(1)   # prior-window high (excl. current)
        lower = l.rolling(lookback).min().shift(1)
        raw = np.where(c >= upper, 1.0, np.where(c <= lower, -1.0, np.nan))
        sig = pd.Series(raw, index=pdf.index).ffill().fillna(0.0).to_numpy()  # state holds
    elif mode == "momentum":
        mom = c - c.shift(mom_n)
        sig = np.where(mom > 0, 1.0, np.where(mom < 0, -1.0, 0.0))
    else:  # trend_filtered_reversal
        comp = pdf["composite_smooth"]
        sma200 = c.rolling(200).mean()
        long = (comp.shift(1) < -osc_thr) & (comp >= -osc_thr) & (c > sma200)
        short = (comp.shift(1) > osc_thr) & (comp <= osc_thr) & (c < sma200)
        sig = np.where(long.fillna(False), 1.0, np.where(short.fillna(False), -1.0, 0.0))

    if direction == "long":
        sig = np.where(sig > 0, 1.0, 0.0)
    elif direction == "short":
        sig = np.where(sig < 0, -1.0, 0.0)

    out = pdf.copy()
    out["signal"] = sig
    return pl.from_pandas(out) if isinstance(features, pl.DataFrame) else out


# --------------------------------------------------------------------------------------
# Self-test — causality + sanity (synthetic, no drive I/O)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from quant import features as F

    rng = np.random.default_rng(11)
    n = 500
    price = 6000 + np.cumsum(rng.normal(0, 5, n))
    bars = pd.DataFrame({
        "open": price, "high": price + np.abs(rng.normal(0, 3, n)),
        "low": price - np.abs(rng.normal(0, 3, n)), "close": price,
        "volume": rng.integers(1000, 5000, n).astype(float),
    })
    feat = F.make_price_features(bars).to_pandas()

    for mode in MODES:
        s = make_signal(feat, mode=mode, osc_thr=0.2, vel_eps=0.01)
        n_long = int((s["signal"] > 0).sum())
        n_short = int((s["signal"] < 0).sum())
        print(f"  {mode:18s}: longs={n_long} shorts={n_short}")
        assert n_long + n_short > 0, f"{mode} produced no signals on a 500-bar series"

    # CAUSALITY: signal at t-1 identical whether computed on full or partial feature frame
    full_sig = make_signal(feat, mode="any_reversal", osc_thr=0.2, vel_eps=0.01)["signal"].to_numpy()
    max_diff = 0.0
    for t in (300, 400):
        partial_feat = F.make_price_features(bars.iloc[:t]).to_pandas()
        partial_sig = make_signal(partial_feat, mode="any_reversal", osc_thr=0.2, vel_eps=0.01)["signal"].to_numpy()
        max_diff = max(max_diff, abs(full_sig[t - 1] - partial_sig[t - 1]))
    print(f"signal causality max diff at t-1 = {max_diff:.1f}")
    assert max_diff == 0.0, "LOOKAHEAD: signal changed when future bars were added"
    print("strategy.py self-test PASSED")
