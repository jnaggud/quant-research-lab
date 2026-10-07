#!/usr/bin/env python3
"""Validate C2/C6/C7 across fixed time slices and stress C7 management params."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from tv_c5_parity_engine import POINT_VALUE, load_bars, run_c5_tv_compatible


def select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def load_params() -> dict[str, dict]:
    c2 = json.loads(Path("reports/c5_participation_overlay_32k_20260618.json").read_text())
    c6 = json.loads(Path("reports/c5_participation_overlay_c2_refine_32k_20260618.json").read_text())
    c7 = json.loads(Path("reports/c6_constrained_refine_32k_20260618.json").read_text())
    return {
        "trusted_c2": dict(select_item(c2, 2)["params"]),
        "c6": dict(select_item(c6, 2)["params"]),
        "c7": dict(select_item(c7, 1)["params"]),
    }


def profit_factor(pnls: list[float]) -> float:
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    return float(sum(wins) / (abs(sum(losses)) or 1e-9)) if pnls else 0.0


def trade_drawdown_pct(pnls: list[float], initial: float = 50_000.0) -> float:
    equity = initial
    peak = initial
    dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, (peak - equity) / peak * 100.0)
    return float(dd)


def period_buy_hold(bars: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> float:
    segment = bars
    if start is not None:
        segment = segment.loc[segment.index >= start]
    if end is not None:
        segment = segment.loc[segment.index < end]
    if segment.empty:
        return 0.0
    return float((segment["close"].iloc[-1] - segment["open"].iloc[0]) * POINT_VALUE)


def summarize_trades(trades, bars: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict:
    rows = []
    for trade in trades:
        exit_time = bars.index[trade.exit_bar]
        if start is not None and exit_time < start:
            continue
        if end is not None and exit_time >= end:
            continue
        rows.append(trade)
    pnls = [float(trade.pnl) for trade in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    return {
        "net": round(sum(pnls), 2),
        "buy_hold": round(period_buy_hold(bars, start, end), 2),
        "excess": round(sum(pnls) - period_buy_hold(bars, start, end), 2),
        "trades": len(rows),
        "win_rate": round(len(wins) / len(rows) * 100.0, 2) if rows else 0.0,
        "profit_factor": profit_factor(pnls),
        "trade_drawdown_pct": trade_drawdown_pct(pnls),
        "core_trades": sum(1 for trade in rows if trade.kind == "core"),
        "cap_trades": sum(1 for trade in rows if trade.kind == "cap"),
        "participation_trades": sum(1 for trade in rows if trade.kind == "participation"),
    }


def result_summary(result, bars: pd.DataFrame) -> dict:
    buy_hold = period_buy_hold(bars, None, None)
    return {
        "net": round(result.net_profit, 2),
        "buy_hold": round(buy_hold, 2),
        "excess": round(result.net_profit - buy_hold, 2),
        "trades": result.n_trades,
        "win_rate": round(result.win_rate, 2),
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": result.max_drawdown,
        "core_trades": result.core_trades,
        "cap_trades": result.cap_trades,
        "participation_trades": result.participation_trades,
    }


def run_strategy(name: str, params: dict, args: argparse.Namespace, end: int) -> dict:
    result = run_c5_tv_compatible(
        args.data,
        daily_bars_path=args.daily_bars,
        h4_bars_path=args.h4_bars,
        params=params,
        end=end,
    )
    return {"name": name, "params": params, "result": result}


def strategy_slices(result, bars: pd.DataFrame) -> dict:
    periods = {
        "full_closed": (None, None),
        "pre_2026": (None, pd.Timestamp("2026-01-01", tz="UTC")),
        "q1_2026": (pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-04-01", tz="UTC")),
        "apr_jun_2026": (pd.Timestamp("2026-04-01", tz="UTC"), None),
        "june_2026": (pd.Timestamp("2026-06-01", tz="UTC"), None),
    }
    return {name: summarize_trades(result.trades, bars, start, end) for name, (start, end) in periods.items()}


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


def stress_params(center: dict, rng: random.Random) -> dict:
    params = dict(center)
    float_windows = {
        "participation_stop_atr": 0.5,
        "participation_trail_atr": 1.0,
        "participation_exit_rsi": 2.0,
    }
    int_windows = {
        "participation_cooldown": 2,
        "participation_min_hold": 2,
        "participation_max_hold": 6,
    }
    bounds = {
        "participation_stop_atr": (2.0, 10.0),
        "participation_trail_atr": (2.0, 14.0),
        "participation_exit_rsi": (35.0, 58.0),
        "participation_cooldown": (0, 32),
        "participation_min_hold": (0, 24),
        "participation_max_hold": (24, 240),
    }
    for key, window in float_windows.items():
        low, high = bounds[key]
        params[key] = min(high, max(low, params[key] + rng.uniform(-window, window)))
    for key, window in int_windows.items():
        low, high = bounds[key]
        params[key] = int(min(high, max(low, params[key] + rng.randint(-window, window))))
    if params["participation_min_hold"] >= params["participation_max_hold"]:
        params["participation_min_hold"] = max(0, params["participation_max_hold"] - 1)
    return params


def stress_worker(worker_id: int, count: int, center: dict, references: dict, args_dict: dict, end: int) -> list[dict]:
    rng = random.Random(args_dict["seed"] + worker_id * 1_000_003)
    bars = load_bars(args_dict["data"]).iloc[:end].copy()
    variants = []
    for idx in range(count):
        params = stress_params(center, rng)
        result = run_c5_tv_compatible(
            args_dict["data"],
            daily_bars_path=args_dict["daily_bars"],
            h4_bars_path=args_dict["h4_bars"],
            params=params,
            end=end,
        )
        slices = strategy_slices(result, bars)
        full = result_summary(result, bars)
        gates = {
            "net_ge_c6": bool(full["net"] >= references["c6"]["full"]["net"]),
            "pf_ge_c6": bool(full["profit_factor"] >= references["c6"]["full"]["profit_factor"]),
            "dd_le_c6": bool(full["max_drawdown_pct"] <= references["c6"]["full"]["max_drawdown_pct"]),
            "june_ge_c2": bool(slices["june_2026"]["net"] >= references["trusted_c2"]["slices"]["june_2026"]["net"]),
        }
        variants.append(
            {
                "idx": worker_id * 1_000_000 + idx,
                "worker_id": worker_id,
                "full": full,
                "june": slices["june_2026"],
                "gates": gates,
                "gates_passed": sum(1 for passed in gates.values() if passed),
                "params": {key: params[key] for key in params if key.startswith("participation_")},
            }
        )
    return variants


def stress_test(center: dict, references: dict, bars: pd.DataFrame, args: argparse.Namespace, end: int) -> dict:
    counts = []
    remaining = args.stress_trials
    while remaining > 0:
        count = min(args.stress_chunk_trials, remaining)
        counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(counts)))
    variants = []
    if workers == 1:
        for worker_id, count in enumerate(counts):
            variants.extend(stress_worker(worker_id, count, center, references, vars(args), end))
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(stress_worker, worker_id, count, center, references, vars(args), end)
                for worker_id, count in enumerate(counts)
            ]
            for future in as_completed(futures):
                variants.extend(future.result())
    nets = [item["full"]["net"] for item in variants]
    pfs = [item["full"]["profit_factor"] for item in variants]
    dds = [item["full"]["max_drawdown_pct"] for item in variants]
    june = [item["june"]["net"] for item in variants]
    variants_by_net = sorted(variants, key=lambda item: item["full"]["net"], reverse=True)
    variants_by_bad = sorted(variants, key=lambda item: (item["gates_passed"], item["full"]["net"]))
    return {
        "trials": len(variants),
        "workers": workers,
        "gate_pass_all_count": sum(1 for item in variants if all(item["gates"].values())),
        "gate_pass_3of4_count": sum(1 for item in variants if item["gates_passed"] >= 3),
        "summary": {
            "net_min": min(nets),
            "net_median": sorted(nets)[len(nets) // 2],
            "net_max": max(nets),
            "pf_min": min(pfs),
            "pf_median": sorted(pfs)[len(pfs) // 2],
            "pf_max": max(pfs),
            "dd_min": min(dds),
            "dd_median": sorted(dds)[len(dds) // 2],
            "dd_max": max(dds),
            "june_min": min(june),
            "june_median": sorted(june)[len(june) // 2],
            "june_max": max(june),
        },
        "top_by_net": variants_by_net[:10],
        "weakest": variants_by_bad[:10],
    }


def markdown_table(rows: list[dict], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(lines)


def write_markdown(payload: dict, out: Path) -> None:
    lines = ["# C7 Forward-Test Validation - 2026-06-18", ""]
    lines.append(f"Data window: `{payload['data']['first_bar']}` to `{payload['data']['last_closed_bar']}`. Latest live bar excluded: `{payload['data']['exclude_tail_bars']}`.")
    lines.append("")
    lines.append("## Full Closed-Bar Summary")
    rows = []
    for name, data in payload["strategies"].items():
        full = data["full"]
        rows.append(
            {
                "strategy": name,
                "net": f"${full['net']:,.2f}",
                "buy_hold": f"${full['buy_hold']:,.2f}",
                "excess": f"${full['excess']:,.2f}",
                "trades": full["trades"],
                "PF": f"{full['profit_factor']:.3f}",
                "DD%": f"{full['max_drawdown_pct']:.2f}",
                "part": full["participation_trades"],
            }
        )
    lines.append(markdown_table(rows, ["strategy", "net", "buy_hold", "excess", "trades", "PF", "DD%", "part"]))
    lines.append("")
    lines.append("## Fixed Time Slices")
    for period in ["pre_2026", "q1_2026", "apr_jun_2026", "june_2026"]:
        lines.append(f"### {period}")
        rows = []
        for name, data in payload["strategies"].items():
            row = data["slices"][period]
            rows.append(
                {
                    "strategy": name,
                    "net": f"${row['net']:,.2f}",
                    "buy_hold": f"${row['buy_hold']:,.2f}",
                    "excess": f"${row['excess']:,.2f}",
                    "trades": row["trades"],
                    "PF": f"{row['profit_factor']:.3f}",
                    "DD%": f"{row['trade_drawdown_pct']:.2f}",
                    "part": row["participation_trades"],
                }
            )
        lines.append(markdown_table(rows, ["strategy", "net", "buy_hold", "excess", "trades", "PF", "DD%", "part"]))
        lines.append("")
    lines.append("## Monthly C7")
    lines.append(
        markdown_table(
            [
                {
                    "month": row["month"],
                    "net": f"${row['net']:,.2f}",
                    "trades": row["trades"],
                    "PF": f"{row['profit_factor']:.3f}",
                    "win%": row["win_rate"],
                }
                for row in payload["strategies"]["c7"]["monthly"]
            ],
            ["month", "net", "trades", "PF", "win%"],
        )
    )
    lines.append("")
    lines.append("## C7 Stress")
    stress = payload["stress"]
    lines.append(f"Random local perturbations: `{stress['trials']}`. All four stress gates passed: `{stress['gate_pass_all_count']}`. At least 3/4 gates passed: `{stress['gate_pass_3of4_count']}`.")
    lines.append("")
    lines.append(
        markdown_table(
            [
                {"metric": key, "value": f"{value:,.4f}" if isinstance(value, float) else value}
                for key, value in stress["summary"].items()
            ],
            ["metric", "value"],
        )
    )
    lines.append("")
    lines.append("## Decision")
    decision = payload["decision"]
    for item in decision:
        lines.append(f"- {item}")
    out.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--exclude-tail-bars", type=int, default=1)
    parser.add_argument("--stress-trials", type=int, default=512)
    parser.add_argument("--stress-chunk-trials", type=int, default=32)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--seed", type=int, default=2026061804)
    parser.add_argument("--out-json", default="reports/c7_forward_validation_20260618.json")
    parser.add_argument("--out-md", default="reports/c7_forward_validation_20260618.md")
    args = parser.parse_args()

    bars_all = load_bars(args.data)
    end = len(bars_all) - args.exclude_tail_bars if args.exclude_tail_bars > 0 else len(bars_all)
    bars = bars_all.iloc[:end].copy()
    params_by_name = load_params()

    strategies = {}
    for name, params in params_by_name.items():
        item = run_strategy(name, params, args, end)
        result = item["result"]
        strategies[name] = {
            "full": result_summary(result, bars),
            "slices": strategy_slices(result, bars),
            "monthly": monthly(result, bars),
            "params_participation": {key: value for key, value in params.items() if key.startswith("participation_")},
        }

    stress = stress_test(params_by_name["c7"], strategies, bars, args, end)
    c7 = strategies["c7"]
    c6 = strategies["c6"]
    c2 = strategies["trusted_c2"]
    decision = [
        "C7 remains forward-test active if it beats C6 on full net/PF and beats trusted C2 on June net.",
        f"Full closed-bar C7 net ${c7['full']['net']:,.2f} vs C6 ${c6['full']['net']:,.2f}.",
        f"June C7 net ${c7['slices']['june_2026']['net']:,.2f} vs trusted C2 ${c2['slices']['june_2026']['net']:,.2f}.",
        f"Stress all-gate pass rate {stress['gate_pass_all_count']}/{stress['trials']}.",
    ]
    if not (
        c7["full"]["net"] >= c6["full"]["net"]
        and c7["full"]["profit_factor"] >= c6["full"]["profit_factor"]
        and c7["slices"]["june_2026"]["net"] >= c2["slices"]["june_2026"]["net"]
    ):
        decision.append("C7 failed one of the forward-test active gates and should remain research-only.")
    else:
        decision.append("C7 clears the forward-test active gate set on the current closed-bar snapshot.")

    payload = {
        "data": {
            "source": args.data,
            "daily_bars": args.daily_bars,
            "h4_bars": args.h4_bars,
            "exclude_tail_bars": args.exclude_tail_bars,
            "first_bar": bars.index[0].isoformat(),
            "last_closed_bar": bars.index[-1].isoformat(),
        },
        "strategies": strategies,
        "stress": stress,
        "decision": decision,
    }
    Path(args.out_json).write_text(json.dumps(payload, indent=2) + "\n")
    write_markdown(payload, Path(args.out_md))
    print(json.dumps({"out_json": args.out_json, "out_md": args.out_md, "decision": decision}, indent=2))


if __name__ == "__main__":
    main()
