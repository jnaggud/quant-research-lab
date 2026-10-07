#!/usr/bin/env python3
"""Compare local C5 parity-engine output against an exported TradingView report."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from tv_c5_parity_engine import run_c5_tv_compatible


def _load_tv_payload(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text())
    report = payload.get("reportData") or payload.get("report")
    if not isinstance(report, dict):
        raise ValueError(f"could not find reportData/report in {path}")
    trades = report.get("trades")
    if not isinstance(trades, list):
        raise ValueError(f"could not find report trades in {path}")
    return report


def _local_tuple(trade: dict) -> tuple:
    return (
        int(trade["entry_bar"]),
        int(trade["exit_bar"]),
        int(trade["direction"]),
        round(float(trade["entry_price"]), 2),
        round(float(trade["exit_price"]), 2),
        round(float(trade["pnl"]), 2),
        str(trade["kind"]),
    )


def _tv_tuple(trade: dict) -> tuple:
    direction = 1 if trade["e"]["tp"] == "le" else -1
    kind = "cap" if "Cap" in trade["e"]["c"] else "core"
    return (
        int(trade["e"]["b"]),
        int(trade["x"]["b"]),
        direction,
        round(float(trade["e"]["p"]), 2),
        round(float(trade["x"]["p"]), 2),
        round(float(trade["tp"]["v"]), 2),
        kind,
    )


def compare(args: argparse.Namespace) -> dict:
    result = run_c5_tv_compatible(
        args.data,
        daily_bars_path=args.daily_bars,
        h4_bars_path=args.h4_bars,
    )
    local = [asdict(trade) for trade in result.trades]
    report = _load_tv_payload(args.tv_report)
    tv = report["trades"]

    mismatches = []
    for idx, (local_trade, tv_trade) in enumerate(zip(local, tv)):
        local_key = _local_tuple(local_trade)
        tv_key = _tv_tuple(tv_trade)
        if local_key != tv_key:
            mismatches.append({"index": idx, "local": local_key, "tv": tv_key})
            if len(mismatches) >= args.max_mismatches:
                break

    if len(local) != len(tv):
        mismatches.append({"index": "length", "local": len(local), "tv": len(tv)})

    tv_perf = report["performance"]
    tv_all = tv_perf["all"]
    summary = {
        "success": not mismatches,
        "local": {
            "trades": result.n_trades,
            "net_profit": result.net_profit,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": result.max_drawdown,
        },
        "tradingview": {
            "trades": len(tv),
            "net_profit": tv_all["netProfit"],
            "profit_factor": tv_all["profitFactor"],
            "max_drawdown": tv_perf["maxStrategyDrawDown"],
        },
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="TradingView-exported 15m bars JSON")
    parser.add_argument("--daily-bars", required=True, help="TradingView-exported 1D bars JSON")
    parser.add_argument("--h4-bars", required=True, help="TradingView-exported 240m bars JSON")
    parser.add_argument("--tv-report", required=True, help="TradingView strategy report export JSON")
    parser.add_argument("--max-mismatches", type=int, default=10)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    summary = compare(args)
    text = json.dumps(summary, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    if not summary["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
