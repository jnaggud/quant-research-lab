#!/usr/bin/env python3
"""Optimize an opt-in long participation sleeve on top of exact C1."""

from __future__ import annotations

import argparse
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from tv_c5_parity_engine import (
    POINT_VALUE,
    apply_tv_daily_security,
    apply_tv_h4_security,
    build_c5_signal_bars,
    build_features,
    load_bars,
    run_tv_compatible_signal_bars,
)


class RandomTrial:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def categorical(self, choices: list):
        return self.rng.choice(choices)

    def integer(self, low: int, high: int):
        return self.rng.randint(low, high)

    def floating(self, low: float, high: float):
        return self.rng.uniform(low, high)


def select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def prepare_features(data_path: str, daily_bars: str, h4_bars: str, params: dict):
    feat = build_features(load_bars(data_path))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    return feat


def buy_hold_net(feat) -> float:
    return float((feat["close"].iloc[-1] - feat["open"].iloc[0]) * POINT_VALUE)


def overlay_params(base: dict, trial: RandomTrial) -> dict:
    params = dict(base)
    params.update(
        {
            "use_participation": True,
            "participation_priority": trial.categorical([False, True]),
            "participation_regime": trial.categorical(
                ["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"]
            ),
            "participation_filter": trial.categorical(["ema21", "ema55", "ema144", "stack", "vwap"]),
            "participation_rsi_min": trial.floating(42.0, 62.0),
            "participation_rsi_max": trial.floating(62.0, 88.0),
            "participation_macd_floor": trial.floating(-4.0, 1.5),
            "participation_vol_mult": trial.floating(0.0, 1.25),
            "participation_adx_min": trial.floating(0.0, 32.0),
            "participation_max_extension_atr": trial.floating(0.6, 6.0),
            "participation_stop_atr": trial.floating(2.0, 10.0),
            "participation_trail_atr": trial.floating(2.0, 14.0),
            "participation_cooldown": trial.integer(0, 32),
            "participation_min_hold": trial.integer(0, 24),
            "participation_max_hold": trial.integer(24, 240),
            "participation_exit_filter": trial.categorical(["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"]),
            "participation_exit_rsi": trial.floating(35.0, 58.0),
            "participation_exit_on_macd_roll": trial.categorical([False, True]),
        }
    )
    if params["participation_rsi_min"] >= params["participation_rsi_max"]:
        params["participation_rsi_min"] = params["participation_rsi_max"] - 1.0
    if params["participation_min_hold"] >= params["participation_max_hold"]:
        params["participation_min_hold"] = max(0, params["participation_max_hold"] - 1)
    return params


def summarize_result(result, feat, baseline_net: float) -> dict:
    trades = result.trades
    recent_start = max(0, len(feat) - 30 * 96)
    recent_net = float(sum(t.pnl for t in trades if t.exit_bar >= recent_start))
    max_winner = max((t.pnl for t in trades), default=0.0)
    return {
        **{k: v for k, v in asdict(result).items() if k != "trades"},
        "buy_hold_net": buy_hold_net(feat),
        "excess_net": result.net_profit - buy_hold_net(feat),
        "delta_vs_c1": result.net_profit - baseline_net,
        "recent_30d_net": recent_net,
        "max_winner_share": max_winner / max(abs(result.net_profit), 1.0),
    }


def score(metrics: dict, *, min_trades: int, baseline_net: float) -> float:
    if metrics["n_trades"] < min_trades:
        return -1_000_000.0 - (min_trades - metrics["n_trades"]) * 1000.0
    delta = metrics["net_profit"] - baseline_net
    excess = metrics["excess_net"]
    return float(
        delta * 1.5
        + excess * 0.75
        + metrics["recent_30d_net"] * 0.5
        + max(0.0, metrics["profit_factor"] - 1.0) * 20_000.0
        - metrics["max_drawdown"] * 1_200.0
        - max(0.0, metrics["max_winner_share"] - 0.22) * 60_000.0
    )


def run_worker(worker_id: int, args_dict: dict, trials: int) -> dict:
    report = json.loads(Path(args_dict["base_report"]).read_text())
    base_item = select_item(report, args_dict["base_rank"])
    base_params = dict(base_item["params"])
    feat = prepare_features(args_dict["data"], args_dict["daily_bars"], args_dict["h4_bars"], base_params)
    base_result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, base_params), base_params)
    baseline_net = base_result.net_profit

    best = None
    for idx in range(trials):
        trial = RandomTrial(args_dict["seed"] + worker_id * 1_000_003 + idx)
        params = overlay_params(base_params, trial)
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
        metrics = summarize_result(result, feat, baseline_net)
        item = {
            "worker_id": worker_id,
            "score": score(metrics, min_trades=args_dict["min_trades"], baseline_net=baseline_net),
            "params": params,
            "metrics": metrics,
            "trials": trials,
        }
        if best is None or item["score"] > best["score"]:
            best = item
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-report", default="reports/c5_successor_tv_parity_128k_exact_20260617.json")
    parser.add_argument("--base-rank", type=int, default=1)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--trials", type=int, default=32768)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--seed", type=int, default=2026061801)
    parser.add_argument("--min-trades", type=int, default=435)
    parser.add_argument("--out", default="reports/c5_participation_overlay_search.json")
    args = parser.parse_args()

    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))
    args_dict = vars(args)

    results = []
    if workers == 1:
        for idx, count in enumerate(trial_counts):
            item = run_worker(idx, args_dict, count)
            results.append(item)
            print(json.dumps(_progress_row(item)), flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_worker, idx, args_dict, count) for idx, count in enumerate(trial_counts)]
            for future in as_completed(futures):
                item = future.result()
                results.append(item)
                print(json.dumps(_progress_row(item)), flush=True)

    payload = {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "base_report": args.base_report,
        "base_rank": args.base_rank,
        "requested_trials": args.trials,
        "completed_trials": sum(r["trials"] for r in results),
        "workers": workers,
        "objective": {
            "mode": "c5_plus_long_participation_overlay",
            "min_trades": args.min_trades,
            "notes": [
                "Base C1 parameters are frozen.",
                "Only opt-in participation sleeve parameters are searched.",
                "Execution uses the same TradingView-parity broker model as C1.",
            ],
        },
        "best": max(results, key=lambda r: r["score"]),
        "top10": sorted(results, key=lambda r: r["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


def _progress_row(item: dict) -> dict:
    metrics = item["metrics"]
    return {
        "worker": item["worker_id"],
        "score": item["score"],
        "net": metrics["net_profit"],
        "buy_hold": metrics["buy_hold_net"],
        "excess": metrics["excess_net"],
        "delta_vs_c1": metrics["delta_vs_c1"],
        "recent_30d": metrics["recent_30d_net"],
        "pf": metrics["profit_factor"],
        "dd_pct": metrics["max_drawdown"],
        "trades": metrics["n_trades"],
        "participation_trades": metrics["participation_trades"],
    }


if __name__ == "__main__":
    main()
