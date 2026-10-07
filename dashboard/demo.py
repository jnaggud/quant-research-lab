"""Deterministic synthetic inputs for the public dashboard; no market data."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path

import numpy as np

from dashboard.realtime_inference import infer_market_state, prepare_bars


def synthetic_bars(seed: int = 42, count: int = 768) -> list[dict]:
    """Generate artificial OHLCV bars with alternating volatility and drift."""
    if count < 201:
        raise ValueError("the dashboard needs at least 201 bars")
    rng = np.random.default_rng(seed)
    index = np.arange(count)
    drift = np.where((index // 128) % 3 == 0, 0.28, -0.06)
    volatility = np.where((index // 128) % 3 == 1, 2.8, 1.2)
    close = 5_000 + np.cumsum(drift + rng.normal(size=count) * volatility)
    opened = np.r_[5_000.0, close[:-1]]
    wick = rng.uniform(0.25, 2.0, count)
    start = 1_767_225_600  # 2026-01-01 UTC; an artificial continuous timeline.
    return [dict(time=start + i * 900, open=float(opened[i]),
                 high=float(max(opened[i], close[i]) + wick[i]),
                 low=float(min(opened[i], close[i]) - wick[i]),
                 close=float(close[i]), volume=int(rng.integers(500, 4_000)))
            for i in range(count)]


def synthetic_report() -> dict:
    """An artificial trade ledger for exercising report rendering, not C11 results."""
    bars = synthetic_bars()
    trades = []
    for number, entry in enumerate(range(200, len(bars) - 10, 8)):
        exit_index = entry + 6
        direction = 1 if number % 3 else -1
        a, b = bars[entry], bars[exit_index]
        pnl = round((b["close"] - a["open"]) * direction * 50 - 30, 2)
        trades.append({
            "e": {"tm": a["time"] * 1_000, "tp": "le" if direction == 1 else "se",
                  "p": a["open"], "c": "Synthetic trend" if direction == 1 else "Synthetic reversal"},
            "x": {"tm": b["time"] * 1_000, "p": b["close"], "c": "Scheduled demo exit"},
            "tp": {"v": pnl, "p": pnl / 50_000 * 100},
            "rn": {"v": max(pnl, 0) + 40}, "dd": {"v": min(pnl, 0) - 40},
            "cm": 5, "bars": exit_index - entry,
        })
    values = np.array([trade["tp"]["v"] for trade in trades])
    wins, losses = values[values > 0], values[values <= 0]
    equity = 50_000 + np.cumsum(values)
    peaks = np.maximum.accumulate(np.r_[50_000, equity])[1:]
    drawdown = peaks - equity
    overall = {
        "netProfit": float(values.sum()), "netProfitPercent": float(values.sum() / 50_000),
        "grossProfit": float(wins.sum()), "grossLoss": float(-losses.sum()),
        "profitFactor": float(wins.sum() / -losses.sum()), "totalTrades": len(values),
        "numberOfWiningTrades": len(wins), "numberOfLosingTrades": len(losses),
        "percentProfitable": float(len(wins) / len(values)),
        "avgTrade": float(values.mean()), "avgWinTrade": float(wins.mean()),
        "avgLosTrade": float(-losses.mean()), "ratioAvgWinAvgLoss": float(wins.mean() / -losses.mean()),
        "commissionPaid": 5 * len(values), "avgBarsInTrade": 6,
    }
    return {"source": {"name": "Synthetic demonstration ledger"}, "reportData": {
        "performance": {"all": overall, "long": {}, "short": {},
            "maxStrategyDrawDown": float(drawdown.max()),
            "maxStrategyDrawDownPercent": float((drawdown / peaks).max()),
            "maxStrategyRunUp": float(np.maximum(equity - 50_000, 0).max()),
            "sharpeRatio": None}, "trades": trades}}


@lru_cache(maxsize=1)
def live_payload() -> dict:
    frame = prepare_bars(synthetic_bars(), exclude_live_bar=True)
    snapshot, history = infer_market_state(frame)
    return {"ok": True, "live": False, "demo": True,
        "source": "Synthetic data · deterministic demo", "symbol": "DEMO", "interval": "15",
        "snapshot": snapshot.to_dict(),
        "history": json.loads(history.reset_index().to_json(orient="records", date_format="iso")),
        "received_at": snapshot.timestamp, "error": None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/demo"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "bars.json").write_text(json.dumps({"success": True, "synthetic": True,
        "symbol": "DEMO", "interval": "15", "bars": synthetic_bars()}, indent=2))
    (args.output / "report.json").write_text(json.dumps(synthetic_report(), indent=2))
    print(f"Wrote synthetic demonstration data to {args.output}")


if __name__ == "__main__":
    main()
