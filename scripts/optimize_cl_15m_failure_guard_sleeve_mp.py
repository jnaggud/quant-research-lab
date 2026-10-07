#!/usr/bin/env python3
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import optuna

from optimize_15m_mtf_reversal import load_json, resample_ohlcv
from optimize_cl_15m_active_router_mp import (
    INITIAL_CAPITAL,
    build_features,
    buy_hold_pnl,
    directional_regime,
    make_regimes,
    trade_pnl,
)


CORE_PARAMS = {
    "use_trend": True,
    "use_range": False,
    "use_breakout": False,
    "h4_fast": 17,
    "h4_slow": 26,
    "d_fast": 12,
    "d_slow": 50,
    "trend_mode": "either",
    "breakout_mode": "either",
    "trend_adx": 26.27168114440552,
    "range_adx": 20.069542274720206,
    "breakout_adx": 14.820210464501796,
    "pullback_atr": 2.3260855157992584,
    "range_band_atr": 0.9291756948505551,
    "trend_long_rsi": 57.759565415455576,
    "trend_short_rsi": 56.31301085447191,
    "range_long_rsi": 36.51408227045883,
    "range_short_rsi": 66.43887664508466,
    "range_stoch": 14.845188828340387,
    "trend_macd_floor": -0.7276752004878191,
    "breakout_macd_floor": 1.339978443518754,
    "vol_mult": 0.9141448739138068,
    "breakout_vol_mult": 1.6054506342856205,
    "stop_atr": 5.350064559397716,
    "target_atr": 6.492336054486658,
    "trail_atr": 7.917312471721442,
    "cooldown": 3,
    "min_hold": 10,
    "max_hold": 51,
    "exit_on_regime_flip": True,
    "exit_on_momentum": True,
    "long_exit_rsi": 47.698774764376665,
    "short_exit_rsi": 47.21280531035125,
    "allow_short": True,
}

BASE_PARAMS = {
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
class HybridResult:
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
    core_net: float
    sleeve_net: float
    positive_months: int
    active_months: int
    top_month_share: float
    pre_march_net: float
    max_stagnation_days: float
    max_winner_share: float


def add_research_features(feat):
    out = feat.copy()
    day = resample_ohlcv(out, "1D")
    prev_high = day["high"].shift(1).reindex(out.index, method="ffill")
    prev_low = day["low"].shift(1).reindex(out.index, method="ffill")
    out["prev_day_high"] = prev_high.fillna(out["high"])
    out["prev_day_low"] = prev_low.fillna(out["low"])
    out["atr_rel"] = out["atr"] / out["atr"].rolling(192, min_periods=20).mean()
    out["vol_rank"] = out["volume"].rolling(96, min_periods=10).rank(pct=True)
    out["vwap_dist_atr"] = (out["close"] - out["vwap"]) / out["atr"].replace(0, np.nan)
    out["adx_slope_8"] = out["adx"] - out["adx"].shift(8)
    ny_hour = out.index.tz_convert("America/New_York").hour
    out["ny_hour"] = ny_hour
    return out.ffill().fillna(0.0)


def in_session(hour, start, end):
    return start <= hour <= end if start <= end else hour >= start or hour <= end


def backtest_hybrid(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    merged = dict(CORE_PARAMS)
    merged.update({k: v for k, v in params.items() if k in CORE_PARAMS})

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
    kin_long_gate = feat["kin_long_gate"].to_numpy(bool) if "kin_long_gate" in feat else np.ones(len(feat), dtype=bool)
    kin_short_gate = feat["kin_short_gate"].to_numpy(bool) if "kin_short_gate" in feat else np.ones(len(feat), dtype=bool)
    h4_signal, daily_signal = make_regimes(feat, merged)
    guard_enabled = params.get("use_failure_guard", True)
    guard_vwap = params.get("guard_vwap_abs", 1.5)
    protect_enabled = params.get("use_profit_protect", True)
    protect_trigger = params.get("protect_trigger_atr", 1.0)
    protect_giveback = params.get("protect_giveback_atr", 0.55)
    momentum_requires_profit = params.get("momentum_requires_profit", False)

    pos = 0
    kind = 0
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
    long_trades = short_trades = core_trades = sleeve_trades = 0
    core_net = sleeve_net = 0.0
    pnls = []
    trade_indices = []

    for i in range(max(start, 300), end):
        if pos:
            exposed += 1
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            if kind == 1:
                stop_atr = merged["stop_atr"]
                target_atr = merged["target_atr"]
                trail_atr = merged["trail_atr"]
                max_hold = merged["max_hold"]
                min_hold = merged["min_hold"]
            else:
                stop_atr = params["sleeve_stop_atr"]
                target_atr = params["sleeve_target_atr"]
                trail_atr = params["sleeve_trail_atr"]
                max_hold = params["sleeve_max_hold"]
                min_hold = params["sleeve_min_hold"]

            exit_price = None
            if pos == 1:
                stop = max(entry - stop_atr * atrv[i], entry_high - trail_atr * atrv[i])
                if protect_enabled and entry_high - entry >= protect_trigger * atrv[i]:
                    stop = max(stop, entry_high - protect_giveback * atrv[i])
                target = entry + target_atr * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif bars_held >= max_hold:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_regime_flip"] and h4_signal[i] == -1 and daily_signal[i] != 1:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_momentum"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < merged["long_exit_rsi"] and (not momentum_requires_profit or close[i] > entry):
                    exit_price = close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] >= vwap[i] + params["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price = close[i]
            else:
                stop = min(entry + stop_atr * atrv[i], entry_low + trail_atr * atrv[i])
                if protect_enabled and entry - entry_low >= protect_trigger * atrv[i]:
                    stop = min(stop, entry_low + protect_giveback * atrv[i])
                target = entry - target_atr * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif bars_held >= max_hold:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_regime_flip"] and h4_signal[i] == 1 and daily_signal[i] != -1:
                    exit_price = close[i]
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_momentum"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > merged["short_exit_rsi"] and (not momentum_requires_profit or close[i] < entry):
                    exit_price = close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] <= vwap[i] - params["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                trade_indices.append(i)
                if kind == 1:
                    core_net += pnl
                else:
                    sleeve_net += pnl
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                if equity > best_equity:
                    best_equity = equity
                    best_equity_i = i
                else:
                    max_stagnation_bars = max(max_stagnation_bars, i - best_equity_i)
                pos = 0
                kind = 0
                bars_held = 0
                last_trade = i

        if pos == 0 and i - last_trade >= min(merged["cooldown"], params["sleeve_cooldown"]):
            vol_ok = volume[i] >= merged["vol_mult"] * vol_sma[i]
            trend_state = adxv[i] >= merged["trend_adx"]
            core_long = (
                trend_state
                and directional_regime(merged["trend_mode"], h4_signal[i], daily_signal[i], 1)
                and (not guard_enabled or not (abs(vwap_dist[i]) >= guard_vwap and daily_signal[i] == -1))
                and close[i] > ema55[i]
                and close[i] <= ema21[i] + merged["pullback_atr"] * atrv[i]
                and rsi_v[i] >= merged["trend_long_rsi"]
                and macd_v[i] >= merged["trend_macd_floor"]
                and vol_ok
            )
            core_short = (
                trend_state
                and directional_regime(merged["trend_mode"], h4_signal[i], daily_signal[i], -1)
                and (not guard_enabled or not (abs(vwap_dist[i]) >= guard_vwap and daily_signal[i] == 1))
                and close[i] < ema55[i]
                and close[i] >= ema21[i] - merged["pullback_atr"] * atrv[i]
                and rsi_v[i] <= merged["trend_short_rsi"]
                and macd_v[i] <= -merged["trend_macd_floor"]
                and vol_ok
            )

            k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
            k_cross_down = stoch_k[i - 1] >= stoch_d[i - 1] and stoch_k[i] < stoch_d[i]
            sleeve_allowed = (
                params["use_sleeve"]
                and not trend_state
                and adxv[i] <= params["sleeve_adx_max"]
                and adx_slope[i] <= params["sleeve_adx_slope_max"]
                and params["atr_rel_min"] <= atr_rel[i] <= params["atr_rel_max"]
                and params["vol_rank_min"] <= vol_rank[i] <= params["vol_rank_max"]
                and in_session(ny_hour[i], params["ny_start_hour"], params["ny_end_hour"])
            )
            near_prev_low = close[i] <= prev_low[i] + params["prev_level_atr"] * atrv[i]
            near_prev_high = close[i] >= prev_high[i] - params["prev_level_atr"] * atrv[i]
            long_location = close[i] < bb_lower[i] + params["bb_atr"] * atrv[i] or near_prev_low
            short_location = close[i] > bb_upper[i] - params["bb_atr"] * atrv[i] or near_prev_high
            sleeve_long = (
                sleeve_allowed
                and params["allow_sleeve_longs"]
                and kin_long_gate[i]
                and vwap_dist[i] <= -params["vwap_dist_atr"]
                and long_location
                and rsi_v[i] <= params["sleeve_long_rsi"]
                and (k_cross_up or stoch_k[i] <= params["sleeve_stoch"])
                and daily_signal[i] != -1
            )
            sleeve_short = (
                sleeve_allowed
                and params["allow_sleeve_shorts"]
                and kin_short_gate[i]
                and vwap_dist[i] >= params["vwap_dist_atr"]
                and short_location
                and rsi_v[i] >= params["sleeve_short_rsi"]
                and (k_cross_down or stoch_k[i] >= 100.0 - params["sleeve_stoch"])
                and daily_signal[i] != 1
            )

            if core_long:
                pos, kind = 1, 1
                core_trades += 1
                long_trades += 1
            elif core_short:
                pos, kind = -1, 1
                core_trades += 1
                short_trades += 1
            elif i - last_trade >= params["sleeve_cooldown"] and sleeve_long:
                pos, kind = 1, 2
                sleeve_trades += 1
                long_trades += 1
            elif i - last_trade >= params["sleeve_cooldown"] and sleeve_short:
                pos, kind = -1, 2
                sleeve_trades += 1
                short_trades += 1
            if pos:
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                bars_held = 0

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        pnls.append(pnl)
        trade_indices.append(end - 1)
        if kind == 1:
            core_net += pnl
        else:
            sleeve_net += pnl

    if not pnls:
        return HybridResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 0, 0, 0.0, 0.0, 0, 0, 1.0, -INITIAL_CAPITAL, 365.0, 1.0)

    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    net = equity - INITIAL_CAPITAL
    trade_dates = feat.index[trade_indices]
    months = {}
    for date, pnl in zip(trade_dates, pnls):
        key = date.strftime("%Y-%m")
        months[key] = months.get(key, 0.0) + pnl
    positive_months = sum(1 for value in months.values() if value > 0)
    positive_total = sum(value for value in months.values() if value > 0)
    top_month_share = max([value for value in months.values() if value > 0] or [0.0]) / (positive_total or 1e-9)
    pre_cutoff = np.datetime64("2026-03-01T00:00:00Z")
    pre_march_net = sum(pnl for date, pnl in zip(trade_dates, pnls) if date.to_datetime64() < pre_cutoff)
    max_winner_share = max(wins) / (sum(wins) or 1e-9) if wins else 1.0
    return HybridResult(
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
        core_net,
        sleeve_net,
        positive_months,
        len(months),
        top_month_share,
        pre_march_net,
        max_stagnation_bars * 15.0 / 60.0 / 24.0,
        max_winner_share,
    )


def suggest_hybrid(trial):
    params = dict(BASE_PARAMS)
    params.update({
        "allow_sleeve_longs": trial.suggest_categorical("allow_sleeve_longs", [True, True, False]),
        "allow_sleeve_shorts": trial.suggest_categorical("allow_sleeve_shorts", [True, True, False]),
        "sleeve_adx_max": trial.suggest_float("sleeve_adx_max", 18.0, 28.0),
        "sleeve_adx_slope_max": trial.suggest_float("sleeve_adx_slope_max", -1.0, 4.0),
        "atr_rel_min": trial.suggest_float("atr_rel_min", 0.65, 1.0),
        "atr_rel_max": trial.suggest_float("atr_rel_max", 1.05, 1.55),
        "vol_rank_min": trial.suggest_float("vol_rank_min", 0.0, 0.35),
        "vol_rank_max": trial.suggest_float("vol_rank_max", 0.72, 1.0),
        "vwap_dist_atr": trial.suggest_float("vwap_dist_atr", 0.25, 0.95),
        "prev_level_atr": trial.suggest_float("prev_level_atr", 0.6, 2.6),
        "bb_atr": trial.suggest_float("bb_atr", 0.35, 1.5),
        "sleeve_long_rsi": trial.suggest_float("sleeve_long_rsi", 34.0, 47.0),
        "sleeve_short_rsi": trial.suggest_float("sleeve_short_rsi", 58.0, 80.0),
        "sleeve_stoch": trial.suggest_float("sleeve_stoch", 18.0, 42.0),
        "sleeve_stop_atr": trial.suggest_float("sleeve_stop_atr", 1.4, 5.0),
        "sleeve_target_atr": trial.suggest_float("sleeve_target_atr", 0.8, 4.0),
        "sleeve_trail_atr": trial.suggest_float("sleeve_trail_atr", 2.0, 7.0),
        "sleeve_exit_vwap_atr": trial.suggest_float("sleeve_exit_vwap_atr", -0.1, 0.7),
        "sleeve_cooldown": trial.suggest_int("sleeve_cooldown", 0, 12),
        "sleeve_min_hold": trial.suggest_int("sleeve_min_hold", 0, 10),
        "sleeve_max_hold": trial.suggest_int("sleeve_max_hold", 12, 60),
        "ny_start_hour": trial.suggest_int("ny_start_hour", 0, 8),
        "ny_end_hour": trial.suggest_int("ny_end_hour", 12, 20),
        "use_failure_guard": True,
        "guard_vwap_abs": trial.suggest_float("guard_vwap_abs", 1.0, 2.6),
        "use_profit_protect": True,
        "protect_trigger_atr": trial.suggest_float("protect_trigger_atr", 0.45, 1.8),
        "protect_giveback_atr": trial.suggest_float("protect_giveback_atr", 0.2, 1.6),
        "momentum_requires_profit": trial.suggest_categorical("momentum_requires_profit", [False, True]),
    })
    params["use_sleeve"] = True
    return params


def objective_factory(feat, min_net, min_trades):
    n = len(feat)
    buy_hold = buy_hold_pnl(feat, 300, n)

    def objective(trial):
        params = suggest_hybrid(trial)
        if params["atr_rel_min"] >= params["atr_rel_max"] or params["vol_rank_min"] >= params["vol_rank_max"]:
            raise optuna.TrialPruned()
        if params["sleeve_min_hold"] >= params["sleeve_max_hold"]:
            raise optuna.TrialPruned()
        if not (params["allow_sleeve_longs"] or params["allow_sleeve_shorts"]):
            raise optuna.TrialPruned()
        full = backtest_hybrid(feat, params, 300, n)
        if full.net_profit < min_net or full.n_trades < min_trades or full.sleeve_trades < 20:
            raise optuna.TrialPruned()
        if full.sleeve_net < -2000 or full.max_drawdown > 13.0:
            raise optuna.TrialPruned()
        score = (
            full.total_return * 1.4
            + (full.net_profit - buy_hold) / INITIAL_CAPITAL * 100.0 * 1.2
            + min(full.profit_factor, 2.8) * 25.0
            + min(full.sleeve_net / INITIAL_CAPITAL * 100.0, 25.0) * 1.5
            + full.positive_months / max(1, full.active_months) * 45.0
            + min(full.pre_march_net / INITIAL_CAPITAL * 100.0, 35.0) * 0.9
            - full.max_drawdown * 2.2
            - max(0.0, full.top_month_share - 0.42) * 140.0
            - max(0.0, full.max_stagnation_days - 55.0) * 1.0
            - max(0.0, full.max_winner_share - 0.14) * 140.0
        )
        trial.set_user_attr("full", asdict(full))
        return score

    return objective


def run_worker(worker_id, data_path, trials, seed, min_net, min_trades):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = add_research_features(build_features(load_json(data_path)))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(180, max(50, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(180, max(50, trials // 5))))
    study.optimize(objective_factory(feat, min_net, min_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    if not any(trial.state == optuna.trial.TrialState.COMPLETE for trial in study.trials):
        return None
    best = study.best_trial
    params = dict(best.params)
    params["use_sleeve"] = True
    n = len(feat)
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {"full": asdict(backtest_hybrid(feat, params, 300, n))},
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=32000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026051818)
    parser.add_argument("--min-net", type=float, default=62000.0)
    parser.add_argument("--min-trades", type=int, default=260)
    parser.add_argument("--out", default="reports/cl_15m_hybrid_sleeve_32k.json")
    args = parser.parse_args()

    raw = load_json(args.data)
    feat = add_research_features(build_features(raw))
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
            executor.submit(run_worker, task_id, args.data, counts[task_id], args.seed, args.min_net, args.min_trades)
            for task_id in range(len(counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "net": full["net_profit"],
                "pf": full["profit_factor"],
                "dd": full["max_drawdown"],
                "trades": full["n_trades"],
                "sleeve_trades": full["sleeve_trades"],
                "sleeve_net": full["sleeve_net"],
                "pre_march_net": full["pre_march_net"],
                "stagnation_days": full["max_stagnation_days"],
            }), flush=True)

    if not results:
        raise SystemExit("No completed trials met the failure-guard constraints; loosen thresholds or run more trials.")

    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "workers": workers,
        "core_params": CORE_PARAMS,
        "base_params": BASE_PARAMS,
        "assumptions": {"objective": "Fixed C3 core plus failure-derived VWAP/daily guard and profit-protection controls."},
        "buy_hold": buy_hold_pnl(feat, 300, len(feat)),
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
