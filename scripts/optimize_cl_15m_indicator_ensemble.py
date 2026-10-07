#!/usr/bin/env python3
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

from optimize_15m_mtf_reversal import atr, ema, load_json, macd_hist, resample_ohlcv, rsi, stoch
from optimize_cl_15m_active_router_mp import (
    COMMISSION_PER_SIDE,
    INITIAL_CAPITAL,
    POINT_VALUE,
    SLIPPAGE_TICKS,
    TICK_SIZE,
    adx,
    buy_hold_pnl,
    trade_pnl,
)


INDICATOR_LIBRARY = [
    "ema_cross", "sma_cross", "macd_hist", "rsi_momentum", "rsi_reversion",
    "stoch_cross", "stoch_reversion", "adx_trend", "donchian_breakout", "bollinger_reversion",
    "keltner_breakout", "vwap_reversion", "vwap_trend", "cci_reversion", "williams_reversion",
    "roc_momentum", "atr_expansion", "volume_impulse", "obv_slope", "mfi_reversion",
    "cmf_flow", "aroon_trend", "ichimoku_bias", "zscore_reversion", "linreg_slope",
    "heikin_ashi", "velocity_turn", "acceleration_turn", "jerk_turn", "price_volume_momentum",
]

@dataclass
class EnsembleResult:
    net_profit: float
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    avg_trade: float
    exposure: float
    long_trades: int
    short_trades: int
    positive_months: int
    active_months: int
    top_month_share: float
    max_stagnation_days: float
    max_winner_share: float


def true_range(df):
    prev = df["close"].shift(1).fillna(df["close"])
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)


def cci(df, length):
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    mean = typical.rolling(length, min_periods=1).mean()
    mad = (typical - mean).abs().rolling(length, min_periods=1).mean()
    return (typical - mean) / (0.015 * mad.replace(0, np.nan))


def mfi(df, length):
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    raw = typical * df["volume"]
    positive = raw.where(typical > typical.shift(1), 0.0).rolling(length, min_periods=1).sum()
    negative = raw.where(typical < typical.shift(1), 0.0).rolling(length, min_periods=1).sum()
    ratio = positive / negative.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + ratio)


def cmf(df, length):
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    mfv = mfm * df["volume"]
    return mfv.rolling(length, min_periods=1).sum() / df["volume"].rolling(length, min_periods=1).sum().replace(0, np.nan)


def aroon_signal(df, length):
    highs = df["high"].rolling(length + 1, min_periods=1)
    lows = df["low"].rolling(length + 1, min_periods=1)
    up = highs.apply(lambda x: 100.0 * np.argmax(x) / max(1, len(x) - 1), raw=True)
    down = lows.apply(lambda x: 100.0 * np.argmin(x) / max(1, len(x) - 1), raw=True)
    return up - down


def linreg_slope(series, length):
    x = np.arange(length, dtype=float)
    x = x - x.mean()
    denom = np.sum(x * x)

    def slope(values):
        if len(values) < length:
            return 0.0
        y = values - np.mean(values)
        return float(np.sum(x * y) / denom)

    return series.rolling(length, min_periods=length).apply(slope, raw=True)


def build_base_features(df):
    out = df.copy()
    out["atr"] = atr(out, 14).replace(0, np.nan)
    out["adx"] = adx(out, 14).fillna(0.0)
    out["rsi"] = rsi(out["close"], 14).fillna(50.0)
    out["stoch_k"] = stoch(out, 14).fillna(50.0)
    out["stoch_d"] = out["stoch_k"].rolling(3, min_periods=1).mean()
    out["macdh"] = macd_hist(out["close"]).fillna(0.0)
    out["vol_sma"] = out["volume"].rolling(48, min_periods=1).mean()
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    session = out.index.floor("1D")
    pv = typical * out["volume"]
    out["vwap"] = pv.groupby(session).cumsum() / out["volume"].replace(0, np.nan).groupby(session).cumsum()
    out["vwap"] = out["vwap"].ffill().fillna(out["close"])
    out["ny_hour"] = out.index.tz_convert("America/New_York").hour
    day = resample_ohlcv(out, "1D")
    out["daily_ema_fast"] = ema(day["close"], 12).shift(1).reindex(out.index, method="ffill")
    out["daily_ema_slow"] = ema(day["close"], 50).shift(1).reindex(out.index, method="ffill")
    h4 = resample_ohlcv(out, "240min")
    out["h4_ema_fast"] = ema(h4["close"], 17).shift(1).reindex(out.index, method="ffill")
    out["h4_ema_slow"] = ema(h4["close"], 26).shift(1).reindex(out.index, method="ffill")
    return out.ffill().fillna(0.0)


def sign_series(condition_long, condition_short):
    return pd.Series(np.where(condition_long, 1.0, np.where(condition_short, -1.0, 0.0)), index=condition_long.index)


def indicator_signals(feat, params):
    close = feat["close"]
    high = feat["high"]
    low = feat["low"]
    volume = feat["volume"]
    atrv = feat["atr"].replace(0, np.nan)
    signals = {}

    ema_fast = ema(close, params["ema_fast"])
    ema_slow = ema(close, params["ema_slow"])
    signals["ema_cross"] = sign_series(ema_fast > ema_slow, ema_fast < ema_slow)

    sma_fast = close.rolling(params["sma_fast"], min_periods=1).mean()
    sma_slow = close.rolling(params["sma_slow"], min_periods=1).mean()
    signals["sma_cross"] = sign_series(sma_fast > sma_slow, sma_fast < sma_slow)

    signals["macd_hist"] = sign_series(feat["macdh"] > params["macd_floor"], feat["macdh"] < -params["macd_floor"])
    signals["rsi_momentum"] = sign_series(feat["rsi"] > params["rsi_mom_high"], feat["rsi"] < params["rsi_mom_low"])
    signals["rsi_reversion"] = sign_series(feat["rsi"] < params["rsi_rev_low"], feat["rsi"] > params["rsi_rev_high"])

    k_cross_up = (feat["stoch_k"].shift(1) <= feat["stoch_d"].shift(1)) & (feat["stoch_k"] > feat["stoch_d"])
    k_cross_down = (feat["stoch_k"].shift(1) >= feat["stoch_d"].shift(1)) & (feat["stoch_k"] < feat["stoch_d"])
    signals["stoch_cross"] = sign_series(k_cross_up, k_cross_down)
    signals["stoch_reversion"] = sign_series(feat["stoch_k"] < params["stoch_low"], feat["stoch_k"] > params["stoch_high"])

    signals["adx_trend"] = sign_series((ema_fast > ema_slow) & (feat["adx"] > params["adx_min"]), (ema_fast < ema_slow) & (feat["adx"] > params["adx_min"]))

    don_high = high.rolling(params["don_len"], min_periods=1).max().shift(1)
    don_low = low.rolling(params["don_len"], min_periods=1).min().shift(1)
    signals["donchian_breakout"] = sign_series(close > don_high, close < don_low)

    bb_basis = close.rolling(params["bb_len"], min_periods=1).mean()
    bb_dev = close.rolling(params["bb_len"], min_periods=1).std(ddof=0).fillna(0.0)
    bb_upper = bb_basis + params["bb_mult"] * bb_dev
    bb_lower = bb_basis - params["bb_mult"] * bb_dev
    signals["bollinger_reversion"] = sign_series(close < bb_lower, close > bb_upper)

    kc_mid = ema(close, params["kc_len"])
    tr = true_range(feat)
    kc_atr = tr.ewm(alpha=1 / params["kc_len"], adjust=False).mean()
    signals["keltner_breakout"] = sign_series(close > kc_mid + params["kc_mult"] * kc_atr, close < kc_mid - params["kc_mult"] * kc_atr)

    vwap_dist = (close - feat["vwap"]) / atrv
    signals["vwap_reversion"] = sign_series(vwap_dist < -params["vwap_atr"], vwap_dist > params["vwap_atr"])
    signals["vwap_trend"] = sign_series((close > feat["vwap"]) & (feat["vwap"] > feat["vwap"].shift(8)), (close < feat["vwap"]) & (feat["vwap"] < feat["vwap"].shift(8)))

    cci_v = cci(feat, params["cci_len"]).fillna(0.0)
    signals["cci_reversion"] = sign_series(cci_v < -params["cci_edge"], cci_v > params["cci_edge"])

    hh = high.rolling(params["will_len"], min_periods=1).max()
    ll = low.rolling(params["will_len"], min_periods=1).min()
    willr = -100.0 * (hh - close) / (hh - ll).replace(0, np.nan)
    signals["williams_reversion"] = sign_series(willr < params["will_low"], willr > params["will_high"])

    roc = (close - close.shift(params["roc_len"])) / close.shift(params["roc_len"]).replace(0, np.nan) * 100.0
    signals["roc_momentum"] = sign_series(roc > params["roc_edge"], roc < -params["roc_edge"])

    atr_rel = feat["atr"] / feat["atr"].rolling(192, min_periods=20).mean()
    signals["atr_expansion"] = sign_series((atr_rel > params["atr_rel_high"]) & (close > close.shift(1)), (atr_rel > params["atr_rel_high"]) & (close < close.shift(1)))

    vol_impulse = (close - close.shift(1)) * volume / ((close - close.shift(1)).abs() * volume).rolling(96, min_periods=10).mean().replace(0, np.nan)
    signals["volume_impulse"] = sign_series(vol_impulse > params["impulse_edge"], vol_impulse < -params["impulse_edge"])

    obv = (np.sign(close.diff().fillna(0.0)) * volume).cumsum()
    obv_s = linreg_slope(obv, params["obv_len"]) / volume.rolling(params["obv_len"], min_periods=1).mean().replace(0, np.nan)
    signals["obv_slope"] = sign_series(obv_s > params["obv_edge"], obv_s < -params["obv_edge"])

    mfi_v = mfi(feat, params["mfi_len"]).fillna(50.0)
    signals["mfi_reversion"] = sign_series(mfi_v < params["mfi_low"], mfi_v > params["mfi_high"])

    cmf_v = cmf(feat, params["cmf_len"]).fillna(0.0)
    signals["cmf_flow"] = sign_series(cmf_v > params["cmf_edge"], cmf_v < -params["cmf_edge"])

    aroon_v = aroon_signal(feat, params["aroon_len"]).fillna(0.0)
    signals["aroon_trend"] = sign_series(aroon_v > params["aroon_edge"], aroon_v < -params["aroon_edge"])

    tenkan = (high.rolling(9, min_periods=1).max() + low.rolling(9, min_periods=1).min()) / 2.0
    kijun = (high.rolling(26, min_periods=1).max() + low.rolling(26, min_periods=1).min()) / 2.0
    span_a = ((tenkan + kijun) / 2.0).shift(26)
    span_b = ((high.rolling(52, min_periods=1).max() + low.rolling(52, min_periods=1).min()) / 2.0).shift(26)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    cloud_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)
    signals["ichimoku_bias"] = sign_series(close > cloud_top, close < cloud_bottom)

    z = (close - bb_basis) / bb_dev.replace(0, np.nan)
    signals["zscore_reversion"] = sign_series(z < -params["z_edge"], z > params["z_edge"])

    slope = linreg_slope(close, params["lr_len"]) / atrv
    signals["linreg_slope"] = sign_series(slope > params["lr_edge"], slope < -params["lr_edge"])

    ha_close = (feat["open"] + high + low + close) / 4.0
    ha_open = ha_close.copy()
    for i in range(1, len(ha_open)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0
    signals["heikin_ashi"] = sign_series(ha_close > ha_open, ha_close < ha_open)

    velocity = (close - close.shift(params["kin_len"])) / atrv
    acceleration = velocity - velocity.shift(params["kin_len"])
    jerk = acceleration - acceleration.shift(params["kin_len"])
    signals["velocity_turn"] = sign_series(velocity < -params["vel_edge"], velocity > params["vel_edge"])
    signals["acceleration_turn"] = sign_series((velocity < 0) & (acceleration > params["accel_edge"]), (velocity > 0) & (acceleration < -params["accel_edge"]))
    signals["jerk_turn"] = sign_series((velocity < 0) & (jerk > params["jerk_edge"]), (velocity > 0) & (jerk < -params["jerk_edge"]))
    signals["price_volume_momentum"] = sign_series((vol_impulse > params["pvm_edge"]) & (roc > 0), (vol_impulse < -params["pvm_edge"]) & (roc < 0))

    return {name: series.replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-1.0, 1.0).to_numpy(float) for name, series in signals.items()}


def suggest_params(trial):
    params = {
        "ema_fast": trial.suggest_int("ema_fast", 5, 24),
        "ema_slow": trial.suggest_int("ema_slow", 25, 140),
        "sma_fast": trial.suggest_int("sma_fast", 5, 28),
        "sma_slow": trial.suggest_int("sma_slow", 30, 180),
        "macd_floor": trial.suggest_float("macd_floor", 0.0, 0.45),
        "rsi_mom_low": trial.suggest_float("rsi_mom_low", 35.0, 49.0),
        "rsi_mom_high": trial.suggest_float("rsi_mom_high", 51.0, 65.0),
        "rsi_rev_low": trial.suggest_float("rsi_rev_low", 20.0, 42.0),
        "rsi_rev_high": trial.suggest_float("rsi_rev_high", 58.0, 82.0),
        "stoch_low": trial.suggest_float("stoch_low", 5.0, 35.0),
        "stoch_high": trial.suggest_float("stoch_high", 65.0, 95.0),
        "adx_min": trial.suggest_float("adx_min", 12.0, 34.0),
        "don_len": trial.suggest_int("don_len", 12, 80),
        "bb_len": trial.suggest_int("bb_len", 16, 80),
        "bb_mult": trial.suggest_float("bb_mult", 1.3, 3.0),
        "kc_len": trial.suggest_int("kc_len", 12, 64),
        "kc_mult": trial.suggest_float("kc_mult", 1.0, 3.2),
        "vwap_atr": trial.suggest_float("vwap_atr", 0.15, 2.2),
        "cci_len": trial.suggest_int("cci_len", 10, 60),
        "cci_edge": trial.suggest_float("cci_edge", 70.0, 220.0),
        "will_len": trial.suggest_int("will_len", 8, 42),
        "will_low": trial.suggest_float("will_low", -95.0, -70.0),
        "will_high": trial.suggest_float("will_high", -30.0, -5.0),
        "roc_len": trial.suggest_int("roc_len", 2, 32),
        "roc_edge": trial.suggest_float("roc_edge", 0.02, 1.2),
        "atr_rel_high": trial.suggest_float("atr_rel_high", 0.9, 1.9),
        "impulse_edge": trial.suggest_float("impulse_edge", 0.4, 3.5),
        "obv_len": trial.suggest_int("obv_len", 12, 80),
        "obv_edge": trial.suggest_float("obv_edge", 0.04, 2.0),
        "mfi_len": trial.suggest_int("mfi_len", 8, 40),
        "mfi_low": trial.suggest_float("mfi_low", 15.0, 40.0),
        "mfi_high": trial.suggest_float("mfi_high", 60.0, 85.0),
        "cmf_len": trial.suggest_int("cmf_len", 10, 60),
        "cmf_edge": trial.suggest_float("cmf_edge", 0.02, 0.35),
        "aroon_len": trial.suggest_int("aroon_len", 10, 60),
        "aroon_edge": trial.suggest_float("aroon_edge", 20.0, 75.0),
        "z_edge": trial.suggest_float("z_edge", 0.7, 2.6),
        "lr_len": trial.suggest_int("lr_len", 12, 96),
        "lr_edge": trial.suggest_float("lr_edge", 0.01, 0.4),
        "kin_len": trial.suggest_int("kin_len", 2, 12),
        "vel_edge": trial.suggest_float("vel_edge", 0.3, 2.5),
        "accel_edge": trial.suggest_float("accel_edge", -0.4, 1.8),
        "jerk_edge": trial.suggest_float("jerk_edge", -0.4, 2.0),
        "pvm_edge": trial.suggest_float("pvm_edge", 0.4, 3.5),
        "long_threshold": trial.suggest_float("long_threshold", 1.2, 8.0),
        "short_threshold": trial.suggest_float("short_threshold", 1.2, 8.0),
        "stop_atr": trial.suggest_float("stop_atr", 0.8, 6.5),
        "target_atr": trial.suggest_float("target_atr", 0.6, 8.0),
        "trail_atr": trial.suggest_float("trail_atr", 1.0, 9.0),
        "max_hold": trial.suggest_int("max_hold", 8, 96),
        "min_hold": trial.suggest_int("min_hold", 0, 12),
        "cooldown": trial.suggest_int("cooldown", 0, 18),
        "ny_start": trial.suggest_int("ny_start", 0, 16),
        "ny_end": trial.suggest_int("ny_end", 7, 23),
        "adx_gate": trial.suggest_float("adx_gate", 0.0, 38.0),
        "use_h4_gate": trial.suggest_categorical("use_h4_gate", [True, False]),
        "use_daily_gate": trial.suggest_categorical("use_daily_gate", [True, False]),
    }
    for name in INDICATOR_LIBRARY:
        enabled = trial.suggest_categorical(f"use_{name}", [True, False, False])
        params[f"w_{name}"] = trial.suggest_float(f"w_{name}", 0.2, 2.5) if enabled else 0.0
    return params


def in_session(hour, start, end):
    return start <= hour <= end if start <= end else hour >= start or hour <= end


def backtest_ensemble(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    if params["ema_fast"] >= params["ema_slow"] or params["sma_fast"] >= params["sma_slow"] or params["min_hold"] >= params["max_hold"]:
        return EnsembleResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 0, 0, 1.0, 365.0, 1.0)
    signals = indicator_signals(feat, params)
    score = np.zeros(len(feat), dtype=float)
    active_count = 0
    for name in INDICATOR_LIBRARY:
        weight = params.get(f"w_{name}", 0.0)
        if weight:
            score += weight * signals[name]
            active_count += 1
    if active_count < 4:
        return EnsembleResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 0, 0, 1.0, 365.0, 1.0)

    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    adxv = feat["adx"].to_numpy(float)
    ny_hour = feat["ny_hour"].to_numpy(int)
    h4_signal = np.where(feat["h4_ema_fast"].to_numpy(float) > feat["h4_ema_slow"].to_numpy(float), 1, -1)
    day_signal = np.where(feat["daily_ema_fast"].to_numpy(float) > feat["daily_ema_slow"].to_numpy(float), 1, -1)

    pos = 0
    entry = 0.0
    entry_high = 0.0
    entry_low = 0.0
    bars_held = 0
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    best_equity = INITIAL_CAPITAL
    best_equity_i = max(start, 300)
    max_stagnation_bars = 0
    max_dd = 0.0
    exposed = 0
    long_trades = short_trades = 0
    pnls = []
    trade_indices = []

    for i in range(max(start, 300), end):
        if pos:
            exposed += 1
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            exit_price = None
            if pos == 1:
                stop = max(entry - params["stop_atr"] * atrv[i], entry_high - params["trail_atr"] * atrv[i])
                target = entry + params["target_atr"] * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif bars_held >= params["max_hold"]:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and score[i] <= 0:
                    exit_price = close[i]
            else:
                stop = min(entry + params["stop_atr"] * atrv[i], entry_low + params["trail_atr"] * atrv[i])
                target = entry - params["target_atr"] * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif bars_held >= params["max_hold"]:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and score[i] >= 0:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                trade_indices.append(i)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                if equity > best_equity:
                    best_equity = equity
                    best_equity_i = i
                else:
                    max_stagnation_bars = max(max_stagnation_bars, i - best_equity_i)
                pos = 0
                bars_held = 0
                last_trade = i

        if pos == 0 and i - last_trade >= params["cooldown"]:
            if not in_session(ny_hour[i], params["ny_start"], params["ny_end"]):
                continue
            if params["adx_gate"] and adxv[i] < params["adx_gate"]:
                continue
            long_gate = (not params["use_h4_gate"] or h4_signal[i] == 1) and (not params["use_daily_gate"] or day_signal[i] == 1)
            short_gate = (not params["use_h4_gate"] or h4_signal[i] == -1) and (not params["use_daily_gate"] or day_signal[i] == -1)
            if score[i] >= params["long_threshold"] and long_gate:
                pos = 1
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                bars_held = 0
                long_trades += 1
            elif score[i] <= -params["short_threshold"] and short_gate:
                pos = -1
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                bars_held = 0
                short_trades += 1

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        pnls.append(pnl)
        trade_indices.append(end - 1)

    if not pnls:
        return EnsembleResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 0, 0, 1.0, 365.0, 1.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    trade_dates = feat.index[trade_indices]
    months = {}
    for date, pnl in zip(trade_dates, pnls):
        key = date.strftime("%Y-%m")
        months[key] = months.get(key, 0.0) + pnl
    positive_total = sum(value for value in months.values() if value > 0)
    net = equity - INITIAL_CAPITAL
    return EnsembleResult(
        net,
        net / INITIAL_CAPITAL * 100.0,
        len(pnls),
        len(wins) / len(pnls) * 100.0,
        sum(wins) / (abs(sum(losses)) or 1e-9),
        max_dd,
        net / len(pnls),
        exposed / max(1, end - max(start, 300)) * 100.0,
        long_trades,
        short_trades,
        sum(1 for value in months.values() if value > 0),
        len(months),
        max([value for value in months.values() if value > 0] or [0.0]) / (positive_total or 1e-9),
        max_stagnation_bars * 15.0 / 60.0 / 24.0,
        max(wins) / (sum(wins) or 1e-9) if wins else 1.0,
    )


def objective_factory(feat, min_trades):
    split = int(len(feat) * 0.72)
    split = max(1000, min(split, len(feat) - 1000))
    buy_hold_train = buy_hold_pnl(feat, 300, split)
    buy_hold_val = buy_hold_pnl(feat, split, len(feat))

    def objective(trial):
        params = suggest_params(trial)
        train = backtest_ensemble(feat, params, 300, split)
        val = backtest_ensemble(feat, params, split, len(feat))
        if train.n_trades < min_trades or val.n_trades < max(10, min_trades // 4):
            raise optuna.TrialPruned()
        if train.max_drawdown > 18.0 or val.max_drawdown > 18.0 or val.net_profit <= 0:
            raise optuna.TrialPruned()
        score = (
            val.total_return * 1.6
            + (val.net_profit - buy_hold_val) / INITIAL_CAPITAL * 100.0 * 1.2
            + train.total_return * 0.25
            + min(val.profit_factor, 3.0) * 24.0
            + val.positive_months / max(1, val.active_months) * 45.0
            - val.max_drawdown * 2.7
            - max(0.0, val.top_month_share - 0.55) * 100.0
            - max(0.0, val.max_winner_share - 0.16) * 140.0
            - max(0.0, train.net_profit - buy_hold_train) / INITIAL_CAPITAL * 10.0
        )
        trial.set_user_attr("train", asdict(train))
        trial.set_user_attr("validation", asdict(val))
        return score

    return objective


def run_worker(worker_id, data_path, trials, seed, min_trades):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_base_features(load_json(data_path))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(180, max(40, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(180, max(40, trials // 5))))
    study.optimize(objective_factory(feat, min_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    complete = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not complete:
        return None
    best = study.best_trial
    params = dict(best.params)
    full = backtest_ensemble(feat, params, 300, len(feat))
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {
            "train": best.user_attrs["train"],
            "validation": best.user_attrs["validation"],
            "full": asdict(full),
        },
        "active_indicators": [name for name in INDICATOR_LIBRARY if params.get(f"w_{name}", 0.0) > 0.0],
        "trials": len(study.trials),
        "complete_trials": len(complete),
    }


def write_markdown(path, payload):
    lines = [
        "# CL1! 15m Public Indicator Ensemble Search",
        "",
        "This search uses a vetted library of standard public-domain indicator formulas rather than copying protected TradingView scripts.",
        "",
        f"- Requested trials: `{payload['requested_trials']}`",
        f"- Completed trials: `{payload['completed_trials']}`",
        f"- Workers: `{payload['workers']}`",
        f"- Buy-and-hold full-range PnL: `${payload['buy_hold']:,.2f}`",
        "",
        "## Indicator Library",
        "",
    ]
    lines.append(", ".join(f"`{name}`" for name in INDICATOR_LIBRARY))
    lines.extend(["", "## Top Candidates", "", "| Rank | Net | PF | DD | Trades | Active Indicators |", "|---:|---:|---:|---:|---:|---|"])
    for rank, item in enumerate(payload["top10"], start=1):
        full = item["metrics"]["full"]
        active = ", ".join(item["active_indicators"])
        lines.append(f"| {rank} | ${full['net_profit']:,.2f} | {full['profit_factor']:.3f} | {full['max_drawdown']:.2f}% | {full['n_trades']} | {active} |")
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=8192)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2026051841)
    parser.add_argument("--min-trades", type=int, default=80)
    parser.add_argument("--out", default="reports/cl_15m_indicator_ensemble_search.json")
    args = parser.parse_args()

    counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(counts)))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_worker, task_id, args.data, counts[task_id], args.seed, args.min_trades)
            for task_id in range(len(counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker": result["worker_id"],
                "score": result["score"],
                "net": full["net_profit"],
                "pf": full["profit_factor"],
                "dd": full["max_drawdown"],
                "trades": full["n_trades"],
                "active": result["active_indicators"],
            }), flush=True)

    if not results:
        raise SystemExit("No ensemble candidates passed validation constraints.")
    feat = build_base_features(load_json(args.data))
    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": sum(item["complete_trials"] for item in results),
        "workers": workers,
        "indicator_library": INDICATOR_LIBRARY,
        "buy_hold": buy_hold_pnl(feat, 300, len(feat)),
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2))
    write_markdown(out.with_suffix(".md"), payload)
    print(out)
    print(out.with_suffix(".md"))


if __name__ == "__main__":
    main()
