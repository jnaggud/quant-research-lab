#!/usr/bin/env python3
"""Compare C8 local parity-engine trades against robust TradingView export."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import (
    POINT_VALUE,
    build_c5_signal_bars,
    build_features,
    load_bars,
    run_tv_compatible_signal_bars,
    apply_tv_daily_security,
    apply_tv_h4_security,
)


def load_c8_params(path: Path, rank: int) -> dict:
    payload = json.loads(path.read_text())
    items = payload.get("top10_promotion_gate_pass") or payload.get("top10") or []
    if rank < 1 or rank > len(items):
        raise ValueError(f"rank {rank} not available in {path}")
    return dict(items[rank - 1]["params"])


def tv_closed_trades(path: Path) -> tuple[list[dict], list[dict]]:
    payload = json.loads(path.read_text())
    rows = []
    for page in payload.get("closed_trades", []):
        rows.extend(page.get("rows", []))
    completed = [row for row in rows if row.get("x", {}).get("c")]
    open_marks = [row for row in rows if not row.get("x", {}).get("c")]
    return completed, open_marks


def tv_kind(row: dict) -> str:
    entry = row.get("e", {}).get("c", "")
    if "Cap" in entry:
        return "cap"
    if "Participation" in entry:
        return "participation"
    if "Trend Carry" in entry:
        return "trend_carry"
    return "core"


def normalize_tv(row: dict) -> dict:
    direction = 1 if row["e"]["tp"] == "le" else -1
    return {
        "entry_bar": int(row["e"]["b"]),
        "exit_bar": int(row["x"]["b"]),
        "direction": direction,
        "kind": tv_kind(row),
        "entry_time_ms": int(row["e"]["tm"]),
        "exit_time_ms": int(row["x"]["tm"]),
        "entry_price": float(row["e"]["p"]),
        "exit_price": float(row["x"]["p"]),
        "pnl": float(row["tp"]["v"]),
        "cumulative_pnl": float(row["cp"]["v"]),
        "entry_signal": row["e"].get("c", ""),
        "exit_signal": row["x"].get("c", ""),
    }


def normalize_local(trade: dict, bars: pd.DataFrame) -> dict:
    entry_ts = bars.index[int(trade["entry_bar"])]
    exit_ts = bars.index[int(trade["exit_bar"])]
    return {
        "entry_bar": int(trade["entry_bar"]),
        "exit_bar": int(trade["exit_bar"]),
        "direction": int(trade["direction"]),
        "kind": str(trade["kind"]),
        "entry_time_ms": int(entry_ts.timestamp() * 1000),
        "exit_time_ms": int(exit_ts.timestamp() * 1000),
        "entry_price": float(trade["entry_price"]),
        "exit_price": float(trade["exit_price"]),
        "pnl": float(trade["pnl"]),
        "exit_reason": str(trade["exit_reason"]),
    }


def rounded_key(row: dict) -> tuple:
    return (
        row["entry_bar"],
        row["exit_bar"],
        row["direction"],
        row["kind"],
        row["entry_time_ms"],
        row["exit_time_ms"],
        round(row["entry_price"], 2),
        round(row["exit_price"], 2),
        round(row["pnl"], 2),
    )


def metric_summary(rows: list[dict]) -> dict:
    pnls = [float(row["pnl"]) for row in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return {
        "trades": len(rows),
        "net": sum(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) * 100.0 if rows else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else None,
    }


def compare(args: argparse.Namespace) -> dict:
    params = load_c8_params(Path(args.c8_report), args.rank)
    bars = load_bars(args.data)
    feat = build_features(bars)
    feat = apply_tv_daily_security(feat, args.daily_bars, params)
    feat = apply_tv_h4_security(feat, args.h4_bars, params)
    if args.exclude_tail_bars:
        feat = feat.iloc[: -args.exclude_tail_bars].copy()
        bars = bars.iloc[: -args.exclude_tail_bars].copy()
    if args.end_bar_exclusive is not None:
        feat = feat.iloc[: args.end_bar_exclusive].copy()
        bars = bars.iloc[: args.end_bar_exclusive].copy()

    local_result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
    all_local_rows = [normalize_local(asdict(trade), bars) for trade in local_result.trades]
    local_open_marks = [row for row in all_local_rows if row.get("exit_reason") == "end_of_data"]
    local_rows = [row for row in all_local_rows if row.get("exit_reason") != "end_of_data"]
    tv_rows = [normalize_tv(row) for row in tv_closed_trades(Path(args.tv_export))[0]]
    tv_open_marks = [normalize_tv(row) for row in tv_closed_trades(Path(args.tv_export))[1]]

    mismatches = []
    for index, (local, tv) in enumerate(zip(local_rows, tv_rows), start=1):
        if rounded_key(local) != rounded_key(tv):
            mismatches.append(
                {
                    "trade_number": index,
                    "local": local,
                    "tv": tv,
                    "field_deltas": {
                        "entry_bar": local["entry_bar"] - tv["entry_bar"],
                        "exit_bar": local["exit_bar"] - tv["exit_bar"],
                        "entry_time_ms": local["entry_time_ms"] - tv["entry_time_ms"],
                        "exit_time_ms": local["exit_time_ms"] - tv["exit_time_ms"],
                        "entry_price": round(local["entry_price"] - tv["entry_price"], 4),
                        "exit_price": round(local["exit_price"] - tv["exit_price"], 4),
                        "pnl": round(local["pnl"] - tv["pnl"], 4),
                    },
                }
            )
            if len(mismatches) >= args.max_mismatches:
                break

    if len(local_rows) != len(tv_rows):
        mismatches.append({"trade_number": "length", "local": len(local_rows), "tv": len(tv_rows)})

    local_summary = {
        "engine": {
            "net_profit": local_result.net_profit,
            "profit_factor": local_result.profit_factor,
            "max_drawdown_pct": local_result.max_drawdown,
            "n_trades": local_result.n_trades,
            "win_rate": local_result.win_rate,
        },
        "from_rows": metric_summary(local_rows),
    }
    tv_summary = metric_summary(tv_rows)
    buy_hold_start = pd.Timestamp(params["start_time"])
    start_pos = int(feat.index.searchsorted(buy_hold_start))
    tv_window_buy_hold = float((feat["close"].iloc[-1] - feat["open"].iloc[start_pos]) * POINT_VALUE)

    return {
        "success": not mismatches,
        "params_source": str(args.c8_report),
        "rank": args.rank,
        "data": {
            "bars_15m": str(args.data),
            "bars_daily": str(args.daily_bars),
            "bars_h4": str(args.h4_bars),
            "bar_count": len(feat),
            "first_bar": feat.index[0].isoformat(),
            "last_bar": feat.index[-1].isoformat(),
            "exclude_tail_bars": args.exclude_tail_bars,
            "end_bar_exclusive": args.end_bar_exclusive,
        },
        "local": local_summary,
        "tradingview": {
            "completed": tv_summary,
            "open_mark_count": len(tv_open_marks),
            "open_marks": tv_open_marks,
        },
        "local_open_mark_count": len(local_open_marks),
        "local_open_marks": local_open_marks,
        "deltas": {
            "completed_trade_count": len(local_rows) - len(tv_rows),
            "completed_net": local_summary["from_rows"]["net"] - tv_summary["net"],
            "completed_profit_factor": (
                local_summary["from_rows"]["profit_factor"] - tv_summary["profit_factor"]
                if tv_summary["profit_factor"] is not None
                else None
            ),
            "date_filtered_buy_hold_local_window": tv_window_buy_hold,
        },
        "mismatch_count_reported": len(mismatches),
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--tv-export", required=True)
    parser.add_argument("--c8-report", default="reports/c8_successor_200k_20260618.json")
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--exclude-tail-bars", type=int, default=0)
    parser.add_argument("--end-bar-exclusive", type=int, default=None)
    parser.add_argument("--max-mismatches", type=int, default=10)
    parser.add_argument("--out")
    args = parser.parse_args()

    payload = compare(args)
    text = json.dumps(payload, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    if not payload["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
