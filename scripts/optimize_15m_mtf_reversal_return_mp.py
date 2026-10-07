#!/usr/bin/env python3
import argparse
import json
import os
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import optuna

from optimize_15m_mtf_reversal import backtest, build_features, load_json, suggest

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


def objective_factory(feat, min_trades):
    n = len(feat)
    splits = [
        (300, int(n * 0.25)),
        (int(n * 0.25), int(n * 0.50)),
        (int(n * 0.50), int(n * 0.75)),
        (int(n * 0.75), n),
    ]

    def objective(trial):
        params = suggest(trial)
        if params["h4_fast"] >= params["h4_slow"] or params["d_fast"] >= params["d_slow"]:
            raise optuna.TrialPruned()
        full = backtest(feat, params, 300, n)
        if full.n_trades < min_trades or full.total_return <= 12.0 or full.profit_factor < 1.10:
            raise optuna.TrialPruned()
        folds = [backtest(feat, params, start, end) for start, end in splits]
        min_return = min(result.total_return for result in folds)
        min_pf = min(result.profit_factor for result in folds)
        max_drawdown = max(result.max_drawdown for result in folds)
        consistency = sum(min(12.0, result.total_return) for result in folds)
        weak_fold_penalty = abs(min_return) * 4.0 if min_return < 0 else 0.0
        score = full.total_return * 2.2 + consistency * 1.1 + min(min_pf, 2.5) * 12.0 - max_drawdown * 2.0 - weak_fold_penalty
        trial.set_user_attr("full", full.__dict__)
        trial.set_user_attr("folds", [result.__dict__ for result in folds])
        return score

    return objective


def run_worker(worker_id, data_path, trials, min_trades, seed):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = build_features(load_json(data_path))
    sampler = optuna.samplers.TPESampler(
        seed=seed + worker_id,
        multivariate=True,
        group=True,
        n_startup_trials=min(150, max(30, trials // 4)),
    )
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective_factory(feat, min_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    completed = [trial for trial in study.trials if trial.value is not None]
    if not completed:
        return None
    best = study.best_trial
    params = dict(best.params)
    params["cost_bps"] = 4.0
    n = len(feat)
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {
            "full": backtest(feat, params, 300, n).__dict__,
            "q1": backtest(feat, params, 300, int(n * 0.25)).__dict__,
            "q2": backtest(feat, params, int(n * 0.25), int(n * 0.50)).__dict__,
            "q3": backtest(feat, params, int(n * 0.50), int(n * 0.75)).__dict__,
            "q4": backtest(feat, params, int(n * 0.75), n).__dict__,
        },
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/bitstamp_btcusd_15m_tvtester_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2026050702)
    parser.add_argument("--out", default="reports/mtf_15m_reversal_tvtester_return_64k.json")
    args = parser.parse_args()

    workers = max(1, min(args.workers, args.trials))
    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        trial_counts.append(count)
        remaining -= count

    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_worker, task_id, args.data, trial_counts[task_id], args.min_trades, args.seed)
            for task_id in range(len(trial_counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            results.append(result)
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "full_return": result["metrics"]["full"]["total_return"],
                "full_pf": result["metrics"]["full"]["profit_factor"],
                "full_trades": result["metrics"]["full"]["n_trades"],
                "max_dd": result["metrics"]["full"]["max_drawdown"],
                "q2_return": result["metrics"]["q2"]["total_return"],
                "q4_return": result["metrics"]["q4"]["total_return"],
            }), flush=True)

    if not results:
        raise SystemExit("No completed optimization trials met the search gate.")

    payload = {
        "source_data": args.data,
        "workers": workers,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
