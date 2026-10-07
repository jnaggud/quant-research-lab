#!/usr/bin/env python3
"""Refine the trusted C5 participation overlay around one exact TradingView rank."""

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


BROAD_BOUNDS = {
    "participation_rsi_min": (42.0, 62.0),
    "participation_rsi_max": (62.0, 88.0),
    "participation_macd_floor": (-4.0, 1.5),
    "participation_vol_mult": (0.0, 1.25),
    "participation_adx_min": (0.0, 32.0),
    "participation_max_extension_atr": (0.6, 6.0),
    "participation_stop_atr": (2.0, 10.0),
    "participation_trail_atr": (2.0, 14.0),
    "participation_exit_rsi": (35.0, 58.0),
    "participation_cooldown": (0, 32),
    "participation_min_hold": (0, 24),
    "participation_max_hold": (24, 240),
}

LOCAL_WINDOWS = {
    "participation_rsi_min": 4.0,
    "participation_rsi_max": 7.0,
    "participation_macd_floor": 1.25,
    "participation_vol_mult": 0.35,
    "participation_adx_min": 7.0,
    "participation_max_extension_atr": 1.4,
    "participation_stop_atr": 1.8,
    "participation_trail_atr": 2.8,
    "participation_exit_rsi": 5.5,
    "participation_cooldown": 8,
    "participation_min_hold": 7,
    "participation_max_hold": 36,
}

CATEGORICAL_CHOICES = {
    "participation_priority": [False, True],
    "participation_regime": ["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"],
    "participation_filter": ["ema21", "ema55", "ema144", "stack", "vwap"],
    "participation_exit_filter": ["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"],
    "participation_exit_on_macd_roll": [False, True],
}


class RandomTrial:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def weighted_center_choice(self, center, choices: list):
        weighted = [center, center, center, center] + [c for c in choices if c != center]
        return self.rng.choice(weighted)

    def local_float(self, center: float, name: str) -> float:
        low, high = BROAD_BOUNDS[name]
        window = LOCAL_WINDOWS[name]
        return min(high, max(low, self.rng.uniform(center - window, center + window)))

    def local_int(self, center: int, name: str) -> int:
        low, high = BROAD_BOUNDS[name]
        window = LOCAL_WINDOWS[name]
        return int(min(high, max(low, self.rng.randint(center - window, center + window))))


def select_item(report: dict, rank: int) -> dict:
    if rank == 0:
        return report["best"]
    return report["top10"][rank - 1]


def prepare_features(data_path: str, daily_bars: str, h4_bars: str, params: dict):
    feat = build_features(load_bars(data_path))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    return feat


def buy_hold_net(feat, params: dict) -> float:
    start = 0
    if params.get("use_date_range") and params.get("start_time"):
        start = int(feat.index.searchsorted(pd.Timestamp(params["start_time"])))
        start = min(max(start, 0), len(feat) - 1)
    return float((feat["close"].iloc[-1] - feat["open"].iloc[start]) * POINT_VALUE)


def refine_params(center: dict, trial: RandomTrial) -> dict:
    params = dict(center)
    params["use_participation"] = True

    for name, choices in CATEGORICAL_CHOICES.items():
        params[name] = trial.weighted_center_choice(center[name], choices)

    for name in (
        "participation_rsi_min",
        "participation_rsi_max",
        "participation_macd_floor",
        "participation_vol_mult",
        "participation_adx_min",
        "participation_max_extension_atr",
        "participation_stop_atr",
        "participation_trail_atr",
        "participation_exit_rsi",
    ):
        params[name] = trial.local_float(float(center[name]), name)

    for name in ("participation_cooldown", "participation_min_hold", "participation_max_hold"):
        params[name] = trial.local_int(int(center[name]), name)

    if params["participation_rsi_min"] >= params["participation_rsi_max"]:
        params["participation_rsi_min"] = max(42.0, params["participation_rsi_max"] - 1.0)
    if params["participation_min_hold"] >= params["participation_max_hold"]:
        params["participation_min_hold"] = max(0, params["participation_max_hold"] - 1)
    return params


def summarize_result(result, feat, center_net: float, params: dict) -> dict:
    trades = result.trades
    recent_start = max(0, len(feat) - 30 * 96)
    recent_net = float(sum(t.pnl for t in trades if t.exit_bar >= recent_start))
    max_winner = max((t.pnl for t in trades), default=0.0)
    buy_hold = buy_hold_net(feat, params)
    return {
        **{k: v for k, v in asdict(result).items() if k != "trades"},
        "buy_hold_net": buy_hold,
        "excess_net": result.net_profit - buy_hold,
        "delta_vs_center": result.net_profit - center_net,
        "recent_30d_net": recent_net,
        "max_winner_share": max_winner / max(abs(result.net_profit), 1.0),
    }


def score(metrics: dict, *, min_trades: int) -> float:
    if metrics["n_trades"] < min_trades:
        return -1_000_000.0 - (min_trades - metrics["n_trades"]) * 1_000.0
    return float(
        metrics["delta_vs_center"] * 2.2
        + metrics["excess_net"] * 0.7
        + metrics["recent_30d_net"] * 0.45
        + max(0.0, metrics["profit_factor"] - 1.0) * 22_000.0
        - metrics["max_drawdown"] * 1_350.0
        - max(0.0, metrics["max_winner_share"] - 0.22) * 70_000.0
    )


def make_item(worker_id: int, params: dict, result, feat, center_net: float, min_trades: int, trials: int) -> dict:
    metrics = summarize_result(result, feat, center_net, params)
    return {
        "worker_id": worker_id,
        "score": score(metrics, min_trades=min_trades),
        "params": params,
        "metrics": metrics,
        "trials": trials,
    }


def run_worker(worker_id: int, args_dict: dict, trials: int) -> dict:
    report = json.loads(Path(args_dict["base_report"]).read_text())
    center_item = select_item(report, args_dict["base_rank"])
    center_params = dict(center_item["params"])
    feat = prepare_features(args_dict["data"], args_dict["daily_bars"], args_dict["h4_bars"], center_params)
    center_result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, center_params), center_params)
    center_net = center_result.net_profit

    best = None
    for idx in range(trials):
        trial = RandomTrial(args_dict["seed"] + worker_id * 1_000_003 + idx)
        params = refine_params(center_params, trial)
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, params), params)
        item = make_item(worker_id, params, result, feat, center_net, args_dict["min_trades"], trials)
        if best is None or item["score"] > best["score"]:
            best = item
    return best


def _progress_row(item: dict) -> dict:
    metrics = item["metrics"]
    return {
        "worker": item["worker_id"],
        "score": item["score"],
        "net": metrics["net_profit"],
        "buy_hold": metrics["buy_hold_net"],
        "excess": metrics["excess_net"],
        "delta_vs_center": metrics["delta_vs_center"],
        "recent_30d": metrics["recent_30d_net"],
        "pf": metrics["profit_factor"],
        "dd_pct": metrics["max_drawdown"],
        "trades": metrics["n_trades"],
        "participation_trades": metrics["participation_trades"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-report", default="reports/c5_participation_overlay_32k_20260618.json")
    parser.add_argument("--base-rank", type=int, default=2)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--trials", type=int, default=32768)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--seed", type=int, default=2026061802)
    parser.add_argument("--min-trades", type=int, default=435)
    parser.add_argument("--out", default="reports/c5_participation_overlay_c2_refine_32k_20260618.json")
    args = parser.parse_args()

    report = json.loads(Path(args.base_report).read_text())
    center_item = select_item(report, args.base_rank)
    center_params = dict(center_item["params"])
    center_feat = prepare_features(args.data, args.daily_bars, args.h4_bars, center_params)
    center_result = run_tv_compatible_signal_bars(build_c5_signal_bars(center_feat, center_params), center_params)
    center = make_item(
        -1,
        center_params,
        center_result,
        center_feat,
        center_result.net_profit,
        args.min_trades,
        0,
    )

    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(trial_counts)))
    args_dict = vars(args)

    results = [center]
    print(json.dumps({"center": _progress_row(center)}), flush=True)
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

    ranked = sorted(results, key=lambda r: r["score"], reverse=True)
    payload = {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "base_report": args.base_report,
        "base_rank": args.base_rank,
        "requested_trials": args.trials,
        "completed_trials": sum(r["trials"] for r in results),
        "workers": workers,
        "center": center,
        "objective": {
            "mode": "c2_participation_overlay_refinement",
            "min_trades": args.min_trades,
            "notes": [
                "Trusted C2 parameters are the center candidate.",
                "Base C5/core/cap behavior is frozen.",
                "Only participation sleeve parameters are locally perturbed.",
                "Execution uses the TradingView-parity broker model.",
            ],
        },
        "best": ranked[0],
        "top10": ranked[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
