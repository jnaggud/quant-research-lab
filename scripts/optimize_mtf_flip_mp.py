#!/usr/bin/env python3
import argparse
import json
import os
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import optuna

from optimize_mtf_flip import backtest, load_json, make_signal, objective_factory

warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)


def run_worker(worker_id, data_path, trials, min_trades, seed):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    df = load_json(data_path)
    sampler = optuna.samplers.TPESampler(
        seed=seed + worker_id,
        multivariate=True,
        group=True,
        n_startup_trials=min(100, max(20, trials // 5)),
    )
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        pruner=optuna.pruners.MedianPruner(n_startup_trials=min(100, max(20, trials // 5))),
    )
    study.optimize(objective_factory(df, min_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    best = study.best_trial
    params = dict(best.params)
    params["cost_bps"] = 4.0
    signal = make_signal(df, params)
    n = len(df)
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {
            "full": backtest(df, signal, 300, n, 4.0).__dict__,
            "q1": backtest(df, signal, 300, int(n * 0.25), 4.0).__dict__,
            "q2": backtest(df, signal, int(n * 0.25), int(n * 0.50), 4.0).__dict__,
            "q3": backtest(df, signal, int(n * 0.50), int(n * 0.75), 4.0).__dict__,
            "q4": backtest(df, signal, int(n * 0.75), n, 4.0).__dict__,
        },
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/bitstamp_btcusd_15m_20250930_20260507.json")
    parser.add_argument("--trials", type=int, default=6400)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--min-trades", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--out", default="reports/mtf_flip_mp_best.json")
    args = parser.parse_args()

    workers = max(1, min(args.workers, args.trials))
    chunk_trials = max(1, args.chunk_trials)
    trial_counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(chunk_trials, remaining)
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
            results.append(result)
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "full_return": result["metrics"]["full"]["total_return"],
                "full_pf": result["metrics"]["full"]["profit_factor"],
                "full_trades": result["metrics"]["full"]["n_trades"],
            }), flush=True)

    best = max(results, key=lambda item: item["score"])
    payload = {
        "source_data": args.data,
        "workers": workers,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "best": best,
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
