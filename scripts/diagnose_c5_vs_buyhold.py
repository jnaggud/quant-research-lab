#!/usr/bin/env python3
"""Diagnose why C5 is under/over-performing buy-and-hold on TV-parity data."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import POINT_VALUE, load_bars, run_c5_tv_compatible


def _bucket_trades(trades, index: pd.DatetimeIndex, freq: str) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for trade in trades:
        label = index[trade.exit_bar].tz_convert(None).to_period(freq).strftime("%Y-%m" if freq == "M" else "%Y-%m-%d")
        item = buckets[label]
        item["pnl"] += trade.pnl
        item["trades"] += 1
        item["wins"] += int(trade.pnl > 0)
    return [
        {
            "period": key,
            "pnl": round(value["pnl"], 2),
            "trades": value["trades"],
            "win_rate": round(value["wins"] / value["trades"] * 100.0, 2) if value["trades"] else 0.0,
        }
        for key, value in sorted(buckets.items())
    ]


def _group_stats(trades, key_fn) -> list[dict]:
    groups: dict[str, list] = defaultdict(list)
    for trade in trades:
        groups[key_fn(trade)].append(trade.pnl)
    rows = []
    for key, pnls in sorted(groups.items()):
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        rows.append(
            {
                "group": key,
                "trades": len(pnls),
                "net": round(sum(pnls), 2),
                "win_rate": round(len(wins) / len(pnls) * 100.0, 2) if pnls else 0.0,
                "avg_trade": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
                "profit_factor": round(sum(wins) / (abs(sum(losses)) or 1e-9), 4) if pnls else 0.0,
            }
        )
    return rows


def diagnose(args: argparse.Namespace) -> dict:
    bars = load_bars(args.data)
    result = run_c5_tv_compatible(args.data, daily_bars_path=args.daily_bars, h4_bars_path=args.h4_bars)
    trades = result.trades
    hold = float((bars["close"].iloc[-1] - bars["open"].iloc[0]) * POINT_VALUE)
    excess = result.net_profit - hold
    recent_start = bars.index[-1] - pd.Timedelta(days=args.recent_days)
    recent_start_idx = int(bars.index.searchsorted(recent_start))
    recent_trades = [t for t in trades if t.exit_bar >= recent_start_idx]
    recent_net = float(sum(t.pnl for t in recent_trades))
    recent_hold = float((bars["close"].iloc[-1] - bars["open"].iloc[recent_start_idx]) * POINT_VALUE)

    monthly = _bucket_trades(trades, bars.index, "M")
    worst_months = sorted(monthly, key=lambda row: row["pnl"])[:5]
    best_months = sorted(monthly, key=lambda row: row["pnl"], reverse=True)[:5]
    by_kind = _group_stats(trades, lambda t: t.kind)
    by_direction = _group_stats(trades, lambda t: "long" if t.direction == 1 else "short")
    by_kind_direction = _group_stats(trades, lambda t: f"{t.kind}_{'long' if t.direction == 1 else 'short'}")

    conclusions = []
    if excess < 0:
        conclusions.append("C5 is under buy-and-hold over this export window; successor scoring should optimize excess return, not standalone net profit.")
    if recent_net < recent_hold:
        conclusions.append(f"C5 is lagging buy-and-hold over the last {args.recent_days} days; add recent-window excess return as a hard validation metric.")
    short_rows = [row for row in by_direction if row["group"] == "short"]
    if short_rows and short_rows[0]["net"] > 0:
        conclusions.append("Shorts are profitable in aggregate, so do not delete them blindly; gate them more tightly during daily bull regimes.")
    cap_rows = [row for row in by_kind if row["group"] == "cap"]
    if cap_rows and cap_rows[0]["profit_factor"] < result.profit_factor:
        conclusions.append("The cap sleeve is lower quality than the whole system in this window; cap exit/hold rules should be re-optimized under TV-parity fills.")

    return {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "summary": {
            "net_profit": round(result.net_profit, 2),
            "buy_hold_net": round(hold, 2),
            "excess_net": round(excess, 2),
            "trades": result.n_trades,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown,
            "recent_days": args.recent_days,
            "recent_net": round(recent_net, 2),
            "recent_buy_hold_net": round(recent_hold, 2),
            "recent_excess_net": round(recent_net - recent_hold, 2),
        },
        "by_kind": by_kind,
        "by_direction": by_direction,
        "by_kind_direction": by_kind_direction,
        "monthly": monthly,
        "worst_months": worst_months,
        "best_months": best_months,
        "conclusions": conclusions,
        "next_successor_tests": [
            "Use TV-parity optimizer with min_trades >= 435 and excess-over-buy-hold objective.",
            "Test daily-bull short gates instead of removing shorts entirely.",
            "Test long-carry sleeve only as an opt-in extension, preserving C5 core/cap behavior as baseline.",
            "Re-optimize cap min hold, max hold, target, trail, and momentum exits with exact TV fill semantics.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--out", default="reports/c5_vs_buyhold_diagnostic.json")
    args = parser.parse_args()

    payload = diagnose(args)
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
