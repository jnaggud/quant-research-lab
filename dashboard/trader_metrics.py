"""Normalize TradingView strategy reports into dashboard trader statistics."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def summarize_report(report: dict, initial_capital: float = 50_000.0) -> dict:
    data = report["reportData"]
    perf = data["performance"]
    overall = perf["all"]
    trades = []
    equity = initial_capital
    peak = initial_capital
    win_streak = loss_streak = max_win_streak = max_loss_streak = 0
    sleeve = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    exits = defaultdict(lambda: {"pnl": 0.0, "trades": 0})
    monthly = defaultdict(float)
    equity_curve = []
    for number, trade in enumerate(data.get("trades", []), 1):
        pnl = float(trade["tp"]["v"])
        direction = "LONG" if trade["e"]["tp"] == "le" else "SHORT"
        name = trade["e"]["c"]
        exit_name = trade["x"]["c"]
        equity += pnl
        peak = max(peak, equity)
        drawdown = equity / peak - 1
        if pnl > 0:
            win_streak += 1; loss_streak = 0; max_win_streak = max(max_win_streak, win_streak)
        else:
            loss_streak += 1; win_streak = 0; max_loss_streak = max(max_loss_streak, loss_streak)
        sleeve[name]["pnl"] += pnl; sleeve[name]["trades"] += 1; sleeve[name]["wins"] += int(pnl > 0)
        exits[exit_name]["pnl"] += pnl; exits[exit_name]["trades"] += 1
        month = _iso(trade["x"]["tm"])[:7]
        monthly[month] += pnl
        row = {"number": number, "entry_time": _iso(trade["e"]["tm"]),
               "exit_time": _iso(trade["x"]["tm"]), "direction": direction,
               "sleeve": name, "exit_reason": exit_name,
               "entry_price": float(trade["e"]["p"]), "exit_price": float(trade["x"]["p"]),
               "pnl": pnl, "pnl_percent": float(trade["tp"]["p"]),
               "bars": int(trade["bars"]) if "bars" in trade else None, "runup": float(trade["rn"]["v"]),
               "drawdown": float(trade["dd"]["v"]), "equity": equity,
               "equity_drawdown": drawdown}
        trades.append(row)
        equity_curve.append({"time": row["exit_time"], "equity": equity,
                             "drawdown": drawdown, "pnl": pnl})
    pnl_values = np.array([x["pnl"] for x in trades], dtype=float)
    positive = pnl_values[pnl_values > 0]
    negative = pnl_values[pnl_values < 0]
    downside = float(np.std(negative)) if len(negative) else 0.0
    stats = {
        "net_profit": float(overall["netProfit"]), "net_profit_percent": float(overall["netProfitPercent"]),
        "gross_profit": float(overall["grossProfit"]), "gross_loss": float(overall["grossLoss"]),
        "profit_factor": float(overall["profitFactor"]), "trades": int(overall["totalTrades"]),
        "wins": int(overall["numberOfWiningTrades"]), "losses": int(overall["numberOfLosingTrades"]),
        "win_rate": float(overall["percentProfitable"]), "expectancy": float(overall["avgTrade"]),
        "avg_win": float(overall["avgWinTrade"]), "avg_loss": -float(overall["avgLosTrade"]),
        "payoff_ratio": float(overall["ratioAvgWinAvgLoss"]),
        "max_drawdown": float(perf["maxStrategyDrawDown"]),
        "max_drawdown_percent": float(perf["maxStrategyDrawDownPercent"]),
        "max_runup": float(perf["maxStrategyRunUp"]), "sharpe": perf.get("sharpeRatio"),
        "commission": float(overall["commissionPaid"]), "avg_bars": float(overall["avgBarsInTrade"]),
        "max_win_streak": max_win_streak, "max_loss_streak": max_loss_streak,
        "current_streak": win_streak if win_streak else -loss_streak,
        "recovery_factor": float(overall["netProfit"] / perf["maxStrategyDrawDown"]),
        "downside_trade_volatility": downside,
    }
    ranked_sleeves = [{**values, "name": name,
                       "win_rate": values["wins"] / values["trades"]}
                      for name, values in sleeve.items()]
    return {"stats": stats, "best_trade": max(trades, key=lambda x: x["pnl"]),
            "worst_trade": min(trades, key=lambda x: x["pnl"]),
            "long": perf["long"], "short": perf["short"], "equity": equity_curve,
            "monthly": [{"month": key, "pnl": value} for key, value in sorted(monthly.items())],
            "sleeves": sorted(ranked_sleeves, key=lambda x: x["pnl"], reverse=True),
            "exits": sorted([{**value, "name": key} for key, value in exits.items()],
                            key=lambda x: x["pnl"], reverse=True),
            "recent_trades": list(reversed(trades[-30:])), "all_trade_pnl": pnl_values.tolist()}
