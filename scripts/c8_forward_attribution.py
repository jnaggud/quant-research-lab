#!/usr/bin/env python3
"""Forward attribution for the C8 strategy family."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from c8_monitor_analyze import buy_hold, load_strategy_params, prepare_features, profit_factor, trade_summary
from tv_c5_parity_engine import build_c5_signal_bars, run_tv_compatible_signal_bars


DEFAULT_15M = "reports/c8_monitor/data/es1_15m_20260620_064007.json"
DEFAULT_1D = "reports/c8_monitor/data/es1_1d_20260620_064007.json"
DEFAULT_240M = "reports/c8_monitor/data/es1_240m_20260620_064007.json"


def money(value: float) -> str:
    return f"${value:,.2f}"


def table(rows: list[dict], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def max_excursions(bars: pd.DataFrame, trade) -> tuple[float, float]:
    segment = bars.iloc[trade.entry_bar : trade.exit_bar + 1]
    if segment.empty:
        return 0.0, 0.0
    if trade.direction == 1:
        mfe = float((segment["high"].max() - trade.entry_price) * 50.0)
        mae = float((segment["low"].min() - trade.entry_price) * 50.0)
    else:
        mfe = float((trade.entry_price - segment["low"].min()) * 50.0)
        mae = float((trade.entry_price - segment["high"].max()) * 50.0)
    return mfe, mae


def entry_context(bars: pd.DataFrame, signal_bars, trade) -> dict:
    row = bars.iloc[trade.entry_bar]
    signal = signal_bars[trade.entry_bar]
    return {
        "rsi": round(float(row["rsi"]), 2),
        "macdh": round(float(row["macdh"]), 4),
        "adx": round(float(row["adx"]), 2),
        "atr": round(float(row["atr"]), 2),
        "h4": int(row.get("h4_signal", 0)),
        "daily": int(row.get("daily_signal", 0)),
        "above_ema21": bool(row["close"] > row["ema21"]),
        "above_ema55": bool(row["close"] > row["ema55"]),
        "above_vwap": bool(row["close"] > row["vwap"]),
        "core_long_signal": bool(signal.core_long),
        "core_short_signal": bool(signal.core_short),
        "cap_long_signal": bool(signal.cap_long),
        "participation_long_signal": bool(signal.participation_long),
    }


def add_regime_columns(bars: pd.DataFrame, signal_bars) -> pd.DataFrame:
    out = bars.copy()
    # The signal-bar booleans are enough for attribution. H4/daily details are
    # approximated here from security EMA columns to keep the report readable.
    out["h4_signal"] = (out["h4_fast_security"] > out["h4_slow_security"]).map({True: 1, False: -1})
    out["daily_signal"] = (out["daily_fast_security"] > out["daily_slow_security"]).map({True: 1, False: -1})
    return out


def build_strategy(name: str, params: dict, bars: pd.DataFrame, forward_idx: int) -> dict:
    signal_bars = build_c5_signal_bars(bars, params)
    bars_with_regime = add_regime_columns(bars, signal_bars)
    result = run_tv_compatible_signal_bars(signal_bars, params)
    forward_trades = [
        trade
        for trade in result.trades
        if trade.exit_bar >= forward_idx and trade.exit_reason != "end_of_data"
    ]
    forward_pnls = [float(trade.pnl) for trade in forward_trades]
    kind_rows = []
    for kind in ["core", "cap", "participation"]:
        pnls = [float(trade.pnl) for trade in forward_trades if trade.kind == kind]
        kind_rows.append(
            {
                "kind": kind,
                "trades": len(pnls),
                "net": round(sum(pnls), 2),
                "pf": round(profit_factor(pnls), 3),
                "wins": sum(1 for pnl in pnls if pnl > 0),
                "losses": sum(1 for pnl in pnls if pnl <= 0),
            }
        )
    trade_rows = []
    for trade in forward_trades:
        mfe, mae = max_excursions(bars_with_regime, trade)
        ctx = entry_context(bars_with_regime, signal_bars, trade)
        trade_rows.append(
            {
                "entry_bar": trade.entry_bar,
                "entry_time": bars.index[trade.entry_bar].isoformat(),
                "exit_bar": trade.exit_bar,
                "exit_time": bars.index[trade.exit_bar].isoformat(),
                "side": "long" if trade.direction == 1 else "short",
                "kind": trade.kind,
                "bars": trade.exit_bar - trade.entry_bar,
                "entry": round(float(trade.entry_price), 2),
                "exit": round(float(trade.exit_price), 2),
                "pnl": round(float(trade.pnl), 2),
                "reason": trade.exit_reason,
                "mfe": round(mfe, 2),
                "mae": round(mae, 2),
                **ctx,
            }
        )
    return {
        "name": name,
        "closed": trade_summary(result, bars, 0, params),
        "forward": {
            "net": round(sum(forward_pnls), 2),
            "buy_hold": round(buy_hold(bars, forward_idx), 2),
            "excess": round(sum(forward_pnls) - buy_hold(bars, forward_idx), 2),
            "trades": len(forward_trades),
            "profit_factor": profit_factor(forward_pnls),
            "win_rate": round(sum(1 for pnl in forward_pnls if pnl > 0) / len(forward_pnls) * 100.0, 3)
            if forward_pnls
            else 0.0,
        },
        "forward_by_kind": kind_rows,
        "forward_trades": trade_rows,
        "result": {key: value for key, value in asdict(result).items() if key != "trades"},
    }


def write_markdown(payload: dict, path: Path) -> None:
    lines = [
        f"# C8 Forward Attribution - {payload['snapshot_id']}",
        "",
        f"Forward start: `{payload['forward_start']}`",
        f"Data window: `{payload['data']['first_bar']}` to `{payload['data']['last_bar']}`",
        "",
        "## Summary",
    ]
    summary_rows = []
    for item in payload["strategies"]:
        closed = item["closed"]
        forward = item["forward"]
        summary_rows.append(
            {
                "strategy": item["name"],
                "closed_net": money(closed["net"]),
                "closed_excess": money(closed["excess"]),
                "closed_pf": round(closed["profit_factor"], 3),
                "forward_net": money(forward["net"]),
                "forward_bh": money(forward["buy_hold"]),
                "forward_excess": money(forward["excess"]),
                "forward_trades": forward["trades"],
                "forward_pf": round(forward["profit_factor"], 3),
            }
        )
    lines.append(table(summary_rows, list(summary_rows[0].keys())))
    lines.append("")
    lines.append("## Forward By Sleeve")
    sleeve_rows = []
    for item in payload["strategies"]:
        for row in item["forward_by_kind"]:
            sleeve_rows.append({"strategy": item["name"], **row, "net": money(row["net"])})
    lines.append(table(sleeve_rows, ["strategy", "kind", "trades", "net", "pf", "wins", "losses"]))
    lines.append("")
    lines.append("## Champion Forward Trades")
    champ = next(item for item in payload["strategies"] if item["name"] == "c8_c5")
    if champ["forward_trades"]:
        columns = [
            "entry_time",
            "exit_time",
            "side",
            "kind",
            "bars",
            "entry",
            "exit",
            "pnl",
            "reason",
            "mfe",
            "mae",
            "h4",
            "daily",
            "rsi",
            "macdh",
            "adx",
            "above_ema21",
            "above_ema55",
            "above_vwap",
        ]
        rows = [{**row, "pnl": money(row["pnl"]), "mfe": money(row["mfe"]), "mae": money(row["mae"])} for row in champ["forward_trades"]]
        lines.append(table(rows, columns))
    else:
        lines.append("No completed champion forward trades.")
    lines.append("")
    lines.append("## Read")
    lines.extend(payload["read"])
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DEFAULT_15M)
    parser.add_argument("--daily-bars", default=DEFAULT_1D)
    parser.add_argument("--h4-bars", default=DEFAULT_240M)
    parser.add_argument("--forward-start", default="2026-06-18T00:00:00Z")
    parser.add_argument("--snapshot-id", default="20260620")
    parser.add_argument("--out-json", default="reports/c8_forward_attribution_20260620.json")
    parser.add_argument("--out-md", default="reports/c8_forward_attribution_20260620.md")
    args = parser.parse_args()

    params = load_strategy_params()
    bars = prepare_features(args.data, args.daily_bars, args.h4_bars, params["c8_c5"], end=10**9)
    forward_idx = int(bars.index.searchsorted(pd.Timestamp(args.forward_start)))
    strategy_names = ["trusted_c2", "c6", "c7", "c8_c1", "c8_c5"]
    strategies = [build_strategy(name, params[name], bars, forward_idx) for name in strategy_names]
    champ = next(item for item in strategies if item["name"] == "c8_c5")
    read = []
    by_kind = {row["kind"]: row for row in champ["forward_by_kind"]}
    worst_kind = min(champ["forward_by_kind"], key=lambda row: row["net"])
    read.append(f"- C8 C5 forward loss is concentrated in `{worst_kind['kind']}`: {money(worst_kind['net'])} across {worst_kind['trades']} trades.")
    if by_kind["participation"]["trades"]:
        read.append(
            f"- Participation forward net is {money(by_kind['participation']['net'])}, so the carry sleeve is directly measurable in this slice."
        )
    read.append(
        "- Do not promote a C9 variant unless it improves this forward slice without breaking exact completed-trade parity against Pine after export."
    )
    payload = {
        "snapshot_id": args.snapshot_id,
        "forward_start": args.forward_start,
        "forward_idx": forward_idx,
        "data": {
            "path": args.data,
            "daily_bars": args.daily_bars,
            "h4_bars": args.h4_bars,
            "first_bar": bars.index[0].isoformat(),
            "last_bar": bars.index[-1].isoformat(),
        },
        "strategies": strategies,
        "read": read,
    }
    Path(args.out_json).write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, Path(args.out_md))
    print(json.dumps({"out_json": args.out_json, "out_md": args.out_md, "status": "ok"}, indent=2))


if __name__ == "__main__":
    main()
