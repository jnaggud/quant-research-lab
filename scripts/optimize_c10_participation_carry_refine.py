#!/usr/bin/env python3
"""C10 search: preserve C9 core/cap and refine carry/participation exposure."""

from __future__ import annotations

import argparse
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from c8_monitor_analyze import buy_hold, load_strategy_params, prepare_features, trade_summary
from tv_c5_parity_engine import build_c5_signal_bars, run_tv_compatible_signal_bars


FLOAT_BOUNDS = {
    "carry_rsi_min": (43.0, 62.0),
    "carry_macd_floor": (-6.0, 1.0),
    "carry_vol_mult": (0.25, 1.25),
    "participation_rsi_min": (42.0, 60.0),
    "participation_rsi_max": (56.0, 82.0),
    "participation_macd_floor": (-6.0, 1.5),
    "participation_vol_mult": (0.25, 1.25),
    "participation_adx_min": (0.0, 30.0),
    "participation_max_extension_atr": (2.0, 9.0),
    "participation_stop_atr": (3.0, 8.0),
    "participation_trail_atr": (3.0, 9.0),
    "participation_exit_rsi": (38.0, 55.0),
}

INT_BOUNDS = {
    "participation_cooldown": (0, 18),
    "participation_min_hold": (0, 40),
    "participation_max_hold": (12, 96),
}

CATEGORIES = {
    "carry_regime": ["both_up", "h4_up", "daily_up", "either_up"],
    "carry_filter": ["none", "ema21", "ema55", "ema144", "stack"],
    "participation_regime": ["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"],
    "participation_filter": ["ema21", "ema55", "ema144", "stack", "vwap"],
    "participation_exit_filter": ["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"],
}

BOOLEANS = ["participation_priority", "participation_exit_on_macd_roll"]


def json_default(value):
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


class RandomTrial:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def bounded_float(self, key: str) -> float:
        low, high = FLOAT_BOUNDS[key]
        return self.rng.uniform(low, high)

    def bounded_int(self, key: str) -> int:
        low, high = INT_BOUNDS[key]
        return self.rng.randint(low, high)

    def weighted_center_choice(self, center, choices: list):
        weighted = [center, center, center] + [choice for choice in choices if choice != center]
        return self.rng.choice(weighted)


def load_c9_center(path: str) -> dict:
    report = json.loads(Path(path).read_text())
    return dict(report["best"]["params"])


def buy_hold_date_filtered(bars: pd.DataFrame, params: dict) -> float:
    start = 0
    if params.get("use_date_range") and params.get("start_time"):
        start = int(bars.index.searchsorted(pd.Timestamp(params["start_time"])))
        start = min(max(start, 0), len(bars) - 1)
    return buy_hold(bars, start)


def summarize(result, bars: pd.DataFrame, params: dict, forward_idx: int, month_idx: int) -> dict:
    closed = trade_summary(result, bars, 0, params)
    forward = trade_summary(result, bars, forward_idx, params)
    current_month = trade_summary(result, bars, month_idx, params)
    return {
        **{key: value for key, value in asdict(result).items() if key != "trades"},
        "closed": closed,
        "forward": forward,
        "current_month": current_month,
        "buy_hold_net": buy_hold_date_filtered(bars, params),
        "excess_net": closed["excess"],
        "max_winner_share": max((trade.pnl for trade in result.trades if trade.exit_reason != "end_of_data"), default=0.0)
        / max(abs(closed["net"]), 1.0),
    }


def make_params(center: dict, trial: RandomTrial) -> dict:
    params = dict(center)
    for key in FLOAT_BOUNDS:
        params[key] = trial.bounded_float(key)
    for key in INT_BOUNDS:
        params[key] = trial.bounded_int(key)
    if params["participation_max_hold"] < params["participation_min_hold"] + 4:
        params["participation_max_hold"] = params["participation_min_hold"] + 4
    if params["participation_rsi_max"] < params["participation_rsi_min"] + 2.0:
        params["participation_rsi_max"] = params["participation_rsi_min"] + 2.0
    for key, choices in CATEGORIES.items():
        params[key] = trial.weighted_center_choice(center.get(key), choices)
    for key in BOOLEANS:
        params[key] = trial.weighted_center_choice(center.get(key), [False, True])
    params["use_carry_long"] = True
    params["use_participation"] = True
    return params


def gates(metrics: dict, refs: dict, min_trades: int, max_winner_share: float) -> dict:
    c9 = refs["c9_c1"]
    c8 = refs["c8_c5"]
    return {
        "min_trades": metrics["closed"]["trades"] >= min_trades,
        "net_ge_c9": metrics["closed"]["net"] >= c9["closed"]["net"],
        "excess_ge_c9": metrics["closed"]["excess"] >= c9["closed"]["excess"],
        "pf_ge_c9": metrics["closed"]["profit_factor"] >= c9["closed"]["profit_factor"],
        "dd_le_c9": metrics["max_drawdown"] <= c9["max_drawdown"],
        "month_ge_c9": metrics["current_month"]["net"] >= c9["current_month"]["net"],
        "forward_gt_c9": metrics["forward"]["net"] > c9["forward"]["net"],
        "forward_non_negative": metrics["forward"]["net"] >= 0.0,
        "net_ge_c8_c5": metrics["closed"]["net"] >= c8["closed"]["net"],
        "max_winner_share_ok": metrics["max_winner_share"] <= max_winner_share,
    }


def score(metrics: dict, refs: dict, min_trades: int, max_winner_share: float) -> float:
    gate = gates(metrics, refs, min_trades, max_winner_share)
    c9 = refs["c9_c1"]
    c8 = refs["c8_c5"]
    return float(
        sum(1 for passed in gate.values() if passed) * 150_000.0
        + (metrics["closed"]["net"] - c9["closed"]["net"]) * 1.8
        + (metrics["closed"]["excess"] - c9["closed"]["excess"]) * 1.3
        + (metrics["forward"]["net"] - c9["forward"]["net"]) * 14.0
        + max(0.0, metrics["forward"]["net"]) * 30.0
        + (metrics["current_month"]["net"] - c9["current_month"]["net"]) * 4.0
        + (metrics["closed"]["profit_factor"] - c9["closed"]["profit_factor"]) * 160_000.0
        - max(0.0, metrics["max_drawdown"] - c9["max_drawdown"]) * 35_000.0
        - max(0.0, c8["closed"]["net"] - metrics["closed"]["net"]) * 0.8
        - max(0.0, min_trades - metrics["closed"]["trades"]) * 3_500.0
        - max(0.0, metrics["max_winner_share"] - max_winner_share) * 160_000.0
    )


def compute_refs(params_by_name: dict, bars: pd.DataFrame, forward_idx: int, month_idx: int) -> dict:
    refs = {}
    for name, params in params_by_name.items():
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(bars, params), params)
        refs[name] = summarize(result, bars, params, forward_idx, month_idx)
    return refs


def build_item(worker_id: int, params: dict, bars: pd.DataFrame, refs: dict, forward_idx: int, month_idx: int, args: dict, trials: int) -> dict:
    result = run_tv_compatible_signal_bars(build_c5_signal_bars(bars, params), params)
    metrics = summarize(result, bars, params, forward_idx, month_idx)
    gate = gates(metrics, refs, args["min_trades"], args["max_winner_share"])
    return {
        "worker_id": worker_id,
        "score": score(metrics, refs, args["min_trades"], args["max_winner_share"]),
        "gates": gate,
        "gates_passed": sum(1 for passed in gate.values() if passed),
        "promotion_gate_pass": all(gate.values()),
        "params": params,
        "metrics": metrics,
        "trials": trials,
    }


def load_context(args: dict):
    params_by_name = load_strategy_params()
    center = load_c9_center(args["c9_report"])
    params_by_name["c9_c1"] = dict(center)
    bars = prepare_features(args["data"], args["daily_bars"], args["h4_bars"], center, end=10**9)
    forward_idx = int(bars.index.searchsorted(pd.Timestamp(args["forward_start"])))
    month_idx = int(bars.index.searchsorted(pd.Timestamp(args["month_start"])))
    refs = compute_refs(params_by_name, bars, forward_idx, month_idx)
    return center, refs, bars, forward_idx, month_idx


def keep_top(items: list[dict], item: dict, limit: int) -> None:
    items.append(item)
    items.sort(key=lambda row: row["score"], reverse=True)
    if len(items) > limit:
        items.pop()


def run_worker(worker_id: int, args: dict, trials: int) -> list[dict]:
    center, refs, bars, forward_idx, month_idx = load_context(args)
    best: list[dict] = []
    for idx in range(trials):
        trial = RandomTrial(args["seed"] + worker_id * 1_000_003 + idx)
        params = make_params(center, trial)
        item = build_item(worker_id, params, bars, refs, forward_idx, month_idx, args, trials)
        keep_top(best, item, args["top_per_chunk"])
    return best


def progress_row(item: dict) -> dict:
    m = item["metrics"]
    return {
        "worker": item["worker_id"],
        "score": round(item["score"], 3),
        "gates": item["gates_passed"],
        "pass": item["promotion_gate_pass"],
        "net": m["closed"]["net"],
        "excess": m["closed"]["excess"],
        "pf": round(m["closed"]["profit_factor"], 4),
        "dd": round(m["max_drawdown"], 4),
        "month": m["current_month"]["net"],
        "forward": m["forward"]["net"],
        "trades": m["closed"]["trades"],
        "participation": m["closed"]["participation_trades"],
        "core": m["closed"]["core_trades"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="reports/c8_monitor/data/es1_15m_20260620_064007.json")
    parser.add_argument("--daily-bars", default="reports/c8_monitor/data/es1_1d_20260620_064007.json")
    parser.add_argument("--h4-bars", default="reports/c8_monitor/data/es1_240m_20260620_064007.json")
    parser.add_argument("--c9-report", default="reports/c9_core_forward_refine_200k_20260620.json")
    parser.add_argument("--forward-start", default="2026-06-18T00:00:00Z")
    parser.add_argument("--month-start", default="2026-06-01T00:00:00Z")
    parser.add_argument("--trials", type=int, default=200000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--top-per-chunk", type=int, default=5)
    parser.add_argument("--seed", type=int, default=2026062101)
    parser.add_argument("--min-trades", type=int, default=435)
    parser.add_argument("--max-winner-share", type=float, default=0.18)
    parser.add_argument("--out", default="reports/c10_participation_carry_refine_200k_20260621.json")
    args = parser.parse_args()

    center, refs, bars, forward_idx, month_idx = load_context(vars(args))
    center_item = build_item(-1, center, bars, refs, forward_idx, month_idx, vars(args), 0)
    print(json.dumps({"center": progress_row(center_item), "references": {k: v["closed"] for k, v in refs.items()}}), flush=True)

    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))

    results = [center_item]
    completed_trials = 0
    if workers == 1:
        for idx, count in enumerate(trial_counts):
            items = run_worker(idx, vars(args), count)
            completed_trials += count
            results.extend(items)
            print(json.dumps(progress_row(items[0])), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_worker, idx, vars(args), count): count for idx, count in enumerate(trial_counts)}
            for future in as_completed(futures):
                items = future.result()
                completed_trials += futures[future]
                results.extend(items)
                print(json.dumps(progress_row(items[0])), flush=True)

    ranked = sorted(results, key=lambda row: row["score"], reverse=True)
    passers = [row for row in ranked if row["promotion_gate_pass"]]
    payload = {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "c9_report": args.c9_report,
        "forward_start": args.forward_start,
        "month_start": args.month_start,
        "requested_trials": args.trials,
        "completed_trials": completed_trials,
        "workers": workers,
        "chunk_trials": args.chunk_trials,
        "top_per_chunk": args.top_per_chunk,
        "objective": {
            "mode": "c10_participation_carry_refine",
            "notes": [
                "C9 core filters and C8 cap parameters are frozen.",
                "Search changes carry and participation exposure only.",
                "Promotion requires C9-or-better net/excess/PF/DD/current month and a better forward slice.",
            ],
        },
        "references": refs,
        "center": center_item,
        "best": ranked[0],
        "best_promotion_gate_pass": passers[0] if passers else None,
        "promotion_gate_pass_count": len(passers),
        "top10": ranked[:10],
        "top10_promotion_gate_pass": passers[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, default=json_default) + "\n")
    print(
        json.dumps(
            {
                "out": args.out,
                "completed_trials": completed_trials,
                "workers": workers,
                "promotion_gate_pass_count": len(passers),
                "best": progress_row(ranked[0]),
                "best_promotion_gate_pass": progress_row(passers[0]) if passers else None,
            },
            indent=2,
            default=json_default,
        )
    )


if __name__ == "__main__":
    main()
