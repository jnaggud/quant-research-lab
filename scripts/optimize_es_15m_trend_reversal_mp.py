#!/usr/bin/env python3
import argparse
import json
import os
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import optuna
import pandas as pd

from optimize_15m_mtf_reversal import atr, cross_over, cross_under, ema, load_json, macd_hist, resample_ohlcv, rsi, stoch

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


POINT_VALUE = 50.0
COMMISSION_PER_SIDE = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.25
INITIAL_CAPITAL = 50_000.0


@dataclass
class Result:
    net_profit: float
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    avg_trade: float
    long_trades: int
    short_trades: int


def build_features(df):
    out = df.copy()
    out["rsi"] = rsi(out["close"], 14)
    out["stoch_k"] = stoch(out, 14)
    out["stoch_d"] = out["stoch_k"].rolling(3, min_periods=1).mean()
    hh = out["high"].rolling(14, min_periods=1).max()
    ll = out["low"].rolling(14, min_periods=1).min()
    out["willr"] = -100.0 * (hh - out["close"]) / (hh - ll + 1e-10)
    out["macdh"] = macd_hist(out["close"])
    out["atr"] = atr(out, 14)
    out["basis20"] = out["close"].rolling(20, min_periods=1).mean()
    out["std20"] = out["close"].rolling(20, min_periods=1).std().fillna(0.0)
    out["ema8"] = ema(out["close"], 8)
    out["ema21"] = ema(out["close"], 21)
    out["ema55"] = ema(out["close"], 55)
    out["vol_sma"] = out["volume"].rolling(48, min_periods=1).mean()
    out["range"] = out["high"] - out["low"]
    out["stoch_up"] = cross_over(out["stoch_k"], out["stoch_d"])
    out["stoch_down"] = cross_under(out["stoch_k"], out["stoch_d"])
    out["rsi_up40"] = cross_over(out["rsi"], pd.Series(40.0, index=out.index))
    out["rsi_down60"] = cross_under(out["rsi"], pd.Series(60.0, index=out.index))
    out["willr_up80"] = cross_over(out["willr"], pd.Series(-80.0, index=out.index))
    out["willr_down20"] = cross_under(out["willr"], pd.Series(-20.0, index=out.index))
    return out


def make_signals(feat, params):
    h4 = resample_ohlcv(feat, "240min")
    day = resample_ohlcv(feat, "1D")
    h4_fast = ema(h4["close"], params["h4_fast"])
    h4_slow = ema(h4["close"], params["h4_slow"])
    day_fast = ema(day["close"], params["d_fast"])
    day_slow = ema(day["close"], params["d_slow"])
    h4_signal = pd.Series(np.where(h4_fast > h4_slow, 1, -1), index=h4.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(np.where(day_fast > day_slow, 1, -1), index=day.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    regime = h4_signal.where(h4_signal == day_signal, 0).astype(int)

    bb_upper = feat["basis20"] + params["bb_mult"] * feat["std20"]
    bb_lower = feat["basis20"] - params["bb_mult"] * feat["std20"]
    valley = (
        (feat["stoch_up"] & (feat["stoch_k"] < params["stoch_low"])).astype(int)
        + (((feat["rsi"] < params["rsi_low"]) & (feat["rsi"] > feat["rsi"].shift(1))) | feat["rsi_up40"]).astype(int)
        + (feat["willr_up80"] | ((feat["willr"] < params["willr_low"]) & (feat["willr"] > feat["willr"].shift(1)))).astype(int)
        + ((feat["low"] <= bb_lower) | (feat["close"] < feat["basis20"] - params["atr_displace"] * feat["atr"])).astype(int)
        + ((feat["macdh"] < 0) & (feat["macdh"] > feat["macdh"].shift(1))).astype(int)
    )
    peak = (
        (feat["stoch_down"] & (feat["stoch_k"] > params["stoch_high"])).astype(int)
        + (((feat["rsi"] > params["rsi_high"]) & (feat["rsi"] < feat["rsi"].shift(1))) | feat["rsi_down60"]).astype(int)
        + (feat["willr_down20"] | ((feat["willr"] > params["willr_high"]) & (feat["willr"] < feat["willr"].shift(1)))).astype(int)
        + ((feat["high"] >= bb_upper) | (feat["close"] > feat["basis20"] + params["atr_displace"] * feat["atr"])).astype(int)
        + ((feat["macdh"] > 0) & (feat["macdh"] < feat["macdh"].shift(1))).astype(int)
    )

    close = feat["close"]
    trend_long = (
        (regime == 1)
        & (feat["ema8"] > feat["ema21"])
        & (feat["ema21"] > feat["ema55"])
        & (feat["low"].rolling(params["pullback_lookback"], min_periods=1).min() <= feat["ema21"] + params["pullback_atr"] * feat["atr"])
        & (close > feat["ema8"])
        & (feat["rsi"] > params["trend_rsi_long"])
        & (feat["macdh"] > feat["macdh"].shift(1))
        & (feat["volume"] >= params["vol_mult"] * feat["vol_sma"])
    )
    trend_short = (
        (regime == -1)
        & (feat["ema8"] < feat["ema21"])
        & (feat["ema21"] < feat["ema55"])
        & (feat["high"].rolling(params["pullback_lookback"], min_periods=1).max() >= feat["ema21"] - params["pullback_atr"] * feat["atr"])
        & (close < feat["ema8"])
        & (feat["rsi"] < params["trend_rsi_short"])
        & (feat["macdh"] < feat["macdh"].shift(1))
        & (feat["volume"] >= params["vol_mult"] * feat["vol_sma"])
    )
    return (
        regime.to_numpy(int),
        valley.to_numpy(int),
        peak.to_numpy(int),
        trend_long.to_numpy(bool),
        trend_short.to_numpy(bool),
    )


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


def backtest(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    regime, valley, peak, trend_long, trend_short = make_signals(feat, params)
    pos = 0
    entry = 0.0
    entry_kind = 0
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_dd = 0.0
    pnls = []
    long_trades = 0
    short_trades = 0

    for i in range(max(start, 300), end):
        if pos:
            exit_price = None
            if pos == 1:
                stop = entry - params["stop_atr"] * atrv[i]
                target = entry + (params["trend_target_atr"] if entry_kind == 2 else params["reversal_target_atr"]) * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif peak[i] >= params["exit_score"] or regime[i] <= 0:
                    exit_price = close[i]
            else:
                stop = entry + params["stop_atr"] * atrv[i]
                target = entry - (params["trend_target_atr"] if entry_kind == 2 else params["reversal_target_atr"]) * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif valley[i] >= params["exit_score"] or regime[i] >= 0:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                pos = 0
                entry_kind = 0
                last_trade = i

        if pos == 0 and i - last_trade >= params["cooldown"]:
            reversal_long = regime[i] == 1 and valley[i] >= params["entry_score"]
            reversal_short = params["allow_short"] and regime[i] == -1 and peak[i] >= params["entry_score"]
            if params["use_trend"] and trend_long[i]:
                pos = 1
                entry = close[i]
                entry_kind = 2
                long_trades += 1
            elif params["use_reversal"] and reversal_long:
                pos = 1
                entry = close[i]
                entry_kind = 1
                long_trades += 1
            elif params["use_trend"] and params["allow_short"] and trend_short[i]:
                pos = -1
                entry = close[i]
                entry_kind = 2
                short_trades += 1
            elif params["use_reversal"] and reversal_short:
                pos = -1
                entry = close[i]
                entry_kind = 1
                short_trades += 1

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        pnls.append(pnl)

    if not pnls:
        return Result(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0, 0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    net = equity - INITIAL_CAPITAL
    return Result(
        net,
        net / INITIAL_CAPITAL * 100.0,
        len(pnls),
        len(wins) / len(pnls) * 100.0,
        sum(wins) / (abs(sum(losses)) or 1e-9),
        max_dd,
        net / len(pnls),
        long_trades,
        short_trades,
    )


def suggest(trial, force_trend=False, force_reversal=False):
    return {
        "h4_fast": trial.suggest_int("h4_fast", 4, 20),
        "h4_slow": trial.suggest_int("h4_slow", 16, 70),
        "d_fast": trial.suggest_int("d_fast", 6, 28),
        "d_slow": trial.suggest_int("d_slow", 18, 90),
        "entry_score": trial.suggest_int("entry_score", 2, 4),
        "exit_score": trial.suggest_int("exit_score", 2, 4),
        "stoch_low": trial.suggest_float("stoch_low", 18.0, 45.0),
        "stoch_high": trial.suggest_float("stoch_high", 55.0, 88.0),
        "rsi_low": trial.suggest_float("rsi_low", 25.0, 45.0),
        "rsi_high": trial.suggest_float("rsi_high", 55.0, 78.0),
        "willr_low": trial.suggest_float("willr_low", -92.0, -62.0),
        "willr_high": trial.suggest_float("willr_high", -38.0, -8.0),
        "bb_mult": trial.suggest_float("bb_mult", 1.2, 2.9),
        "atr_displace": trial.suggest_float("atr_displace", 0.25, 1.8),
        "pullback_lookback": trial.suggest_int("pullback_lookback", 2, 18),
        "pullback_atr": trial.suggest_float("pullback_atr", 0.05, 1.25),
        "trend_rsi_long": trial.suggest_float("trend_rsi_long", 45.0, 66.0),
        "trend_rsi_short": trial.suggest_float("trend_rsi_short", 34.0, 55.0),
        "vol_mult": trial.suggest_float("vol_mult", 0.15, 1.3),
        "stop_atr": trial.suggest_float("stop_atr", 1.0, 5.5),
        "reversal_target_atr": trial.suggest_float("reversal_target_atr", 1.5, 10.0),
        "trend_target_atr": trial.suggest_float("trend_target_atr", 2.0, 16.0),
        "cooldown": trial.suggest_int("cooldown", 0, 48),
        "allow_short": True,
        "use_reversal": True if force_reversal else trial.suggest_categorical("use_reversal", [True, False]),
        "use_trend": True if force_trend else trial.suggest_categorical("use_trend", [True, False]),
    }


def objective_factory(feat, min_trades, max_trades, force_trend=False, force_reversal=False):
    n = len(feat)
    splits = [(300, int(n * 0.25)), (int(n * 0.25), int(n * 0.5)), (int(n * 0.5), int(n * 0.75)), (int(n * 0.75), n)]

    def objective(trial):
        params = suggest(trial, force_trend, force_reversal)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        if not params["use_reversal"] and not params["use_trend"]:
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n)
        if full.n_trades < min_trades or full.n_trades > max_trades:
            raise optuna.TrialPruned()
        if full.short_trades < 5:
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, a, b) for a, b in splits]
        min_ret = min(r.total_return for r in folds)
        avg_ret = float(np.mean([r.total_return for r in folds]))
        min_pf = min(r.profit_factor for r in folds)
        dd = max(r.max_drawdown for r in folds)
        short_balance_penalty = max(0, 10 - full.short_trades) * 5.0
        trade_penalty = max(0, full.n_trades - 260) * 0.15
        score = full.total_return * 1.0 + avg_ret * 1.4 + min_ret * 2.2 + min(min_pf, 3.0) * 7.0 - dd * 1.35 - trade_penalty - short_balance_penalty
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("folds", [r.__dict__ for r in folds])
        return score

    return objective


def run_worker(worker_id, data_path, trials, min_trades, max_trades, seed, force_trend, force_reversal):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(data_path))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(120, max(30, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(120, max(30, trials // 5))))
    study.optimize(objective_factory(feat, min_trades, max_trades, force_trend, force_reversal), n_trials=trials, n_jobs=1, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["allow_short"] = True
    if force_trend:
        params["use_trend"] = True
    if force_reversal:
        params["use_reversal"] = True
    n = len(feat)
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {
            "full": backtest(feat, params, 300, n).__dict__,
            "q1": backtest(feat, params, 300, int(n * 0.25)).__dict__,
            "q2": backtest(feat, params, int(n * 0.25), int(n * 0.5)).__dict__,
            "q3": backtest(feat, params, int(n * 0.5), int(n * 0.75)).__dict__,
            "q4": backtest(feat, params, int(n * 0.75), n).__dict__,
        },
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_es1_15m_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=90)
    parser.add_argument("--max-trades", type=int, default=360)
    parser.add_argument("--seed", type=int, default=2026050802)
    parser.add_argument("--out", default="reports/es_15m_trend_reversal_short_64k.json")
    parser.add_argument("--force-trend", action="store_true")
    parser.add_argument("--force-reversal", action="store_true")
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
            executor.submit(run_worker, task_id, args.data, trial_counts[task_id], args.min_trades, args.max_trades, args.seed, args.force_trend, args.force_reversal)
            for task_id in range(len(trial_counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "net_profit": full["net_profit"],
                "return": full["total_return"],
                "pf": full["profit_factor"],
                "trades": full["n_trades"],
                "shorts": full["short_trades"],
                "q4_return": result["metrics"]["q4"]["total_return"],
            }), flush=True)

    payload = {
        "source_data": args.data,
        "workers": workers,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "assumptions": {
            "initial_capital": INITIAL_CAPITAL,
            "point_value": POINT_VALUE,
            "commission_per_side": COMMISSION_PER_SIDE,
            "slippage_ticks_per_side": SLIPPAGE_TICKS,
            "tick_size": TICK_SIZE,
            "force_trend": args.force_trend,
            "force_reversal": args.force_reversal,
        },
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
