"""Causal ES failed-breakout mean-reversion strategy.

This is a mechanical translation of a discretionary reversal setup:

1. Price reaches a causal rolling support/resistance level via a fast move.
2. Participation before the move is flat rather than steadily increasing.
3. Price has crossed a 30-period mean frequently and that mean is flat.
4. The preceding market is inefficient/choppy rather than directional.
5. A completed bar breaches the level and closes back inside it.

The module is independent of C11. Signals are formed on completed one-minute
bars and filled at the next bar open. Stops are beyond the rejection extreme,
bounded by ATR, and targets are one unit of initial risk (1R).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from quant import backtest as B


CACHE = Path(__file__).parent / "cache"


@dataclass(frozen=True)
class MRParams:
    level_type: str = "session_union"
    trigger_delay: int = 1
    level_lookback: int = 480
    spike_bars: int = 2
    spike_atr: float = 1.5
    volume_fast: int = 30
    volume_slow: int = 120
    volume_ratio_max: float = 1.05
    climax_volume_min: float = 1.5
    ma_length: int = 30
    context_bars: int = 240
    min_crosses: int = 6
    ma_slope_bars: int = 30
    ma_slope_atr_max: float = 0.75
    efficiency_max: float = 0.25
    stop_buffer_atr: float = 0.15
    min_risk_atr: float = 1.0
    max_risk_atr: float = 3.0
    reward_risk: float = 1.0
    max_hold_bars: int = 90
    cooldown_bars: int = 15
    rth_only: bool = True


def load_all_1m() -> pd.DataFrame:
    """Load the back-adjusted continuous ES one-minute history."""
    frames = []
    for path in sorted(CACHE.glob("ES_continuous_minute_*.parquet")):
        frame = pl.read_parquet(path)
        adjusted = {c: c.removeprefix("adj_") for c in frame.columns if c.startswith("adj_")}
        if adjusted:
            frame = frame.drop([v for v in adjusted.values() if v in frame.columns]).rename(adjusted)
        frames.append(frame.select(["ts", "open", "high", "low", "close", "volume"]).to_pandas())
    if not frames:
        raise SystemExit("no staged ES one-minute data")
    return (pd.concat(frames, ignore_index=True)
            .drop_duplicates("ts").sort_values("ts").reset_index(drop=True))


def build_features(bars: pd.DataFrame, p: MRParams = MRParams()) -> pd.DataFrame:
    """Build causal features and rejection signals on completed bars."""
    out = bars.copy()
    o, h, l, c = (out[x].astype(float) for x in ("open", "high", "low", "close"))
    v = out["volume"].astype(float)

    previous_close = c.shift(1)
    true_range = pd.concat([
        h - l, (h - previous_close).abs(), (l - previous_close).abs()
    ], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / 30, adjust=False).mean()

    # Rolling levels exclude the current bar. Session levels are completed before
    # RTH begins: prior RTH high/low and the just-completed overnight high/low.
    rolling_resistance = h.shift(1).rolling(
        p.level_lookback, min_periods=p.level_lookback).max()
    rolling_support = l.shift(1).rolling(
        p.level_lookback, min_periods=p.level_lookback).min()
    chicago = pd.DatetimeIndex(out["ts"]).tz_convert("America/Chicago")
    local_date = pd.Series(chicago.date, index=out.index)
    minute = chicago.hour * 60 + chicago.minute
    rth_mask = (minute >= 8 * 60 + 30) & (minute < 15 * 60)

    session_work = pd.DataFrame({
        "date": local_date, "high": h, "low": l, "rth": rth_mask,
    })
    rth_levels = session_work[session_work["rth"]].groupby("date").agg(
        prior_rth_high=("high", "max"), prior_rth_low=("low", "min"))
    rth_levels = rth_levels.shift(1)
    prior_rth_high = local_date.map(rth_levels["prior_rth_high"])
    prior_rth_low = local_date.map(rth_levels["prior_rth_low"])

    overnight_date = pd.Series(
        (chicago + pd.to_timedelta((chicago.hour >= 17).astype(int), unit="D")).date,
        index=out.index,
    )
    overnight_mask = (minute >= 17 * 60) | (minute < 8 * 60 + 30)
    overnight_work = pd.DataFrame({
        "date": overnight_date, "high": h, "low": l, "overnight": overnight_mask,
    })
    overnight_levels = overnight_work[overnight_work["overnight"]].groupby("date").agg(
        overnight_high=("high", "max"), overnight_low=("low", "min"))
    overnight_high = local_date.map(overnight_levels["overnight_high"])
    overnight_low = local_date.map(overnight_levels["overnight_low"])

    ma = c.rolling(p.ma_length, min_periods=p.ma_length).mean()
    side = np.sign(c - ma)
    crossed = pd.Series(side, index=out.index).ne(pd.Series(side, index=out.index).shift(1))
    crosses = crossed.shift(1).rolling(p.context_bars, min_periods=p.context_bars).sum()
    ma_slope_atr = (ma.shift(1) - ma.shift(1 + p.ma_slope_bars)).abs() / atr.shift(1)

    path = c.diff().abs().shift(1).rolling(p.context_bars, min_periods=p.context_bars).sum()
    net = (c.shift(1) - c.shift(1 + p.context_bars)).abs()
    efficiency = net / path.replace(0.0, np.nan)

    # Measure volume before the spike, not volume generated by the rejection bar.
    event_shift = p.trigger_delay
    pre_v = v.shift(p.spike_bars + event_shift)
    volume_ratio = (pre_v.rolling(p.volume_fast, min_periods=p.volume_fast).mean() /
                    pre_v.rolling(p.volume_slow, min_periods=p.volume_slow).mean())
    volume_ok = volume_ratio <= p.volume_ratio_max

    event_high = h.shift(event_shift)
    event_low = l.shift(event_shift)
    event_atr = atr.shift(event_shift)
    approach_from = c.shift(p.spike_bars + event_shift)
    spike_up = (event_high - approach_from) / event_atr
    spike_down = (approach_from - event_low) / event_atr
    pre_spike_volume = v.shift(event_shift + 1).rolling(
        p.volume_slow, min_periods=p.volume_slow).mean()
    climax_ratio = v.shift(event_shift) / pre_spike_volume
    climax_ok = climax_ratio >= p.climax_volume_min
    chop_ok = ((crosses >= p.min_crosses) &
               (ma_slope_atr <= p.ma_slope_atr_max) &
               (efficiency <= p.efficiency_max))

    if p.level_type == "rolling":
        resistance, support = rolling_resistance, rolling_support
        event_resistance = resistance.shift(event_shift)
        event_support = support.shift(event_shift)
        short_rejection = (event_high > event_resistance) & (c < event_resistance)
        long_rejection = (event_low < event_support) & (c > event_support)
    elif p.level_type == "prior_rth":
        resistance, support = prior_rth_high, prior_rth_low
        event_resistance = resistance.shift(event_shift)
        event_support = support.shift(event_shift)
        short_rejection = (event_high > event_resistance) & (c < event_resistance)
        long_rejection = (event_low < event_support) & (c > event_support)
    elif p.level_type == "overnight":
        resistance, support = overnight_high, overnight_low
        event_resistance = resistance.shift(event_shift)
        event_support = support.shift(event_shift)
        short_rejection = (event_high > event_resistance) & (c < event_resistance)
        long_rejection = (event_low < event_support) & (c > event_support)
    elif p.level_type == "session_union":
        resistance = pd.concat([prior_rth_high, overnight_high], axis=1).min(axis=1)
        support = pd.concat([prior_rth_low, overnight_low], axis=1).max(axis=1)
        event_rth_high = prior_rth_high.shift(event_shift)
        event_rth_low = prior_rth_low.shift(event_shift)
        event_on_high = overnight_high.shift(event_shift)
        event_on_low = overnight_low.shift(event_shift)
        short_rejection = ((event_high > event_rth_high) & (c < event_rth_high)) | \
                          ((event_high > event_on_high) & (c < event_on_high))
        long_rejection = ((event_low < event_rth_low) & (c > event_rth_low)) | \
                         ((event_low < event_on_low) & (c > event_on_low))
    else:
        raise ValueError(f"unknown level_type: {p.level_type}")
    short_signal = (short_rejection & (spike_up >= p.spike_atr) &
                    volume_ok & climax_ok & chop_ok)
    long_signal = (long_rejection & (spike_down >= p.spike_atr) &
                   volume_ok & climax_ok & chop_ok)

    if p.rth_only:
        short_signal &= rth_mask
        long_signal &= rth_mask

    out["atr"] = atr
    out["resistance"] = resistance
    out["support"] = support
    out["prior_rth_high"] = prior_rth_high
    out["prior_rth_low"] = prior_rth_low
    out["overnight_high"] = overnight_high
    out["overnight_low"] = overnight_low
    out["spike_up_atr"] = spike_up
    out["spike_down_atr"] = spike_down
    out["volume_ratio"] = volume_ratio
    out["climax_ratio"] = climax_ratio
    out["ma_crosses"] = crosses
    out["ma_slope_atr"] = ma_slope_atr
    out["efficiency"] = efficiency
    out["short_rejection"] = short_rejection.fillna(False)
    out["long_rejection"] = long_rejection.fillna(False)
    out["signal"] = np.where(long_signal & ~short_signal, 1,
                             np.where(short_signal & ~long_signal, -1, 0))
    return out


def run_backtest(frame: pd.DataFrame, p: MRParams = MRParams(), *,
                 slippage_ticks: float = 1.0, starting_equity: float = 100_000.0,
                 direction: str = "both", force_close_end: bool = False) -> dict:
    """Backtest dynamic structure stops and 1R targets conservatively."""
    o = frame["open"].to_numpy(float)
    h = frame["high"].to_numpy(float)
    l = frame["low"].to_numpy(float)
    c = frame["close"].to_numpy(float)
    atr = frame["atr"].to_numpy(float)
    signal = frame["signal"].to_numpy(int)
    n = len(frame)
    pv = B.ES.point_value
    slip = slippage_ticks * B.ES.tick
    equity = starting_equity
    eq_curve = np.full(n, starting_equity, dtype=float)
    trades: list[dict] = []
    pos = 0
    entry_i = -1
    entry_px = stop_px = target_px = 0.0
    last_exit_i = -10**9

    for i in range(n):
        if pos:
            held = i - entry_i
            exit_px = None
            reason = None
            # Conservative ambiguity rule: when stop and target occur in the same
            # one-minute bar, book the stop first.
            if pos > 0:
                if l[i] <= stop_px:
                    exit_px, reason = min(o[i], stop_px), "stop"
                elif h[i] >= target_px:
                    exit_px, reason = max(o[i], target_px), "target"
            else:
                if h[i] >= stop_px:
                    exit_px, reason = max(o[i], stop_px), "stop"
                elif l[i] <= target_px:
                    exit_px, reason = min(o[i], target_px), "target"
            if exit_px is None and held >= p.max_hold_bars:
                exit_px, reason = c[i], "max_hold"
            if exit_px is None and force_close_end and i == n - 1:
                exit_px, reason = c[i], "end_of_window"
            if exit_px is not None:
                exit_px -= slip * pos
                pnl = (exit_px - entry_px) * pos * pv - 2 * B.ES.commission
                equity += pnl
                trades.append({
                    "entry_i": entry_i, "exit_i": i, "dir": pos,
                    "entry_px": entry_px, "exit_px": exit_px,
                    "stop_px": stop_px, "target_px": target_px,
                    "bars_held": held, "reason": reason, "pnl": pnl,
                    "equity": equity,
                })
                pos = 0
                last_exit_i = i

        allowed = (signal[i] > 0 and direction in ("long", "both")) or \
                  (signal[i] < 0 and direction in ("short", "both"))
        if pos == 0 and i - last_exit_i >= p.cooldown_bars and allowed and i + 1 < n:
            trade_direction = int(signal[i])
            raw_entry = o[i + 1]
            candidate_entry = raw_entry + slip * trade_direction
            rejection_extreme = (l[i] - p.stop_buffer_atr * atr[i]
                                 if trade_direction > 0 else h[i] + p.stop_buffer_atr * atr[i])
            structural_risk = ((candidate_entry - rejection_extreme) if trade_direction > 0
                               else (rejection_extreme - candidate_entry))
            min_risk = p.min_risk_atr * atr[i]
            max_risk = p.max_risk_atr * atr[i]
            risk = max(structural_risk, min_risk)
            if np.isfinite(risk) and 0 < risk <= max_risk:
                pos = trade_direction
                entry_i = i + 1
                entry_px = candidate_entry
                stop_px = entry_px - trade_direction * risk
                target_px = entry_px + trade_direction * risk * p.reward_risk

        eq_curve[i] = equity

    metrics = B._metrics(trades, eq_curve, starting_equity)
    return {"trades": trades, "equity_curve": eq_curve, "metrics": metrics}


def signal_diagnostics(frame: pd.DataFrame) -> dict:
    """Counts showing where candidates are removed by the mechanical filters."""
    finite = frame.dropna(subset=["atr", "resistance", "support"])
    return {
        "bars": len(frame),
        "raw_short_rejections": int(finite["short_rejection"].sum()),
        "raw_long_rejections": int(finite["long_rejection"].sum()),
        "final_short_signals": int((finite["signal"] < 0).sum()),
        "final_long_signals": int((finite["signal"] > 0).sum()),
    }
