#!/usr/bin/env python3
"""Rerank C5/C6/C7/C8 family candidates with Pine date-filtered buy/hold."""

from __future__ import annotations

import argparse
import json
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


def select_item(report: dict, rank: int, key: str = "top10") -> dict:
    if rank == 0:
        return report["best"]
    return report[key][rank - 1]


def prepare_features(data: str, daily_bars: str, h4_bars: str, params: dict, exclude_tail_bars: int):
    feat = build_features(load_bars(data))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    if exclude_tail_bars > 0:
        feat = feat.iloc[:-exclude_tail_bars].copy()
    return feat


def date_start_index(feat, params: dict) -> int:
    if params.get("use_date_range") and params.get("start_time"):
        idx = int(feat.index.searchsorted(pd.Timestamp(params["start_time"])))
        return min(max(idx, 0), len(feat) - 1)
    return 0


def buy_hold_net(feat, params: dict) -> float:
    start = date_start_index(feat, params)
    return float((feat["close"].iloc[-1] - feat["open"].iloc[start]) * POINT_VALUE)


def period_hold(feat, start_time: str) -> float:
    start = int(feat.index.searchsorted(pd.Timestamp(start_time, tz="UTC")))
    start = min(max(start, 0), len(feat) - 1)
    return float((feat["close"].iloc[-1] - feat["open"].iloc[start]) * POINT_VALUE)


def summarize(name: str, source: str, rank: int, params: dict, feat) -> dict:
    result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
    trades = result.trades
    buy_hold = buy_hold_net(feat, params)
    june_start = int(feat.index.searchsorted(pd.Timestamp("2026-06-01", tz="UTC")))
    june_trades = [trade for trade in trades if trade.exit_bar >= june_start]
    pnls = [trade.pnl for trade in trades]
    max_winner = max(pnls, default=0.0)
    return {
        "name": name,
        "source": source,
        "rank": rank,
        "metrics": {
            **{key: value for key, value in asdict(result).items() if key != "trades"},
            "buy_hold_net_corrected": buy_hold,
            "excess_net_corrected": result.net_profit - buy_hold,
            "june_net": float(sum(trade.pnl for trade in june_trades)),
            "june_trades": len(june_trades),
            "june_buy_hold_net": period_hold(feat, "2026-06-01T00:00:00Z"),
            "max_winner_share": max_winner / max(abs(result.net_profit), 1.0),
            "date_start_index": date_start_index(feat, params),
            "date_start_time": feat.index[date_start_index(feat, params)].isoformat(),
        },
        "params": params,
    }


def score(row: dict) -> float:
    m = row["metrics"]
    return float(
        m["net_profit"] * 1.0
        + m["excess_net_corrected"] * 0.6
        + m["june_net"] * 1.5
        + m["profit_factor"] * 25_000.0
        - m["max_drawdown"] * 2_500.0
        - max(0, 435 - m["n_trades"]) * 5_000.0
        - max(0.0, m["max_winner_share"] - 0.18) * 100_000.0
    )


def row_for_table(row: dict) -> dict:
    m = row["metrics"]
    return {
        "name": row["name"],
        "net": round(m["net_profit"], 2),
        "pf": round(m["profit_factor"], 6),
        "dd_pct": round(m["max_drawdown"], 6),
        "trades": m["n_trades"],
        "win_rate": round(m["win_rate"], 6),
        "buy_hold_corrected": round(m["buy_hold_net_corrected"], 2),
        "excess_corrected": round(m["excess_net_corrected"], 2),
        "june": round(m["june_net"], 2),
        "part_trades": m.get("participation_trades"),
        "score": round(row["score"], 4),
    }


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c8-report", default="reports/c8_successor_200k_20260618.json")
    parser.add_argument("--out", default="reports/c8_family_corrected_rerank_20260620.json")
    parser.add_argument("--md-out", default="reports/c8_family_corrected_rerank_20260620.md")
    args = parser.parse_args()

    c8_report = json.loads(Path(args.c8_report).read_text())
    base_report = json.loads(Path(c8_report["base_report"]).read_text())
    c6_refine_report = json.loads(Path(c8_report["c6_report"]).read_text())
    c7_report = json.loads(Path(c8_report["c7_report"]).read_text())

    seed_params = dict(c8_report["top10_promotion_gate_pass"][0]["params"])
    feat = prepare_features(
        c8_report["source_data"],
        c8_report["daily_bars"],
        c8_report["h4_bars"],
        seed_params,
        c8_report.get("exclude_tail_bars", 0),
    )

    specs = [
        ("C5 Participation Overlay C2", c8_report["base_report"], 2, select_item(base_report, 2)),
        ("C6 Participation Refine C2", c8_report["c6_report"], 2, select_item(c6_refine_report, 2)),
        ("C7 Constrained Refine C1", c8_report["c7_report"], 1, select_item(c7_report, 1)),
    ]
    for idx, item in enumerate(c8_report["top10_promotion_gate_pass"][:10], start=1):
        specs.append((f"C8 Successor 200k C{idx}", args.c8_report, idx, item))

    rows = []
    for name, source, rank, item in specs:
        row = summarize(name, source, rank, dict(item["params"]), feat)
        row["score"] = score(row)
        rows.append(row)

    rows.sort(key=lambda row: row["score"], reverse=True)
    payload = {
        "success": True,
        "source_data": c8_report["source_data"],
        "daily_bars": c8_report["daily_bars"],
        "h4_bars": c8_report["h4_bars"],
        "exclude_tail_bars": c8_report.get("exclude_tail_bars", 0),
        "buy_hold_policy": "Pine date-filtered: use params.start_time when use_date_range is true",
        "ranking_policy": "score = net + 0.6*corrected_excess + 1.5*june + 25000*PF - 2500*DD - trade/max-winner penalties",
        "best": rows[0],
        "ranked": rows,
        "table": [row_for_table(row) for row in rows],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")

    table_rows = payload["table"]
    lines = [
        "# C8 Family Corrected Rerank - 2026-06-20",
        "",
        "Buy/hold and excess are recomputed using the same Pine date filter as the strategy.",
        "",
        markdown_table(
            table_rows,
            ["name", "net", "pf", "dd_pct", "trades", "buy_hold_corrected", "excess_corrected", "june", "part_trades", "score"],
        ),
        "",
        f"Best corrected candidate: `{rows[0]['name']}`.",
    ]
    Path(args.md_out).write_text("\n".join(lines) + "\n")
    print(json.dumps({"best": row_for_table(rows[0]), "out": args.out, "md_out": args.md_out}, indent=2))


if __name__ == "__main__":
    main()
