#!/usr/bin/env python3
"""Analyze a C7 monitor snapshot and write dated reports."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import POINT_VALUE, load_bars, run_c5_tv_compatible


def select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def load_strategy_params() -> dict[str, dict]:
    c2 = json.loads(Path("reports/c5_participation_overlay_32k_20260618.json").read_text())
    c6 = json.loads(Path("reports/c5_participation_overlay_c2_refine_32k_20260618.json").read_text())
    c7 = json.loads(Path("reports/c6_constrained_refine_32k_20260618.json").read_text())
    return {
        "trusted_c2": dict(select_item(c2, 2)["params"]),
        "c6": dict(select_item(c6, 2)["params"]),
        "c7": dict(select_item(c7, 1)["params"]),
    }


def buy_hold(bars: pd.DataFrame, start: int = 0, end: int | None = None) -> float:
    if end is None:
        end = len(bars)
    if end <= start:
        return 0.0
    segment = bars.iloc[start:end]
    if segment.empty:
        return 0.0
    return float((segment["close"].iloc[-1] - segment["open"].iloc[0]) * POINT_VALUE)


def profit_factor(pnls: list[float]) -> float:
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    return float(sum(wins) / (abs(sum(losses)) or 1e-9)) if pnls else 0.0


def trade_summary(result, bars: pd.DataFrame, start_idx: int = 0) -> dict:
    trades = [trade for trade in result.trades if trade.exit_bar >= start_idx]
    pnls = [float(trade.pnl) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    return {
        "net": round(sum(pnls), 2),
        "buy_hold": round(buy_hold(bars, start_idx), 2),
        "excess": round(sum(pnls) - buy_hold(bars, start_idx), 2),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100.0, 2) if trades else 0.0,
        "profit_factor": profit_factor(pnls),
        "core_trades": sum(1 for trade in trades if trade.kind == "core"),
        "cap_trades": sum(1 for trade in trades if trade.kind == "cap"),
        "participation_trades": sum(1 for trade in trades if trade.kind == "participation"),
    }


def monthly(result, bars: pd.DataFrame) -> list[dict]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in result.trades:
        label = bars.index[trade.exit_bar].tz_convert(None).to_period("M").strftime("%Y-%m")
        buckets[label].append(float(trade.pnl))
    return [
        {
            "month": month,
            "net": round(sum(pnls), 2),
            "trades": len(pnls),
            "profit_factor": profit_factor(pnls),
            "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls) * 100.0, 2),
        }
        for month, pnls in sorted(buckets.items())
    ]


def latest_trade_row(result, bars: pd.DataFrame) -> dict | None:
    if not result.trades:
        return None
    trade = result.trades[-1]
    return {
        "entry_bar": trade.entry_bar,
        "entry_time": bars.index[trade.entry_bar].isoformat(),
        "exit_bar": trade.exit_bar,
        "exit_time": bars.index[trade.exit_bar].isoformat(),
        "side": "long" if trade.direction == 1 else "short",
        "kind": trade.kind,
        "entry_price": round(trade.entry_price, 2),
        "exit_price": round(trade.exit_price, 2),
        "pnl": round(trade.pnl, 2),
        "exit_reason": trade.exit_reason,
    }


def tv_snapshot(path: Path) -> dict:
    payload = json.loads(path.read_text())
    report = payload.get("reportData") or {}
    perf = report.get("performance") or {}
    allp = perf.get("all") or {}
    trades = report.get("trades") or []
    latest = None
    if trades:
        trade = trades[-1]
        latest = {
            "entry_comment": trade["e"].get("c"),
            "entry_bar": trade["e"].get("b"),
            "entry_price": trade["e"].get("p"),
            "exit_comment": trade["x"].get("c"),
            "exit_bar": trade["x"].get("b"),
            "exit_price": trade["x"].get("p"),
            "pnl": trade.get("tp", {}).get("v"),
            "side": trade["e"].get("tp"),
        }
    return {
        "source_name": (payload.get("source") or {}).get("name"),
        "net": allp.get("netProfit"),
        "trades": allp.get("totalTrades"),
        "profit_factor": allp.get("profitFactor"),
        "max_drawdown": perf.get("maxStrategyDrawDown"),
        "buy_hold_return": perf.get("buyHoldReturn"),
        "latest_trade": latest,
    }


def trigger_status(strategies: dict, tv: dict, dd_threshold_pct: float) -> dict:
    c2 = strategies["trusted_c2"]
    c6 = strategies["c6"]
    c7 = strategies["c7"]
    triggers = {
        "c7_net_below_c6": bool(c7["closed"]["net"] < c6["closed"]["net"]),
        "c7_pf_below_c6": bool(c7["closed"]["profit_factor"] < c6["closed"]["profit_factor"]),
        "c7_june_below_c2": bool(c7["june"]["net"] < c2["june"]["net"]),
        "c7_dd_above_c6": bool(c7["max_drawdown_pct"] > c6["max_drawdown_pct"]),
        "c7_dd_above_threshold": bool(c7["max_drawdown_pct"] > dd_threshold_pct),
        "tv_active_source_not_c7": not str(tv.get("source_name") or "").startswith("JD ES 15m C7"),
    }
    return {
        "status": "REVIEW" if any(triggers.values()) else "OK",
        "triggers": triggers,
    }


def table(rows: list[dict], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def write_markdown(payload: dict, path: Path) -> None:
    lines = [f"# C7 Monitor Snapshot - {payload['snapshot_id']}", ""]
    lines.append(f"Status: `{payload['status']['status']}`")
    lines.append("")
    lines.append(f"Data window: `{payload['data']['first_bar']}` to `{payload['data']['last_closed_bar']}`. Latest bars excluded: `{payload['data']['exclude_tail_bars']}`.")
    lines.append("")
    lines.append("## Closed-Bar Comparison")
    rows = []
    for name, item in payload["strategies"].items():
        closed = item["closed"]
        rows.append(
            {
                "strategy": name,
                "net": f"${closed['net']:,.2f}",
                "buy_hold": f"${closed['buy_hold']:,.2f}",
                "excess": f"${closed['excess']:,.2f}",
                "trades": closed["trades"],
                "PF": f"{closed['profit_factor']:.3f}",
                "DD%": f"{item['max_drawdown_pct']:.2f}",
                "June": f"${item['june']['net']:,.2f}",
            }
        )
    lines.append(table(rows, ["strategy", "net", "buy_hold", "excess", "trades", "PF", "DD%", "June"]))
    lines.append("")
    lines.append("## Trigger Checks")
    rows = [{"trigger": key, "fired": value} for key, value in payload["status"]["triggers"].items()]
    lines.append(table(rows, ["trigger", "fired"]))
    lines.append("")
    lines.append("## TradingView Snapshot")
    tv = payload["tradingview"]
    lines.extend(
        [
            f"- Source: `{tv.get('source_name')}`",
            f"- Net: `${tv.get('net'):,.2f}`" if isinstance(tv.get("net"), (int, float)) else f"- Net: `{tv.get('net')}`",
            f"- Trades: `{tv.get('trades')}`",
            f"- PF: `{tv.get('profit_factor')}`",
            f"- Max DD: `${tv.get('max_drawdown'):,.2f}`" if isinstance(tv.get("max_drawdown"), (int, float)) else f"- Max DD: `{tv.get('max_drawdown')}`",
            f"- Buy/Hold: `${tv.get('buy_hold_return'):,.2f}`" if isinstance(tv.get("buy_hold_return"), (int, float)) else f"- Buy/Hold: `{tv.get('buy_hold_return')}`",
        ]
    )
    lines.append("")
    lines.append("## Latest Local C7 Trade")
    latest = payload["strategies"]["c7"]["latest_trade"]
    if latest:
        lines.append(table([latest], list(latest.keys())))
    else:
        lines.append("No local trades.")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--tv-report", required=True)
    parser.add_argument("--exclude-tail-bars", type=int, default=1)
    parser.add_argument("--dd-threshold-pct", type=float, default=22.0)
    parser.add_argument("--out-dir", default="reports/c7_monitor")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bars_all = load_bars(args.data)
    end = len(bars_all) - args.exclude_tail_bars if args.exclude_tail_bars > 0 else len(bars_all)
    bars = bars_all.iloc[:end].copy()
    june_start = int(bars.index.searchsorted(pd.Timestamp("2026-06-01", tz="UTC")))

    strategies = {}
    for name, params in load_strategy_params().items():
        result = run_c5_tv_compatible(
            args.data,
            daily_bars_path=args.daily_bars,
            h4_bars_path=args.h4_bars,
            params=params,
            end=end,
        )
        closed = trade_summary(result, bars)
        strategies[name] = {
            "closed": closed,
            "june": trade_summary(result, bars, june_start),
            "max_drawdown_pct": result.max_drawdown,
            "monthly": monthly(result, bars),
            "latest_trade": latest_trade_row(result, bars),
        }

    tv = tv_snapshot(Path(args.tv_report))
    status = trigger_status(strategies, tv, args.dd_threshold_pct)
    payload = {
        "snapshot_id": args.snapshot_id,
        "data": {
            "source": args.data,
            "daily_bars": args.daily_bars,
            "h4_bars": args.h4_bars,
            "exclude_tail_bars": args.exclude_tail_bars,
            "first_bar": bars.index[0].isoformat(),
            "last_closed_bar": bars.index[-1].isoformat(),
        },
        "status": status,
        "strategies": strategies,
        "tradingview": tv,
    }
    json_path = out_dir / f"{args.snapshot_id}.json"
    md_path = out_dir / f"{args.snapshot_id}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, md_path)
    latest_json = out_dir / "latest.json"
    latest_md = out_dir / "latest.md"
    latest_json.write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, latest_md)
    print(json.dumps({"status": status["status"], "json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
