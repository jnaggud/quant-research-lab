#!/usr/bin/env python3
"""Search C5 successor parameters using the TradingView-parity engine."""

from __future__ import annotations

import argparse
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np

try:
    import optuna
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    optuna = None

from tv_c5_parity_engine import (
    POINT_VALUE,
    apply_tv_daily_security,
    apply_tv_h4_security,
    build_c5_signal_bars,
    build_features,
    default_c5_params,
    load_bars,
    run_tv_compatible_signal_bars,
)


def prepare_features(data_path: str, daily_bars: str, h4_bars: str, params: dict):
    feat = build_features(load_bars(data_path))
    feat = apply_tv_daily_security(feat, daily_bars, params)
    feat = apply_tv_h4_security(feat, h4_bars, params)
    return feat


def buy_hold_net(feat) -> float:
    return float((feat["close"].iloc[-1] - feat["open"].iloc[0]) * POINT_VALUE)


class RandomTrial:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.params: dict = {}

    def suggest_categorical(self, name: str, choices: list):
        value = self.rng.choice(choices)
        self.params[name] = value
        return value

    def suggest_int(self, name: str, low: int, high: int):
        value = self.rng.randint(low, high)
        self.params[name] = value
        return value

    def suggest_float(self, name: str, low: float, high: float):
        value = self.rng.uniform(low, high)
        self.params[name] = value
        return value


def trial_params(trial) -> dict:
    params = default_c5_params()
    params.update(
        {
            "allow_short": trial.suggest_categorical("allow_short", [True, False]),
            "short_gate": trial.suggest_categorical(
                "short_gate",
                ["any", "daily_bear", "not_daily_bull", "h4_and_daily_bear"],
            ),
            "use_carry_long": trial.suggest_categorical("use_carry_long", [False, True]),
            "carry_regime": trial.suggest_categorical("carry_regime", ["both_up", "h4_up", "daily_up", "either_up"]),
            "carry_filter": trial.suggest_categorical("carry_filter", ["ema21", "ema55", "ema144", "stack"]),
            "carry_rsi_min": trial.suggest_float("carry_rsi_min", 38.0, 58.0),
            "carry_macd_floor": trial.suggest_float("carry_macd_floor", -4.0, 1.0),
            "carry_vol_mult": trial.suggest_float("carry_vol_mult", 0.25, 1.25),
            "cooldown": trial.suggest_int("cooldown", 0, 48),
            "stop_atr": trial.suggest_float("stop_atr", 2.0, 7.5),
            "trail_atr": trial.suggest_float("trail_atr", 2.5, 10.0),
            "long_rsi_min": trial.suggest_float("long_rsi_min", 32.0, 55.0),
            "short_rsi_max": trial.suggest_float("short_rsi_max", 45.0, 68.0),
            "macd_floor": trial.suggest_float("macd_floor", -6.0, 0.5),
            "vol_mult": trial.suggest_float("vol_mult", 0.25, 1.35),
            "cap_regime": trial.suggest_categorical("cap_regime", ["any", "daily_not_bear", "h4_up", "either_up"]),
            "cap_cooldown": trial.suggest_int("cap_cooldown", 0, 24),
            "cap_min_hold": trial.suggest_int("cap_min_hold", 0, 16),
            "cap_max_hold": trial.suggest_int("cap_max_hold", 12, 120),
            "cap_stop_atr": trial.suggest_float("cap_stop_atr", 1.5, 7.0),
            "cap_target_atr": trial.suggest_float("cap_target_atr", 0.75, 5.0),
            "cap_trail_atr": trial.suggest_float("cap_trail_atr", 0.25, 3.0),
            "cap_exit_vwap_atr": trial.suggest_float("cap_exit_vwap_atr", -1.0, 1.5),
            "cap_exit_rsi": trial.suggest_float("cap_exit_rsi", 45.0, 78.0),
            "cap_exit_range_pos": trial.suggest_float("cap_exit_range_pos", 0.0, 0.8),
            "cap_exit_on_momentum_peak": trial.suggest_categorical("cap_exit_on_momentum_peak", [True, False]),
        }
    )
    if params["cap_min_hold"] >= params["cap_max_hold"]:
        params["cap_min_hold"] = max(0, params["cap_max_hold"] - 1)
    if not params["allow_short"]:
        params["short_gate"] = "any"
    return params


def params_from_mapping(values: dict) -> dict:
    params = default_c5_params()
    params.update(values)
    if params["cap_min_hold"] >= params["cap_max_hold"]:
        params["cap_min_hold"] = max(0, params["cap_max_hold"] - 1)
    if not params["allow_short"]:
        params["short_gate"] = "any"
    return params


def score_result(result, feat, min_trades: int, min_excess: float) -> tuple[float, dict]:
    hold = buy_hold_net(feat)
    excess = result.net_profit - hold
    trades = result.trades
    recent_start = max(0, len(feat) - 30 * 96)
    recent_net = float(sum(t.pnl for t in trades if t.exit_bar >= recent_start))
    max_winner = max((t.pnl for t in trades), default=0.0)
    max_winner_share = max_winner / max(abs(result.net_profit), 1.0)

    if result.n_trades < min_trades:
        return -1_000_000.0 - (min_trades - result.n_trades) * 1000.0, {
            "buy_hold_net": hold,
            "excess_net": excess,
            "recent_30d_net": recent_net,
            "max_winner_share": max_winner_share,
        }

    score = (
        excess
        + result.net_profit * 0.25
        + max(0.0, result.profit_factor - 1.0) * 25_000.0
        + recent_net * 0.75
        - result.max_drawdown * 1_000.0
        - max(0.0, max_winner_share - 0.25) * 50_000.0
        - max(0.0, min_excess - excess) * 1.5
    )
    return float(score), {
        "buy_hold_net": hold,
        "excess_net": excess,
        "recent_30d_net": recent_net,
        "max_winner_share": max_winner_share,
    }


def run_worker(worker_id: int, args_dict: dict, trials: int) -> dict:
    base_params = default_c5_params()
    feat = prepare_features(args_dict["data"], args_dict["daily_bars"], args_dict["h4_bars"], base_params)

    def evaluate_params(params: dict) -> tuple[float, dict, dict]:
        signal_bars = build_c5_signal_bars(feat, params)
        result = run_tv_compatible_signal_bars(signal_bars, params)
        score, extras = score_result(result, feat, args_dict["min_trades"], args_dict["min_excess"])
        compact = asdict(result)
        compact.pop("trades", None)
        return score, params, {**compact, **extras}

    def objective(trial) -> float:
        params = trial_params(trial)
        score, _, compact = evaluate_params(params)
        trial.set_user_attr("metrics", compact)
        return score

    if optuna is not None:
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        sampler = optuna.samplers.TPESampler(seed=args_dict["seed"] + worker_id, multivariate=True, group=True)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(objective, n_trials=trials, n_jobs=1, show_progress_bar=False)
        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        best = max(completed, key=lambda t: t.value)
        params = params_from_mapping(best.params)
        score, params, metrics = evaluate_params(params)
    else:
        best_item = None
        for idx in range(trials):
            trial = RandomTrial(args_dict["seed"] + worker_id * 1_000_003 + idx)
            params = trial_params(trial)
            item = evaluate_params(params)
            if best_item is None or item[0] > best_item[0]:
                best_item = item
        score, params, metrics = best_item

    return {
        "worker_id": worker_id,
        "score": score,
        "params": params,
        "metrics": metrics,
        "trials": trials,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--daily-bars", required=True)
    parser.add_argument("--h4-bars", required=True)
    parser.add_argument("--trials", type=int, default=1024)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--chunk-trials", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2026061701)
    parser.add_argument("--min-trades", type=int, default=435)
    parser.add_argument("--min-excess", type=float, default=0.0)
    parser.add_argument("--out", default="reports/c5_successor_tv_parity_search.json")
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
        iterator = [run_worker(idx, args_dict, count) for idx, count in enumerate(trial_counts)]
        for item in iterator:
            results.append(item)
            metrics = item["metrics"]
            print(
                json.dumps(
                    {
                        "worker": item["worker_id"],
                        "score": item["score"],
                        "net": metrics["net_profit"],
                        "buy_hold": metrics["buy_hold_net"],
                        "excess": metrics["excess_net"],
                        "recent_30d": metrics["recent_30d_net"],
                        "pf": metrics["profit_factor"],
                        "dd_pct": metrics["max_drawdown"],
                        "trades": metrics["n_trades"],
                    }
                ),
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_worker, idx, args_dict, count) for idx, count in enumerate(trial_counts)]
            for future in as_completed(futures):
                item = future.result()
                results.append(item)
                metrics = item["metrics"]
                print(
                    json.dumps(
                        {
                            "worker": item["worker_id"],
                            "score": item["score"],
                            "net": metrics["net_profit"],
                            "buy_hold": metrics["buy_hold_net"],
                            "excess": metrics["excess_net"],
                            "recent_30d": metrics["recent_30d_net"],
                            "pf": metrics["profit_factor"],
                            "dd_pct": metrics["max_drawdown"],
                            "trades": metrics["n_trades"],
                        }
                    ),
                    flush=True,
                )

    if not results:
        raise SystemExit("no completed optimizer results")
    payload = {
        "source_data": args.data,
        "daily_bars": args.daily_bars,
        "h4_bars": args.h4_bars,
        "requested_trials": args.trials,
        "completed_trials": sum(r["trials"] for r in results),
        "workers": workers,
        "sampler": "optuna_tpe" if optuna is not None else "deterministic_random",
        "objective": {
            "mode": "tv_parity_excess_return",
            "min_trades": args.min_trades,
            "min_excess": args.min_excess,
            "notes": [
                "Uses TradingView-exported 1D and 240m bars for request.security parity.",
                "Scores excess over buy-and-hold, recent 30-day PnL, PF, and drawdown.",
                "Tests opt-in successor controls: short gating and long-carry sleeve.",
            ],
        },
        "best": max(results, key=lambda r: r["score"]),
        "top10": sorted(results, key=lambda r: r["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
