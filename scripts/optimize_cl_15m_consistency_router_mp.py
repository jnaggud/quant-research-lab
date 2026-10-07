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

from optimize_15m_mtf_reversal import load_json
from optimize_cl_15m_active_router_mp import (
    COMMISSION_PER_SIDE,
    INITIAL_CAPITAL,
    POINT_VALUE,
    SLIPPAGE_TICKS,
    TICK_SIZE,
    build_features,
    buy_hold_pnl,
    directional_regime,
    make_regimes,
    suggest,
    trade_pnl,
)

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


@dataclass
class ConsistencyResult:
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
    max_winner_share: float
    positive_months: int
    active_months: int
    worst_month: float
    top_month_share: float
    pre_march_net: float
    pre_march_trades: int
    max_stagnation_days: float


def backtest_consistency(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
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
    ema144 = feat["ema144"].to_numpy(float)
    vol_sma = feat["vol_sma"].to_numpy(float)
    bb_upper = feat["bb_upper"].to_numpy(float)
    bb_lower = feat["bb_lower"].to_numpy(float)
    don_high = feat["don_high"].to_numpy(float)
    don_low = feat["don_low"].to_numpy(float)
    vwap = feat["vwap"].to_numpy(float)
    h4_signal, daily_signal = make_regimes(feat, params)

    pos = 0
    entry = 0.0
    entry_high = 0.0
    entry_low = 0.0
    bars_held = 0
    entry_i = 0
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_dd = 0.0
    best_equity = INITIAL_CAPITAL
    best_equity_i = max(start, 300)
    max_stagnation_bars = 0
    exposed = 0
    long_trades = 0
    short_trades = 0
    trade_pnls = []
    trade_indices = []
    trade_sides = []

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
                elif bars_held >= params["min_hold"] and params["exit_on_regime_flip"] and h4_signal[i] == -1 and daily_signal[i] != 1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["exit_on_momentum"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < params["long_exit_rsi"]:
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
                elif bars_held >= params["min_hold"] and params["exit_on_regime_flip"] and h4_signal[i] == 1 and daily_signal[i] != -1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["exit_on_momentum"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > params["short_exit_rsi"]:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                equity += pnl
                trade_pnls.append(pnl)
                trade_indices.append(i)
                trade_sides.append(pos)
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
            vol_ok = volume[i] >= params["vol_mult"] * vol_sma[i]
            trend_state = adxv[i] >= params["trend_adx"]
            range_state = adxv[i] <= params["range_adx"]
            k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
            k_cross_down = stoch_k[i - 1] >= stoch_d[i - 1] and stoch_k[i] < stoch_d[i]

            trend_long = (
                params["use_trend"]
                and trend_state
                and directional_regime(params["trend_mode"], h4_signal[i], daily_signal[i], 1)
                and close[i] > ema55[i]
                and close[i] <= ema21[i] + params["pullback_atr"] * atrv[i]
                and rsi_v[i] >= params["trend_long_rsi"]
                and macd_v[i] >= params["trend_macd_floor"]
                and vol_ok
            )
            trend_short = (
                params["use_trend"]
                and trend_state
                and directional_regime(params["trend_mode"], h4_signal[i], daily_signal[i], -1)
                and close[i] < ema55[i]
                and close[i] >= ema21[i] - params["pullback_atr"] * atrv[i]
                and rsi_v[i] <= params["trend_short_rsi"]
                and macd_v[i] <= -params["trend_macd_floor"]
                and vol_ok
            )
            range_long = (
                params["use_range"]
                and range_state
                and close[i] < bb_lower[i] + params["range_band_atr"] * atrv[i]
                and close[i] < vwap[i]
                and rsi_v[i] <= params["range_long_rsi"]
                and (k_cross_up or stoch_k[i] <= params["range_stoch"])
                and daily_signal[i] != -1
                and vol_ok
            )
            range_short = (
                params["use_range"]
                and range_state
                and close[i] > bb_upper[i] - params["range_band_atr"] * atrv[i]
                and close[i] > vwap[i]
                and rsi_v[i] >= params["range_short_rsi"]
                and (k_cross_down or stoch_k[i] >= 100.0 - params["range_stoch"])
                and daily_signal[i] != 1
                and vol_ok
            )
            breakout_long = (
                params["use_breakout"]
                and close[i] > don_high[i]
                and close[i] > ema144[i]
                and directional_regime(params["breakout_mode"], h4_signal[i], daily_signal[i], 1)
                and adxv[i] >= params["breakout_adx"]
                and macd_v[i] >= params["breakout_macd_floor"]
                and volume[i] >= params["breakout_vol_mult"] * vol_sma[i]
            )
            breakout_short = (
                params["use_breakout"]
                and close[i] < don_low[i]
                and close[i] < ema144[i]
                and directional_regime(params["breakout_mode"], h4_signal[i], daily_signal[i], -1)
                and adxv[i] >= params["breakout_adx"]
                and macd_v[i] <= -params["breakout_macd_floor"]
                and volume[i] >= params["breakout_vol_mult"] * vol_sma[i]
            )

            if trend_long or range_long or breakout_long:
                pos = 1
                entry = close[i]
                entry_i = i
                entry_high = high[i]
                entry_low = low[i]
                long_trades += 1
            elif params["allow_short"] and (trend_short or range_short or breakout_short):
                pos = -1
                entry = close[i]
                entry_i = i
                entry_high = high[i]
                entry_low = low[i]
                short_trades += 1

    if pos:
        pnl = trade_pnl(entry, close[end - 1], pos)
        equity += pnl
        trade_pnls.append(pnl)
        trade_indices.append(end - 1)
        trade_sides.append(pos)

    if not trade_pnls:
        return ConsistencyResult(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 1.0, 0, 0, -INITIAL_CAPITAL, 1.0, -INITIAL_CAPITAL, 0, 365.0)

    wins = [x for x in trade_pnls if x > 0]
    losses = [x for x in trade_pnls if x <= 0]
    net = equity - INITIAL_CAPITAL
    trade_dates = feat.index[trade_indices]
    months = {}
    for date, pnl in zip(trade_dates, trade_pnls):
        key = date.strftime("%Y-%m")
        months[key] = months.get(key, 0.0) + pnl
    active_months = len(months)
    positive_months = sum(1 for value in months.values() if value > 0)
    worst_month = min(months.values()) if months else 0.0
    positive_total = sum(value for value in months.values() if value > 0)
    top_month_share = max([value for value in months.values() if value > 0] or [0.0]) / (positive_total or 1e-9)
    pre_cutoff = np.datetime64("2026-03-01T00:00:00Z")
    pre_march_pnls = [pnl for date, pnl in zip(trade_dates, trade_pnls) if date.to_datetime64() < pre_cutoff]
    max_winner_share = max(wins) / (sum(wins) or 1e-9) if wins else 1.0
    max_stagnation_days = max_stagnation_bars * 15.0 / 60.0 / 24.0

    return ConsistencyResult(
        net,
        net / INITIAL_CAPITAL * 100.0,
        len(trade_pnls),
        len(wins) / len(trade_pnls) * 100.0,
        sum(wins) / (abs(sum(losses)) or 1e-9),
        max_dd,
        net / len(trade_pnls),
        exposed / max(1, end - max(start, 300)) * 100.0,
        long_trades,
        short_trades,
        max_winner_share,
        positive_months,
        active_months,
        worst_month,
        top_month_share,
        sum(pre_march_pnls),
        len(pre_march_pnls),
        max_stagnation_days,
    )


def consistency_score(result, buy_hold):
    excess_return = (result.net_profit - buy_hold) / INITIAL_CAPITAL * 100.0
    positive_month_ratio = result.positive_months / max(1, result.active_months)
    stagnation_penalty = max(0.0, result.max_stagnation_days - 35.0) * 1.4
    concentration_penalty = max(0.0, result.top_month_share - 0.38) * 180.0
    dead_period_penalty = max(0.0, -result.pre_march_net / INITIAL_CAPITAL * 100.0) * 2.2
    pre_march_bonus = min(result.pre_march_net / INITIAL_CAPITAL * 100.0, 35.0) * 1.4
    trade_bonus = min(result.n_trades / 320.0, 1.4) * 25.0 - abs(result.n_trades - 320.0) / 320.0 * 10.0
    return (
        result.total_return * 0.9
        + excess_return * 1.4
        + min(result.profit_factor, 2.6) * 20.0
        + positive_month_ratio * 55.0
        + pre_march_bonus
        + trade_bonus
        - result.max_drawdown * 1.5
        - max(0.0, -result.worst_month / INITIAL_CAPITAL * 100.0) * 1.2
        - concentration_penalty
        - stagnation_penalty
        - dead_period_penalty
        - max(0.0, result.max_winner_share - 0.18) * 160.0
    )


def objective_factory(feat, min_trades, train_start_idx):
    n = len(feat)
    oos_start = 300
    train_start = max(train_start_idx, 300)
    full_bh = buy_hold_pnl(feat, 300, n)
    train_bh = buy_hold_pnl(feat, train_start, n)
    oos_bh = buy_hold_pnl(feat, oos_start, train_start)

    def objective(trial):
        params = suggest(trial)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        if not (params["use_trend"] or params["use_range"] or params["use_breakout"]):
            raise optuna.TrialPruned()
        if not params["use_range"]:
            raise optuna.TrialPruned()
        if params["range_adx"] > params["trend_adx"] + 10:
            raise optuna.TrialPruned()
        if params["min_hold"] >= params["max_hold"]:
            raise optuna.TrialPruned()

        full = backtest_consistency(feat, params, 300, n)
        train = backtest_consistency(feat, params, train_start, n)
        oos = backtest_consistency(feat, params, oos_start, train_start)
        if full.n_trades < min_trades or full.long_trades < 40 or full.short_trades < 40:
            raise optuna.TrialPruned()
        if full.pre_march_trades < 80 or full.active_months < 7:
            raise optuna.TrialPruned()
        if full.top_month_share > 0.62:
            raise optuna.TrialPruned()

        score = (
            consistency_score(full, full_bh) * 1.0
            + consistency_score(train, train_bh) * 0.65
            + consistency_score(oos, oos_bh) * 0.5
            + min(full.pre_march_net / INITIAL_CAPITAL * 100.0, 35.0) * 1.2
        )
        trial.set_user_attr("full", asdict(full))
        trial.set_user_attr("train", asdict(train))
        trial.set_user_attr("oos", asdict(oos))
        return score

    return objective


def run_worker(worker_id, data_path, trials, min_trades, seed, train_start_ts):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(data_path))
    train_start_idx = int(np.searchsorted(feat.index.view("int64") // 10**9, train_start_ts))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(220, max(60, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(220, max(60, trials // 5))))
    study.optimize(objective_factory(feat, min_trades, train_start_idx), n_trials=trials, n_jobs=1, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["allow_short"] = True
    n = len(feat)
    train_start = max(train_start_idx, 300)
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {
            "full": asdict(backtest_consistency(feat, params, 300, n)),
            "train": asdict(backtest_consistency(feat, params, train_start, n)),
            "oos": asdict(backtest_consistency(feat, params, 300, train_start)),
        },
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=32000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=220)
    parser.add_argument("--seed", type=int, default=2026051812)
    parser.add_argument("--train-start-ts", type=int, default=1759190400)
    parser.add_argument("--out", default="reports/cl_15m_consistency_router_32k.json")
    args = parser.parse_args()

    raw = load_json(args.data)
    feat = build_features(raw)
    train_start_idx = int(np.searchsorted(raw.index.view("int64") // 10**9, args.train_start_ts))
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
            executor.submit(run_worker, task_id, args.data, trial_counts[task_id], args.min_trades, args.seed, args.train_start_ts)
            for task_id in range(len(trial_counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "net": full["net_profit"],
                "pf": full["profit_factor"],
                "dd": full["max_drawdown"],
                "trades": full["n_trades"],
                "positive_months": full["positive_months"],
                "active_months": full["active_months"],
                "top_month_share": full["top_month_share"],
                "pre_march_net": full["pre_march_net"],
                "stagnation_days": full["max_stagnation_days"],
            }), flush=True)

    payload = {
        "source_data": args.data,
        "workers": workers,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "train_start_ts": args.train_start_ts,
        "assumptions": {
            "initial_capital": INITIAL_CAPITAL,
            "point_value": POINT_VALUE,
            "commission_per_side": COMMISSION_PER_SIDE,
            "slippage_ticks_per_side": SLIPPAGE_TICKS,
            "tick_size": TICK_SIZE,
            "objective": "Penalizes flat equity, monthly concentration, weak pre-March PnL, and high drawdown.",
        },
        "buy_hold": {
            "full": buy_hold_pnl(feat, 300, len(feat)),
            "train": buy_hold_pnl(feat, max(train_start_idx, 300), len(feat)),
            "oos": buy_hold_pnl(feat, 300, max(train_start_idx, 300)),
        },
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
