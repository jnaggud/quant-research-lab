#!/usr/bin/env python3
"""Constrained C6 refinement: preserve net/PF while improving drawdown and June behavior."""

from __future__ import annotations

import argparse
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
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


MANAGEMENT_FLOAT_BOUNDS = {
    "participation_stop_atr": (2.0, 10.0, 1.25),
    "participation_trail_atr": (2.0, 14.0, 2.0),
    "participation_exit_rsi": (35.0, 58.0, 4.0),
}

MANAGEMENT_INT_BOUNDS = {
    "participation_cooldown": (0, 32, 8),
    "participation_min_hold": (0, 24, 6),
    "participation_max_hold": (24, 240, 28),
}

MANAGEMENT_CATEGORIES = {
    "participation_exit_filter": ["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"],
    "participation_exit_on_macd_roll": [False, True],
}


class RandomTrial:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def local_float(self, center: float, name: str) -> float:
        low, high, window = MANAGEMENT_FLOAT_BOUNDS[name]
        return min(high, max(low, self.rng.uniform(center - window, center + window)))

    def local_int(self, center: int, name: str) -> int:
        low, high, window = MANAGEMENT_INT_BOUNDS[name]
        return int(min(high, max(low, self.rng.randint(center - window, center + window))))

    def weighted_center_choice(self, center, choices: list):
        weighted = [center, center, center, center, center] + [c for c in choices if c != center]
        return self.rng.choice(weighted)


def select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def prepare_features(data_path: str, daily_bars: str, h4_bars: str, params: dict, exclude_tail_bars: int):
    feat = build_features(load_bars(data_path))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    if exclude_tail_bars > 0:
        feat = feat.iloc[:-exclude_tail_bars].copy()
    return feat


def buy_hold_net(feat, params: dict) -> float:
    start = 0
    if params.get("use_date_range") and params.get("start_time"):
        start = int(feat.index.searchsorted(pd.Timestamp(params["start_time"])))
        start = min(max(start, 0), len(feat) - 1)
    return float((feat["close"].iloc[-1] - feat["open"].iloc[start]) * POINT_VALUE)


def june_net(result, feat) -> tuple[float, int, float]:
    june_start = int(feat.index.searchsorted(pd.Timestamp("2026-06-01", tz="UTC")))
    trades = [trade for trade in result.trades if trade.exit_bar >= june_start]
    hold = float((feat["close"].iloc[-1] - feat["open"].iloc[june_start]) * POINT_VALUE)
    return float(sum(trade.pnl for trade in trades)), len(trades), hold


def summarize_result(result, feat, references: dict, params: dict) -> dict:
    june_pnl, june_trades, june_hold = june_net(result, feat)
    max_winner = max((trade.pnl for trade in result.trades), default=0.0)
    buy_hold = buy_hold_net(feat, params)
    return {
        **{key: value for key, value in asdict(result).items() if key != "trades"},
        "buy_hold_net": buy_hold,
        "excess_net": result.net_profit - buy_hold,
        "delta_vs_c6": result.net_profit - references["c6"]["net_profit"],
        "delta_pf_vs_c6": result.profit_factor - references["c6"]["profit_factor"],
        "delta_dd_vs_c6": result.max_drawdown - references["c6"]["max_drawdown"],
        "june_net": june_pnl,
        "june_trades": june_trades,
        "june_buy_hold_net": june_hold,
        "delta_june_vs_trusted_c2": june_pnl - references["trusted_c2"]["june_net"],
        "max_winner_share": max_winner / max(abs(result.net_profit), 1.0),
    }


def refine_params(center: dict, trial: RandomTrial) -> dict:
    params = dict(center)
    for name in MANAGEMENT_FLOAT_BOUNDS:
        params[name] = trial.local_float(float(center[name]), name)
    for name in MANAGEMENT_INT_BOUNDS:
        params[name] = trial.local_int(int(center[name]), name)
    for name, choices in MANAGEMENT_CATEGORIES.items():
        params[name] = trial.weighted_center_choice(center[name], choices)
    if params["participation_min_hold"] >= params["participation_max_hold"]:
        params["participation_min_hold"] = max(0, params["participation_max_hold"] - 1)
    return params


def gates(metrics: dict, references: dict, min_trades: int) -> dict:
    risk_dd = references["risk_target"]["max_drawdown"]
    return {
        "min_trades": bool(metrics["n_trades"] >= min_trades),
        "net_ge_c6": bool(metrics["net_profit"] >= references["c6"]["net_profit"]),
        "pf_ge_c6": bool(metrics["profit_factor"] >= references["c6"]["profit_factor"]),
        "dd_le_risk_target": bool(metrics["max_drawdown"] <= risk_dd),
        "june_ge_trusted_c2": bool(metrics["june_net"] >= references["trusted_c2"]["june_net"]),
    }


def score(metrics: dict, references: dict, min_trades: int) -> float:
    gate = gates(metrics, references, min_trades)
    gate_count = sum(1 for passed in gate.values() if passed)
    risk_dd = references["risk_target"]["max_drawdown"]
    return float(
        gate_count * 100_000.0
        + metrics["delta_vs_c6"] * 1.6
        + metrics["delta_june_vs_trusted_c2"] * 2.3
        + metrics["delta_pf_vs_c6"] * 80_000.0
        - max(0.0, metrics["max_drawdown"] - risk_dd) * 14_000.0
        - max(0.0, min_trades - metrics["n_trades"]) * 2_000.0
        - max(0.0, metrics["max_winner_share"] - 0.18) * 80_000.0
    )


def make_item(worker_id: int, params: dict, result, feat, references: dict, min_trades: int, trials: int) -> dict:
    metrics = summarize_result(result, feat, references, params)
    gate = gates(metrics, references, min_trades)
    return {
        "worker_id": worker_id,
        "score": score(metrics, references, min_trades),
        "gates": gate,
        "gates_passed": sum(1 for passed in gate.values() if passed),
        "promotion_gate_pass": all(gate.values()),
        "params": params,
        "metrics": metrics,
        "trials": trials,
    }


def compute_reference(name: str, params: dict, feat) -> dict:
    result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
    june_pnl, june_trades, june_hold = june_net(result, feat)
    return {
        "name": name,
        "net_profit": result.net_profit,
        "profit_factor": result.profit_factor,
        "max_drawdown": result.max_drawdown,
        "n_trades": result.n_trades,
        "june_net": june_pnl,
        "june_trades": june_trades,
        "june_buy_hold_net": june_hold,
    }


def load_references(args_dict: dict) -> tuple[dict, dict, object]:
    base_report = json.loads(Path(args_dict["base_report"]).read_text())
    refine_report = json.loads(Path(args_dict["refine_report"]).read_text())
    trusted_item = select_item(base_report, args_dict["trusted_rank"])
    c6_item = select_item(refine_report, args_dict["c6_rank"])
    rank4_item = select_item(refine_report, args_dict["risk_rank_a"])
    rank9_item = select_item(refine_report, args_dict["risk_rank_b"])
    c6_params = dict(c6_item["params"])
    feat = prepare_features(
        args_dict["data"],
        args_dict["daily_bars"],
        args_dict["h4_bars"],
        c6_params,
        args_dict["exclude_tail_bars"],
    )
    references = {
        "trusted_c2": compute_reference("trusted_c2", dict(trusted_item["params"]), feat),
        "c6": compute_reference("c6", c6_params, feat),
        "rank4": compute_reference("rank4", dict(rank4_item["params"]), feat),
        "rank9": compute_reference("rank9", dict(rank9_item["params"]), feat),
    }
    references["risk_target"] = min((references["rank4"], references["rank9"]), key=lambda row: row["max_drawdown"])
    return c6_params, references, feat


def run_worker(worker_id: int, args_dict: dict, trials: int) -> dict:
    center_params, references, feat = load_references(args_dict)
    best = None
    for idx in range(trials):
        trial = RandomTrial(args_dict["seed"] + worker_id * 1_000_003 + idx)
        params = refine_params(center_params, trial)
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
        item = make_item(worker_id, params, result, feat, references, args_dict["min_trades"], trials)
        if best is None or item["score"] > best["score"]:
            best = item
    return best


def progress_row(item: dict) -> dict:
    metrics = item["metrics"]
    return {
        "worker": item["worker_id"],
        "score": item["score"],
        "gates": item["gates_passed"],
        "pass": item["promotion_gate_pass"],
        "net": metrics["net_profit"],
        "delta_vs_c6": metrics["delta_vs_c6"],
        "pf": metrics["profit_factor"],
        "dd": metrics["max_drawdown"],
        "june": metrics["june_net"],
        "delta_june": metrics["delta_june_vs_trusted_c2"],
        "trades": metrics["n_trades"],
        "participation_trades": metrics["participation_trades"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-report", default="reports/c5_participation_overlay_32k_20260618.json")
    parser.add_argument("--refine-report", default="reports/c5_participation_overlay_c2_refine_32k_20260618.json")
    parser.add_argument("--trusted-rank", type=int, default=2)
    parser.add_argument("--c6-rank", type=int, default=2)
    parser.add_argument("--risk-rank-a", type=int, default=4)
    parser.add_argument("--risk-rank-b", type=int, default=9)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--exclude-tail-bars", type=int, default=1)
    parser.add_argument("--trials", type=int, default=32768)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--seed", type=int, default=2026061803)
    parser.add_argument("--min-trades", type=int, default=435)
    parser.add_argument("--out", default="reports/c6_constrained_refine_32k_20260618.json")
    args = parser.parse_args()

    center_params, references, feat = load_references(vars(args))
    center_result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, center_params), center_params)
    center = make_item(-1, center_params, center_result, feat, references, args.min_trades, 0)
    print(json.dumps({"center": progress_row(center), "references": references}), flush=True)

    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))

    results = [center]
    if workers == 1:
        for idx, count in enumerate(trial_counts):
            item = run_worker(idx, vars(args), count)
            results.append(item)
            print(json.dumps(progress_row(item)), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_worker, idx, vars(args), count) for idx, count in enumerate(trial_counts)]
            for future in as_completed(futures):
                item = future.result()
                results.append(item)
                print(json.dumps(progress_row(item)), flush=True)

    ranked = sorted(results, key=lambda item: item["score"], reverse=True)
    passers = [item for item in ranked if item["promotion_gate_pass"]]
    payload = {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "exclude_tail_bars": args.exclude_tail_bars,
        "base_report": args.base_report,
        "refine_report": args.refine_report,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "workers": workers,
        "objective": {
            "mode": "c6_constrained_management_refinement",
            "min_trades": args.min_trades,
            "notes": [
                "C6 entry logic is frozen.",
                "Only participation stop/trail/exit/hold/cooldown settings are searched.",
                "Promotion gates require net>=C6, PF>=C6, DD<=risk reference, and June>=trusted C2.",
                "Latest live bar is excluded from local scoring.",
            ],
        },
        "references": references,
        "center": center,
        "best": ranked[0],
        "best_promotion_gate_pass": passers[0] if passers else None,
        "promotion_gate_pass_count": len(passers),
        "top10": ranked[:10],
        "top10_promotion_gate_pass": passers[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
