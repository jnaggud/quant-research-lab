#!/usr/bin/env python3
"""Dependency-free random search for GC 15m trend-bias candidates."""

from __future__ import annotations

import argparse
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


POINT_VALUE = 100.0
COMMISSION_PER_SIDE = 2.50
SLIPPAGE_TICKS = 1.0
TICK_SIZE = 0.1
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


def json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def ema(series, length):
    return series.ewm(span=int(length), adjust=False).mean()


def rma(series, length):
    return series.ewm(alpha=1 / int(length), adjust=False).mean()


def rsi(close, length):
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    rs = rma(gain, length) / (rma(loss, length) + 1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def atr(df, length):
    prev = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return rma(tr, length)


def macd_hist(close):
    line = ema(close, 12) - ema(close, 26)
    return line - ema(line, 9)


def stoch(df, length):
    low = df["low"].rolling(length, min_periods=1).min()
    high = df["high"].rolling(length, min_periods=1).max()
    return 100.0 * (df["close"] - low) / (high - low + 1e-10)


def load_json(path):
    payload = json.load(open(path))
    df = pd.DataFrame(payload["bars"])
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def resample_ohlcv(df, tf):
    return df.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


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


def make_regimes(feat, params):
    h4 = resample_ohlcv(feat, "240min")
    day = resample_ohlcv(feat, "1D")
    h4_signal = pd.Series(
        np.where(ema(h4["close"], params["h4_fast"]) > ema(h4["close"], params["h4_slow"]), 1, -1),
        index=h4.index,
    )
    h4_signal = h4_signal.shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(
        np.where(ema(day["close"], params["d_fast"]) > ema(day["close"], params["d_slow"]), 1, -1),
        index=day.index,
    )
    day_signal = day_signal.shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    return h4_signal.to_numpy(int), day_signal.to_numpy(int)


def local_filters(params, close, ema8, ema21, ema55, ema144):
    if params["local_filter"] == "ema21":
        return close > ema21, close < ema21
    if params["local_filter"] == "ema55":
        return close > ema55, close < ema55
    if params["local_filter"] == "stack":
        return (ema8 > ema21) & (ema21 > ema55) & (close > ema8), (ema8 < ema21) & (ema21 < ema55) & (close < ema8)
    if params["local_filter"] == "ema144":
        return close > ema144, close < ema144
    return np.ones_like(close, dtype=bool), np.ones_like(close, dtype=bool)


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
    h4_signal, daily_signal = make_regimes(feat, params)
    long_filter, short_filter = local_filters(params, close, ema8, ema21, ema55, ema144)

    pos = 0
    entry = 0.0
    bars_held = 0
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
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            exit_price = None
            if pos == 1:
                hard_stop = entry - params["stop_atr"] * atrv[i]
                trail_stop = entry_high - params["trail_atr"] * atrv[i]
                stop = max(hard_stop, trail_stop)
                if low[i] <= stop:
                    exit_price = stop
                elif bars_held >= params["min_hold"] and params["long_exit_mode"] == "h4_down" and h4_signal[i] == -1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["long_exit_mode"] == "daily_down" and daily_signal[i] == -1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["long_exit_mode"] == "both_down" and h4_signal[i] == -1 and daily_signal[i] == -1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["use_momentum_exit"] and daily_signal[i] != 1 and macd_v[i] < macd_v[i - 1] and rsi_v[i] < params["long_exit_rsi"]:
                    exit_price = close[i]
            else:
                hard_stop = entry + params["stop_atr"] * atrv[i]
                trail_stop = entry_low + params["short_trail_atr"] * atrv[i]
                stop = min(hard_stop, trail_stop)
                if high[i] >= stop:
                    exit_price = stop
                elif bars_held >= params["min_hold"] and params["short_exit_mode"] == "h4_up" and h4_signal[i] == 1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["short_exit_mode"] == "daily_up" and daily_signal[i] == 1:
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["short_exit_mode"] == "either_up" and (h4_signal[i] == 1 or daily_signal[i] == 1):
                    exit_price = close[i]
                elif bars_held >= params["min_hold"] and params["use_momentum_exit"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > params["short_exit_rsi"]:
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
            long_regime = {
                "daily_up": daily_signal[i] == 1,
                "h4_up": h4_signal[i] == 1,
                "both_up": h4_signal[i] == 1 and daily_signal[i] == 1,
                "either_up": h4_signal[i] == 1 or daily_signal[i] == 1,
            }[params["long_mode"]]
            short_regime = {
                "both_down": h4_signal[i] == -1 and daily_signal[i] == -1,
                "daily_down": daily_signal[i] == -1,
                "h4_down_daily_not_up": h4_signal[i] == -1 and daily_signal[i] != 1,
                "h4_down": h4_signal[i] == -1,
            }[params["short_mode"]]
            long_ok = long_regime and long_filter[i] and rsi_v[i] >= params["long_rsi_min"] and macd_v[i] >= params["long_macd_floor"] and vol_ok
            short_ok = params["allow_short"] and short_regime and short_filter[i] and rsi_v[i] <= params["short_rsi_max"] and macd_v[i] <= params["short_macd_ceiling"] and vol_ok
            if long_ok:
                pos = 1
                entry = close[i]
                entry_high = high[i]
                entry_low = low[i]
                bars_held = 0
                long_trades += 1
            elif short_ok:
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


def buy_hold_pnl(feat, start, end):
    start = max(start, 0)
    end = min(end, len(feat))
    if end <= start:
        return 0.0
    return (feat["close"].iloc[end - 1] - feat["open"].iloc[start]) * POINT_VALUE


class Trial:
    def __init__(self, seed):
        self.rng = random.Random(seed)

    def randint(self, low, high):
        return self.rng.randint(low, high)

    def uniform(self, low, high):
        return self.rng.uniform(low, high)

    def choice(self, values):
        return self.rng.choice(values)


def suggest(trial):
    return {
        "h4_fast": trial.randint(3, 28),
        "h4_slow": trial.randint(16, 120),
        "d_fast": trial.randint(4, 42),
        "d_slow": trial.randint(20, 180),
        "long_mode": trial.choice(["h4_up", "daily_up", "both_up", "either_up"]),
        "short_mode": trial.choice(["both_down", "daily_down", "h4_down_daily_not_up", "h4_down"]),
        "local_filter": trial.choice(["none", "ema21", "ema55", "stack", "ema144"]),
        "stop_atr": trial.uniform(1.5, 14.0),
        "trail_atr": trial.uniform(4.0, 60.0),
        "short_trail_atr": trial.uniform(1.5, 24.0),
        "cooldown": trial.randint(0, 32),
        "min_hold": trial.randint(0, 64),
        "long_rsi_min": trial.uniform(30.0, 68.0),
        "short_rsi_max": trial.uniform(22.0, 62.0),
        "long_macd_floor": trial.uniform(-14.0, 12.0),
        "short_macd_ceiling": trial.uniform(-12.0, 8.0),
        "vol_mult": trial.uniform(0.0, 1.6),
        "use_momentum_exit": trial.choice([True, False]),
        "long_exit_rsi": trial.uniform(25.0, 62.0),
        "short_exit_rsi": trial.uniform(35.0, 78.0),
        "long_exit_mode": trial.choice(["h4_down", "daily_down", "both_down", "none"]),
        "short_exit_mode": trial.choice(["h4_up", "daily_up", "either_up", "none"]),
        "allow_short": trial.choice([True, False]),
    }


def valid_params(params):
    return params["h4_fast"] < params["h4_slow"] and params["d_fast"] < params["d_slow"]


def score(metrics, refs, min_trades):
    full = metrics["full"]
    train = metrics["train"]
    oos = metrics["oos"]
    month = metrics["month"]
    full_excess = full["net_profit"] - refs["buy_hold"]["full"]
    train_excess = train["net_profit"] - refs["buy_hold"]["train"]
    oos_excess = oos["net_profit"] - refs["buy_hold"]["oos"]
    month_excess = month["net_profit"] - refs["buy_hold"]["month"]
    trade_penalty = max(0, min_trades - full["n_trades"]) * 10_000.0
    return (
        full["net_profit"] * 1.0
        + full_excess * 1.6
        + train_excess * 1.8
        + oos["net_profit"] * 2.0
        + oos_excess * 1.0
        + month["net_profit"] * 3.0
        + month_excess * 1.5
        + min(full["profit_factor"], 4.0) * 80_000.0
        + min(train["profit_factor"], 4.0) * 50_000.0
        - full["max_drawdown"] * 25_000.0
        - max(0.0, 1.0 - month["profit_factor"]) * 100_000.0
        - trade_penalty
    )


def metric_bundle(feat, params, train_start_idx, month_start_idx):
    n = len(feat)
    return {
        "full": asdict(backtest(feat, params, 300, n)),
        "train": asdict(backtest(feat, params, max(train_start_idx, 300), n)),
        "oos": asdict(backtest(feat, params, 300, max(train_start_idx, 301))),
        "month": asdict(backtest(feat, params, max(month_start_idx, 300), n)),
    }


def keep_top(rows, row, limit):
    rows.append(row)
    rows.sort(key=lambda item: item["score"], reverse=True)
    if len(rows) > limit:
        rows.pop()


def run_worker(worker_id, args, trials):
    feat = build_features(load_json(args["data"]))
    train_start_idx = int(np.searchsorted(feat.index.view("int64") // 10**9, args["train_start_ts"]))
    month_start_idx = int(np.searchsorted(feat.index.view("int64") // 10**9, args["month_start_ts"]))
    refs = {
        "buy_hold": {
            "full": buy_hold_pnl(feat, 300, len(feat)),
            "train": buy_hold_pnl(feat, max(train_start_idx, 300), len(feat)),
            "oos": buy_hold_pnl(feat, 300, max(train_start_idx, 301)),
            "month": buy_hold_pnl(feat, max(month_start_idx, 300), len(feat)),
        }
    }
    best = []
    attempted = 0
    accepted = 0
    idx = 0
    while accepted < trials:
        attempted += 1
        trial = Trial(args["seed"] + worker_id * 1_000_003 + idx)
        idx += 1
        params = suggest(trial)
        if not valid_params(params):
            continue
        metrics = metric_bundle(feat, params, train_start_idx, month_start_idx)
        full = metrics["full"]
        train = metrics["train"]
        if full["n_trades"] < args["min_trades"] or train["n_trades"] < args["min_trades"] or full["long_trades"] < 10:
            continue
        accepted += 1
        row = {
            "worker_id": worker_id,
            "score": score(metrics, refs, args["min_trades"]),
            "params": params,
            "metrics": metrics,
            "trials": accepted,
            "attempted": attempted,
        }
        keep_top(best, row, args["top_per_worker"])
    return best


def progress_row(row):
    full = row["metrics"]["full"]
    train = row["metrics"]["train"]
    oos = row["metrics"]["oos"]
    month = row["metrics"]["month"]
    return {
        "worker": row["worker_id"],
        "score": round(row["score"], 2),
        "net": round(full["net_profit"], 2),
        "pf": round(full["profit_factor"], 3),
        "dd": round(full["max_drawdown"], 2),
        "trades": full["n_trades"],
        "train": round(train["net_profit"], 2),
        "oos": round(oos["net_profit"], 2),
        "month": round(month["net_profit"], 2),
        "long_short": f"{full['long_trades']}/{full['short_trades']}",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="reports/tv_gc1_15m_bars_20260626.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--top-per-worker", type=int, default=5)
    parser.add_argument("--min-trades", type=int, default=40)
    parser.add_argument("--seed", type=int, default=2026062601)
    parser.add_argument("--train-start-ts", type=int, default=1759190400)
    parser.add_argument("--month-start-ts", type=int, default=1780272000)
    parser.add_argument("--out", default="reports/gc_15m_trend_bias_random_64k_20260626.json")
    args = parser.parse_args()

    raw = load_json(args.data)
    train_start_idx = int(np.searchsorted(raw.index.view("int64") // 10**9, args.train_start_ts))
    month_start_idx = int(np.searchsorted(raw.index.view("int64") // 10**9, args.month_start_ts))
    refs = {
        "buy_hold": {
            "full": buy_hold_pnl(raw, 300, len(raw)),
            "train": buy_hold_pnl(raw, max(train_start_idx, 300), len(raw)),
            "oos": buy_hold_pnl(raw, 300, max(train_start_idx, 301)),
            "month": buy_hold_pnl(raw, max(month_start_idx, 300), len(raw)),
        }
    }
    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))
    run_args = vars(args)
    results = []
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(run_worker, idx, run_args, count): count for idx, count in enumerate(trial_counts)}
        for future in as_completed(futures):
            rows = future.result()
            completed += futures[future]
            results.extend(rows)
            if rows:
                print(json.dumps(progress_row(rows[0])), flush=True)

    ranked = sorted(results, key=lambda row: row["score"], reverse=True)
    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": completed,
        "workers": workers,
        "chunk_trials": args.chunk_trials,
        "min_trades": args.min_trades,
        "train_start_ts": args.train_start_ts,
        "month_start_ts": args.month_start_ts,
        "assumptions": {
            "initial_capital": INITIAL_CAPITAL,
            "point_value": POINT_VALUE,
            "commission_per_side": COMMISSION_PER_SIDE,
            "slippage_ticks_per_side": SLIPPAGE_TICKS,
            "tick_size": TICK_SIZE,
            "fill_model": "entry at signal close; intrabar hard/trailing stops; close exits at signal close",
        },
        "buy_hold": refs["buy_hold"],
        "best": ranked[0] if ranked else None,
        "top10": ranked[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, default=json_default) + "\n")
    print(json.dumps({"out": args.out, "completed_trials": completed, "best": progress_row(ranked[0]) if ranked else None}, indent=2))


if __name__ == "__main__":
    main()
