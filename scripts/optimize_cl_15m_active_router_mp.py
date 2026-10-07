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

POINT_VALUE = 1000.0
COMMISSION_PER_SIDE = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.01
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
    max_winner_share: float


def adx(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    plus_dm = (high.diff()).where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
    minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_rma = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / (atr_rma + 1e-12)
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / (atr_rma + 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    return dx.ewm(alpha=1 / length, adjust=False).mean()


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
    out["don_high"] = out["high"].rolling(32, min_periods=1).max().shift(1)
    out["don_low"] = out["low"].rolling(32, min_periods=1).min().shift(1)
    typical = (out["high"] + out["low"] + out["close"]) / 3.0
    session = out.index.floor("1D")
    pv = typical * out["volume"]
    out["vwap"] = pv.groupby(session).cumsum() / out["volume"].replace(0, np.nan).groupby(session).cumsum()
    out["vwap"] = out["vwap"].ffill().fillna(out["close"])
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


def make_regimes(feat, params):
    h4 = resample_ohlcv(feat, "240min")
    day = resample_ohlcv(feat, "1D")
    h4_fast = ema(h4["close"], params["h4_fast"])
    h4_slow = ema(h4["close"], params["h4_slow"])
    day_fast = ema(day["close"], params["d_fast"])
    day_slow = ema(day["close"], params["d_slow"])
    h4_signal = pd.Series(np.where(h4_fast > h4_slow, 1, -1), index=h4.index)
    h4_signal = h4_signal.shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(np.where(day_fast > day_slow, 1, -1), index=day.index)
    day_signal = day_signal.shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    return h4_signal.to_numpy(int), day_signal.to_numpy(int)


def directional_regime(mode, h4, day, side):
    target = 1 if side == 1 else -1
    if mode == "h4":
        return h4 == target
    if mode == "daily":
        return day == target
    if mode == "both":
        return h4 == target and day == target
    if mode == "not_against_daily":
        return h4 == target and day != -target
    return h4 == target or day == target


def backtest(feat, params, start=300, end=None):
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
    ema8 = feat["ema8"].to_numpy(float)
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
    last_trade = -100000
    equity = INITIAL_CAPITAL
    peak_equity = INITIAL_CAPITAL
    max_dd = 0.0
    pnls = []
    exposed = 0
    long_trades = 0
    short_trades = 0

    for i in range(max(start, 300), end):
        if pos:
            exposed += 1
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            exit_price = None
            if pos == 1:
                hard_stop = entry - params["stop_atr"] * atrv[i]
                trail_stop = entry_high - params["trail_atr"] * atrv[i]
                stop = max(hard_stop, trail_stop)
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
                hard_stop = entry + params["stop_atr"] * atrv[i]
                trail_stop = entry_low + params["trail_atr"] * atrv[i]
                stop = min(hard_stop, trail_stop)
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
                pnls.append(pnl)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
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

            long_ok = trend_long or range_long or breakout_long
            short_ok = params["allow_short"] and (trend_short or range_short or breakout_short)
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
        return Result(-INITIAL_CAPITAL, -100.0, 0, 0.0, 0.0, 100.0, 0.0, 0.0, 0, 0, 1.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    net = equity - INITIAL_CAPITAL
    max_winner_share = (max(wins) / (sum(wins) or 1e-9)) if wins else 1.0
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
        max_winner_share,
    )


def buy_hold_pnl(feat, start, end):
    start = max(start, 0)
    end = min(end, len(feat))
    if end <= start:
        return 0.0
    return (feat["close"].iloc[end - 1] - feat["open"].iloc[start]) * POINT_VALUE


def suggest(trial):
    use_trend = trial.suggest_categorical("use_trend", [True, True, False])
    use_range = trial.suggest_categorical("use_range", [True, True, False])
    use_breakout = trial.suggest_categorical("use_breakout", [True, False])
    return {
        "h4_fast": trial.suggest_int("h4_fast", 4, 18),
        "h4_slow": trial.suggest_int("h4_slow", 20, 80),
        "d_fast": trial.suggest_int("d_fast", 5, 30),
        "d_slow": trial.suggest_int("d_slow", 25, 120),
        "trend_mode": trial.suggest_categorical("trend_mode", ["h4", "either", "not_against_daily", "both"]),
        "breakout_mode": trial.suggest_categorical("breakout_mode", ["h4", "either", "not_against_daily", "both"]),
        "use_trend": use_trend,
        "use_range": use_range,
        "use_breakout": use_breakout,
        "trend_adx": trial.suggest_float("trend_adx", 12.0, 34.0),
        "range_adx": trial.suggest_float("range_adx", 10.0, 28.0),
        "breakout_adx": trial.suggest_float("breakout_adx", 12.0, 34.0),
        "pullback_atr": trial.suggest_float("pullback_atr", 0.2, 2.6),
        "range_band_atr": trial.suggest_float("range_band_atr", 0.0, 1.5),
        "trend_long_rsi": trial.suggest_float("trend_long_rsi", 38.0, 58.0),
        "trend_short_rsi": trial.suggest_float("trend_short_rsi", 42.0, 62.0),
        "range_long_rsi": trial.suggest_float("range_long_rsi", 22.0, 45.0),
        "range_short_rsi": trial.suggest_float("range_short_rsi", 55.0, 78.0),
        "range_stoch": trial.suggest_float("range_stoch", 8.0, 35.0),
        "trend_macd_floor": trial.suggest_float("trend_macd_floor", -3.0, 3.0),
        "breakout_macd_floor": trial.suggest_float("breakout_macd_floor", -1.0, 4.0),
        "vol_mult": trial.suggest_float("vol_mult", 0.0, 1.2),
        "breakout_vol_mult": trial.suggest_float("breakout_vol_mult", 0.6, 2.4),
        "stop_atr": trial.suggest_float("stop_atr", 1.0, 6.0),
        "target_atr": trial.suggest_float("target_atr", 0.8, 8.0),
        "trail_atr": trial.suggest_float("trail_atr", 1.0, 10.0),
        "cooldown": trial.suggest_int("cooldown", 0, 8),
        "min_hold": trial.suggest_int("min_hold", 0, 10),
        "max_hold": trial.suggest_int("max_hold", 8, 80),
        "exit_on_regime_flip": trial.suggest_categorical("exit_on_regime_flip", [True, False]),
        "exit_on_momentum": trial.suggest_categorical("exit_on_momentum", [True, False]),
        "long_exit_rsi": trial.suggest_float("long_exit_rsi", 35.0, 55.0),
        "short_exit_rsi": trial.suggest_float("short_exit_rsi", 45.0, 65.0),
        "allow_short": True,
    }


def objective_factory(feat, min_trades, target_trades, train_start_idx):
    n = len(feat)
    oos_start = 300
    train_start = max(train_start_idx, 300)
    full_bh = buy_hold_pnl(feat, 300, n)
    train_bh = buy_hold_pnl(feat, train_start, n)
    oos_bh = buy_hold_pnl(feat, oos_start, train_start)
    train_splits = [
        (train_start, int(train_start + (n - train_start) * 0.25)),
        (int(train_start + (n - train_start) * 0.25), int(train_start + (n - train_start) * 0.5)),
        (int(train_start + (n - train_start) * 0.5), int(train_start + (n - train_start) * 0.75)),
        (int(train_start + (n - train_start) * 0.75), n),
    ]

    def objective(trial):
        params = suggest(trial)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        if not (params["use_trend"] or params["use_range"] or params["use_breakout"]):
            raise optuna.TrialPruned()
        if params["range_adx"] > params["trend_adx"] + 8:
            raise optuna.TrialPruned()
        if params["min_hold"] >= params["max_hold"]:
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n)
        train = backtest(feat, params, train_start, n)
        oos = backtest(feat, params, oos_start, train_start)
        if full.n_trades < min_trades or train.n_trades < int(min_trades * 0.65):
            raise optuna.TrialPruned()
        if full.long_trades < 25 or full.short_trades < 25:
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, a, b) for a, b in train_splits if b > a + 100]
        fold_returns = [r.total_return for r in folds] or [-100.0]
        fold_dd = [r.max_drawdown for r in folds] or [100.0]
        trade_bonus = min(full.n_trades / target_trades, 1.5) * 35.0 - abs(full.n_trades - target_trades) / target_trades * 18.0
        full_excess = (full.net_profit - full_bh) / INITIAL_CAPITAL * 100.0
        train_excess = (train.net_profit - train_bh) / INITIAL_CAPITAL * 100.0
        oos_excess = (oos.net_profit - oos_bh) / INITIAL_CAPITAL * 100.0
        score = (
            full.total_return * 1.5
            + train.total_return * 1.0
            + full_excess * 1.8
            + train_excess * 1.2
            + oos.total_return * 0.8
            + oos_excess * 0.9
            + min(fold_returns) * 1.2
            + np.mean(fold_returns) * 0.6
            + min(full.profit_factor, 3.0) * 18.0
            + trade_bonus
            - max(fold_dd) * 1.6
            - full.max_drawdown * 1.1
            - max(0.0, full.max_winner_share - 0.25) * 120.0
        )
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("train", train.__dict__)
        trial.set_user_attr("oos", oos.__dict__)
        trial.set_user_attr("folds", [r.__dict__ for r in folds])
        return score

    return objective


def run_worker(worker_id, data_path, trials, min_trades, target_trades, seed, train_start_ts):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(data_path))
    train_start_idx = int(np.searchsorted(feat.index.view("int64") // 10**9, train_start_ts))
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(180, max(50, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(180, max(50, trials // 5))))
    study.optimize(objective_factory(feat, min_trades, target_trades, train_start_idx), n_trials=trials, n_jobs=1, show_progress_bar=False)
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
            "full": backtest(feat, params, 300, n).__dict__,
            "train": backtest(feat, params, train_start, n).__dict__,
            "oos": backtest(feat, params, 300, train_start).__dict__,
        },
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=220)
    parser.add_argument("--target-trades", type=int, default=420)
    parser.add_argument("--seed", type=int, default=2026051801)
    parser.add_argument("--train-start-ts", type=int, default=1759190400)
    parser.add_argument("--out", default="reports/cl_15m_active_router_64k.json")
    args = parser.parse_args()

    raw = load_json(args.data)
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
            executor.submit(run_worker, task_id, args.data, trial_counts[task_id], args.min_trades, args.target_trades, args.seed, args.train_start_ts)
            for task_id in range(len(trial_counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            full = result["metrics"]["full"]
            train = result["metrics"]["train"]
            oos = result["metrics"]["oos"]
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "full_net": full["net_profit"],
                "full_return": full["total_return"],
                "full_pf": full["profit_factor"],
                "full_dd": full["max_drawdown"],
                "full_trades": full["n_trades"],
                "train_net": train["net_profit"],
                "oos_net": oos["net_profit"],
                "oos_return": oos["total_return"],
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
        },
        "buy_hold": {
            "full": buy_hold_pnl(raw, 300, len(raw)),
            "train": buy_hold_pnl(raw, max(train_start_idx, 300), len(raw)),
            "oos": buy_hold_pnl(raw, 300, max(train_start_idx, 300)),
        },
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
