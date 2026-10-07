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


def rsi(close, length):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(int(length), min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(int(length), min_periods=1).mean()
    rs = gain / (loss + 1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def atr(df, length):
    prev_close = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=int(length), adjust=False).mean()


def stoch(df, length):
    lo = df["low"].rolling(int(length), min_periods=1).min()
    hi = df["high"].rolling(int(length), min_periods=1).max()
    return 100.0 * (df["close"] - lo) / (hi - lo + 1e-10)


def williams(df, length):
    hi = df["high"].rolling(int(length), min_periods=1).max()
    lo = df["low"].rolling(int(length), min_periods=1).min()
    return -100.0 * (hi - df["close"]) / (hi - lo + 1e-10)


def macd_hist(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    return line - ema(line, signal)


def adx(df, length):
    prev_close = df["close"].shift(1).fillna(df["close"])
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_s = tr.rolling(int(length), min_periods=1).mean()
    up_move = df["high"] - df["high"].shift(1)
    down_move = df["low"].shift(1) - df["low"]
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100.0 * plus_dm.rolling(int(length), min_periods=1).mean() / (atr_s + 1e-10)
    minus_di = 100.0 * minus_dm.rolling(int(length), min_periods=1).mean() / (atr_s + 1e-10)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.rolling(int(length), min_periods=1).mean().fillna(0.0)


def norm_minmax(series, length):
    lo = series.rolling(int(length), min_periods=1).min()
    hi = series.rolling(int(length), min_periods=1).max()
    out = 2.0 * (series - lo) / (hi - lo + 1e-10) - 1.0
    return out.clip(-1.0, 1.0).fillna(0.0)


def aroon_osc(df, length):
    length = int(length)

    def high_pos(x):
        return np.argmax(x) / max(length, 1) * 100.0

    def low_pos(x):
        return np.argmin(x) / max(length, 1) * 100.0

    up = df["high"].rolling(length + 1, min_periods=1).apply(high_pos, raw=True)
    down = df["low"].rolling(length + 1, min_periods=1).apply(low_pos, raw=True)
    return up - down


def mfi(df, length):
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    flow = typical * df["volume"].fillna(0.0)
    pos = flow.where(typical > typical.shift(1), 0.0).rolling(int(length), min_periods=1).sum()
    neg = flow.where(typical < typical.shift(1), 0.0).rolling(int(length), min_periods=1).sum()
    return 100.0 - 100.0 / (1.0 + pos / (neg + 1e-10))


def load_tv_json(path):
    payload = json.load(open(path))
    bars = payload["bars"]
    df = pd.DataFrame(bars)
    df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("datetime")
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def build_features(df):
    out = df.copy()
    out["ret"] = out["close"].pct_change().fillna(0.0)
    out["atr14"] = atr(out, 14)
    out["adx14"] = adx(out, 14)
    out["rsi14"] = rsi(out["close"], 14)
    out["mfi14"] = mfi(out, 14)
    out["macdh"] = macd_hist(out["close"])
    out["obv"] = np.sign(out["close"].diff().fillna(0.0)).mul(out["volume"]).cumsum()
    out["obv_ema"] = ema(out["obv"], 21)
    out["vwap_num"] = ((out["high"] + out["low"] + out["close"]) / 3.0 * out["volume"]).groupby(out.index.date).cumsum()
    out["vwap_den"] = out["volume"].groupby(out.index.date).cumsum().replace(0, np.nan)
    out["vwap"] = (out["vwap_num"] / out["vwap_den"]).ffill().fillna(out["close"])

    roc_norm = norm_minmax(out["close"].pct_change(10) * 100.0, 50)
    macd_norm = norm_minmax(out["macdh"], 50)
    aroon_norm = aroon_osc(out, 25) / 100.0
    trend = (roc_norm + macd_norm + aroon_norm) / 3.0
    reversion = ((out["rsi14"] - 50.0) / 50.0 + (stoch(out, 14) - 50.0) / 50.0 + (williams(out, 14) + 50.0) / 50.0) / 3.0
    weight = (out["adx14"] / 100.0).clip(0.0, 1.0)
    out["arwo"] = (weight * trend + (1.0 - weight) * reversion).rolling(3, min_periods=1).mean().clip(-1.0, 1.0)
    out["vel"] = out["arwo"].diff().fillna(0.0)

    for tf, label in [("60min", "h1"), ("240min", "h4")]:
        htf = out[["open", "high", "low", "close", "volume"]].resample(tf).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        htf[f"{label}_ema_fast"] = ema(htf["close"], 21)
        htf[f"{label}_ema_slow"] = ema(htf["close"], 55)
        htf[f"{label}_rsi"] = rsi(htf["close"], 14)
        htf[f"{label}_macdh"] = macd_hist(htf["close"])
        htf[f"{label}_adx"] = adx(htf, 14)
        cols = [f"{label}_ema_fast", f"{label}_ema_slow", f"{label}_rsi", f"{label}_macdh", f"{label}_adx"]
        out = out.join(htf[cols].reindex(out.index, method="ffill"))
    return out.ffill().fillna(0.0)


@dataclass
class Result:
    total_return: float
    n_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_like: float


def backtest(data, p, start=0, end=None):
    if end is None:
        end = len(data["close"])
    close = data["close"]
    high = data["high"]
    low = data["low"]
    atrv = data["atr"]
    pos = 0
    entry = 0.0
    high_water = 0.0
    low_water = 0.0
    last_exit = -10_000
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    pnls = []

    for i in range(max(start, 220), end):
        if pos:
            high_water = max(high_water, high[i])
            low_water = min(low_water, low[i])
            exit_price = None
            if pos == 1:
                stop = entry - p["stop_atr"] * atrv[i]
                target = entry + p["tp_atr"] * atrv[i]
                if low[i] <= stop:
                    exit_price = stop
                elif high[i] >= target:
                    exit_price = target
                elif high_water >= entry + p["trail_start_atr"] * atrv[i] and low[i] <= high_water - p["trail_atr"] * atrv[i]:
                    exit_price = high_water - p["trail_atr"] * atrv[i]
                elif data["long_exit"][i]:
                    exit_price = close[i]
            else:
                stop = entry + p["stop_atr"] * atrv[i]
                target = entry - p["tp_atr"] * atrv[i]
                if high[i] >= stop:
                    exit_price = stop
                elif low[i] <= target:
                    exit_price = target
                elif low_water <= entry - p["trail_start_atr"] * atrv[i] and high[i] >= low_water + p["trail_atr"] * atrv[i]:
                    exit_price = low_water + p["trail_atr"] * atrv[i]
                elif data["short_exit"][i]:
                    exit_price = close[i]

            if exit_price is not None:
                pnl = (exit_price / entry - 1.0) * pos
                pnl -= p["cost_bps"] / 10_000.0
                equity *= max(0.01, 1.0 + pnl)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)
                pnls.append(pnl * 100.0)
                pos = 0
                last_exit = i

        if pos == 0 and i - last_exit >= p["cooldown"]:
            if data["long_entry"][i]:
                pos = 1
                entry = close[i]
                high_water = close[i]
                low_water = close[i]
            elif p["allow_short"] and data["short_entry"][i]:
                pos = -1
                entry = close[i]
                high_water = close[i]
                low_water = close[i]

    if pos:
        pnl = (close[end - 1] / entry - 1.0) * pos - p["cost_bps"] / 10_000.0
        equity *= max(0.01, 1.0 + pnl)
        pnls.append(pnl * 100.0)

    if not pnls:
        return Result(-100.0, 0, 0.0, 0.0, 100.0, -100.0)
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses)) or 1e-9
    total_return = (equity - 1.0) * 100.0
    mean = float(np.mean(pnls))
    std = float(np.std(pnls)) or 1e-9
    return Result(total_return, len(pnls), len(wins) / len(pnls) * 100.0, gross_profit / gross_loss, max_dd, mean / std * math.sqrt(len(pnls)))


def make_signals(feat, p):
    close = feat["close"]
    ema_fast = ema(close, p["ema_fast"])
    ema_slow = ema(close, p["ema_slow"])
    ema_regime = ema(close, p["ema_regime"])
    don_high = feat["high"].rolling(p["donchian"], min_periods=1).max().shift(1)
    don_low = feat["low"].rolling(p["donchian"], min_periods=1).min().shift(1)
    vol_ma = feat["volume"].rolling(p["vol_len"], min_periods=1).mean()
    vwap = feat["vwap"]
    arwo = feat["arwo"]
    vel = feat["vel"]
    vel_std = vel.rolling(p["vel_std"], min_periods=1).std().fillna(0.0)

    h1_bull = (feat["h1_ema_fast"] > feat["h1_ema_slow"]) & (feat["h1_macdh"] > p["h1_macd_floor"])
    h1_bear = (feat["h1_ema_fast"] < feat["h1_ema_slow"]) & (feat["h1_macdh"] < -p["h1_macd_floor"])
    h4_bull = (feat["h4_ema_fast"] > feat["h4_ema_slow"]) & (feat["h4_rsi"] > p["h4_rsi_long"])
    h4_bear = (feat["h4_ema_fast"] < feat["h4_ema_slow"]) & (feat["h4_rsi"] < p["h4_rsi_short"])
    vol_ok = feat["volume"] > vol_ma * p["vol_mult"]
    obv_bull = feat["obv"] > feat["obv_ema"]
    obv_bear = feat["obv"] < feat["obv_ema"]
    trend_long = (ema_fast > ema_slow) & (close > ema_regime) & (feat["adx14"] > p["adx_min"])
    trend_short = (ema_fast < ema_slow) & (close < ema_regime) & (feat["adx14"] > p["adx_min"])
    arwo_long = ((arwo.shift(1) < p["arwo_long_cross"]) & (arwo >= p["arwo_long_cross"])) | ((arwo > p["arwo_long_floor"]) & (vel > vel_std * p["vel_mult"]))
    arwo_short = ((arwo.shift(1) > p["arwo_short_cross"]) & (arwo <= p["arwo_short_cross"])) | ((arwo < p["arwo_short_ceiling"]) & (vel < -vel_std * p["vel_mult"]))
    breakout_long = (close > don_high) & (feat["macdh"] > p["macd_floor"])
    breakout_short = (close < don_low) & (feat["macdh"] < -p["macd_floor"])
    pullback_long = (close > ema_slow) & (close < ema_fast + p["pullback_atr"] * feat["atr14"]) & (feat["rsi14"] > p["rsi_long"])
    pullback_short = (close < ema_slow) & (close > ema_fast - p["pullback_atr"] * feat["atr14"]) & (feat["rsi14"] < p["rsi_short"])

    if p["mode"] == "breakout":
        long_entry = trend_long & h1_bull & h4_bull & breakout_long
        short_entry = trend_short & h1_bear & h4_bear & breakout_short
    elif p["mode"] == "pullback":
        long_entry = trend_long & h1_bull & (arwo_long | pullback_long)
        short_entry = trend_short & h1_bear & (arwo_short | pullback_short)
    else:
        long_entry = (trend_long | h4_bull) & h1_bull & (arwo_long | breakout_long)
        short_entry = (trend_short | h4_bear) & h1_bear & (arwo_short | breakout_short)

    if p["require_h4"]:
        long_entry &= h4_bull
        short_entry &= h4_bear
    if p["require_vol"]:
        long_entry &= vol_ok
        short_entry &= vol_ok
    if p["require_obv"]:
        long_entry &= obv_bull
        short_entry &= obv_bear
    if p["require_vwap"]:
        long_entry &= close > vwap
        short_entry &= close < vwap

    long_exit = (ema_fast < ema_slow) | (arwo < p["long_exit_arwo"]) | (feat["rsi14"] > p["rsi_take_long"])
    short_exit = (ema_fast > ema_slow) | (arwo > p["short_exit_arwo"]) | (feat["rsi14"] < p["rsi_take_short"])

    return {
        "open": feat["open"].to_numpy(float),
        "high": feat["high"].to_numpy(float),
        "low": feat["low"].to_numpy(float),
        "close": close.to_numpy(float),
        "atr": feat["atr14"].to_numpy(float),
        "long_entry": long_entry.fillna(False).to_numpy(bool),
        "short_entry": short_entry.fillna(False).to_numpy(bool),
        "long_exit": long_exit.fillna(False).to_numpy(bool),
        "short_exit": short_exit.fillna(False).to_numpy(bool),
    }


def suggest_params(trial):
    return {
        "mode": trial.suggest_categorical("mode", ["breakout", "pullback", "hybrid"]),
        "allow_short": trial.suggest_categorical("allow_short", [True, False]),
        "ema_fast": trial.suggest_int("ema_fast", 5, 55),
        "ema_slow": trial.suggest_int("ema_slow", 21, 160),
        "ema_regime": trial.suggest_int("ema_regime", 80, 260),
        "donchian": trial.suggest_int("donchian", 8, 96),
        "vol_len": trial.suggest_int("vol_len", 8, 80),
        "vol_mult": trial.suggest_float("vol_mult", 0.2, 2.0),
        "vel_std": trial.suggest_int("vel_std", 5, 60),
        "vel_mult": trial.suggest_float("vel_mult", 0.0, 2.5),
        "adx_min": trial.suggest_float("adx_min", 0.0, 35.0),
        "arwo_long_cross": trial.suggest_float("arwo_long_cross", -0.55, 0.2),
        "arwo_short_cross": trial.suggest_float("arwo_short_cross", -0.2, 0.55),
        "arwo_long_floor": trial.suggest_float("arwo_long_floor", -0.8, 0.4),
        "arwo_short_ceiling": trial.suggest_float("arwo_short_ceiling", -0.4, 0.8),
        "macd_floor": trial.suggest_float("macd_floor", 0.0, 80.0),
        "h1_macd_floor": trial.suggest_float("h1_macd_floor", 0.0, 120.0),
        "h4_rsi_long": trial.suggest_float("h4_rsi_long", 35.0, 62.0),
        "h4_rsi_short": trial.suggest_float("h4_rsi_short", 38.0, 65.0),
        "rsi_long": trial.suggest_float("rsi_long", 35.0, 70.0),
        "rsi_short": trial.suggest_float("rsi_short", 30.0, 65.0),
        "rsi_take_long": trial.suggest_float("rsi_take_long", 55.0, 90.0),
        "rsi_take_short": trial.suggest_float("rsi_take_short", 10.0, 45.0),
        "long_exit_arwo": trial.suggest_float("long_exit_arwo", -0.9, 0.1),
        "short_exit_arwo": trial.suggest_float("short_exit_arwo", -0.1, 0.9),
        "pullback_atr": trial.suggest_float("pullback_atr", -1.0, 2.5),
        "require_h4": trial.suggest_categorical("require_h4", [True, False]),
        "require_vol": trial.suggest_categorical("require_vol", [True, False]),
        "require_obv": trial.suggest_categorical("require_obv", [True, False]),
        "require_vwap": trial.suggest_categorical("require_vwap", [True, False]),
        "stop_atr": trial.suggest_float("stop_atr", 0.5, 8.0),
        "tp_atr": trial.suggest_float("tp_atr", 0.8, 16.0),
        "trail_start_atr": trial.suggest_float("trail_start_atr", 0.5, 12.0),
        "trail_atr": trial.suggest_float("trail_atr", 0.4, 8.0),
        "cooldown": trial.suggest_int("cooldown", 0, 40),
        "cost_bps": 4.0,
    }


def objective_factory(feat, min_trades):
    n = len(feat)
    folds = [(int(n * 0.00), int(n * 0.55)), (int(n * 0.25), int(n * 0.78)), (int(n * 0.45), n)]
    test_slices = [(int(n * 0.55), int(n * 0.72)), (int(n * 0.78), int(n * 0.90)), (int(n * 0.90), n)]

    def objective(trial):
        p = suggest_params(trial)
        if p["ema_fast"] >= p["ema_slow"]:
            raise optuna.TrialPruned()
        data = make_signals(feat, p)
        train_results = [backtest(data, p, a, b) for a, b in folds]
        test_results = [backtest(data, p, a, b) for a, b in test_slices]
        full = backtest(data, p, 0, n)
        if full.n_trades < min_trades:
            raise optuna.TrialPruned()
        avg_test_return = np.mean([r.total_return for r in test_results])
        min_test_return = min(r.total_return for r in test_results)
        avg_pf = np.mean([min(r.profit_factor, 10.0) for r in test_results])
        no_trade_penalty = sum(1 for r in test_results if r.n_trades == 0) * 25.0
        train_test_gap = abs(np.mean([r.total_return for r in train_results]) - avg_test_return)
        dd_penalty = max(r.max_drawdown for r in test_results)
        score = avg_test_return + min_test_return * 0.7 + avg_pf * 4.0 + full.total_return * 0.15 - dd_penalty * 0.65 - train_test_gap * 0.12 - no_trade_penalty
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("tests", [r.__dict__ for r in test_results])
        return score

    return objective


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_btcusd_15m_500.json")
    parser.add_argument("--trials", type=int, default=3000)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--min-trades", type=int, default=8)
    parser.add_argument("--out", default="reports/mtf_velocity_optuna_best.json")
    args = parser.parse_args()

    df = load_tv_json(args.data)
    feat = build_features(df)
    sampler = optuna.samplers.TPESampler(seed=42, multivariate=True, group=True, n_startup_trials=max(100, args.jobs * 4))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=100))
    study.optimize(objective_factory(feat, args.min_trades), n_trials=args.trials, n_jobs=args.jobs, show_progress_bar=True)
    best = study.best_trial
    params = dict(best.params)
    params["cost_bps"] = 4.0
    data = make_signals(feat, params)
    full = backtest(data, params, 0, len(feat))
    n = len(feat)
    splits = {
        "full": full.__dict__,
        "train_0_60": backtest(data, params, 0, int(n * 0.6)).__dict__,
        "test_60_80": backtest(data, params, int(n * 0.6), int(n * 0.8)).__dict__,
        "test_80_100": backtest(data, params, int(n * 0.8), n).__dict__,
    }
    payload = {
        "source_data": args.data,
        "rows": len(feat),
        "start": str(feat.index.min()),
        "end": str(feat.index.max()),
        "best_score": best.value,
        "params": params,
        "metrics": splits,
        "cpu_jobs": args.jobs,
        "trials": len(study.trials),
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
