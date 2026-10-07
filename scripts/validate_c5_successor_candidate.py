#!/usr/bin/env python3
"""Validate a saved C5-successor candidate with trade-level diagnostics."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import POINT_VALUE, load_bars, run_c5_tv_compatible


def _trade_rows(trades, index: pd.DatetimeIndex) -> list[dict]:
    rows = []
    for trade in trades:
        rows.append(
            {
                "entry_bar": trade.entry_bar,
                "entry_time": index[trade.entry_bar].isoformat(),
                "exit_bar": trade.exit_bar,
                "exit_time": index[trade.exit_bar].isoformat(),
                "direction": "long" if trade.direction == 1 else "short",
                "kind": trade.kind,
                "entry_price": round(trade.entry_price, 2),
                "exit_price": round(trade.exit_price, 2),
                "pnl": round(trade.pnl, 2),
                "exit_reason": trade.exit_reason,
            }
        )
    return rows


def _group_stats(trades, key_fn) -> list[dict]:
    groups: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade))].append(float(trade.pnl))
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


def _bucket_trades(trades, index: pd.DatetimeIndex, freq: str) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0})
    for trade in trades:
        period = index[trade.exit_bar].tz_convert(None).to_period(freq)
        label = period.strftime("%Y-%m" if freq == "M" else "%Y-%m-%d")
        bucket = buckets[label]
        bucket["pnl"] += float(trade.pnl)
        bucket["trades"] += 1
        bucket["wins"] += int(trade.pnl > 0)
    return [
        {
            "period": key,
            "pnl": round(value["pnl"], 2),
            "trades": value["trades"],
            "win_rate": round(value["wins"] / value["trades"] * 100.0, 2) if value["trades"] else 0.0,
        }
        for key, value in sorted(buckets.items())
    ]


def _summary(result, bars: pd.DataFrame, recent_days: int) -> dict:
    buy_hold = float((bars["close"].iloc[-1] - bars["open"].iloc[0]) * POINT_VALUE)
    recent_start_time = bars.index[-1] - pd.Timedelta(days=recent_days)
    recent_start_idx = int(bars.index.searchsorted(recent_start_time))
    recent_trades = [t for t in result.trades if t.exit_bar >= recent_start_idx]
    recent_net = float(sum(t.pnl for t in recent_trades))
    recent_buy_hold = float((bars["close"].iloc[-1] - bars["open"].iloc[recent_start_idx]) * POINT_VALUE)
    recent_bar_start_idx = max(0, len(bars) - recent_days * 96)
    recent_bar_trades = [t for t in result.trades if t.exit_bar >= recent_bar_start_idx]
    recent_bar_net = float(sum(t.pnl for t in recent_bar_trades))
    recent_bar_buy_hold = float((bars["close"].iloc[-1] - bars["open"].iloc[recent_bar_start_idx]) * POINT_VALUE)
    return {
        "net_profit": round(result.net_profit, 2),
        "buy_hold_net": round(buy_hold, 2),
        "excess_net": round(result.net_profit - buy_hold, 2),
        "trades": result.n_trades,
        "win_rate": round(result.win_rate, 4),
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown,
        "long_trades": result.long_trades,
        "short_trades": result.short_trades,
        "core_trades": result.core_trades,
        "cap_trades": result.cap_trades,
        "recent_days": recent_days,
        "recent_net": round(recent_net, 2),
        "recent_buy_hold_net": round(recent_buy_hold, 2),
        "recent_excess_net": round(recent_net - recent_buy_hold, 2),
        "recent_bar_window_bars": recent_days * 96,
        "recent_bar_window_net": round(recent_bar_net, 2),
        "recent_bar_window_buy_hold_net": round(recent_bar_buy_hold, 2),
        "recent_bar_window_excess_net": round(recent_bar_net - recent_bar_buy_hold, 2),
    }


def _select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def validate(args: argparse.Namespace) -> dict:
    report = json.loads(Path(args.report).read_text())
    item = _select_item(report, args.rank)
    params = item["params"]
    bars = load_bars(args.data or report["source_data"])

    candidate = run_c5_tv_compatible(
        args.data or report["source_data"],
        daily_bars_path=args.daily_bars or report["daily_bars"],
        h4_bars_path=args.h4_bars or report["h4_bars"],
        params=params,
    )
    baseline = run_c5_tv_compatible(
        args.data or report["source_data"],
        daily_bars_path=args.daily_bars or report["daily_bars"],
        h4_bars_path=args.h4_bars or report["h4_bars"],
    )

    trade_rows = _trade_rows(candidate.trades, bars.index)
    payload = {
        "source_report": args.report,
        "source_data": args.data or report["source_data"],
        "daily_bars": args.daily_bars or report["daily_bars"],
        "h4_bars": args.h4_bars or report["h4_bars"],
        "selected_rank": args.rank,
        "selected_worker_id": item["worker_id"],
        "selected_score": item["score"],
        "sampler": report.get("sampler"),
        "candidate_summary": _summary(candidate, bars, args.recent_days),
        "baseline_c5_summary": _summary(baseline, bars, args.recent_days),
        "delta_vs_c5": {
            "net_profit": round(candidate.net_profit - baseline.net_profit, 2),
            "trades": candidate.n_trades - baseline.n_trades,
            "profit_factor": candidate.profit_factor - baseline.profit_factor,
            "max_drawdown_pct": candidate.max_drawdown - baseline.max_drawdown,
        },
        "by_kind": _group_stats(candidate.trades, lambda t: t.kind),
        "by_direction": _group_stats(candidate.trades, lambda t: "long" if t.direction == 1 else "short"),
        "by_kind_direction": _group_stats(candidate.trades, lambda t: f"{t.kind}_{'long' if t.direction == 1 else 'short'}"),
        "monthly": _bucket_trades(candidate.trades, bars.index, "M"),
        "worst_months": sorted(_bucket_trades(candidate.trades, bars.index, "M"), key=lambda row: row["pnl"])[:5],
        "best_months": sorted(_bucket_trades(candidate.trades, bars.index, "M"), key=lambda row: row["pnl"], reverse=True)[:5],
        "params": params,
        "trades": trade_rows if args.include_trades else [],
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/c5_successor_tv_parity_128k.json")
    parser.add_argument("--rank", type=int, default=0, help="0 selects report best; 1 selects top10[0].")
    parser.add_argument("--data", default=None)
    parser.add_argument("--daily-bars", default=None)
    parser.add_argument("--h4-bars", default=None)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--out", default="reports/c5_successor_candidate_validation.json")
    parser.add_argument("--trades-csv", default="reports/c5_successor_candidate_trades.csv")
    parser.add_argument("--include-trades", action="store_true")
    args = parser.parse_args()

    payload = validate(args)
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    if args.trades_csv:
        rows = payload["trades"] or _trade_rows(
            run_c5_tv_compatible(
                payload["source_data"],
                daily_bars_path=payload["daily_bars"],
                h4_bars_path=payload["h4_bars"],
                params=payload["params"],
            ).trades,
            load_bars(payload["source_data"]).index,
        )
        with Path(args.trades_csv).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
            if rows:
                writer.writeheader()
                writer.writerows(rows)
    print(json.dumps({k: payload[k] for k in ("candidate_summary", "baseline_c5_summary", "delta_vs_c5")}, indent=2))


if __name__ == "__main__":
    main()
