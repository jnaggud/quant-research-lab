#!/usr/bin/env python3
import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import optuna
import pandas as pd


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


def cross_over(a, b):
    return (a.shift(1) <= b.shift(1)) & (a > b)


def cross_under(a, b):
    return (a.shift(1) >= b.shift(1)) & (a < b)


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
    out["stoch_up"] = cross_over(out["stoch_k"], out["stoch_d"])
    out["stoch_down"] = cross_under(out["stoch_k"], out["stoch_d"])
    out["rsi_up40"] = cross_over(out["rsi"], pd.Series(40.0, index=out.index))
    out["rsi_down60"] = cross_under(out["rsi"], pd.Series(60.0, index=out.index))
    out["willr_up80"] = cross_over(out["willr"], pd.Series(-80.0, index=out.index))
    out["willr_down20"] = cross_under(out["willr"], pd.Series(-20.0, index=out.index))
    return out


@dataclass
class Result:
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float


def make_signals(feat, params):
    h4 = resample_ohlcv(feat, "240min")
    day = resample_ohlcv(feat, "1D")
    h4_signal = pd.Series(
        np.where(ema(h4["close"], params["h4_fast"]) > ema(h4["close"], params["h4_slow"]), 1, -1),
        index=h4.index,
    ).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
    day_signal = pd.Series(
        np.where(ema(day["close"], params["d_fast"]) > ema(day["close"], params["d_slow"]), 1, -1),
        index=day.index,
    ).shift(1).reindex(feat.index, method="ffill").fillna(0).astype(int)
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
    return regime.to_numpy(int), valley.to_numpy(int), peak.to_numpy(int)


def backtest(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    regime, valley, peak = make_signals(feat, params)
    pos = 0
    entry = 0.0
    last_trade = -100000
    equity = 1.0
    peak_equity = 1.0
    max_dd = 0.0
    pnls = []

    for i in range(max(start, 300), end):
        if pos:
            exit_price = None
            if pos == 1:
                stop = entry - params["stop_atr"] * atrv[i]
                target = entry + params["target_atr"] * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif peak[i] >= params["exit_score"] or regime[i] <= 0:
                    exit_price = close[i]
            else:
                stop = entry + params["stop_atr"] * atrv[i]
                target = entry - params["target_atr"] * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif valley[i] >= params["exit_score"] or regime[i] >= 0:
                    exit_price = close[i]
            if exit_price is not None:
                pnl = (exit_price / entry - 1.0) * pos - params["cost_bps"] / 10_000.0
                equity *= max(0.01, 1.0 + pnl)
                pnls.append(pnl * 100.0)
                peak_equity = max(peak_equity, equity)
                max_dd = max(max_dd, (peak_equity - equity) / peak_equity * 100.0)
                pos = 0
                last_trade = i

        if pos == 0 and i - last_trade >= params["cooldown"]:
            if regime[i] == 1 and valley[i] >= params["entry_score"]:
                pos = 1
                entry = close[i]
            elif params["allow_short"] and regime[i] == -1 and peak[i] >= params["entry_score"]:
                pos = -1
                entry = close[i]

    if pos:
        pnl = (close[end - 1] / entry - 1.0) * pos - params["cost_bps"] / 10_000.0
        equity *= max(0.01, 1.0 + pnl)
        pnls.append(pnl * 100.0)

    if not pnls:
        return Result(-100.0, 0, 0.0, 0.0, 100.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    return Result((equity - 1.0) * 100.0, len(pnls), len(wins) / len(pnls) * 100.0, sum(wins) / (abs(sum(losses)) or 1e-9), max_dd)


def suggest(trial):
    return {
        "h4_fast": trial.suggest_int("h4_fast", 4, 16),
        "h4_slow": trial.suggest_int("h4_slow", 10, 40),
        "d_fast": trial.suggest_int("d_fast", 8, 24),
        "d_slow": trial.suggest_int("d_slow", 20, 70),
        "entry_score": trial.suggest_int("entry_score", 2, 4),
        "exit_score": trial.suggest_int("exit_score", 2, 4),
        "stoch_low": trial.suggest_float("stoch_low", 20.0, 45.0),
        "stoch_high": trial.suggest_float("stoch_high", 55.0, 85.0),
        "rsi_low": trial.suggest_float("rsi_low", 28.0, 45.0),
        "rsi_high": trial.suggest_float("rsi_high", 55.0, 75.0),
        "willr_low": trial.suggest_float("willr_low", -90.0, -65.0),
        "willr_high": trial.suggest_float("willr_high", -35.0, -10.0),
        "bb_mult": trial.suggest_float("bb_mult", 1.4, 2.8),
        "atr_displace": trial.suggest_float("atr_displace", 0.4, 1.8),
        "stop_atr": trial.suggest_float("stop_atr", 1.2, 5.5),
        "target_atr": trial.suggest_float("target_atr", 1.5, 10.0),
        "cooldown": trial.suggest_int("cooldown", 4, 64),
        "allow_short": trial.suggest_categorical("allow_short", [True, False]),
        "cost_bps": 4.0,
    }


def objective_factory(feat, min_trades):
    n = len(feat)
    splits = [(300, int(n * 0.25)), (int(n * 0.25), int(n * 0.5)), (int(n * 0.5), int(n * 0.75)), (int(n * 0.75), n)]

    def objective(trial):
        params = suggest(trial)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n)
        if full.n_trades < min_trades:
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, a, b) for a, b in splits]
        min_ret = min(r.total_return for r in folds)
        avg_ret = float(np.mean([r.total_return for r in folds]))
        min_pf = min(r.profit_factor for r in folds)
        dd = max(r.max_drawdown for r in folds)
        overtrade = max(0, full.n_trades - 180) * 0.2
        score = full.total_return * 0.7 + avg_ret * 1.5 + min_ret * 3.0 + min(min_pf, 4.0) * 18.0 - dd * 1.8 - overtrade
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("folds", [r.__dict__ for r in folds])
        return score

    return objective


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/bitstamp_btcusd_15m_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--out", default="reports/mtf_15m_reversal_best.json")
    parser.add_argument("--seed", type=int, default=20260507)
    args = parser.parse_args()

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(args.data))
    sampler = optuna.samplers.TPESampler(seed=args.seed, multivariate=True, group=True, n_startup_trials=100)
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=100))
    study.optimize(objective_factory(feat, args.min_trades), n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["cost_bps"] = 4.0
    n = len(feat)
    payload = {
        "source_data": args.data,
        "rows": n,
        "start": str(feat.index.min()),
        "end": str(feat.index.max()),
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
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
