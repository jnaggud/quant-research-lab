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

from optimize_15m_mtf_reversal import atr, ema, load_json, macd_hist, resample_ohlcv, rsi, stoch

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
    exposure: float
    long_trades: int
    short_trades: int


def build_features(df):
    out = df.copy()
    out["rsi"] = rsi(out["close"], 14)
    out["stoch_k"] = stoch(out, 14)
    out["stoch_d"] = out["stoch_k"].rolling(3, min_periods=1).mean()
    out["macdh"] = macd_hist(out["close"])
    out["atr"] = atr(out, 14)
    out["ema8"] = ema(out["close"], 8)
    out["ema21"] = ema(out["close"], 21)
    out["ema55"] = ema(out["close"], 55)
    out["ema144"] = ema(out["close"], 144)
    out["vol_sma"] = out["volume"].rolling(48, min_periods=1).mean()
    return out


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


def make_regime(feat, params):
    h4 = resample_ohlcv(feat, "240min")
    day = resample_ohlcv(feat, "1D")
    h4_fast = ema(h4["close"], params["h4_fast"])
    h4_slow = ema(h4["close"], params["h4_slow"])
    day_fast = ema(day["close"], params["d_fast"])
    day_slow = ema(day["close"], params["d_slow"])
    h4_signal = pd.Series(np.where(h4_fast > h4_slow, 1, -1), index=h4.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(np.where(day_fast > day_slow, 1, -1), index=day.index).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    if params["regime_mode"] == "both":
        regime = h4_signal.where(h4_signal == day_signal, 0).astype(int)
    elif params["regime_mode"] == "h4":
        regime = h4_signal.astype(int)
    else:
        regime = h4_signal.where(day_signal != -h4_signal, 0).astype(int)
    return regime.to_numpy(int)


def backtest(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    rsi_v = feat["rsi"].to_numpy(float)
    macd_v = feat["macdh"].to_numpy(float)
    ema8 = feat["ema8"].to_numpy(float)
    ema21 = feat["ema21"].to_numpy(float)
    ema55 = feat["ema55"].to_numpy(float)
    ema144 = feat["ema144"].to_numpy(float)
    volume = feat["volume"].to_numpy(float)
    vol_sma = feat["vol_sma"].to_numpy(float)
    regime = make_regime(feat, params)

    pos = 0
    entry = 0.0
    last_trade = -100000
    long_trades = 0
    short_trades = 0
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_dd = 0.0
    pnls = []
    entry_high = 0.0
    entry_low = 0.0
    exposed = 0

    for i in range(max(start, 300), end):
        if pos:
            exposed += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            exit_price = None
            if pos == 1:
                hard_stop = entry - params["stop_atr"] * atrv[i]
                trail_stop = entry_high - params["trail_atr"] * atrv[i]
                stop = max(hard_stop, trail_stop)
                if low[i] <= stop:
                    exit_price = stop
                elif regime[i] <= params["long_exit_regime"]:
                    exit_price = close[i]
                elif params["use_momentum_exit"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < params["long_exit_rsi"]:
                    exit_price = close[i]
            else:
                hard_stop = entry + params["stop_atr"] * atrv[i]
                trail_stop = entry_low + params["trail_atr"] * atrv[i]
                stop = min(hard_stop, trail_stop)
                if high[i] >= stop:
                    exit_price = stop
                elif regime[i] >= params["short_exit_regime"]:
                    exit_price = close[i]
                elif params["use_momentum_exit"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > params["short_exit_rsi"]:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                pnls.append(pnl)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                pos = 0
                last_trade = i

        if pos == 0 and i - last_trade >= params["cooldown"]:
            long_filter = True
            short_filter = True
            if params["local_filter"] == "ema21":
                long_filter = close[i] > ema21[i]
                short_filter = close[i] < ema21[i]
            elif params["local_filter"] == "ema55":
                long_filter = close[i] > ema55[i]
                short_filter = close[i] < ema55[i]
            elif params["local_filter"] == "stack":
                long_filter = ema8[i] > ema21[i] > ema55[i] and close[i] > ema8[i]
                short_filter = ema8[i] < ema21[i] < ema55[i] and close[i] < ema8[i]
            elif params["local_filter"] == "ema144":
                long_filter = close[i] > ema144[i]
                short_filter = close[i] < ema144[i]
            vol_ok = volume[i] >= params["vol_mult"] * vol_sma[i]
            long_ok = regime[i] == 1 and long_filter and rsi_v[i] >= params["long_rsi_min"] and macd_v[i] >= params["macd_floor"] and vol_ok
            short_ok = params["allow_short"] and regime[i] == -1 and short_filter and rsi_v[i] <= params["short_rsi_max"] and macd_v[i] <= -params["macd_floor"] and vol_ok
            if long_ok:
                pos = 1
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                long_trades += 1
            elif short_ok:
                pos = -1
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                short_trades += 1

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        pnls.append(pnl)

    if not pnls:
        return Result(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0)
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
        exposed / max(1, end - max(start, 300)) * 100.0,
        long_trades,
        short_trades,
    )


def suggest(trial):
    return {
        "h4_fast": trial.suggest_int("h4_fast", 4, 24),
        "h4_slow": trial.suggest_int("h4_slow", 18, 90),
        "d_fast": trial.suggest_int("d_fast", 5, 35),
        "d_slow": trial.suggest_int("d_slow", 20, 110),
        "regime_mode": trial.suggest_categorical("regime_mode", ["both", "h4", "h4_daily_veto"]),
        "local_filter": trial.suggest_categorical("local_filter", ["none", "ema21", "ema55", "stack", "ema144"]),
        "stop_atr": trial.suggest_float("stop_atr", 1.5, 8.0),
        "trail_atr": trial.suggest_float("trail_atr", 2.0, 22.0),
        "cooldown": trial.suggest_int("cooldown", 0, 24),
        "long_rsi_min": trial.suggest_float("long_rsi_min", 35.0, 62.0),
        "short_rsi_max": trial.suggest_float("short_rsi_max", 38.0, 65.0),
        "macd_floor": trial.suggest_float("macd_floor", -4.0, 8.0),
        "vol_mult": trial.suggest_float("vol_mult", 0.0, 1.2),
        "use_momentum_exit": trial.suggest_categorical("use_momentum_exit", [True, False]),
        "long_exit_rsi": trial.suggest_float("long_exit_rsi", 38.0, 58.0),
        "short_exit_rsi": trial.suggest_float("short_exit_rsi", 42.0, 62.0),
        "long_exit_regime": trial.suggest_categorical("long_exit_regime", [-1, 0]),
        "short_exit_regime": trial.suggest_categorical("short_exit_regime", [0, 1]),
        "allow_short": True,
    }


def objective_factory(feat, min_trades, buy_hold_pnl):
    n = len(feat)
    splits = [(300, int(n * 0.25)), (int(n * 0.25), int(n * 0.5)), (int(n * 0.5), int(n * 0.75)), (int(n * 0.75), n)]

    def objective(trial):
        params = suggest(trial)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n)
        if full.n_trades < min_trades or full.short_trades < 8:
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, a, b) for a, b in splits]
        min_ret = min(r.total_return for r in folds)
        avg_ret = float(np.mean([r.total_return for r in folds]))
        dd = max(r.max_drawdown for r in folds)
        excess = (full.net_profit - buy_hold_pnl) / INITIAL_CAPITAL * 100.0
        score = full.total_return * 1.4 + excess * 2.0 + avg_ret * 0.8 + min_ret * 1.4 + min(full.profit_factor, 3.0) * 6.0 - dd * 1.2
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("folds", [r.__dict__ for r in folds])
        return score

    return objective


def run_worker(worker_id, data_path, trials, min_trades, buy_hold_pnl, seed, point_value, commission_per_side, slippage_ticks, tick_size, initial_capital):
    global POINT_VALUE, COMMISSION_PER_SIDE, SLIPPAGE_TICKS, TICK_SIZE, INITIAL_CAPITAL
    POINT_VALUE = point_value
    COMMISSION_PER_SIDE = commission_per_side
    SLIPPAGE_TICKS = slippage_ticks
    TICK_SIZE = tick_size
    INITIAL_CAPITAL = initial_capital
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(data_path))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(120, max(30, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(120, max(30, trials // 5))))
    study.optimize(objective_factory(feat, min_trades, buy_hold_pnl), n_trials=trials, n_jobs=1, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["allow_short"] = True
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
    global POINT_VALUE, COMMISSION_PER_SIDE, SLIPPAGE_TICKS, TICK_SIZE, INITIAL_CAPITAL
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_es1_15m_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--seed", type=int, default=2026050805)
    parser.add_argument("--out", default="reports/es_15m_regime_carry_64k.json")
    parser.add_argument("--point-value", type=float, default=POINT_VALUE)
    parser.add_argument("--commission-per-side", type=float, default=COMMISSION_PER_SIDE)
    parser.add_argument("--slippage-ticks", type=float, default=SLIPPAGE_TICKS)
    parser.add_argument("--tick-size", type=float, default=TICK_SIZE)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    args = parser.parse_args()

    POINT_VALUE = args.point_value
    COMMISSION_PER_SIDE = args.commission_per_side
    SLIPPAGE_TICKS = args.slippage_ticks
    TICK_SIZE = args.tick_size
    INITIAL_CAPITAL = args.initial_capital

    raw = load_json(args.data)
    buy_hold_pnl = (raw["close"].iloc[-1] - raw["open"].iloc[0]) * POINT_VALUE
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
                run_worker,
                task_id,
                args.data,
                trial_counts[task_id],
                args.min_trades,
                buy_hold_pnl,
                args.seed,
                args.point_value,
                args.commission_per_side,
                args.slippage_ticks,
                args.tick_size,
                args.initial_capital,
            )
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
                "excess_vs_bh": full["net_profit"] - buy_hold_pnl,
                "return": full["total_return"],
                "pf": full["profit_factor"],
                "dd": full["max_drawdown"],
                "trades": full["n_trades"],
                "exposure": full["exposure"],
                "shorts": full["short_trades"],
            }), flush=True)

    payload = {
        "source_data": args.data,
        "workers": workers,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "buy_hold_pnl": buy_hold_pnl,
        "assumptions": {
            "initial_capital": args.initial_capital,
            "point_value": args.point_value,
            "commission_per_side": args.commission_per_side,
            "slippage_ticks_per_side": args.slippage_ticks,
            "tick_size": args.tick_size,
        },
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
