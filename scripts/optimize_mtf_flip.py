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


def load_json(path):
    payload = json.load(open(path))
    df = pd.DataFrame(payload["bars"])
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]].astype(float)


@dataclass
class Result:
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float


def resample_ohlcv(df, tf):
    return df.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def make_signal(df, params):
    htf = resample_ohlcv(df, params["tf"])
    htf_fast = ema(htf["close"], params["fast"])
    htf_slow = ema(htf["close"], params["slow"])
    raw = pd.Series(np.where(htf_fast > htf_slow, 1, -1), index=htf.index).shift(1)
    signal = raw.reindex(df.index, method="ffill").fillna(0).astype(int)

    if params["confirm"] != "none":
        confirm = resample_ohlcv(df, params["confirm"])
        confirm_fast = ema(confirm["close"], params["confirm_fast"])
        confirm_slow = ema(confirm["close"], params["confirm_slow"])
        confirm_sig = pd.Series(np.where(confirm_fast > confirm_slow, 1, -1), index=confirm.index).shift(1)
        confirm_signal = confirm_sig.reindex(df.index, method="ffill").fillna(0).astype(int)
        signal = signal.where(signal == confirm_signal, 0)

    if params["hold_bars"] > 0:
        changes = signal.ne(signal.shift(1)).cumsum()
        age = signal.groupby(changes).cumcount()
        signal = signal.where(age >= params["hold_bars"], signal.shift(1).fillna(0)).astype(int)
    return signal


def backtest(df, signal, start=0, end=None, cost_bps=4.0):
    if end is None:
        end = len(df)
    close = df["close"].iloc[start:end].to_numpy(float)
    desired = signal.iloc[start:end].to_numpy(int)
    if len(close) < 2:
        return Result(-100.0, 0, 0.0, 0.0, 100.0)
    position = 0
    entry = 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    pnls = []

    for i in range(1, len(close)):
        target = int(desired[i])
        if target != position:
            if position:
                pnl = (close[i] / entry - 1.0) * position - cost_bps / 10_000.0
                equity *= max(0.01, 1.0 + pnl)
                pnls.append(pnl * 100.0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)
                position = 0
            if target:
                position = target
                entry = close[i]

    if position:
        pnl = (close[-1] / entry - 1.0) * position - cost_bps / 10_000.0
        equity *= max(0.01, 1.0 + pnl)
        pnls.append(pnl * 100.0)

    if not pnls:
        return Result(-100.0, 0, 0.0, 0.0, 100.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    return Result(
        total_return=(equity - 1.0) * 100.0,
        n_trades=len(pnls),
        win_rate=len(wins) / len(pnls) * 100.0,
        profit_factor=sum(wins) / (abs(sum(losses)) or 1e-9),
        max_drawdown=max_dd,
    )


def suggest(trial):
    tf = trial.suggest_categorical("tf", ["60min", "120min", "240min", "1D"])
    fast = trial.suggest_int("fast", 3, 34)
    slow = trial.suggest_int("slow", 10, 120)
    confirm = trial.suggest_categorical("confirm", ["none", "240min", "1D"])
    return {
        "tf": tf,
        "fast": fast,
        "slow": slow,
        "confirm": confirm,
        "confirm_fast": trial.suggest_int("confirm_fast", 3, 34),
        "confirm_slow": trial.suggest_int("confirm_slow", 10, 120),
        "hold_bars": trial.suggest_int("hold_bars", 0, 4),
        "cost_bps": 4.0,
    }


def objective_factory(df, min_trades):
    n = len(df)
    warmup = 300
    slices = [
        (warmup, int(n * 0.25)),
        (int(n * 0.25), int(n * 0.50)),
        (int(n * 0.50), int(n * 0.75)),
        (int(n * 0.75), n),
    ]

    def objective(trial):
        params = suggest(trial)
        if params["fast"] >= params["slow"] or params["confirm_fast"] >= params["confirm_slow"]:
            raise optuna.TrialPruned()
        signal = make_signal(df, params)
        full = backtest(df, signal, warmup, n, params["cost_bps"])
        if full.n_trades < min_trades:
            raise optuna.TrialPruned()
        fold_results = [backtest(df, signal, a, b, params["cost_bps"]) for a, b in slices]
        min_fold_return = min(r.total_return for r in fold_results)
        min_pf = min(r.profit_factor for r in fold_results)
        max_dd = max(r.max_drawdown for r in fold_results)
        trade_penalty = max(0, full.n_trades - 180) * 0.25
        score = full.total_return + min_fold_return * 4.0 + min(min_pf, 5.0) * 20.0 - max_dd * 2.0 - trade_penalty
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("folds", [r.__dict__ for r in fold_results])
        return score

    return objective


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/bitstamp_btcusd_15m_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--out", default="reports/mtf_flip_optuna_best.json")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    df = load_json(args.data)
    sampler = optuna.samplers.TPESampler(seed=args.seed, multivariate=True, group=True, n_startup_trials=max(100, args.jobs * 4))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=100))
    study.optimize(objective_factory(df, args.min_trades), n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["cost_bps"] = 4.0
    signal = make_signal(df, params)
    n = len(df)
    payload = {
        "source_data": args.data,
        "rows": n,
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "best_score": best.value,
        "params": params,
        "metrics": {
            "full": backtest(df, signal, 300, n, 4.0).__dict__,
            "q1": backtest(df, signal, 300, int(n * 0.25), 4.0).__dict__,
            "q2": backtest(df, signal, int(n * 0.25), int(n * 0.50), 4.0).__dict__,
            "q3": backtest(df, signal, int(n * 0.50), int(n * 0.75), 4.0).__dict__,
            "q4": backtest(df, signal, int(n * 0.75), n, 4.0).__dict__,
        },
        "cpu_jobs": args.jobs,
        "trials": len(study.trials),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
