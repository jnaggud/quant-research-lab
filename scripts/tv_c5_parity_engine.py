#!/usr/bin/env python3
"""
TradingView-compatible execution model for the ES 15m C5 strategy family.

This module intentionally starts narrow. It models the order timing used by
the current C5 Pine script with process_orders_on_close=true and no
calc_on_order_fills. Indicator parity still depends on feeding it TradingView
bars and TradingView-aligned higher-timeframe/session features.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd


POINT_VALUE = 50.0
TICK_SIZE = 0.25
SLIPPAGE_TICKS = 1.0
COMMISSION_PER_SIDE = 2.50
INITIAL_CAPITAL = 50_000.0


CORE_PARAMS = {
    "h4_fast": 11,
    "h4_slow": 27,
    "d_fast": 9,
    "d_slow": 80,
    "regime_mode": "h4",
    "local_filter": "none",
    "stop_atr": 4.084981554127161,
    "trail_atr": 7.393095335737284,
    "cooldown": 21,
    "long_rsi_min": 40.33802129365303,
    "core_long_rsi_max": 100.0,
    "core_adx_min": 0.0,
    "core_long_max_extension_atr": 1_000_000.0,
    "core_long_max_vwap_dist_atr": 1_000_000.0,
    "short_rsi_max": 59.05022189927175,
    "macd_floor": -3.1231746759752084,
    "vol_mult": 0.9293673650029148,
    "use_momentum_exit": True,
    "long_exit_rsi": 39.66129925548556,
    "short_exit_rsi": 43.043945472221175,
    "long_exit_regime": -1,
    "short_exit_regime": 0,
    "allow_short": True,
    "h4_offset_minutes": 120,
    "short_gate": "any",
    "use_carry_long": False,
    "carry_regime": "both_up",
    "carry_filter": "ema55",
    "carry_rsi_min": 45.0,
    "carry_macd_floor": -1.0,
    "carry_vol_mult": 0.75,
    "use_participation": False,
    "participation_priority": False,
    "participation_regime": "both_up",
    "participation_filter": "ema55",
    "participation_rsi_min": 50.0,
    "participation_rsi_max": 80.0,
    "participation_macd_floor": -1.0,
    "participation_vol_mult": 0.5,
    "participation_adx_min": 10.0,
    "participation_max_extension_atr": 3.0,
    "participation_stop_atr": 5.0,
    "participation_trail_atr": 6.0,
    "participation_cooldown": 0,
    "participation_min_hold": 0,
    "participation_max_hold": 10_000,
    "participation_exit_filter": "ema55",
    "participation_exit_rsi": 45.0,
    "participation_exit_on_macd_roll": True,
    "use_trend_carry": False,
    "trend_carry_priority": False,
    "trend_carry_regime": "both_up",
    "trend_carry_filter": "stack",
    "trend_carry_rsi_min": 48.0,
    "trend_carry_rsi_max": 74.0,
    "trend_carry_macd_floor": -1.0,
    "trend_carry_vol_mult": 0.5,
    "trend_carry_adx_min": 8.0,
    "trend_carry_max_extension_atr": 4.0,
    "trend_carry_max_vwap_dist_atr": 4.0,
    "trend_carry_atr_rel_max": 3.0,
    "trend_carry_stop_atr": 5.0,
    "trend_carry_trail_atr": 7.0,
    "trend_carry_cooldown": 0,
    "trend_carry_min_hold": 4,
    "trend_carry_max_hold": 96,
    "trend_carry_exit_filter": "ema21",
    "trend_carry_exit_rsi": 44.0,
    "trend_carry_exit_regime": "h4_down",
    "trend_carry_exit_on_macd_roll": True,
    "trend_carry_exit_atr_rel_max": 4.0,
}


C5_CAP_PARAMS = {
    "cap_priority": False,
    "cap_regime": "daily_not_bear",
    "cap_adx_min": 7.311941,
    "cap_adx_max": 64.515881,
    "cap_atr_rel_min": 0.771198,
    "cap_atr_rel_max": 3.89685,
    "cap_vwap_dist_atr": 3.554982,
    "cap_bb_atr": -0.504851,
    "cap_prev_low_atr": 1.686516,
    "cap_low_break_atr": 1.343469,
    "cap_low96_atr": 0.47606,
    "cap_rsi_max": 39.841345,
    "cap_stoch_max": 21.963174,
    "cap_ret_z": 0.456169,
    "cap_reclaim_pos": 0.020825,
    "cap_volume_mult": 0.675144,
    "cap_pv_z_max": 0.141433,
    "cap_require_reversal": False,
    "cap_stop_atr": 4.218804,
    "cap_target_atr": 2.35392,
    "cap_trail_atr": 0.657293,
    "cap_exit_vwap_atr": -0.183714,
    "cap_exit_rsi": 62.269664,
    "cap_exit_range_pos": 0.202509,
    "cap_exit_on_peak": False,
    "cap_exit_on_momentum_peak": True,
    "cap_cooldown": 0,
    "cap_min_hold": 8,
    "cap_max_hold": 77,
    "use_cap": True,
    "use_date_range": True,
    "start_time": "2025-09-30T00:00:00Z",
}


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=int(length), adjust=False).mean()


def rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1 / int(length), adjust=False).mean()


def rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    rs = rma(gain, length) / (rma(loss, length) + 1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    prev = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return rma(tr, length)


def macd_hist(close: pd.Series) -> pd.Series:
    line = ema(close, 12) - ema(close, 26)
    return line - ema(line, 9)


def stoch(df: pd.DataFrame, length: int) -> pd.Series:
    low = df["low"].rolling(length, min_periods=1).min()
    high = df["high"].rolling(length, min_periods=1).max()
    return 100.0 * (df["close"] - low) / (high - low + 1e-10)


def adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = high.diff().where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
    minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_rma = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / (atr_rma + 1e-12)
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / (atr_rma + 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    return dx.ewm(alpha=1 / length, adjust=False).mean()


def load_bars(path: str | Path) -> pd.DataFrame:
    payload = json.loads(Path(path).read_text())
    bars = payload.get("bars")
    if bars is None:
        result = payload.get("result", {})
        bars = result.get("bars") if isinstance(result, dict) else result
    df = pd.DataFrame(bars)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def resample_ohlcv(df: pd.DataFrame, tf: str, *, offset: str | None = None) -> pd.DataFrame:
    kwargs = {"offset": offset} if offset else {}
    return df.resample(tf, **kwargs).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def session_daily_prev_low(df: pd.DataFrame) -> pd.Series:
    """Emulate request.security(..., "1D", low[1]) for CME-style futures days."""
    child_step = _chart_step(df.index)
    ny_index = df.index.tz_convert("America/New_York")
    session_day = (ny_index - pd.Timedelta(hours=18)).floor("D")
    daily = df.groupby(session_day).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    # The daily value is visible on the final child bar before the next
    # 18:00 New York session boundary, matching request.security lookahead_off.
    labels = (daily.index + pd.Timedelta(days=1) + pd.Timedelta(hours=18)).tz_convert("UTC") - child_step
    prev_low = daily["low"].shift(1).copy()
    prev_low.index = labels
    return prev_low.reindex(df.index, method="ffill")


def cme_session_key(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    ny_index = index.tz_convert("America/New_York")
    return (ny_index - pd.Timedelta(hours=18)).floor("D")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rsi"] = rsi(out["close"], 14)
    out["stoch_k"] = stoch(out, 14)
    out["stoch_d"] = out["stoch_k"].rolling(3, min_periods=1).mean()
    out["macdh"] = macd_hist(out["close"])
    out["atr"] = atr(out, 14)
    out["adx"] = adx(out, 14)
    out["ema8"] = ema(out["close"], 8)
    out["ema21"] = ema(out["close"], 21)
    out["ema55"] = ema(out["close"], 55)
    out["ema144"] = ema(out["close"], 144)
    out["vol_sma"] = out["volume"].rolling(48, min_periods=1).mean()
    basis = out["close"].rolling(40, min_periods=1).mean()
    dev = out["close"].rolling(40, min_periods=1).std(ddof=0).fillna(0.0)
    out["bb_upper"] = basis + 2.0 * dev
    out["bb_lower"] = basis - 2.0 * dev
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    session = cme_session_key(out.index)
    pv = typical * out["volume"]
    out["vwap"] = pv.groupby(session).cumsum() / out["volume"].replace(0, np.nan).groupby(session).cumsum()
    out["vwap"] = out["vwap"].ffill().fillna(out["close"])
    out["prev_day_low"] = session_daily_prev_low(out).fillna(out["low"])
    out["atr_rel"] = out["atr"] / out["atr"].rolling(192, min_periods=20).mean()
    out["vwap_dist_atr"] = (out["close"] - out["vwap"]) / out["atr"].replace(0, np.nan)
    ret1 = out["close"].pct_change()
    out["ret_z"] = (ret1 - ret1.rolling(96, min_periods=20).mean()) / ret1.rolling(96, min_periods=20).std(ddof=0)
    out["range_pos"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    out["low_24"] = out["low"].rolling(24, min_periods=1).min().shift(1)
    out["low_96"] = out["low"].rolling(96, min_periods=1).min().shift(1)
    velocity = out["close"].diff()
    pv_momentum = (velocity * out["volume"]).rolling(4, min_periods=1).sum()
    out["pv_z"] = pv_momentum / pv_momentum.rolling(96, min_periods=20).std(ddof=0)
    out["climax_volume"] = out["volume"] / out["volume"].rolling(96, min_periods=20).mean()
    return out.ffill().fillna(0.0)


def apply_tv_daily_security(feat: pd.DataFrame, daily_path: str | Path, params: dict) -> pd.DataFrame:
    """Use TradingView-exported 1D bars for daily request.security features.

    With barmerge.lookahead_off, TradingView exposes the requested higher
    timeframe value on the final child bar of the higher timeframe candle.
    For ES 15m this means the daily low/EMA values used by C5 update on the
    last 15m bar of the current CME daily session, not at the session open.
    """
    payload = json.loads(Path(daily_path).read_text())
    bars = payload.get("bars")
    if bars is None:
        result = payload.get("result", {})
        bars = result.get("bars") if isinstance(result, dict) else result
    if not bars:
        raise ValueError(f"no daily bars found in {daily_path}")
    daily = pd.DataFrame(bars)
    daily["datetime"] = pd.to_datetime(daily["time"], unit="s", utc=True)
    daily = daily.set_index("datetime").sort_index()
    labels = _htf_security_labels(daily.index, feat.index, pd.Timedelta(days=1))
    prev_low = daily["low"].astype(float).shift(1)
    prev_low.index = labels
    daily_fast = ema(daily["close"].astype(float), params["d_fast"]).shift(1)
    daily_fast.index = labels
    daily_slow = ema(daily["close"].astype(float), params["d_slow"]).shift(1)
    daily_slow.index = labels
    out = feat.copy()
    out["prev_day_low"] = prev_low.reindex(out.index, method="ffill").fillna(out["prev_day_low"])
    out["daily_fast_security"] = daily_fast.reindex(out.index, method="ffill")
    out["daily_slow_security"] = daily_slow.reindex(out.index, method="ffill")
    return out


def apply_tv_daily_prev_low(feat: pd.DataFrame, daily_path: str | Path) -> pd.DataFrame:
    return apply_tv_daily_security(feat, daily_path, default_c5_params())


def apply_tv_h4_security(feat: pd.DataFrame, h4_path: str | Path, params: dict) -> pd.DataFrame:
    """Use TradingView-exported 240m bars for request.security(..., "240", EMA[1])."""
    payload = json.loads(Path(h4_path).read_text())
    bars = payload.get("bars")
    if bars is None:
        result = payload.get("result", {})
        bars = result.get("bars") if isinstance(result, dict) else result
    if not bars:
        raise ValueError(f"no 240m bars found in {h4_path}")
    h4 = pd.DataFrame(bars)
    h4["datetime"] = pd.to_datetime(h4["time"], unit="s", utc=True)
    h4 = h4.set_index("datetime").sort_index()
    labels = _htf_security_labels(h4.index, feat.index, pd.Timedelta(minutes=240))
    h4_fast = ema(h4["close"].astype(float), params["h4_fast"]).shift(1)
    h4_fast.index = labels
    h4_slow = ema(h4["close"].astype(float), params["h4_slow"]).shift(1)
    h4_slow.index = labels
    out = feat.copy()
    out["h4_fast_security"] = h4_fast.reindex(out.index, method="ffill")
    out["h4_slow_security"] = h4_slow.reindex(out.index, method="ffill")
    return out


def _chart_step(index: pd.DatetimeIndex) -> pd.Timedelta:
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        return pd.Timedelta(0)
    return diffs.mode().iloc[0]


def _htf_security_labels(
    htf_index: pd.DatetimeIndex,
    child_index: pd.DatetimeIndex,
    nominal_duration: pd.Timedelta,
) -> pd.DatetimeIndex:
    """Label HTF values on the actual final child bar before the next HTF open.

    Exported TradingView higher-timeframe bars are timestamped at their open.
    With lookahead_off, Pine exposes the requested HTF value on the last child
    chart bar inside that HTF candle. Around futures maintenance breaks, that
    is often earlier than ``htf_open + nominal_duration - child_step`` because
    the theoretical final child bar does not exist.
    """
    labels = []
    child_step = _chart_step(child_index)
    for i, start in enumerate(htf_index):
        end = htf_index[i + 1] if i + 1 < len(htf_index) else start + nominal_duration
        pos = child_index.searchsorted(end, side="left") - 1
        if pos >= 0 and child_index[pos] >= start:
            labels.append(child_index[pos])
        else:
            labels.append(end - child_step)
    return pd.DatetimeIndex(labels)


def _security_prev_series(
    df: pd.DataFrame,
    tf: str,
    values_fn,
    *,
    offset: str | None = None,
    child_step: pd.Timedelta | None = None,
) -> pd.Series:
    """Approximate request.security(..., expr[1], lookahead_off) on child bars.

    TradingView timestamps the 240-minute value on the final child bar of the
    higher-timeframe candle. For a 15-minute chart, the 4H value for a candle
    ending at 18:00 first appears on the 17:45 bar.
    """
    kwargs = {"offset": offset} if offset else {}
    htf = df.resample(tf, closed="left", label="right", **kwargs).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    values = values_fn(htf).shift(1)
    step = child_step if child_step is not None else _chart_step(df.index)
    values.index = values.index - step
    return values.reindex(df.index, method="ffill")


def _cme_session_htf_prev_series(
    df: pd.DataFrame,
    tf_minutes: int,
    values_fn,
    *,
    child_step: pd.Timedelta | None = None,
) -> pd.Series:
    child = child_step if child_step is not None else _chart_step(df.index)
    ny_index = df.index.tz_convert("America/New_York")
    session_start_ny = (ny_index - pd.Timedelta(hours=18)).floor("D") + pd.Timedelta(hours=18)
    session_start = session_start_ny.tz_convert("UTC")
    elapsed_ns = (df.index - session_start).asi8
    bucket_ns = pd.Timedelta(minutes=tf_minutes).value
    bucket_start = pd.DatetimeIndex(session_start.asi8 + (elapsed_ns // bucket_ns) * bucket_ns, tz="UTC")
    bucket_end = bucket_start + pd.Timedelta(minutes=tf_minutes)
    htf = df.groupby(bucket_end).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    values = values_fn(htf).shift(1)
    values.index = values.index - child
    return values.reindex(df.index, method="ffill")


def make_regime(feat: pd.DataFrame, params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    child_step = _chart_step(feat.index)
    if "h4_fast_security" in feat.columns and "h4_slow_security" in feat.columns:
        h4_fast = feat["h4_fast_security"]
        h4_slow = feat["h4_slow_security"]
    else:
        h4_fast = _cme_session_htf_prev_series(feat, 240, lambda htf: ema(htf["close"], params["h4_fast"]), child_step=child_step)
        h4_slow = _cme_session_htf_prev_series(feat, 240, lambda htf: ema(htf["close"], params["h4_slow"]), child_step=child_step)
    if "daily_fast_security" in feat.columns and "daily_slow_security" in feat.columns:
        day_fast = feat["daily_fast_security"]
        day_slow = feat["daily_slow_security"]
    else:
        day_fast = _security_prev_series(feat, "1D", lambda htf: ema(htf["close"], params["d_fast"]), child_step=child_step)
        day_slow = _security_prev_series(feat, "1D", lambda htf: ema(htf["close"], params["d_slow"]), child_step=child_step)
    h4_signal = pd.Series(np.where(h4_fast > h4_slow, 1, -1), index=feat.index).fillna(0).astype(int)
    day_signal = pd.Series(np.where(day_fast > day_slow, 1, -1), index=feat.index).fillna(0).astype(int)
    if params["regime_mode"] == "both":
        regime = h4_signal.where(h4_signal == day_signal, 0).astype(int)
    elif params["regime_mode"] == "h4":
        regime = h4_signal.astype(int)
    else:
        regime = h4_signal.where(day_signal != -h4_signal, 0).astype(int)
    return regime.to_numpy(int), h4_signal.to_numpy(int), day_signal.to_numpy(int)


@dataclass(frozen=True)
class SignalBar:
    time: object
    open: float
    high: float
    low: float
    close: float
    atr: float = 1.0
    core_long: bool = False
    core_short: bool = False
    cap_long: bool = False
    trend_carry_long: bool = False
    core_long_close_exit: bool = False
    core_short_close_exit: bool = False
    cap_close_exit: bool = False
    participation_long: bool = False
    participation_close_exit: bool = False
    trend_carry_close_exit: bool = False


@dataclass
class ActiveExit:
    stop: Optional[float] = None
    limit: Optional[float] = None
    marketable_stop: bool = False


@dataclass
class Trade:
    entry_bar: int
    exit_bar: int
    direction: int
    kind: str
    entry_price: float
    exit_price: float
    pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    net_profit: float
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    long_trades: int
    short_trades: int
    core_trades: int
    cap_trades: int
    participation_trades: int
    trend_carry_trades: int
    trades: list[Trade]


def _slip_price(price: float, direction: int, is_entry: bool, order_type: str) -> float:
    """Apply Pine-style tick slippage approximation.

    Slippage applies to market and stop fills. Limits are kept at the limit
    price because TradingView limit orders fill at the specified or better
    price; exact better-price behavior is intentionally not modeled here.
    """
    if order_type == "stop":
        if direction == 1:
            price = math.floor(price / TICK_SIZE) * TICK_SIZE
        else:
            price = math.ceil(price / TICK_SIZE) * TICK_SIZE
    elif order_type == "limit":
        if direction == 1:
            price = math.ceil(price / TICK_SIZE) * TICK_SIZE
        else:
            price = math.floor(price / TICK_SIZE) * TICK_SIZE
        return price
    slip = SLIPPAGE_TICKS * TICK_SIZE
    if direction == 1:
        return price + slip if is_entry else price - slip
    return price - slip if is_entry else price + slip


def _trade_pnl(entry_price: float, exit_price: float, direction: int) -> float:
    points = (exit_price - entry_price) * direction
    return points * POINT_VALUE - 2.0 * COMMISSION_PER_SIDE


def _ohlc_path(bar: SignalBar) -> list[float]:
    """TradingView historical-bar path approximation.

    TradingView's broker emulator uses an OHLC path heuristic on historical
    bars. This path is enough to resolve same-bar stop/limit ambiguity in a
    deterministic way for fixture and local candidate testing.
    """
    if abs(bar.open - bar.high) < abs(bar.open - bar.low):
        return [bar.open, bar.high, bar.low, bar.close]
    return [bar.open, bar.low, bar.high, bar.close]


def _first_protective_fill(bar: SignalBar, direction: int, active: ActiveExit) -> tuple[Optional[str], Optional[float]]:
    if active.marketable_stop:
        if direction == 1 and active.stop is not None and bar.close < math.floor(active.stop / TICK_SIZE) * TICK_SIZE:
            return "stop", bar.close
        if direction == -1 and active.stop is not None and bar.close > math.ceil(active.stop / TICK_SIZE) * TICK_SIZE:
            return "stop", bar.close
        return None, None
    if direction == 1 and active.stop is not None and bar.open <= active.stop:
        return "stop", bar.open
    if direction == -1 and active.stop is not None and bar.open >= active.stop:
        return "stop", bar.open
    if direction == 1 and active.limit is not None and bar.open >= active.limit:
        return "limit", bar.open
    if direction == -1 and active.limit is not None and bar.open <= active.limit:
        return "limit", bar.open
    path = _ohlc_path(bar)
    for start, end in zip(path, path[1:]):
        lo, hi = min(start, end), max(start, end)
        if direction == 1:
            if active.stop is not None and end < start and lo <= active.stop <= hi:
                return "stop", active.stop
            if active.limit is not None and end > start and lo <= active.limit <= hi:
                return "limit", active.limit
        else:
            if active.stop is not None and end > start and lo <= active.stop <= hi:
                return "stop", active.stop
    return None, None


def run_tv_compatible_signal_bars(
    bars: Iterable[SignalBar],
    params: dict,
    *,
    initial_capital: float = INITIAL_CAPITAL,
) -> BacktestResult:
    """Run C5-style orders with TradingView close-processing semantics.

    The model follows the Pine ordering in C5:
    entries are submitted before exits in code, but market fills happen after
    the script pass. A newly submitted entry therefore has no protective
    strategy.exit active until a later script pass observes the open position.
    """
    rows = list(bars)
    equity = initial_capital
    peak_equity = initial_capital
    max_drawdown = 0.0
    trades: list[Trade] = []

    pos = 0
    kind = 0  # 1 core, 2 cap, 3 participation, 4 trend carry
    entry_bar: Optional[int] = None
    entry_price = 0.0
    entry_high = np.nan
    entry_low = np.nan
    active_exit: Optional[ActiveExit] = None
    last_exit_bar: Optional[int] = None

    long_trades = short_trades = core_trades = cap_trades = participation_trades = trend_carry_trades = 0

    def make_active_exit(bar: SignalBar) -> Optional[ActiveExit]:
        if not pos:
            return None
        if kind == 1 and pos == 1:
            stop = max(entry_price - params["stop_atr"] * bar.atr, entry_high - params["trail_atr"] * bar.atr)
            return ActiveExit(stop=stop)
        if kind == 1 and pos == -1:
            stop = min(entry_price + params["stop_atr"] * bar.atr, entry_low + params["trail_atr"] * bar.atr)
            return ActiveExit(stop=stop)
        if kind == 2:
            stop = max(entry_price - params["cap_stop_atr"] * bar.atr, entry_high - params["cap_trail_atr"] * bar.atr)
            target = entry_price + params["cap_target_atr"] * bar.atr
            return ActiveExit(stop=stop, limit=target)
        if kind == 3:
            stop = max(
                entry_price - params["participation_stop_atr"] * bar.atr,
                entry_high - params["participation_trail_atr"] * bar.atr,
            )
            return ActiveExit(stop=stop)
        if kind == 4:
            stop = max(
                entry_price - params["trend_carry_stop_atr"] * bar.atr,
                entry_high - params["trend_carry_trail_atr"] * bar.atr,
            )
            return ActiveExit(stop=stop)
        return None

    def entry_bar_active_exit(bar: SignalBar) -> Optional[ActiveExit]:
        return None

    def close_position(i: int, raw_exit: float, reason: str, order_type: str, *, cooldown_lag: int = 1) -> None:
        nonlocal pos, kind, entry_bar, entry_price, entry_high, entry_low
        nonlocal active_exit, last_exit_bar, equity, peak_equity, max_drawdown
        if entry_bar is None:
            raise RuntimeError("position has no entry bar")
        exit_price = _slip_price(raw_exit, pos, False, order_type)
        pnl = _trade_pnl(entry_price, exit_price, pos)
        equity += pnl
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity * 100.0)
        trades.append(
            Trade(
                entry_bar=entry_bar,
                exit_bar=i,
                direction=pos,
                kind="core" if kind == 1 else "cap" if kind == 2 else "participation" if kind == 3 else "trend_carry",
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                exit_reason=reason,
            )
        )
        pos = 0
        kind = 0
        entry_bar = None
        entry_price = 0.0
        entry_high = np.nan
        entry_low = np.nan
        active_exit = None
        last_exit_bar = i + cooldown_lag

    def cooldown_ready(i: int, cooldown: int) -> bool:
        return last_exit_bar is None or i - last_exit_bar >= cooldown

    for i, bar in enumerate(rows):
        if pos and active_exit is not None:
            fill_type, fill_price = _first_protective_fill(bar, pos, active_exit)
            if fill_type is not None and fill_price is not None:
                was_marketable = active_exit.marketable_stop
                close_position(i, fill_price, fill_type, fill_type, cooldown_lag=1 if was_marketable else 0)
                if was_marketable:
                    continue

        if pos == 0:
            core_ready = cooldown_ready(i, int(params.get("cooldown", 0)))
            cap_ready = cooldown_ready(i, int(params.get("cap_cooldown", 0)))
            participation_ready = cooldown_ready(i, int(params.get("participation_cooldown", 0)))
            trend_carry_ready = cooldown_ready(i, int(params.get("trend_carry_cooldown", 0)))
            if params.get("cap_priority", False) and cap_ready and bar.cap_long:
                pos, kind = 1, 2
            elif params.get("participation_priority", False) and participation_ready and bar.participation_long:
                pos, kind = 1, 3
            elif params.get("trend_carry_priority", False) and trend_carry_ready and bar.trend_carry_long:
                pos, kind = 1, 4
            elif core_ready and bar.core_long:
                pos, kind = 1, 1
            elif participation_ready and bar.participation_long:
                pos, kind = 1, 3
            elif trend_carry_ready and bar.trend_carry_long:
                pos, kind = 1, 4
            elif core_ready and params.get("allow_short", True) and bar.core_short:
                pos, kind = -1, 1
            elif cap_ready and bar.cap_long:
                pos, kind = 1, 2

            if pos:
                entry_bar = i
                entry_price = _slip_price(bar.close, pos, True, "market")
                entry_high = bar.high
                entry_low = bar.low
                active_exit = entry_bar_active_exit(bar)
                if pos == 1:
                    long_trades += 1
                else:
                    short_trades += 1
                if kind == 1:
                    core_trades += 1
                elif kind == 2:
                    cap_trades += 1
                elif kind == 3:
                    participation_trades += 1
                else:
                    trend_carry_trades += 1
            continue

        # Pine recalculates strategy.exit orders on the current script pass.
        # On historical bars, those stops/limits can be filled by the current
        # bar's OHLC path before a market strategy.close fallback is applied.
        if pos:
            bars_held = i - (entry_bar if entry_bar is not None else i)
            close_exit = False
            close_reason = ""

            if kind == 1 and pos == 1:
                active_exit = make_active_exit(bar)
                close_exit = bool(bar.core_long_close_exit)
                close_reason = "core_close"
            elif kind == 1 and pos == -1:
                active_exit = make_active_exit(bar)
                close_exit = bool(bar.core_short_close_exit)
                close_reason = "core_close"
            elif kind == 2:
                active_exit = make_active_exit(bar)
                close_exit = bars_held >= params.get("cap_max_hold", 10**9) or (
                    bars_held >= params.get("cap_min_hold", 0) and bar.cap_close_exit
                )
                close_reason = "cap_close"
            elif kind == 3:
                active_exit = make_active_exit(bar)
                close_exit = bars_held >= params.get("participation_max_hold", 10**9) or (
                    bars_held >= params.get("participation_min_hold", 0) and bar.participation_close_exit
                )
                close_reason = "participation_close"
            elif kind == 4:
                active_exit = make_active_exit(bar)
                close_exit = bars_held >= params.get("trend_carry_max_hold", 10**9) or (
                    bars_held >= params.get("trend_carry_min_hold", 0) and bar.trend_carry_close_exit
                )
                close_reason = "trend_carry_close"

            if active_exit is not None and active_exit.stop is not None:
                current_marketable = (pos == 1 and bar.close <= active_exit.stop) or (pos == -1 and bar.close >= active_exit.stop)
                if current_marketable:
                    close_position(i, bar.close, "stop", "stop", cooldown_lag=1)
                    continue
            if active_exit is not None and active_exit.limit is not None:
                current_limit = pos == 1 and bar.close >= active_exit.limit
                if current_limit:
                    close_position(i, bar.close, "limit", "limit", cooldown_lag=1)
                    continue

            if pos and close_exit:
                close_position(i, bar.close, close_reason, "market")
                continue

            if pos:
                entry_high = bar.high if np.isnan(entry_high) else max(entry_high, bar.high)
                entry_low = bar.low if np.isnan(entry_low) else min(entry_low, bar.low)

    if pos and rows:
        close_position(len(rows) - 1, rows[-1].close, "end_of_data", "market")

    pnls = [trade.pnl for trade in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    net = equity - initial_capital
    return BacktestResult(
        net_profit=net,
        total_return=net / initial_capital * 100.0,
        n_trades=len(trades),
        win_rate=len(wins) / len(trades) * 100.0 if trades else 0.0,
        profit_factor=sum(wins) / (abs(sum(losses)) or 1e-9) if trades else 0.0,
        max_drawdown=max_drawdown,
        long_trades=long_trades,
        short_trades=short_trades,
        core_trades=core_trades,
        cap_trades=cap_trades,
        participation_trades=participation_trades,
        trend_carry_trades=trend_carry_trades,
        trades=trades,
    )


def build_c5_signal_bars(feat: pd.DataFrame, params: dict) -> list[SignalBar]:
    regime, h4_signal, daily_signal = make_regime(feat, params)
    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    open_ = feat["open"].to_numpy(float)
    volume = feat["volume"].to_numpy(float)
    vol_sma = feat["vol_sma"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    adxv = feat["adx"].to_numpy(float)
    rsi_v = feat["rsi"].to_numpy(float)
    stoch_k = feat["stoch_k"].to_numpy(float)
    stoch_d = feat["stoch_d"].to_numpy(float)
    macd_v = feat["macdh"].to_numpy(float)
    ema8 = feat["ema8"].to_numpy(float)
    ema21 = feat["ema21"].to_numpy(float)
    ema55 = feat["ema55"].to_numpy(float)
    ema144 = feat["ema144"].to_numpy(float)
    bb_lower = feat["bb_lower"].to_numpy(float)
    vwap = feat["vwap"].to_numpy(float)
    prev_low = feat["prev_day_low"].to_numpy(float)
    atr_rel = feat["atr_rel"].to_numpy(float)
    vwap_dist = feat["vwap_dist_atr"].to_numpy(float)
    ret_z = feat["ret_z"].to_numpy(float)
    range_pos = feat["range_pos"].to_numpy(float)
    low_24 = feat["low_24"].to_numpy(float)
    low_96 = feat["low_96"].to_numpy(float)
    pv_z = feat["pv_z"].to_numpy(float)
    climax_volume = feat["climax_volume"].to_numpy(float)
    start_time = pd.Timestamp(params["start_time"]) if params.get("use_date_range") else None

    bars: list[SignalBar] = []
    for i, idx in enumerate(feat.index):
        if i == 0:
            bars.append(SignalBar(idx, open_[i], high[i], low[i], close[i], atrv[i]))
            continue
        if params["local_filter"] == "ema21":
            long_filter, short_filter = close[i] > ema21[i], close[i] < ema21[i]
        elif params["local_filter"] == "ema55":
            long_filter, short_filter = close[i] > ema55[i], close[i] < ema55[i]
        elif params["local_filter"] == "stack":
            long_filter = ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i]
            short_filter = ema8[i] < ema21[i] < ema55[i] and close[i] < ema8[i]
        elif params["local_filter"] == "ema144":
            long_filter, short_filter = close[i] > ema144[i], close[i] < ema144[i]
        else:
            long_filter = short_filter = True

        vol_ok = volume[i] >= params["vol_mult"] * vol_sma[i]
        short_gate = params.get("short_gate", "any")
        short_gate_ok = (
            short_gate == "any"
            or (short_gate == "daily_bear" and daily_signal[i] == -1)
            or (short_gate == "not_daily_bull" and daily_signal[i] != 1)
            or (short_gate == "h4_and_daily_bear" and h4_signal[i] == -1 and daily_signal[i] == -1)
        )
        carry_regime = params.get("carry_regime", "both_up")
        carry_regime_ok = (
            carry_regime == "h4_up"
            and h4_signal[i] == 1
            or carry_regime == "daily_up"
            and daily_signal[i] == 1
            or carry_regime == "both_up"
            and h4_signal[i] == 1
            and daily_signal[i] == 1
            or carry_regime == "either_up"
            and (h4_signal[i] == 1 or daily_signal[i] == 1)
        )
        carry_filter = params.get("carry_filter", "ema55")
        carry_filter_ok = (
            carry_filter == "none"
            or (carry_filter == "ema21" and close[i] > ema21[i])
            or (carry_filter == "ema55" and close[i] > ema55[i])
            or (carry_filter == "ema144" and close[i] > ema144[i])
            or (carry_filter == "stack" and ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i])
        )
        carry_long = (
            params.get("use_carry_long", False)
            and carry_regime_ok
            and carry_filter_ok
            and rsi_v[i] >= params.get("carry_rsi_min", 45.0)
            and macd_v[i] >= params.get("carry_macd_floor", -1.0)
            and volume[i] >= params.get("carry_vol_mult", 0.75) * vol_sma[i]
        )
        participation_regime = params.get("participation_regime", "both_up")
        participation_regime_ok = (
            (participation_regime == "h4_up" and h4_signal[i] == 1)
            or (participation_regime == "daily_up" and daily_signal[i] == 1)
            or (participation_regime == "both_up" and h4_signal[i] == 1 and daily_signal[i] == 1)
            or (participation_regime == "h4_up_daily_not_bear" and h4_signal[i] == 1 and daily_signal[i] != -1)
            or (participation_regime == "either_up" and (h4_signal[i] == 1 or daily_signal[i] == 1))
        )
        participation_filter = params.get("participation_filter", "ema55")
        participation_filter_ok = (
            participation_filter == "none"
            or (participation_filter == "ema21" and close[i] > ema21[i])
            or (participation_filter == "ema55" and close[i] > ema55[i])
            or (participation_filter == "ema144" and close[i] > ema144[i])
            or (participation_filter == "stack" and ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i])
            or (participation_filter == "vwap" and close[i] > vwap[i])
        )
        participation_extension_ok = (
            close[i] - ema21[i]
        ) <= params.get("participation_max_extension_atr", 3.0) * atrv[i]
        participation_long = (
            params.get("use_participation", False)
            and participation_regime_ok
            and participation_filter_ok
            and participation_extension_ok
            and rsi_v[i] >= params.get("participation_rsi_min", 50.0)
            and rsi_v[i] <= params.get("participation_rsi_max", 80.0)
            and macd_v[i] >= params.get("participation_macd_floor", -1.0)
            and volume[i] >= params.get("participation_vol_mult", 0.5) * vol_sma[i]
            and adxv[i] >= params.get("participation_adx_min", 10.0)
        )
        trend_carry_regime = params.get("trend_carry_regime", "both_up")
        trend_carry_regime_ok = (
            (trend_carry_regime == "h4_up" and h4_signal[i] == 1)
            or (trend_carry_regime == "daily_up" and daily_signal[i] == 1)
            or (trend_carry_regime == "both_up" and h4_signal[i] == 1 and daily_signal[i] == 1)
            or (trend_carry_regime == "h4_up_daily_not_bear" and h4_signal[i] == 1 and daily_signal[i] != -1)
            or (trend_carry_regime == "either_up" and (h4_signal[i] == 1 or daily_signal[i] == 1))
        )
        trend_carry_filter = params.get("trend_carry_filter", "stack")
        trend_carry_filter_ok = (
            trend_carry_filter == "none"
            or (trend_carry_filter == "ema21" and close[i] > ema21[i])
            or (trend_carry_filter == "ema55" and close[i] > ema55[i])
            or (trend_carry_filter == "ema144" and close[i] > ema144[i])
            or (trend_carry_filter == "stack" and ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i])
            or (trend_carry_filter == "vwap" and close[i] > vwap[i])
        )
        trend_carry_extension_ok = (
            close[i] - ema21[i]
        ) <= params.get("trend_carry_max_extension_atr", 4.0) * atrv[i]
        trend_carry_vwap_ok = (
            close[i] - vwap[i]
        ) <= params.get("trend_carry_max_vwap_dist_atr", 4.0) * atrv[i]
        trend_carry_atr_ok = atr_rel[i] <= params.get("trend_carry_atr_rel_max", 3.0)
        trend_carry_long = (
            params.get("use_trend_carry", False)
            and trend_carry_regime_ok
            and trend_carry_filter_ok
            and trend_carry_extension_ok
            and trend_carry_vwap_ok
            and trend_carry_atr_ok
            and rsi_v[i] >= params.get("trend_carry_rsi_min", 48.0)
            and rsi_v[i] <= params.get("trend_carry_rsi_max", 74.0)
            and macd_v[i] >= params.get("trend_carry_macd_floor", -1.0)
            and volume[i] >= params.get("trend_carry_vol_mult", 0.5) * vol_sma[i]
            and adxv[i] >= params.get("trend_carry_adx_min", 8.0)
        )
        core_long_extension_ok = (close[i] - ema21[i]) <= params.get("core_long_max_extension_atr", 1_000_000.0) * atrv[i]
        core_long_vwap_ok = (close[i] - vwap[i]) <= params.get("core_long_max_vwap_dist_atr", 1_000_000.0) * atrv[i]
        core_long = (
            regime[i] == 1
            and long_filter
            and rsi_v[i] >= params["long_rsi_min"]
            and rsi_v[i] <= params.get("core_long_rsi_max", 100.0)
            and macd_v[i] >= params["macd_floor"]
            and adxv[i] >= params.get("core_adx_min", 0.0)
            and core_long_extension_ok
            and core_long_vwap_ok
            and vol_ok
        )
        core_short = (
            params.get("allow_short", True)
            and short_gate_ok
            and regime[i] == -1
            and short_filter
            and rsi_v[i] <= params["short_rsi_max"]
            and macd_v[i] <= -params["macd_floor"]
            and vol_ok
        )
        k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
        cap_regime_ok = (
            params["cap_regime"] == "any"
            or (params["cap_regime"] == "daily_not_bear" and daily_signal[i] != -1)
            or (params["cap_regime"] == "h4_up" and h4_signal[i] == 1)
            or (params["cap_regime"] == "either_up" and (h4_signal[i] == 1 or daily_signal[i] == 1))
        )
        cap_deep = (
            vwap_dist[i] <= -params["cap_vwap_dist_atr"]
            or close[i] <= bb_lower[i] + params["cap_bb_atr"] * atrv[i]
            or close[i] <= prev_low[i] + params["cap_prev_low_atr"] * atrv[i]
            or low[i] <= low_24[i] - params["cap_low_break_atr"] * atrv[i]
            or low[i] <= low_96[i] + params["cap_low96_atr"] * atrv[i]
        )
        cap_exhaustion = (
            rsi_v[i] <= params["cap_rsi_max"]
            and stoch_k[i] <= params["cap_stoch_max"]
            and ret_z[i] <= -params["cap_ret_z"]
            and range_pos[i] >= params["cap_reclaim_pos"]
            and climax_volume[i] >= params["cap_volume_mult"]
            and pv_z[i] <= params["cap_pv_z_max"]
            and atr_rel[i] >= params["cap_atr_rel_min"]
            and atr_rel[i] <= params["cap_atr_rel_max"]
            and adxv[i] >= params["cap_adx_min"]
            and adxv[i] <= params["cap_adx_max"]
        )
        cap_reversal = k_cross_up or close[i] > close[i - 1] or macd_v[i] > macd_v[i - 1]
        cap_long = (
            params.get("use_cap", True)
            and cap_regime_ok
            and cap_deep
            and cap_exhaustion
            and (not params.get("cap_require_reversal", False) or cap_reversal)
        )
        core_long_close_exit = regime[i] <= params["long_exit_regime"] or (
            params["use_momentum_exit"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < params["long_exit_rsi"]
        )
        core_short_close_exit = regime[i] >= params["short_exit_regime"] or (
            params["use_momentum_exit"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > params["short_exit_rsi"]
        )
        cap_close_exit = (
            close[i] >= vwap[i] + params["cap_exit_vwap_atr"] * atrv[i]
            or rsi_v[i] >= params["cap_exit_rsi"]
            or (params["cap_exit_on_momentum_peak"] and macd_v[i] < macd_v[i - 1] and range_pos[i] <= params["cap_exit_range_pos"])
        )
        participation_exit_filter = params.get("participation_exit_filter", "ema55")
        participation_filter_exit = (
            (participation_exit_filter == "ema21" and close[i] < ema21[i])
            or (participation_exit_filter == "ema55" and close[i] < ema55[i])
            or (participation_exit_filter == "ema144" and close[i] < ema144[i])
            or (participation_exit_filter == "vwap" and close[i] < vwap[i])
            or (participation_exit_filter == "h4_down" and h4_signal[i] != 1)
            or (participation_exit_filter == "daily_bear" and daily_signal[i] == -1)
        )
        participation_close_exit = (
            h4_signal[i] != 1
            or participation_filter_exit
            or rsi_v[i] < params.get("participation_exit_rsi", 45.0)
            or (
                params.get("participation_exit_on_macd_roll", True)
                and macd_v[i] < macd_v[i - 1]
                and rsi_v[i] < params.get("participation_rsi_min", 50.0)
            )
        )
        trend_carry_exit_filter = params.get("trend_carry_exit_filter", "ema21")
        trend_carry_filter_exit = (
            (trend_carry_exit_filter == "ema21" and close[i] < ema21[i])
            or (trend_carry_exit_filter == "ema55" and close[i] < ema55[i])
            or (trend_carry_exit_filter == "ema144" and close[i] < ema144[i])
            or (trend_carry_exit_filter == "vwap" and close[i] < vwap[i])
            or (trend_carry_exit_filter == "h4_down" and h4_signal[i] != 1)
            or (trend_carry_exit_filter == "daily_bear" and daily_signal[i] == -1)
        )
        trend_carry_exit_regime = params.get("trend_carry_exit_regime", "h4_down")
        trend_carry_regime_exit = (
            (trend_carry_exit_regime == "none" and False)
            or (trend_carry_exit_regime == "h4_down" and h4_signal[i] != 1)
            or (trend_carry_exit_regime == "daily_bear" and daily_signal[i] == -1)
            or (trend_carry_exit_regime == "either_down" and (h4_signal[i] != 1 or daily_signal[i] == -1))
            or (trend_carry_exit_regime == "both_down" and h4_signal[i] != 1 and daily_signal[i] == -1)
        )
        trend_carry_close_exit = (
            trend_carry_regime_exit
            or trend_carry_filter_exit
            or rsi_v[i] < params.get("trend_carry_exit_rsi", 44.0)
            or atr_rel[i] > params.get("trend_carry_exit_atr_rel_max", 4.0)
            or (
                params.get("trend_carry_exit_on_macd_roll", True)
                and macd_v[i] < macd_v[i - 1]
                and rsi_v[i] < params.get("trend_carry_rsi_min", 48.0)
            )
        )
        in_range = start_time is None or idx >= start_time
        bars.append(
            SignalBar(
                time=idx,
                open=open_[i],
                high=high[i],
                low=low[i],
                close=close[i],
                atr=atrv[i],
                core_long=bool(in_range and (core_long or carry_long)),
                core_short=bool(in_range and core_short),
                cap_long=bool(in_range and cap_long),
                trend_carry_long=bool(in_range and trend_carry_long),
                core_long_close_exit=bool(core_long_close_exit),
                core_short_close_exit=bool(core_short_close_exit),
                cap_close_exit=bool(cap_close_exit),
                participation_long=bool(in_range and participation_long),
                participation_close_exit=bool(participation_close_exit),
                trend_carry_close_exit=bool(trend_carry_close_exit),
            )
        )
    return bars


def default_c5_params() -> dict:
    params = dict(CORE_PARAMS)
    params.update(C5_CAP_PARAMS)
    return params


def run_c5_tv_compatible(
    data_path: str | Path,
    *,
    start: int = 0,
    end: Optional[int] = None,
    daily_bars_path: str | Path | None = None,
    h4_bars_path: str | Path | None = None,
    params: dict | None = None,
) -> BacktestResult:
    raw = load_bars(data_path)
    feat = build_features(raw)
    run_params = default_c5_params()
    if params:
        run_params.update(params)
    if daily_bars_path is not None:
        feat = apply_tv_daily_security(feat, daily_bars_path, run_params)
    if h4_bars_path is not None:
        feat = apply_tv_h4_security(feat, h4_bars_path, run_params)
    if end is None:
        end = len(feat)
    feat = feat.iloc[start:end].copy()
    bars = build_c5_signal_bars(feat, run_params)
    return run_tv_compatible_signal_bars(bars, run_params)


def _result_to_jsonable(result: BacktestResult) -> dict:
    data = asdict(result)
    data["trades"] = [asdict(trade) for trade in result.trades]
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the C5 TradingView-compatible local simulator.")
    parser.add_argument("data", help="TradingView-style JSON bars file")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--daily-bars", default=None, help="TradingView-exported 1D bars for exact request.security daily lows")
    parser.add_argument("--h4-bars", default=None, help="TradingView-exported 240m bars for exact request.security H4 EMAs")
    parser.add_argument("--trades", action="store_true", help="Include trade list in JSON output")
    args = parser.parse_args()

    result = run_c5_tv_compatible(
        args.data,
        start=args.start,
        end=args.end,
        daily_bars_path=args.daily_bars,
        h4_bars_path=args.h4_bars,
    )
    payload = _result_to_jsonable(result)
    if not args.trades:
        payload.pop("trades", None)
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
