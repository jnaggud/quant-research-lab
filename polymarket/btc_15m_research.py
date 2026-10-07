"""Chronological, fee-aware research for BTC 15-minute Up/Down contracts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


FEATURES = ["market_logit", "spot_move", "mom_5", "mom_15", "mom_60", "vol_60",
            "abs_move_vol", "elapsed_fraction"]


def crypto_taker_fee(shares: float, price: float) -> float:
    return shares * 0.07 * price * (1 - price)


def build_dataset(root: Path, entry_seconds: int) -> pd.DataFrame:
    markets = json.loads((root / "markets.json").read_text())
    histories = json.loads((root / "up_price_history.json").read_text())
    spot = pd.read_csv(root / "btcusdt_1m.csv.gz")
    spot.index = pd.to_datetime(spot["open_time"].astype("int64"), unit="ms", utc=True)
    close = spot["close"].astype(float).sort_index()
    open_price = spot["open"].astype(float).sort_index()
    returns = np.log(close / close.shift(1))
    rows = []
    for market in markets:
        points = histories.get(market["up_token"], [])
        cutoff = market["start_ts"] + entry_seconds
        eligible = [x for x in points if cutoff - 60 <= x["t"] <= cutoff]
        if not eligible:
            continue
        quote = eligible[-1]
        when = pd.Timestamp(market["start_ts"], unit="s", tz="UTC")
        quote_when = pd.Timestamp(quote["t"], unit="s", tz="UTC")
        entry_when = quote_when.floor("min") - pd.Timedelta(minutes=1)
        if when.floor("min") not in open_price.index or entry_when not in close.index:
            continue
        p = float(np.clip(quote["p"], .005, .995))
        sigma = returns.loc[:entry_when].tail(60).std()
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        spot_move = np.log(close.loc[entry_when] / open_price.loc[when.floor("min")])
        row = {**market, "quote_ts": int(quote["t"]), "up_price": p,
               "quote_staleness": cutoff - int(quote["t"]),
               "market_logit": np.log(p / (1 - p)), "spot_move": spot_move,
               "mom_5": returns.loc[:entry_when].tail(5).sum(),
               "mom_15": returns.loc[:entry_when].tail(15).sum(),
               "mom_60": returns.loc[:entry_when].tail(60).sum(), "vol_60": sigma,
               "abs_move_vol": abs(spot_move) / (sigma * np.sqrt(max(entry_seconds / 60, 1))),
               "elapsed_fraction": entry_seconds / 900}
        rows.append(row)
    return pd.DataFrame(rows).sort_values("start_ts").reset_index(drop=True)


def evaluate(frame: pd.DataFrame, entry_seconds: int) -> dict:
    n = len(frame); train_end = int(.6 * n); validation_end = int(.8 * n)
    train = frame.iloc[:train_end].copy()
    validation = frame.iloc[train_end:validation_end].copy()
    holdout = frame.iloc[validation_end:].copy()
    model = make_pipeline(StandardScaler(), LogisticRegression(C=.2, max_iter=1000))
    model.fit(train[FEATURES], train["outcome"])
    for part in (validation, holdout):
        part.loc[:, "model_probability"] = model.predict_proba(part[FEATURES])[:, 1]
    best = None
    for edge in np.arange(.02, .201, .01):
        result = trade_metrics(validation, edge)
        score = result["net"] - 2 * abs(result["max_drawdown"])
        if result["trades"] >= 30 and (best is None or score > best[0]):
            best = (score, edge, result)
    if best is None:
        raise ValueError("no validation threshold produced 30 trades")
    edge = best[1]
    baseline_threshold, baseline_validation = select_favorite_baseline(validation)
    return {"entry_seconds": entry_seconds, "observations": n, "threshold": edge,
            "train": probability_metrics(train, model.predict_proba(train[FEATURES])[:, 1]),
            "validation": {**probability_metrics(validation, validation["model_probability"]),
                           **trade_metrics(validation, edge)},
            "holdout": {**probability_metrics(holdout, holdout["model_probability"]),
                        **trade_metrics(holdout, edge),
                        "slippage_stress": {
                            str(cents): trade_metrics(holdout, edge, cents / 100)
                            for cents in (1, 2, 3)}},
            "favorite_baseline": {"threshold": baseline_threshold,
                                  "validation": baseline_validation,
                                  "holdout": favorite_metrics(holdout, baseline_threshold)}}


def probability_metrics(frame, probability) -> dict:
    return {"brier": float(brier_score_loss(frame["outcome"], probability)),
            "log_loss": float(log_loss(frame["outcome"], probability)),
            "base_rate": float(frame["outcome"].mean())}


def trade_metrics(frame: pd.DataFrame, threshold: float, slippage: float = .01) -> dict:
    p_model = frame["model_probability"].to_numpy()
    p_market = frame["up_price"].to_numpy()
    up_edge = p_model - p_market
    down_price = 1 - p_market
    down_edge = (1 - p_model) - down_price
    side = np.where(up_edge >= down_edge, 1, 0)
    edge = np.maximum(up_edge, down_edge)
    price = np.where(side == 1, p_market, down_price) + slippage
    take = (edge >= threshold) & (price < 1)
    outcome = frame["outcome"].to_numpy()
    win = np.where(side == 1, outcome, 1 - outcome)
    pnl = np.where(take, win - price - crypto_taker_fee(1, price), 0.0)
    selected = pnl[take]
    equity = np.cumsum(selected)
    drawdown = equity - np.maximum.accumulate(np.r_[0, equity])[-len(equity):] if len(equity) else np.array([])
    return {"trades": int(take.sum()), "net": float(selected.sum()),
            "avg_trade": float(selected.mean()) if len(selected) else 0.0,
            "win_rate": float((selected > 0).mean()) if len(selected) else 0.0,
            "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0}


def favorite_metrics(frame: pd.DataFrame, threshold: float, slippage: float = .01) -> dict:
    p_market = frame["up_price"].to_numpy()
    side = (p_market >= .5).astype(int)
    price = np.maximum(p_market, 1 - p_market) + slippage
    take = (np.maximum(p_market, 1 - p_market) >= threshold) & (price < 1)
    outcome = frame["outcome"].to_numpy()
    win = np.where(side == 1, outcome, 1 - outcome)
    selected = (win - price - crypto_taker_fee(1, price))[take]
    equity = np.cumsum(selected)
    peaks = np.maximum.accumulate(np.r_[0, equity])[-len(equity):] if len(equity) else []
    drawdown = equity - peaks if len(equity) else np.array([])
    return {"trades": int(take.sum()), "net": float(selected.sum()),
            "avg_trade": float(selected.mean()) if len(selected) else 0.0,
            "win_rate": float((selected > 0).mean()) if len(selected) else 0.0,
            "max_drawdown": float(drawdown.min()) if len(drawdown) else 0.0}


def select_favorite_baseline(validation: pd.DataFrame) -> tuple[float, dict]:
    candidates = []
    for threshold in np.arange(.55, .951, .05):
        result = favorite_metrics(validation, threshold)
        if result["trades"] >= 30:
            candidates.append((result["net"] - 2 * abs(result["max_drawdown"]), threshold, result))
    if not candidates:
        return .5, favorite_metrics(validation, .5)
    _, threshold, result = max(candidates, key=lambda x: x[0])
    return float(threshold), result


def main():
    root = Path("data/polymarket_crypto/btc_15m")
    results = []
    for seconds in (60, 180, 300, 600):
        frame = build_dataset(root, seconds)
        results.append(evaluate(frame, seconds))
    output = Path("reports/polymarket_btc_15m_research.json")
    output.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
