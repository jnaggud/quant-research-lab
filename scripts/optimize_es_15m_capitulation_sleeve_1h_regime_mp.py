#!/usr/bin/env python3
import argparse
import json
import os
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from scipy.signal import find_peaks

from optimize_15m_mtf_reversal import atr, ema, macd_hist, resample_ohlcv, rsi, stoch
from optimize_cl_15m_active_router_mp import adx

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)

POINT_VALUE = 50.0
COMMISSION_PER_SIDE = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.25
INITIAL_CAPITAL = 50_000.0

CORE_PARAMS = {
    "h1_fast": 11,
    "h1_slow": 27,
    "d_fast": 9,
    "d_slow": 80,
    "regime_mode": "h1",
    "local_filter": "none",
    "stop_atr": 4.084981554127161,
    "trail_atr": 7.393095335737284,
    "cooldown": 21,
    "long_rsi_min": 40.33802129365303,
    "short_rsi_max": 59.05022189927175,
    "macd_floor": -3.1231746759752084,
    "vol_mult": 0.9293673650029148,
    "use_momentum_exit": True,
    "long_exit_rsi": 39.66129925548556,
    "short_exit_rsi": 43.043945472221175,
    "long_exit_regime": -1,
    "short_exit_regime": 0,
    "allow_short": True,
}

BASELINE = {
    "name": "JD ES 15m Regime Carry 64k 20260508",
    "net_profit": 49402.39747955333,
    "profit_factor": 1.5765576048387717,
    "max_drawdown": 17.7946294395624,
    "trades": 235,
}


@dataclass
class Result:
    net_profit: float
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe: float
    sortino: float
    calmar: float
    buy_hold_net: float
    excess_net: float
    excess_return: float
    avg_trade: float
    exposure: float
    long_trades: int
    short_trades: int
    core_trades: int
    cap_trades: int
    core_net: float
    cap_net: float
    cap_win_rate: float
    cap_truth_hits: int
    cap_truth_precision: float
    cap_truth_coverage: float
    positive_months: int
    active_months: int
    pre_march_net: float
    top_month_share: float
    max_stagnation_days: float
    max_winner_share: float


def load_bars(path):
    payload = json.loads(Path(path).read_text())
    bars = payload.get("bars")
    if bars is None:
        result = payload.get("result", {})
        bars = result.get("bars") if isinstance(result, dict) else result
    df = pd.DataFrame(bars)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def build_features(df):
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
    session = out.index.floor("1D")
    pv = typical * out["volume"]
    out["vwap"] = pv.groupby(session).cumsum() / out["volume"].replace(0, np.nan).groupby(session).cumsum()
    out["vwap"] = out["vwap"].ffill().fillna(out["close"])
    day = resample_ohlcv(out, "1D")
    out["prev_day_high"] = day["high"].shift(1).reindex(out.index, method="ffill").fillna(out["high"])
    out["prev_day_low"] = day["low"].shift(1).reindex(out.index, method="ffill").fillna(out["low"])
    out["atr_rel"] = out["atr"] / out["atr"].rolling(192, min_periods=20).mean()
    out["vol_rank"] = out["volume"].rolling(96, min_periods=10).rank(pct=True)
    out["vwap_dist_atr"] = (out["close"] - out["vwap"]) / out["atr"].replace(0, np.nan)
    out["adx_slope_8"] = out["adx"] - out["adx"].shift(8)
    ret1 = out["close"].pct_change()
    out["ret_z"] = (ret1 - ret1.rolling(96, min_periods=20).mean()) / ret1.rolling(96, min_periods=20).std(ddof=0)
    out["range_pos"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    out["low_24"] = out["low"].rolling(24, min_periods=1).min().shift(1)
    out["low_96"] = out["low"].rolling(96, min_periods=1).min().shift(1)
    out["velocity"] = out["close"].diff()
    out["acceleration"] = out["velocity"].diff()
    out["jerk"] = out["acceleration"].diff()
    pv_momentum = (out["velocity"] * out["volume"]).rolling(4, min_periods=1).sum()
    out["pv_z"] = pv_momentum / pv_momentum.rolling(96, min_periods=20).std(ddof=0)
    out["climax_volume"] = out["volume"] / out["volume"].rolling(96, min_periods=20).mean()
    out["ny_hour"] = out.index.tz_convert("America/New_York").hour
    return out.ffill().fillna(0.0)


def mark_truth(feat, prominence_pct=1.0, distance=5, window=4):
    prominence = feat["close"].median() * prominence_pct / 100.0
    peaks, _ = find_peaks(feat["high"].to_numpy(float), prominence=prominence, distance=distance)
    valleys, _ = find_peaks(-feat["low"].to_numpy(float), prominence=prominence, distance=distance)
    truth_valley = np.zeros(len(feat), dtype=bool)
    truth_window = np.zeros(len(feat), dtype=bool)
    truth_peak = np.zeros(len(feat), dtype=bool)
    truth_valley[valleys] = True
    truth_peak[peaks] = True
    for idx in valleys:
        truth_window[idx:min(len(feat), idx + window + 1)] = True
    return truth_peak, truth_valley, truth_window, {
        "prominence_pct": prominence_pct,
        "distance": distance,
        "absolute_prominence": float(prominence),
        "peaks": int(len(peaks)),
        "valleys": int(len(valleys)),
    }


def trade_pnl(entry, exit_price, pos):
    if pos == 1:
        slipped_entry = entry + SLIPPAGE_TICKS * TICK_SIZE
        slipped_exit = exit_price - SLIPPAGE_TICKS * TICK_SIZE
        points = slipped_exit - slipped_entry
    else:
        slipped_entry = entry - SLIPPAGE_TICKS * TICK_SIZE
        slipped_exit = exit_price + SLIPPAGE_TICKS * TICK_SIZE
        points = slipped_entry - slipped_exit
    return points * POINT_VALUE - 2.0 * COMMISSION_PER_SIDE


def risk_adjusted_metrics(monthly, net, max_dd):
    returns = monthly / INITIAL_CAPITAL
    if len(returns) < 2:
        sharpe = 0.0
        sortino = 0.0
    else:
        std = float(returns.std(ddof=0))
        downside = returns[returns < 0.0]
        downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
        mean_return = float(returns.mean())
        sharpe = mean_return / std * np.sqrt(12.0) if std > 1e-12 else (10.0 if mean_return > 0 else 0.0)
        sortino = mean_return / downside_std * np.sqrt(12.0) if downside_std > 1e-12 else (10.0 if mean_return > 0 else 0.0)
    calmar = (net / INITIAL_CAPITAL * 100.0) / max(max_dd, 1e-9)
    return float(np.clip(sharpe, -10.0, 10.0)), float(np.clip(sortino, -10.0, 10.0)), float(np.clip(calmar, -10.0, 10.0))


def make_regime(feat, params):
    h1 = resample_ohlcv(feat, "60min")
    day = resample_ohlcv(feat, "1D")
    h1_fast = ema(h1["close"], params["h1_fast"])
    h1_slow = ema(h1["close"], params["h1_slow"])
    day_fast = ema(day["close"], params["d_fast"])
    day_slow = ema(day["close"], params["d_slow"])
    h1_signal = pd.Series(np.where(h1_fast > h1_slow, 1, -1), index=h1.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(np.where(day_fast > day_slow, 1, -1), index=day.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    if params["regime_mode"] == "both":
        regime = h1_signal.where(h1_signal == day_signal, 0).astype(int)
    elif params["regime_mode"] == "h1":
        regime = h1_signal.astype(int)
    else:
        regime = h1_signal.where(day_signal != -h1_signal, 0).astype(int)
    return regime.to_numpy(int), h1_signal.to_numpy(int), day_signal.to_numpy(int)


def local_filters(params, close, ema8, ema21, ema55, ema144, i):
    if params["local_filter"] == "ema21":
        return close[i] > ema21[i], close[i] < ema21[i]
    if params["local_filter"] == "ema55":
        return close[i] > ema55[i], close[i] < ema55[i]
    if params["local_filter"] == "stack":
        return ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i], ema8[i] < ema21[i] < ema55[i] and close[i] < ema8[i]
    if params["local_filter"] == "ema144":
        return close[i] > ema144[i], close[i] < ema144[i]
    return True, True


def backtest(feat, cap_params=None, start=300, end=None, truth=None):
    if end is None:
        end = len(feat)
    p = dict(CORE_PARAMS)
    if cap_params:
        p.update(cap_params)
    truth_peak, truth_valley, truth_window, truth_meta = truth or mark_truth(feat)
    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    volume = feat["volume"].to_numpy(float)
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
    vol_sma = feat["vol_sma"].to_numpy(float)
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
    regime, h1_signal, daily_signal = make_regime(feat, p)

    pos = kind = 0
    entry = entry_high = entry_low = 0.0
    bars_held = 0
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    best_equity = INITIAL_CAPITAL
    best_i = max(start, 300)
    max_stagnation_bars = 0
    max_dd = 0.0
    exposed = long_trades = short_trades = core_trades = cap_trades = cap_truth_hits = 0
    core_net = cap_net = 0.0
    cap_pnls = []
    pnls = []
    trade_indices = []

    for i in range(max(start, 300), end):
        exited_this_bar = False
        if pos:
            exposed += 1
            bars_held += 1
            exit_price = None
            if kind == 1:
                if pos == 1:
                    stop = max(entry - p["stop_atr"] * atrv[i], entry_high - p["trail_atr"] * atrv[i])
                    if low[i] <= stop:
                        exit_price = stop
                    elif regime[i] <= p["long_exit_regime"]:
                        exit_price = close[i]
                    elif p["use_momentum_exit"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < p["long_exit_rsi"]:
                        exit_price = close[i]
                else:
                    stop = min(entry + p["stop_atr"] * atrv[i], entry_low + p["trail_atr"] * atrv[i])
                    if high[i] >= stop:
                        exit_price = stop
                    elif regime[i] >= p["short_exit_regime"]:
                        exit_price = close[i]
                    elif p["use_momentum_exit"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > p["short_exit_rsi"]:
                        exit_price = close[i]
            else:
                hard_stop = entry - p["cap_stop_atr"] * atrv[i]
                trail_stop = entry_high - p["cap_trail_atr"] * atrv[i]
                if close[i] < close[i - 1]:
                    trail_stop -= max(0.0, trail_stop - hard_stop) * p.get("cap_trail_relax_pct", 0.0)
                stop = max(hard_stop, trail_stop)
                target = entry + p["cap_target_atr"] * atrv[i]
                hit_stop = low[i] <= stop
                hit_target = high[i] >= target
                if hit_stop:
                    exit_price = stop
                elif hit_target:
                    exit_price = target
                elif bars_held >= p["cap_max_hold"]:
                    exit_price = close[i]
                elif bars_held >= p["cap_min_hold"] and (
                    close[i] >= vwap[i] + p["cap_exit_vwap_atr"] * atrv[i]
                    or rsi_v[i] >= p["cap_exit_rsi"]
                    or (p["cap_exit_on_peak"] and truth_peak[i])
                    or (p["cap_exit_on_momentum_peak"] and macd_v[i] < macd_v[i - 1] and range_pos[i] <= p["cap_exit_range_pos"])
                ):
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                trade_indices.append(i)
                if kind == 1:
                    core_net += pnl
                else:
                    cap_net += pnl
                    cap_pnls.append(pnl)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                if equity > best_equity:
                    best_equity = equity
                    best_i = i
                else:
                    max_stagnation_bars = max(max_stagnation_bars, i - best_i)
                pos = kind = 0
                bars_held = 0
                last_trade = i
                exited_this_bar = True
            else:
                entry_high = max(entry_high, high[i])
                entry_low = min(entry_low, low[i])

        if pos == 0 and not exited_this_bar:
            if True:
                core_ready = i - last_trade >= p["cooldown"]
                cap_ready = i - last_trade >= p["cap_cooldown"]
                long_filter, short_filter = local_filters(p, close, ema8, ema21, ema55, ema144, i)
                vol_ok = volume[i] >= p["vol_mult"] * vol_sma[i]
                core_long = core_ready and regime[i] == 1 and long_filter and rsi_v[i] >= p["long_rsi_min"] and macd_v[i] >= p["macd_floor"] and vol_ok
                core_short = core_ready and p["allow_short"] and regime[i] == -1 and short_filter and rsi_v[i] <= p["short_rsi_max"] and macd_v[i] <= -p["macd_floor"] and vol_ok
                k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
                cap_regime_ok = (
                    p["cap_regime"] == "any"
                    or (p["cap_regime"] == "daily_not_bear" and daily_signal[i] != -1)
                    or (p["cap_regime"] == "h1_up" and h1_signal[i] == 1)
                    or (p["cap_regime"] == "either_up" and (h1_signal[i] == 1 or daily_signal[i] == 1))
                )
                cap_deep = (
                    vwap_dist[i] <= -p["cap_vwap_dist_atr"]
                    or close[i] <= bb_lower[i] + p["cap_bb_atr"] * atrv[i]
                    or close[i] <= prev_low[i] + p["cap_prev_low_atr"] * atrv[i]
                    or low[i] <= low_24[i] - p["cap_low_break_atr"] * atrv[i]
                    or low[i] <= low_96[i] + p["cap_low96_atr"] * atrv[i]
                )
                cap_exhaustion = (
                    rsi_v[i] <= p["cap_rsi_max"]
                    and stoch_k[i] <= p["cap_stoch_max"]
                    and ret_z[i] <= -p["cap_ret_z"]
                    and range_pos[i] >= p["cap_reclaim_pos"]
                    and climax_volume[i] >= p["cap_volume_mult"]
                    and pv_z[i] <= p["cap_pv_z_max"]
                    and atr_rel[i] >= p["cap_atr_rel_min"]
                    and atr_rel[i] <= p["cap_atr_rel_max"]
                    and adxv[i] >= p["cap_adx_min"]
                    and adxv[i] <= p["cap_adx_max"]
                )
                cap_reversal = k_cross_up or close[i] > close[i - 1] or macd_v[i] > macd_v[i - 1]
                cap_long = p["use_cap"] and cap_ready and cap_regime_ok and cap_deep and cap_exhaustion and (not p["cap_require_reversal"] or cap_reversal)
                if p["cap_priority"] and cap_long:
                    pos, kind, entry = 1, 2, close[i]
                    cap_trades += 1
                    long_trades += 1
                    cap_truth_hits += int(truth_window[i])
                elif core_long:
                    pos, kind, entry = 1, 1, close[i]
                    core_trades += 1
                    long_trades += 1
                elif core_short:
                    pos, kind, entry = -1, 1, close[i]
                    core_trades += 1
                    short_trades += 1
                elif cap_long:
                    pos, kind, entry = 1, 2, close[i]
                    cap_trades += 1
                    long_trades += 1
                    cap_truth_hits += int(truth_window[i])
                if pos:
                    entry_high, entry_low = high[i], low[i]
                    bars_held = 0

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        pnls.append(pnl)
        trade_indices.append(end - 1)
        if kind == 1:
            core_net += pnl
        else:
            cap_net += pnl
            cap_pnls.append(pnl)

    test_start = max(start, 300)
    buy_hold_net = (close[end - 1] - close[test_start]) * POINT_VALUE
    if not pnls:
        return Result(
            net_profit=-INITIAL_CAPITAL, total_return=-100.0, n_trades=0, win_rate=0.0,
            profit_factor=0.0, max_drawdown=100.0, sharpe=-10.0, sortino=-10.0, calmar=-10.0,
            buy_hold_net=buy_hold_net, excess_net=-INITIAL_CAPITAL - buy_hold_net, excess_return=-100.0 - buy_hold_net / INITIAL_CAPITAL * 100.0,
            avg_trade=0.0, exposure=0.0, long_trades=0, short_trades=0, core_trades=0, cap_trades=0,
            core_net=0.0, cap_net=0.0, cap_win_rate=0.0, cap_truth_hits=0, cap_truth_precision=0.0,
            cap_truth_coverage=0.0, positive_months=0, active_months=0, pre_march_net=0.0,
            top_month_share=1.0, max_stagnation_days=999.0, max_winner_share=1.0,
        )
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    monthly = pd.Series(pnls, index=feat.index[trade_indices] if trade_indices else feat.index[:len(pnls)]).groupby(pd.Grouper(freq="ME")).sum()
    active_months = int((monthly != 0).sum())
    positive_months = int((monthly > 0).sum())
    net = equity - INITIAL_CAPITAL
    total_return = net / INITIAL_CAPITAL * 100.0
    buy_hold_return = buy_hold_net / INITIAL_CAPITAL * 100.0
    sharpe, sortino, calmar = risk_adjusted_metrics(monthly, net, max_dd)
    return Result(
        net_profit=net, total_return=total_return, n_trades=len(pnls), win_rate=len(wins) / len(pnls) * 100.0,
        profit_factor=sum(wins) / (abs(sum(losses)) or 1e-9), max_drawdown=max_dd,
        sharpe=sharpe, sortino=sortino, calmar=calmar, buy_hold_net=buy_hold_net,
        excess_net=net - buy_hold_net, excess_return=total_return - buy_hold_return,
        avg_trade=net / len(pnls), exposure=exposed / max(1, end - test_start) * 100.0,
        long_trades=long_trades, short_trades=short_trades, core_trades=core_trades, cap_trades=cap_trades,
        core_net=core_net, cap_net=cap_net,
        cap_win_rate=len([x for x in cap_pnls if x > 0]) / max(1, len(cap_pnls)) * 100.0,
        cap_truth_hits=cap_truth_hits,
        cap_truth_precision=cap_truth_hits / max(1, cap_trades) * 100.0,
        cap_truth_coverage=cap_truth_hits / max(1, int(truth_valley.sum())) * 100.0,
        positive_months=positive_months, active_months=active_months,
        pre_march_net=float(monthly[monthly.index < pd.Timestamp("2026-03-01", tz="UTC")].sum()) if len(monthly) else 0.0,
        top_month_share=float(monthly.max() / max(abs(net), 1.0)) if len(monthly) else 1.0,
        max_stagnation_days=max_stagnation_bars * 15.0 / 60.0 / 24.0,
        max_winner_share=max(wins) / max(abs(net), 1.0) if wins else 1.0,
    )


def suggest_core(trial):
    return {
        "h1_fast": trial.suggest_int("h1_fast", 3, 34),
        "h1_slow": trial.suggest_int("h1_slow", 8, 96),
        "d_fast": trial.suggest_int("d_fast", 3, 30),
        "d_slow": trial.suggest_int("d_slow", 20, 160),
        "regime_mode": trial.suggest_categorical("regime_mode", ["both", "h1", "h1_daily_veto"]),
        "local_filter": trial.suggest_categorical("local_filter", ["none", "ema21", "ema55", "stack", "ema144"]),
        "stop_atr": trial.suggest_float("stop_atr", 0.8, 6.5),
        "trail_atr": trial.suggest_float("trail_atr", 0.8, 10.0),
        "cooldown": trial.suggest_int("cooldown", 0, 24),
        "long_rsi_min": trial.suggest_float("long_rsi_min", 24.0, 62.0),
        "short_rsi_max": trial.suggest_float("short_rsi_max", 38.0, 76.0),
        "macd_floor": trial.suggest_float("macd_floor", -8.0, 2.0),
        "vol_mult": trial.suggest_float("vol_mult", 0.15, 1.75),
        "use_momentum_exit": trial.suggest_categorical("use_momentum_exit", [True, False]),
        "long_exit_rsi": trial.suggest_float("long_exit_rsi", 24.0, 70.0),
        "short_exit_rsi": trial.suggest_float("short_exit_rsi", 30.0, 78.0),
        "long_exit_regime": trial.suggest_int("long_exit_regime", -1, 0),
        "short_exit_regime": trial.suggest_int("short_exit_regime", 0, 1),
        "allow_short": trial.suggest_categorical("allow_short", [True, False]),
    }


def disabled_cap_params():
    return {
        "cap_regime": "any",
        "cap_priority": False,
        "cap_adx_min": 0.0,
        "cap_adx_max": 100.0,
        "cap_atr_rel_min": 0.0,
        "cap_atr_rel_max": 10.0,
        "cap_vwap_dist_atr": 0.0,
        "cap_bb_atr": 0.0,
        "cap_prev_low_atr": 0.0,
        "cap_low_break_atr": 0.0,
        "cap_low96_atr": 0.0,
        "cap_rsi_max": 100.0,
        "cap_stoch_max": 100.0,
        "cap_ret_z": 0.0,
        "cap_reclaim_pos": 0.0,
        "cap_volume_mult": 0.0,
        "cap_pv_z_max": 10.0,
        "cap_require_reversal": False,
        "cap_stop_atr": 1.0,
        "cap_target_atr": 1.0,
        "cap_trail_atr": 1.0,
        "cap_trail_relax_pct": 0.0,
        "cap_exit_vwap_atr": 0.0,
        "cap_exit_rsi": 100.0,
        "cap_exit_range_pos": 1.0,
        "cap_exit_on_peak": False,
        "cap_exit_on_momentum_peak": False,
        "cap_cooldown": 0,
        "cap_min_hold": 0,
        "cap_max_hold": 1,
        "use_cap": False,
    }


def suggest(trial, optimize_core=False, disable_cap=False):
    params = suggest_core(trial) if optimize_core else {}
    if disable_cap:
        params.update(disabled_cap_params())
        return params
    params.update({
        "cap_regime": trial.suggest_categorical("cap_regime", ["any", "daily_not_bear", "h1_up", "either_up"]),
        "cap_priority": trial.suggest_categorical("cap_priority", [True, False]),
        "cap_adx_min": trial.suggest_float("cap_adx_min", 0.0, 35.0),
        "cap_adx_max": trial.suggest_float("cap_adx_max", 15.0, 85.0),
        "cap_atr_rel_min": trial.suggest_float("cap_atr_rel_min", 0.1, 1.6),
        "cap_atr_rel_max": trial.suggest_float("cap_atr_rel_max", 0.8, 5.0),
        "cap_vwap_dist_atr": trial.suggest_float("cap_vwap_dist_atr", -0.25, 5.5),
        "cap_bb_atr": trial.suggest_float("cap_bb_atr", -2.5, 2.5),
        "cap_prev_low_atr": trial.suggest_float("cap_prev_low_atr", -3.0, 3.0),
        "cap_low_break_atr": trial.suggest_float("cap_low_break_atr", -3.0, 3.0),
        "cap_low96_atr": trial.suggest_float("cap_low96_atr", -3.0, 3.0),
        "cap_rsi_max": trial.suggest_float("cap_rsi_max", 15.0, 65.0),
        "cap_stoch_max": trial.suggest_float("cap_stoch_max", 3.0, 70.0),
        "cap_ret_z": trial.suggest_float("cap_ret_z", -0.5, 3.8),
        "cap_reclaim_pos": trial.suggest_float("cap_reclaim_pos", 0.0, 0.95),
        "cap_volume_mult": trial.suggest_float("cap_volume_mult", 0.1, 4.0),
        "cap_pv_z_max": trial.suggest_float("cap_pv_z_max", -3.5, 2.5),
        "cap_require_reversal": trial.suggest_categorical("cap_require_reversal", [True, False]),
        "cap_stop_atr": trial.suggest_float("cap_stop_atr", 0.3, 7.5),
        "cap_target_atr": trial.suggest_float("cap_target_atr", 0.25, 11.0),
        "cap_trail_atr": trial.suggest_float("cap_trail_atr", 0.25, 9.5),
        "cap_trail_relax_pct": trial.suggest_float("cap_trail_relax_pct", 0.0, 0.9),
        "cap_exit_vwap_atr": trial.suggest_float("cap_exit_vwap_atr", -1.5, 2.0),
        "cap_exit_rsi": trial.suggest_float("cap_exit_rsi", 34.0, 84.0),
        "cap_exit_range_pos": trial.suggest_float("cap_exit_range_pos", 0.0, 0.95),
        "cap_exit_on_peak": trial.suggest_categorical("cap_exit_on_peak", [True, False]),
        "cap_exit_on_momentum_peak": trial.suggest_categorical("cap_exit_on_momentum_peak", [True, False]),
        "cap_cooldown": trial.suggest_int("cap_cooldown", 0, 24),
        "cap_min_hold": trial.suggest_int("cap_min_hold", 0, 16),
        "cap_max_hold": trial.suggest_int("cap_max_hold", 4, 120),
        "use_cap": True,
    })
    return params


def objective_factory(feat, truth, min_cap_trades, min_net, min_excess_net, min_sharpe, min_sortino, min_trades, trade_weight, optimize_core, disable_cap):
    n = len(feat)
    splits = [(300, int(n * 0.25)), (int(n * 0.25), int(n * 0.5)), (int(n * 0.5), int(n * 0.75)), (int(n * 0.75), n)]

    def objective(trial):
        params = suggest(trial, optimize_core, disable_cap)
        if (
            params.get("h1_fast", CORE_PARAMS["h1_fast"]) >= params.get("h1_slow", CORE_PARAMS["h1_slow"])
            or params.get("d_fast", CORE_PARAMS["d_fast"]) >= params.get("d_slow", CORE_PARAMS["d_slow"])
            or params["cap_adx_min"] >= params["cap_adx_max"]
            or params["cap_atr_rel_min"] >= params["cap_atr_rel_max"]
            or params["cap_min_hold"] >= params["cap_max_hold"]
        ):
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n, truth)
        if (
            full.net_profit < min_net
            or full.excess_net < min_excess_net
            or full.sharpe < min_sharpe
            or full.sortino < min_sortino
            or full.cap_trades < min_cap_trades
            or (disable_cap and full.cap_trades != 0)
            or full.n_trades < min_trades
        ):
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, a, b, truth) for a, b in splits]
        min_fold = min(r.net_profit for r in folds)
        min_fold_excess = min(r.excess_net for r in folds)
        avg_fold = float(np.mean([r.net_profit for r in folds]))
        avg_fold_excess = float(np.mean([r.excess_net for r in folds]))
        fold_sharpe = float(np.mean([r.sharpe for r in folds]))
        fold_sortino = float(np.mean([r.sortino for r in folds]))
        score = (
            full.excess_return * 3.0
            + full.total_return * 0.6
            + (full.net_profit - BASELINE["net_profit"]) / INITIAL_CAPITAL * 100.0 * 2.4
            + full.excess_net / INITIAL_CAPITAL * 100.0 * 2.0
            + avg_fold / INITIAL_CAPITAL * 100.0 * 0.8
            + min_fold / INITIAL_CAPITAL * 100.0 * 0.8
            + avg_fold_excess / INITIAL_CAPITAL * 100.0 * 1.2
            + min_fold_excess / INITIAL_CAPITAL * 100.0 * 1.6
            + min(full.profit_factor, 4.0) * 12.0
            + min(full.sharpe, 5.0) * 18.0
            + min(full.sortino, 6.0) * 16.0
            + min(full.calmar, 8.0) * 10.0
            + min(fold_sharpe, 5.0) * 8.0
            + min(fold_sortino, 6.0) * 7.0
            + full.cap_truth_hits * 0.6
            + full.positive_months * 6.0
            + min(full.n_trades, 700) * trade_weight
            - full.max_drawdown * 2.4
            - max(0.0, 1.25 - full.sharpe) * 85.0
            - max(0.0, 1.75 - full.sortino) * 75.0
            - max(0.0, 1.5 - full.calmar) * 60.0
            - max(0.0, -min_fold_excess / INITIAL_CAPITAL * 100.0) * 4.0
            - max(0.0, full.top_month_share - 0.45) * 80.0
            - full.max_winner_share * 45.0
            - full.max_stagnation_days * 0.35
        )
        trial.set_user_attr("full", asdict(full))
        return score

    return objective


def run_worker(worker_id, data_path, trials, seed, min_cap_trades, min_net, min_excess_net, min_sharpe, min_sortino, min_trades, trade_weight, optimize_core, disable_cap):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_bars(data_path))
    truth = mark_truth(feat)
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(160, max(40, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(160, max(40, trials // 5))))
    study.optimize(objective_factory(feat, truth, min_cap_trades, min_net, min_excess_net, min_sharpe, min_sortino, min_trades, trade_weight, optimize_core, disable_cap), n_trials=trials, n_jobs=1, show_progress_bar=False)
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        return {"worker_id": worker_id, "skipped": True, "trials": len(study.trials)}
    best = max(completed, key=lambda t: t.value)
    params = dict(best.params)
    if disable_cap:
        params.update(disabled_cap_params())
    else:
        params["use_cap"] = True
    full = backtest(feat, params, 300, len(feat), truth)
    return {"worker_id": worker_id, "score": best.value, "params": params, "metrics": {"full": asdict(full)}, "truth": truth[3], "trials": len(study.trials)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_es1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026051901)
    parser.add_argument("--min-cap-trades", type=int, default=20)
    parser.add_argument("--min-net", type=float, default=50000.0)
    parser.add_argument("--min-excess-net", type=float, default=5000.0)
    parser.add_argument("--min-sharpe", type=float, default=0.75)
    parser.add_argument("--min-sortino", type=float, default=1.0)
    parser.add_argument("--min-trades", type=int, default=BASELINE["trades"])
    parser.add_argument("--trade-weight", type=float, default=0.0)
    parser.add_argument("--optimize-core", action="store_true")
    parser.add_argument("--disable-cap", action="store_true")
    parser.add_argument("--out", default="reports/es_15m_capitulation_sleeve_1h_regime_16k.json")
    args = parser.parse_args()

    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                run_worker, task_id, args.data, trial_counts[task_id], args.seed,
                args.min_cap_trades, args.min_net, args.min_excess_net, args.min_sharpe, args.min_sortino,
                args.min_trades, args.trade_weight, args.optimize_core, args.disable_cap,
            )
            for task_id in range(len(trial_counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result.get("skipped"):
                print(json.dumps(result), flush=True)
                continue
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker": result["worker_id"], "score": result["score"], "net": full["net_profit"],
                "pf": full["profit_factor"], "dd": full["max_drawdown"], "trades": full["n_trades"],
                "cap_trades": full["cap_trades"], "cap_net": full["cap_net"],
                "buy_hold": full["buy_hold_net"], "excess": full["excess_net"],
                "sharpe": full["sharpe"], "sortino": full["sortino"], "calmar": full["calmar"],
                "pre_march_net": full["pre_march_net"], "stagnation_days": full["max_stagnation_days"],
            }), flush=True)
    if not results:
        raise SystemExit("No completed trials survived pruning")
    raw = load_bars(args.data)
    buy_hold = (raw["close"].iloc[-1] - raw["open"].iloc[0]) * POINT_VALUE
    feat = build_features(raw)
    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "workers": workers,
        "core_params": CORE_PARAMS,
        "truth": mark_truth(feat)[3],
        "baseline": BASELINE,
        "buy_hold": buy_hold,
        "objective": {
            "mode": "risk_adjusted_excess_return",
            "min_excess_net": args.min_excess_net,
            "min_sharpe": args.min_sharpe,
            "min_sortino": args.min_sortino,
            "min_trades": args.min_trades,
            "trade_weight": args.trade_weight,
            "optimize_core": args.optimize_core,
            "disable_cap": args.disable_cap,
            "notes": [
                "Candidates are scored on excess return over buy-and-hold, not absolute P&L alone.",
                "Low Sharpe, Sortino, and Calmar ratios are penalized.",
                "Folds with negative excess return receive an additional penalty.",
                "When trade_weight is positive, higher trade count is rewarded up to 700 trades.",
            ],
        },
        "best": max(results, key=lambda x: x["score"]),
        "top10": sorted(results, key=lambda x: x["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
