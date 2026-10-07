#!/usr/bin/env python3
"""Analyze the current ES 15m champion monitor snapshot and write dated reports."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import (
    POINT_VALUE,
    apply_tv_daily_security,
    apply_tv_h4_security,
    build_c5_signal_bars,
    build_features,
    load_bars,
    run_tv_compatible_signal_bars,
)
from compare_c8_tv_exact import compare as exact_compare


CHAMPION_NAME = "c9_c1"
CHAMPION_TITLE = "JD ES 15m C9 Core Forward Refine 200k C1 20260620"


def select_item(report: dict, rank: int, key: str = "top10") -> dict:
    if rank == 0:
        return report["best"]
    return report[key][rank - 1]


def load_strategy_params() -> dict[str, dict]:
    c5 = json.loads(Path("reports/c5_participation_overlay_32k_20260618.json").read_text())
    c6_refine = json.loads(Path("reports/c5_participation_overlay_c2_refine_32k_20260618.json").read_text())
    c7 = json.loads(Path("reports/c6_constrained_refine_32k_20260618.json").read_text())
    c8 = json.loads(Path("reports/c8_successor_200k_20260618.json").read_text())
    c9 = json.loads(Path("reports/c9_core_forward_refine_200k_20260620.json").read_text())
    return {
        "trusted_c2": dict(select_item(c5, 2)["params"]),
        "c6": dict(select_item(c6_refine, 2)["params"]),
        "c7": dict(select_item(c7, 1)["params"]),
        "c8_c1": dict(c8["top10_promotion_gate_pass"][0]["params"]),
        "c8_c5": dict(c8["top10_promotion_gate_pass"][4]["params"]),
        "c9_c1": dict(c9["best"]["params"]),
    }


def prepare_features(data: str, daily_bars: str, h4_bars: str, params: dict, end: int):
    feat = build_features(load_bars(data))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    return feat.iloc[:end].copy()


def date_start_index(bars: pd.DataFrame, params: dict) -> int:
    if params.get("use_date_range") and params.get("start_time"):
        idx = int(bars.index.searchsorted(pd.Timestamp(params["start_time"])))
        return min(max(idx, 0), len(bars) - 1)
    return 0


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


def trade_summary(result, bars: pd.DataFrame, start_idx: int = 0, params: dict | None = None) -> dict:
    trades = [trade for trade in result.trades if trade.exit_bar >= start_idx and trade.exit_reason != "end_of_data"]
    pnls = [float(trade.pnl) for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    hold = buy_hold(bars, start_idx)
    if start_idx == 0 and params is not None:
        hold = buy_hold(bars, date_start_index(bars, params))
    return {
        "net": round(sum(pnls), 2),
        "buy_hold": round(hold, 2),
        "excess": round(sum(pnls) - hold, 2),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100.0, 3) if trades else 0.0,
        "profit_factor": profit_factor(pnls),
        "core_trades": sum(1 for trade in trades if trade.kind == "core"),
        "cap_trades": sum(1 for trade in trades if trade.kind == "cap"),
        "participation_trades": sum(1 for trade in trades if trade.kind == "participation"),
        "trend_carry_trades": sum(1 for trade in trades if trade.kind == "trend_carry"),
    }


def monthly(result, bars: pd.DataFrame) -> list[dict]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for trade in result.trades:
        if trade.exit_reason == "end_of_data":
            continue
        label = bars.index[trade.exit_bar].tz_convert(None).to_period("M").strftime("%Y-%m")
        buckets[label].append(float(trade.pnl))
    return [
        {
            "month": month,
            "net": round(sum(pnls), 2),
            "trades": len(pnls),
            "profit_factor": profit_factor(pnls),
            "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls) * 100.0, 3),
        }
        for month, pnls in sorted(buckets.items())
    ]


def latest_trade_row(result, bars: pd.DataFrame) -> dict | None:
    completed = [trade for trade in result.trades if trade.exit_reason != "end_of_data"]
    if not completed:
        return None
    trade = completed[-1]
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


def open_mark_row(result, bars: pd.DataFrame) -> dict | None:
    marks = [trade for trade in result.trades if trade.exit_reason == "end_of_data"]
    if not marks:
        return None
    trade = marks[-1]
    return {
        "entry_bar": trade.entry_bar,
        "entry_time": bars.index[trade.entry_bar].isoformat(),
        "mark_bar": trade.exit_bar,
        "mark_time": bars.index[trade.exit_bar].isoformat(),
        "side": "long" if trade.direction == 1 else "short",
        "kind": trade.kind,
        "entry_price": round(trade.entry_price, 2),
        "mark_price": round(trade.exit_price, 2),
        "marked_pnl": round(trade.pnl, 2),
    }


def tv_snapshot(path: Path) -> dict:
    payload = json.loads(path.read_text())
    perf = (((payload.get("metrics") or {}).get("reportData") or {}).get("performance") or {})
    rows = []
    for page in payload.get("closed_trades", []):
        rows.extend(page.get("rows", []))
    completed = [row for row in rows if row.get("x", {}).get("c")]
    open_marks = [row for row in rows if not row.get("x", {}).get("c")]
    pnls = [float(row["tp"]["v"]) for row in completed]
    latest = completed[-1] if completed else None
    source = (payload.get("source") or {}).get("source") or {}
    return {
        "source_name": source.get("name"),
        "completed_trades": len(completed),
        "net": round(sum(pnls), 2),
        "profit_factor": profit_factor(pnls),
        "max_drawdown": perf.get("maxStrategyDrawDown"),
        "buy_hold_return": perf.get("buyHoldReturn"),
        "open_pl": perf.get("openPL"),
        "open_mark_count": len(open_marks),
        "open_mark": open_marks[-1] if open_marks else None,
        "latest_trade": latest,
    }


def trigger_status(strategies: dict, tv: dict, exact: dict, dd_threshold_pct: float) -> dict:
    champ = strategies[CHAMPION_NAME]
    c7 = strategies["c7"]
    c8 = strategies["c8_c5"]
    triggers = {
        "active_source_not_champion": not str(tv.get("source_name") or "").startswith(CHAMPION_TITLE),
        "exact_completed_parity_failed": not bool(exact.get("success")),
        "champion_net_below_c8_c5": bool(champ["closed"]["net"] < c8["closed"]["net"]),
        "champion_pf_below_c8_c5": bool(champ["closed"]["profit_factor"] < c8["closed"]["profit_factor"]),
        "champion_dd_above_c8_c5": bool(champ["max_drawdown_pct"] > c8["max_drawdown_pct"]),
        "champion_net_below_c7": bool(champ["closed"]["net"] < c7["closed"]["net"]),
        "champion_dd_above_threshold": bool(champ["max_drawdown_pct"] > dd_threshold_pct),
        "champion_current_month_negative": bool(champ["current_month"]["net"] < 0),
        "champion_forward_negative": bool(champ["forward"]["net"] < 0),
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


def money(value) -> str:
    return f"${float(value):,.2f}" if isinstance(value, (int, float)) else f"`{value}`"


def write_markdown(payload: dict, path: Path) -> None:
    lines = [f"# Champion Monitor Snapshot - {payload['snapshot_id']}", ""]
    lines.append(f"Status: `{payload['status']['status']}`")
    lines.append("")
    lines.append(f"Data window: `{payload['data']['first_bar']}` to `{payload['data']['last_closed_bar']}`. Latest bars excluded: `{payload['data']['exclude_tail_bars']}`.")
    lines.append("")
    lines.append("## Champion")
    champ = payload["strategies"][CHAMPION_NAME]
    lines.extend(
        [
            f"- Strategy: `{CHAMPION_TITLE}`",
            f"- Closed net: {money(champ['closed']['net'])}",
            f"- Corrected excess: {money(champ['closed']['excess'])}",
            f"- Profit factor: `{champ['closed']['profit_factor']:.6f}`",
            f"- Max drawdown: `{champ['max_drawdown_pct']:.3f}%`",
            f"- Current month net: {money(champ['current_month']['net'])}",
            f"- Forward net since selection: {money(champ['forward']['net'])}",
            "",
        ]
    )
    lines.append("## Strategy Comparison")
    rows = []
    for name, item in payload["strategies"].items():
        closed = item["closed"]
        rows.append(
            {
                "strategy": name,
                "net": money(closed["net"]),
                "buy_hold": money(closed["buy_hold"]),
                "excess": money(closed["excess"]),
                "trades": closed["trades"],
                "PF": f"{closed['profit_factor']:.3f}",
                "DD%": f"{item['max_drawdown_pct']:.2f}",
                "month": money(item["current_month"]["net"]),
                "forward": money(item["forward"]["net"]),
            }
        )
    lines.append(table(rows, ["strategy", "net", "buy_hold", "excess", "trades", "PF", "DD%", "month", "forward"]))
    lines.append("")
    lines.append("## Exact TradingView Parity")
    exact = payload["exact_parity"]
    deltas = exact.get("deltas") or {}
    lines.extend(
        [
            f"- Success: `{exact.get('success')}`",
            f"- Completed trade delta: `{deltas.get('completed_trade_count')}`",
            f"- Completed net delta: `{deltas.get('completed_net')}`",
            f"- Completed PF delta: `{deltas.get('completed_profit_factor')}`",
            f"- Mismatches reported: `{exact.get('mismatch_count_reported')}`",
            "",
        ]
    )
    lines.append("## Trigger Checks")
    lines.append(table([{"trigger": key, "fired": value} for key, value in payload["status"]["triggers"].items()], ["trigger", "fired"]))
    lines.append("")
    lines.append("## TradingView Snapshot")
    tv = payload["tradingview"]
    lines.extend(
        [
            f"- Source: `{tv.get('source_name')}`",
            f"- Completed trades: `{tv.get('completed_trades')}`",
            f"- Net: {money(tv.get('net'))}",
            f"- PF: `{tv.get('profit_factor')}`",
            f"- Max DD: {money(tv.get('max_drawdown'))}",
            f"- Buy/Hold: {money(tv.get('buy_hold_return'))}",
            f"- Open P&L: {money(tv.get('open_pl'))}",
            f"- Open mark count: `{tv.get('open_mark_count')}`",
            "",
        ]
    )
    lines.append("## Latest Completed Champion Trade")
    latest = champ.get("latest_trade")
    lines.append(table([latest], list(latest.keys())) if latest else "No completed champion trade.")
    lines.append("")
    lines.append("## Open Champion Mark")
    open_mark = champ.get("open_mark")
    lines.append(table([open_mark], list(open_mark.keys())) if open_mark else "No local open mark.")
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--tv-report", required=True)
    parser.add_argument("--exclude-tail-bars", type=int, default=1)
    parser.add_argument("--dd-threshold-pct", type=float, default=16.0)
    parser.add_argument("--forward-start", default="2026-06-18T00:00:00Z")
    parser.add_argument("--out-dir", default="reports/c8_monitor")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bars_all = load_bars(args.data)
    end = len(bars_all) - args.exclude_tail_bars if args.exclude_tail_bars > 0 else len(bars_all)
    params_by_name = load_strategy_params()
    champion_params = params_by_name[CHAMPION_NAME]
    feat = prepare_features(args.data, args.daily_bars, args.h4_bars, champion_params, end)
    bars = bars_all.iloc[:end].copy()
    current_month_start = pd.Timestamp(bars.index[-1].strftime("%Y-%m-01"), tz="UTC")
    current_month_idx = int(bars.index.searchsorted(current_month_start))
    forward_idx = int(bars.index.searchsorted(pd.Timestamp(args.forward_start)))

    strategies = {}
    for name, params in params_by_name.items():
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
        strategies[name] = {
            "closed": trade_summary(result, bars, 0, params=params),
            "current_month": trade_summary(result, bars, current_month_idx),
            "forward": trade_summary(result, bars, forward_idx),
            "max_drawdown_pct": result.max_drawdown,
            "monthly": monthly(result, bars),
            "latest_trade": latest_trade_row(result, bars),
            "open_mark": open_mark_row(result, bars),
        }

    compare_out = out_dir / f"exact_compare_{args.snapshot_id}.json"
    exact_args = argparse.Namespace(
        data=args.data,
        daily_bars=args.daily_bars,
        h4_bars=args.h4_bars,
        tv_export=args.tv_report,
        c8_report="reports/c9_core_forward_refine_200k_20260620.json",
        rank=1,
        exclude_tail_bars=args.exclude_tail_bars,
        end_bar_exclusive=None,
        max_mismatches=20,
        out=None,
    )
    exact = exact_compare(exact_args)
    compare_out.write_text(json.dumps(exact, indent=2) + "\n")
    tv = tv_snapshot(Path(args.tv_report))
    status = trigger_status(strategies, tv, exact, args.dd_threshold_pct)
    payload = {
        "snapshot_id": args.snapshot_id,
        "champion": {"key": CHAMPION_NAME, "title": CHAMPION_TITLE},
        "data": {
            "source": args.data,
            "daily_bars": args.daily_bars,
            "h4_bars": args.h4_bars,
            "tv_report": args.tv_report,
            "exact_compare": str(compare_out),
            "exclude_tail_bars": args.exclude_tail_bars,
            "first_bar": bars.index[0].isoformat(),
            "last_closed_bar": bars.index[-1].isoformat(),
            "forward_start": args.forward_start,
        },
        "status": status,
        "strategies": strategies,
        "tradingview": tv,
        "exact_parity": exact,
    }
    json_path = out_dir / f"{args.snapshot_id}.json"
    md_path = out_dir / f"{args.snapshot_id}.md"
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, md_path)
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, out_dir / "latest.md")
    print(json.dumps({"status": status["status"], "json": str(json_path), "markdown": str(md_path), "exact_compare": str(compare_out)}, indent=2))


if __name__ == "__main__":
    main()
