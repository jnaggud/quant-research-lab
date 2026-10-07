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

from optimize_15m_mtf_reversal import load_json, resample_ohlcv
from optimize_cl_15m_active_router_mp import (
    INITIAL_CAPITAL,
    build_features,
    buy_hold_pnl,
    directional_regime,
    make_regimes,
    trade_pnl,
)
from optimize_cl_15m_hybrid_sleeve_mp import CORE_PARAMS, add_research_features

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


BASE_SLEEVE = {
    "allow_sleeve_longs": True,
    "allow_sleeve_shorts": True,
    "sleeve_adx_max": 24.111181455078224,
    "sleeve_adx_slope_max": 2.369942613878797,
    "atr_rel_min": 0.8130426484809107,
    "atr_rel_max": 1.1838094620099848,
    "vol_rank_min": 0.20068031699404018,
    "vol_rank_max": 0.9213924280365459,
    "vwap_dist_atr": 0.5432991795348431,
    "prev_level_atr": 1.8717803994832265,
    "bb_atr": 1.0289185256346374,
    "sleeve_long_rsi": 42.52113131638666,
    "sleeve_short_rsi": 74.21737222162857,
    "sleeve_stoch": 33.05609732630522,
    "sleeve_stop_atr": 4.170279319035829,
    "sleeve_target_atr": 2.198406120324361,
    "sleeve_trail_atr": 5.840965368951672,
    "sleeve_exit_vwap_atr": 0.3045559114252387,
    "sleeve_cooldown": 5,
    "sleeve_min_hold": 8,
    "sleeve_max_hold": 39,
    "ny_start_hour": 0,
    "ny_end_hour": 18,
    "use_sleeve": True,
}


@dataclass
class CapResult:
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
    core_trades: int
    sleeve_trades: int
    cap_trades: int
    core_net: float
    sleeve_net: float
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


def add_cap_features(feat):
    out = add_research_features(feat)
    out["ret1"] = out["close"].pct_change().fillna(0.0)
    out["price_velocity"] = out["close"].diff().fillna(0.0)
    out["price_acceleration"] = out["price_velocity"].diff().fillna(0.0)
    out["price_jerk"] = out["price_acceleration"].diff().fillna(0.0)
    out["ret_z"] = (out["ret1"] - out["ret1"].rolling(96, min_periods=20).mean()) / out["ret1"].rolling(96, min_periods=20).std().replace(0, np.nan)
    out["range_pos"] = (out["close"] - out["low"]) / (out["high"] - out["low"]).replace(0, np.nan)
    out["low_24"] = out["low"].rolling(24, min_periods=1).min().shift(1)
    out["low_96"] = out["low"].rolling(96, min_periods=1).min().shift(1)
    out["high_24"] = out["high"].rolling(24, min_periods=1).max().shift(1)
    out["pv_momentum"] = (out["close"].diff() * out["volume"]).rolling(4, min_periods=1).sum()
    out["pv_momentum_z"] = out["pv_momentum"] / out["pv_momentum"].rolling(96, min_periods=20).std().replace(0, np.nan)
    out["climax_volume"] = out["volume"] / out["volume"].rolling(96, min_periods=10).mean().replace(0, np.nan)
    return out.ffill().fillna(0.0)


def add_truth_labels(feat, prominence_pct=1.0, distance=5, forward_bars=4):
    out = feat.copy()
    avg_price = out["close"].mean()
    prominence = avg_price * (prominence_pct / 100.0)
    peaks, _ = find_peaks(out["high"].to_numpy(float), prominence=prominence, distance=distance)
    valleys, _ = find_peaks(-out["low"].to_numpy(float), prominence=prominence, distance=distance)
    truth_valley = np.zeros(len(out), dtype=bool)
    truth_peak = np.zeros(len(out), dtype=bool)
    valley_window = np.zeros(len(out), dtype=bool)
    for i in valleys:
        truth_valley[i] = True
        valley_window[i : min(len(out), i + forward_bars + 1)] = True
    for i in peaks:
        truth_peak[i] = True
    out["truth_valley"] = truth_valley
    out["truth_peak"] = truth_peak
    out["truth_valley_entry_window"] = valley_window
    return out, {"prominence_pct": prominence_pct, "distance": distance, "absolute_prominence": prominence, "peaks": int(len(peaks)), "valleys": int(len(valleys))}


def in_session(hour, start, end):
    return start <= hour <= end if start <= end else hour >= start or hour <= end


def with_params(params):
    merged = dict(CORE_PARAMS)
    merged.update(BASE_SLEEVE)
    merged.update(params)
    return merged


def backtest_cap(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    p = with_params(params)
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
    ema21 = feat["ema21"].to_numpy(float)
    ema55 = feat["ema55"].to_numpy(float)
    vol_sma = feat["vol_sma"].to_numpy(float)
    bb_upper = feat["bb_upper"].to_numpy(float)
    bb_lower = feat["bb_lower"].to_numpy(float)
    vwap = feat["vwap"].to_numpy(float)
    prev_high = feat["prev_day_high"].to_numpy(float)
    prev_low = feat["prev_day_low"].to_numpy(float)
    atr_rel = feat["atr_rel"].to_numpy(float)
    vol_rank = feat["vol_rank"].to_numpy(float)
    vwap_dist = feat["vwap_dist_atr"].to_numpy(float)
    adx_slope = feat["adx_slope_8"].to_numpy(float)
    ny_hour = feat["ny_hour"].to_numpy(int)
    ret_z = feat["ret_z"].to_numpy(float)
    range_pos = feat["range_pos"].to_numpy(float)
    low_24 = feat["low_24"].to_numpy(float)
    low_96 = feat["low_96"].to_numpy(float)
    pv_z = feat["pv_momentum_z"].to_numpy(float)
    climax_volume = feat["climax_volume"].to_numpy(float)
    truth_window = feat["truth_valley_entry_window"].to_numpy(bool)
    truth_valley = feat["truth_valley"].to_numpy(bool)
    h4_signal, daily_signal = make_regimes(feat, p)

    pos = 0
    kind = 0
    entry = entry_high = entry_low = 0.0
    bars_held = 0
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    best_equity = INITIAL_CAPITAL
    best_i = max(start, 300)
    max_stagnation_bars = 0
    max_dd = 0.0
    exposed = 0
    long_trades = short_trades = core_trades = sleeve_trades = cap_trades = 0
    core_net = sleeve_net = cap_net = 0.0
    cap_pnls = []
    cap_truth_hits = 0
    cap_entry_indices = []
    pnls = []
    trade_indices = []

    for i in range(max(start, 300), end):
        if pos:
            exposed += 1
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            if kind == 1:
                stop_atr, target_atr, trail_atr = p["stop_atr"], p["target_atr"], p["trail_atr"]
                min_hold, max_hold = p["min_hold"], p["max_hold"]
            elif kind == 2:
                stop_atr, target_atr, trail_atr = p["sleeve_stop_atr"], p["sleeve_target_atr"], p["sleeve_trail_atr"]
                min_hold, max_hold = p["sleeve_min_hold"], p["sleeve_max_hold"]
            else:
                stop_atr, target_atr, trail_atr = p["cap_stop_atr"], p["cap_target_atr"], p["cap_trail_atr"]
                min_hold, max_hold = p["cap_min_hold"], p["cap_max_hold"]
            exit_price = None
            if pos == 1:
                stop = max(entry - stop_atr * atrv[i], entry_high - trail_atr * atrv[i])
                target = entry + target_atr * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif bars_held >= max_hold:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and h4_signal[i] == -1 and daily_signal[i] != 1:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and macd_v[i] < macd_v[i - 1] and rsi_v[i] < p["long_exit_rsi"]:
                    exit_price = close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] >= vwap[i] + p["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price = close[i]
                elif kind == 3 and bars_held >= min_hold and (
                    close[i] >= vwap[i] + p["cap_exit_vwap_atr"] * atrv[i]
                    or rsi_v[i] >= p["cap_exit_rsi"]
                    or (p["cap_exit_on_peak"] and truth_valley[i] is False and macd_v[i] < macd_v[i - 1] and range_pos[i] <= p["cap_exit_range_pos"])
                ):
                    exit_price = close[i]
            else:
                stop = min(entry + stop_atr * atrv[i], entry_low + trail_atr * atrv[i])
                target = entry - target_atr * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif bars_held >= max_hold:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and h4_signal[i] == 1 and daily_signal[i] != -1:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and macd_v[i] > macd_v[i - 1] and rsi_v[i] > p["short_exit_rsi"]:
                    exit_price = close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] <= vwap[i] - p["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                trade_indices.append(i)
                if kind == 1:
                    core_net += pnl
                elif kind == 2:
                    sleeve_net += pnl
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

        if pos == 0:
            min_cooldown = min(p["cooldown"], p["sleeve_cooldown"], p["cap_cooldown"])
            if i - last_trade >= min_cooldown:
                vol_ok = volume[i] >= p["vol_mult"] * vol_sma[i]
                core_trend_state = adxv[i] >= p["trend_adx"]
                core_long = (
                    core_trend_state
                    and directional_regime(p["trend_mode"], h4_signal[i], daily_signal[i], 1)
                    and close[i] > ema55[i]
                    and close[i] <= ema21[i] + p["pullback_atr"] * atrv[i]
                    and rsi_v[i] >= p["trend_long_rsi"]
                    and macd_v[i] >= p["trend_macd_floor"]
                    and vol_ok
                )
                core_short = (
                    core_trend_state
                    and directional_regime(p["trend_mode"], h4_signal[i], daily_signal[i], -1)
                    and close[i] < ema55[i]
                    and close[i] >= ema21[i] - p["pullback_atr"] * atrv[i]
                    and rsi_v[i] <= p["trend_short_rsi"]
                    and macd_v[i] <= -p["trend_macd_floor"]
                    and vol_ok
                )
                k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
                k_cross_down = stoch_k[i - 1] >= stoch_d[i - 1] and stoch_k[i] < stoch_d[i]
                sleeve_allowed = (
                    p["use_sleeve"]
                    and not core_trend_state
                    and adxv[i] <= p["sleeve_adx_max"]
                    and adx_slope[i] <= p["sleeve_adx_slope_max"]
                    and p["atr_rel_min"] <= atr_rel[i] <= p["atr_rel_max"]
                    and p["vol_rank_min"] <= vol_rank[i] <= p["vol_rank_max"]
                    and in_session(ny_hour[i], p["ny_start_hour"], p["ny_end_hour"])
                )
                long_location = close[i] < bb_lower[i] + p["bb_atr"] * atrv[i] or close[i] <= prev_low[i] + p["prev_level_atr"] * atrv[i]
                short_location = close[i] > bb_upper[i] - p["bb_atr"] * atrv[i] or close[i] >= prev_high[i] - p["prev_level_atr"] * atrv[i]
                sleeve_long = (
                    sleeve_allowed and p["allow_sleeve_longs"] and vwap_dist[i] <= -p["vwap_dist_atr"]
                    and long_location and rsi_v[i] <= p["sleeve_long_rsi"]
                    and (k_cross_up or stoch_k[i] <= p["sleeve_stoch"]) and daily_signal[i] != -1
                )
                sleeve_short = (
                    sleeve_allowed and p["allow_sleeve_shorts"] and vwap_dist[i] >= p["vwap_dist_atr"]
                    and short_location and rsi_v[i] >= p["sleeve_short_rsi"]
                    and (k_cross_down or stoch_k[i] >= 100.0 - p["sleeve_stoch"]) and daily_signal[i] != 1
                )
                regime_ok = (
                    p["cap_regime"] == "any"
                    or (p["cap_regime"] == "daily_not_bear" and daily_signal[i] != -1)
                    or (p["cap_regime"] == "h4_up" and h4_signal[i] == 1)
                    or (p["cap_regime"] == "either_up" and (h4_signal[i] == 1 or daily_signal[i] == 1))
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
                )
                cap_reversal = k_cross_up or close[i] > close[i - 1] or macd_v[i] > macd_v[i - 1]
                cap_long = (
                    p["use_cap"]
                    and i - last_trade >= p["cap_cooldown"]
                    and regime_ok
                    and p["cap_atr_rel_min"] <= atr_rel[i] <= p["cap_atr_rel_max"]
                    and p["cap_adx_min"] <= adxv[i] <= p["cap_adx_max"]
                    and cap_deep
                    and cap_exhaustion
                    and (not p["cap_require_reversal"] or cap_reversal)
                )
                if core_long:
                    pos, kind, entry = 1, 1, close[i]
                    core_trades += 1
                    long_trades += 1
                elif core_short:
                    pos, kind, entry = -1, 1, close[i]
                    core_trades += 1
                    short_trades += 1
                elif i - last_trade >= p["sleeve_cooldown"] and sleeve_long:
                    pos, kind, entry = 1, 2, close[i]
                    sleeve_trades += 1
                    long_trades += 1
                elif i - last_trade >= p["sleeve_cooldown"] and sleeve_short:
                    pos, kind, entry = -1, 2, close[i]
                    sleeve_trades += 1
                    short_trades += 1
                elif cap_long:
                    pos, kind, entry = 1, 3, close[i]
                    cap_trades += 1
                    long_trades += 1
                    cap_entry_indices.append(i)
                    if truth_window[i]:
                        cap_truth_hits += 1
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
        elif kind == 2:
            sleeve_net += pnl
        else:
            cap_net += pnl
            cap_pnls.append(pnl)

    if not pnls:
        return CapResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0, 0, -INITIAL_CAPITAL, 1.0, 365.0, 1.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    cap_wins = [x for x in cap_pnls if x > 0]
    net = equity - INITIAL_CAPITAL
    trade_dates = feat.index[trade_indices]
    months = {}
    for date, pnl in zip(trade_dates, pnls):
        months[date.strftime("%Y-%m")] = months.get(date.strftime("%Y-%m"), 0.0) + pnl
    positive_months = sum(1 for value in months.values() if value > 0)
    positive_total = sum(value for value in months.values() if value > 0)
    pre_cutoff = np.datetime64("2026-03-01T00:00:00Z")
    pre_march_net = sum(pnl for date, pnl in zip(trade_dates, pnls) if date.to_datetime64() < pre_cutoff)
    truth_total = int(feat["truth_valley"].iloc[start:end].sum())
    return CapResult(
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
        core_trades,
        sleeve_trades,
        cap_trades,
        core_net,
        sleeve_net,
        cap_net,
        len(cap_wins) / len(cap_pnls) * 100.0 if cap_pnls else 0.0,
        cap_truth_hits,
        cap_truth_hits / cap_trades * 100.0 if cap_trades else 0.0,
        cap_truth_hits / truth_total * 100.0 if truth_total else 0.0,
        positive_months,
        len(months),
        pre_march_net,
        max([value for value in months.values() if value > 0] or [0.0]) / (positive_total or 1e-9),
        max_stagnation_bars * 15.0 / 60.0 / 24.0,
        max(wins) / (sum(wins) or 1e-9) if wins else 1.0,
    )


def suggest_cap(trial):
    return {
        "use_cap": True,
        "cap_regime": trial.suggest_categorical("cap_regime", ["any", "daily_not_bear", "h4_up", "either_up"]),
        "cap_adx_min": trial.suggest_float("cap_adx_min", 8.0, 28.0),
        "cap_adx_max": trial.suggest_float("cap_adx_max", 18.0, 55.0),
        "cap_atr_rel_min": trial.suggest_float("cap_atr_rel_min", 0.85, 2.0),
        "cap_atr_rel_max": trial.suggest_float("cap_atr_rel_max", 1.1, 3.5),
        "cap_vwap_dist_atr": trial.suggest_float("cap_vwap_dist_atr", 0.8, 5.0),
        "cap_bb_atr": trial.suggest_float("cap_bb_atr", -1.2, 1.2),
        "cap_prev_low_atr": trial.suggest_float("cap_prev_low_atr", -1.0, 2.5),
        "cap_low_break_atr": trial.suggest_float("cap_low_break_atr", -0.6, 1.8),
        "cap_low96_atr": trial.suggest_float("cap_low96_atr", -1.5, 1.5),
        "cap_rsi_max": trial.suggest_float("cap_rsi_max", 18.0, 48.0),
        "cap_stoch_max": trial.suggest_float("cap_stoch_max", 4.0, 42.0),
        "cap_ret_z": trial.suggest_float("cap_ret_z", 0.2, 3.2),
        "cap_reclaim_pos": trial.suggest_float("cap_reclaim_pos", 0.02, 0.85),
        "cap_volume_mult": trial.suggest_float("cap_volume_mult", 0.25, 3.5),
        "cap_pv_z_max": trial.suggest_float("cap_pv_z_max", -4.0, 1.5),
        "cap_require_reversal": trial.suggest_categorical("cap_require_reversal", [True, True, False]),
        "cap_stop_atr": trial.suggest_float("cap_stop_atr", 0.7, 6.0),
        "cap_target_atr": trial.suggest_float("cap_target_atr", 0.6, 8.5),
        "cap_trail_atr": trial.suggest_float("cap_trail_atr", 0.8, 7.5),
        "cap_exit_vwap_atr": trial.suggest_float("cap_exit_vwap_atr", -1.0, 1.5),
        "cap_exit_rsi": trial.suggest_float("cap_exit_rsi", 38.0, 78.0),
        "cap_exit_range_pos": trial.suggest_float("cap_exit_range_pos", 0.05, 0.8),
        "cap_exit_on_peak": trial.suggest_categorical("cap_exit_on_peak", [False, True]),
        "cap_cooldown": trial.suggest_int("cap_cooldown", 0, 18),
        "cap_min_hold": trial.suggest_int("cap_min_hold", 0, 10),
        "cap_max_hold": trial.suggest_int("cap_max_hold", 4, 60),
    }


def objective_factory(feat, baseline_net, buy_hold, min_net, min_cap_trades):
    n = len(feat)

    def objective(trial):
        params = suggest_cap(trial)
        if params["cap_adx_min"] >= params["cap_adx_max"] or params["cap_atr_rel_min"] >= params["cap_atr_rel_max"]:
            raise optuna.TrialPruned()
        if params["cap_min_hold"] >= params["cap_max_hold"]:
            raise optuna.TrialPruned()
        full = backtest_cap(feat, params, 300, n)
        if full.net_profit < min_net or full.n_trades < 280 or full.cap_trades < min_cap_trades:
            raise optuna.TrialPruned()
        if full.cap_net < -1000 or full.max_drawdown > 13.5:
            raise optuna.TrialPruned()
        score = (
            full.total_return * 1.25
            + (full.net_profit - buy_hold) / INITIAL_CAPITAL * 100.0 * 1.15
            + max(0.0, full.net_profit - baseline_net) / INITIAL_CAPITAL * 100.0 * 1.8
            + min(full.profit_factor, 3.0) * 25.0
            + min(full.cap_net / INITIAL_CAPITAL * 100.0, 50.0) * 2.0
            + min(full.cap_truth_precision, 60.0) * 0.8
            + min(full.cap_truth_coverage, 22.0) * 1.2
            + full.positive_months / max(1, full.active_months) * 50.0
            + min(full.pre_march_net / INITIAL_CAPITAL * 100.0, 40.0) * 1.0
            - full.max_drawdown * 2.2
            - max(0.0, full.top_month_share - 0.45) * 150.0
            - max(0.0, full.max_stagnation_days - 50.0) * 1.2
            - max(0.0, full.max_winner_share - 0.12) * 150.0
        )
        trial.set_user_attr("full", asdict(full))
        return score

    return objective


def run_worker(worker_id, data_path, trials, seed, min_net, min_cap_trades):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    raw = load_json(data_path)
    feat, truth = add_truth_labels(add_cap_features(build_features(raw)))
    baseline_net = 91187.14623151795
    buy_hold = buy_hold_pnl(feat, 300, len(feat))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(200, max(50, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(200, max(50, trials // 5))))
    study.optimize(objective_factory(feat, baseline_net, buy_hold, min_net, min_cap_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    completed = [trial for trial in study.trials if trial.value is not None]
    if not completed:
        return {
            "worker_id": worker_id,
            "score": None,
            "params": {},
            "metrics": None,
            "truth": truth,
            "trials": len(study.trials),
            "skipped": True,
            "reason": "no_completed_trials",
        }
    best = max(completed, key=lambda trial: trial.value)
    params = dict(best.params)
    params["use_cap"] = True
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {"full": asdict(backtest_cap(feat, params, 300, len(feat)))},
        "truth": truth,
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026051901)
    parser.add_argument("--min-net", type=float, default=88000.0)
    parser.add_argument("--min-cap-trades", type=int, default=12)
    parser.add_argument("--out", default="reports/cl_15m_capitulation_sleeve_64k.json")
    args = parser.parse_args()

    raw = load_json(args.data)
    feat, truth = add_truth_labels(add_cap_features(build_features(raw)))
    counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(counts), os.cpu_count() or 1))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_worker, task_id, args.data, counts[task_id], args.seed, args.min_net, args.min_cap_trades)
            for task_id in range(len(counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result.get("skipped"):
                print(json.dumps({
                    "worker": result["worker_id"],
                    "skipped": True,
                    "reason": result["reason"],
                    "trials": result["trials"],
                }), flush=True)
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
                "cap_trades": full["cap_trades"],
                "cap_net": full["cap_net"],
                "cap_precision": full["cap_truth_precision"],
                "pre_march_net": full["pre_march_net"],
                "stagnation_days": full["max_stagnation_days"],
            }), flush=True)
    if not results:
        raise RuntimeError("No optimization results")
    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": sum(r["trials"] for r in results),
        "workers": workers,
        "core_params": CORE_PARAMS,
        "base_sleeve": BASE_SLEEVE,
        "truth": truth,
        "baseline": {
            "name": "JD CL 15m Hybrid Sleeve 32k Best 20260518",
            "net_profit": 91187.14623151795,
            "profit_factor": 2.307893440419791,
            "max_drawdown": 8.572723215542084,
            "trades": 288,
        },
        "buy_hold": buy_hold_pnl(feat, 300, len(feat)),
        "best": max(results, key=lambda x: x["score"]),
        "top10": sorted(results, key=lambda x: x["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
