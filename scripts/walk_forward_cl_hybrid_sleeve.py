#!/usr/bin/env python3
import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

import numpy as np
import optuna

from optimize_15m_mtf_reversal import load_json
from optimize_cl_15m_active_router_mp import INITIAL_CAPITAL, build_features, buy_hold_pnl
from optimize_cl_15m_hybrid_sleeve_mp import add_research_features, backtest_hybrid


BASELINE_REPORT = Path("reports/cl_15m_hybrid_sleeve_32k.json")


def load_baseline_params(path=BASELINE_REPORT):
    payload = json.loads(path.read_text())
    params = dict(payload["best"]["params"])
    params["use_sleeve"] = True
    return params


def clamp(value, low, high):
    return max(low, min(high, value))


def around_float(trial, name, base, pct, low, high, min_width=0.01):
    width = max(abs(base) * pct, min_width)
    return trial.suggest_float(name, clamp(base - width, low, high), clamp(base + width, low, high))


def around_int(trial, name, base, radius, low, high):
    return trial.suggest_int(name, int(clamp(base - radius, low, high)), int(clamp(base + radius, low, high)))


def suggest_adaptive_params(trial, baseline):
    params = dict(baseline)
    params.update({
        "allow_sleeve_longs": True,
        "allow_sleeve_shorts": True,
        "sleeve_adx_max": around_float(trial, "sleeve_adx_max", baseline["sleeve_adx_max"], 0.28, 12.0, 30.0),
        "sleeve_adx_slope_max": around_float(trial, "sleeve_adx_slope_max", baseline["sleeve_adx_slope_max"], 0.85, -5.0, 5.0, 0.5),
        "atr_rel_min": around_float(trial, "atr_rel_min", baseline["atr_rel_min"], 0.28, 0.45, 1.25),
        "atr_rel_max": around_float(trial, "atr_rel_max", baseline["atr_rel_max"], 0.34, 0.9, 2.35),
        "vol_rank_min": around_float(trial, "vol_rank_min", baseline["vol_rank_min"], 0.80, 0.0, 0.65, 0.05),
        "vol_rank_max": around_float(trial, "vol_rank_max", baseline["vol_rank_max"], 0.20, 0.35, 1.0, 0.05),
        "vwap_dist_atr": around_float(trial, "vwap_dist_atr", baseline["vwap_dist_atr"], 0.65, 0.02, 1.8),
        "prev_level_atr": around_float(trial, "prev_level_atr", baseline["prev_level_atr"], 0.45, 0.0, 3.0),
        "bb_atr": around_float(trial, "bb_atr", baseline["bb_atr"], 0.50, 0.0, 1.8),
        "sleeve_long_rsi": around_float(trial, "sleeve_long_rsi", baseline["sleeve_long_rsi"], 0.18, 25.0, 52.0),
        "sleeve_short_rsi": around_float(trial, "sleeve_short_rsi", baseline["sleeve_short_rsi"], 0.16, 48.0, 82.0),
        "sleeve_stoch": around_float(trial, "sleeve_stoch", baseline["sleeve_stoch"], 0.35, 6.0, 48.0),
        "sleeve_stop_atr": around_float(trial, "sleeve_stop_atr", baseline["sleeve_stop_atr"], 0.38, 0.6, 6.0),
        "sleeve_target_atr": around_float(trial, "sleeve_target_atr", baseline["sleeve_target_atr"], 0.55, 0.4, 5.5),
        "sleeve_trail_atr": around_float(trial, "sleeve_trail_atr", baseline["sleeve_trail_atr"], 0.35, 0.7, 7.5),
        "sleeve_exit_vwap_atr": around_float(trial, "sleeve_exit_vwap_atr", baseline["sleeve_exit_vwap_atr"], 1.2, -0.35, 1.0, 0.15),
        "sleeve_cooldown": around_int(trial, "sleeve_cooldown", baseline["sleeve_cooldown"], 6, 0, 18),
        "sleeve_min_hold": around_int(trial, "sleeve_min_hold", baseline["sleeve_min_hold"], 6, 0, 12),
        "sleeve_max_hold": around_int(trial, "sleeve_max_hold", baseline["sleeve_max_hold"], 18, 6, 72),
        "ny_start_hour": around_int(trial, "ny_start_hour", baseline["ny_start_hour"], 4, 0, 18),
        "ny_end_hour": around_int(trial, "ny_end_hour", baseline["ny_end_hour"], 4, 5, 23),
        "use_sleeve": True,
    })
    return params


def index_at_or_after(index, timestamp):
    return int(index.searchsorted(timestamp, side="left"))


def make_folds(index, train_days, test_days, step_days, warmup_bars):
    start = index[warmup_bars]
    end = index[-1]
    folds = []
    train_start = start
    while True:
        train_end = train_start + np.timedelta64(train_days, "D")
        test_end = train_end + np.timedelta64(test_days, "D")
        if test_end > end:
            break
        train_start_i = index_at_or_after(index, train_start)
        train_end_i = index_at_or_after(index, train_end)
        test_end_i = index_at_or_after(index, test_end)
        if train_end_i - train_start_i >= warmup_bars and test_end_i - train_end_i > 0:
            folds.append({
                "train_start_i": train_start_i,
                "train_end_i": train_end_i,
                "test_start_i": train_end_i,
                "test_end_i": test_end_i,
                "train_start": str(index[train_start_i]),
                "train_end": str(index[train_end_i - 1]),
                "test_start": str(index[train_end_i]),
                "test_end": str(index[test_end_i - 1]),
            })
        train_start = train_start + np.timedelta64(step_days, "D")
    return folds


def objective_factory(feat, baseline, train_start_i, train_end_i, min_train_trades):
    buy_hold = buy_hold_pnl(feat, train_start_i, train_end_i)

    def objective(trial):
        params = suggest_adaptive_params(trial, baseline)
        if params["atr_rel_min"] >= params["atr_rel_max"] or params["vol_rank_min"] >= params["vol_rank_max"]:
            raise optuna.TrialPruned()
        if params["sleeve_min_hold"] >= params["sleeve_max_hold"]:
            raise optuna.TrialPruned()
        result = backtest_hybrid(feat, params, train_start_i, train_end_i)
        if result.n_trades < min_train_trades or result.max_drawdown > 18.0:
            raise optuna.TrialPruned()
        score = (
            result.total_return * 1.15
            + (result.net_profit - buy_hold) / INITIAL_CAPITAL * 100.0 * 0.85
            + min(result.profit_factor, 3.0) * 18.0
            + min(result.win_rate, 65.0) * 0.25
            + min(result.sleeve_net / INITIAL_CAPITAL * 100.0, 25.0) * 0.8
            - result.max_drawdown * 2.6
            - max(0.0, result.top_month_share - 0.55) * 90.0
            - max(0.0, result.max_winner_share - 0.18) * 120.0
        )
        trial.set_user_attr("train", asdict(result))
        return score

    return objective


def optimize_fold_worker(worker_id, data_path, baseline, fold, trials, seed, min_train_trades):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    feat = add_research_features(build_features(load_json(data_path)))
    sampler = optuna.samplers.TPESampler(
        seed=seed + worker_id,
        multivariate=True,
        group=True,
        n_startup_trials=min(160, max(40, trials // 5)),
    )
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        pruner=optuna.pruners.MedianPruner(n_startup_trials=min(160, max(40, trials // 5))),
    )
    study.optimize(
        objective_factory(feat, baseline, fold["train_start_i"], fold["train_end_i"], min_train_trades),
        n_trials=trials,
        n_jobs=1,
        show_progress_bar=False,
    )
    complete = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not complete:
        return None
    best = study.best_trial
    params = dict(best.params)
    params["allow_sleeve_longs"] = True
    params["allow_sleeve_shorts"] = True
    params["use_sleeve"] = True
    train = backtest_hybrid(feat, params, fold["train_start_i"], fold["train_end_i"])
    test = backtest_hybrid(feat, params, fold["test_start_i"], fold["test_end_i"])
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "train": asdict(train),
        "test": asdict(test),
        "trials": len(study.trials),
        "complete_trials": len(complete),
    }


def optimize_fold(data_path, baseline, fold, fold_id, trials, workers, chunk_trials, seed, min_train_trades):
    counts = []
    remaining = trials
    while remaining > 0:
        count = min(chunk_trials, remaining)
        counts.append(count)
        remaining -= count
    max_workers = max(1, min(workers, len(counts)))
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                optimize_fold_worker,
                fold_id * 1000 + task_id,
                data_path,
                baseline,
                fold,
                counts[task_id],
                seed,
                min_train_trades,
            )
            for task_id in range(len(counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    if not results:
        return None
    return max(results, key=lambda item: item["score"])


def summarize(values):
    return {
        "net_profit": float(sum(item["net_profit"] for item in values)),
        "trades": int(sum(item["n_trades"] for item in values)),
        "long_trades": int(sum(item["long_trades"] for item in values)),
        "short_trades": int(sum(item["short_trades"] for item in values)),
        "avg_profit_factor": float(np.mean([item["profit_factor"] for item in values if item["profit_factor"] > 0] or [0.0])),
        "worst_drawdown_pct": float(max(item["max_drawdown"] for item in values)),
        "positive_folds": int(sum(1 for item in values if item["net_profit"] > 0)),
        "folds": len(values),
    }


def write_markdown(path, payload):
    lines = [
        "# CL 15m Walk-Forward Validation",
        "",
        f"- Data: `{payload['source_data']}`",
        f"- Train window: `{payload['train_days']}` days",
        f"- Test window: `{payload['test_days']}` days",
        f"- Step: `{payload['step_days']}` days",
        f"- Trials per fold: `{payload['trials_per_fold']}`",
        f"- Workers: `{payload['workers']}`",
        "",
        "## Summary",
        "",
        f"- Adaptive OOS net: `${payload['adaptive_summary']['net_profit']:,.2f}` across `{payload['adaptive_summary']['trades']}` trades; positive folds `{payload['adaptive_summary']['positive_folds']}/{payload['adaptive_summary']['folds']}`.",
        f"- Fixed baseline OOS net: `${payload['baseline_summary']['net_profit']:,.2f}` across `{payload['baseline_summary']['trades']}` trades; positive folds `{payload['baseline_summary']['positive_folds']}/{payload['baseline_summary']['folds']}`.",
        f"- Buy-and-hold OOS net over same fold windows: `${payload['buy_hold_oos']:,.2f}`.",
        "",
        "## Fold Results",
        "",
        "| Fold | Test Window | Adaptive Net | Baseline Net | Buy/Hold | Adaptive Trades | Baseline Trades |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for fold in payload["folds"]:
        lines.append(
            f"| {fold['fold']} | {fold['test_start']} → {fold['test_end']} | "
            f"${fold['adaptive']['net_profit']:,.2f} | ${fold['baseline']['net_profit']:,.2f} | "
            f"${fold['buy_hold']:,.2f} | {fold['adaptive']['n_trades']} | {fold['baseline']['n_trades']} |"
        )
    lines.extend([
        "",
        "## Decision Rule",
        "",
        "Promote adaptive retraining only if out-of-sample net improves versus the fixed baseline, positive folds do not deteriorate, max drawdown remains comparable, and improvement is not concentrated in one test fold.",
    ])
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--baseline-report", default=str(BASELINE_REPORT))
    parser.add_argument("--train-days", type=int, default=120)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=30)
    parser.add_argument("--trials-per-fold", type=int, default=4096)
    parser.add_argument("--chunk-trials", type=int, default=512)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--seed", type=int, default=2026051831)
    parser.add_argument("--min-train-trades", type=int, default=35)
    parser.add_argument("--out", default="reports/cl_15m_walk_forward_hybrid_sleeve.json")
    args = parser.parse_args()

    raw = load_json(args.data)
    feat = add_research_features(build_features(raw))
    baseline = load_baseline_params(Path(args.baseline_report))
    folds = make_folds(feat.index, args.train_days, args.test_days, args.step_days, 300)
    if not folds:
        raise SystemExit("No folds created. Reduce train/test windows or check data range.")

    fold_payloads = []
    for fold_id, fold in enumerate(folds, start=1):
        baseline_train = asdict(backtest_hybrid(feat, baseline, fold["train_start_i"], fold["train_end_i"]))
        baseline_test = asdict(backtest_hybrid(feat, baseline, fold["test_start_i"], fold["test_end_i"]))
        buy_hold = buy_hold_pnl(feat, fold["test_start_i"], fold["test_end_i"])
        best = optimize_fold(
            args.data,
            baseline,
            fold,
            fold_id,
            args.trials_per_fold,
            args.workers,
            args.chunk_trials,
            args.seed,
            args.min_train_trades,
        )
        if best is None:
            adaptive = baseline_test
            selected = {"fallback": "baseline_no_completed_trials", "params": baseline, "train": baseline_train, "test": baseline_test}
        else:
            adaptive = best["test"]
            selected = best
        row = {
            "fold": fold_id,
            **{k: fold[k] for k in ["train_start", "train_end", "test_start", "test_end"]},
            "baseline_train": baseline_train,
            "baseline": baseline_test,
            "adaptive": adaptive,
            "selected": selected,
            "buy_hold": buy_hold,
        }
        fold_payloads.append(row)
        print(json.dumps({
            "fold": fold_id,
            "test": [fold["test_start"], fold["test_end"]],
            "adaptive_net": adaptive["net_profit"],
            "baseline_net": baseline_test["net_profit"],
            "buy_hold": buy_hold,
            "adaptive_trades": adaptive["n_trades"],
            "baseline_trades": baseline_test["n_trades"],
        }), flush=True)

    payload = {
        "source_data": args.data,
        "baseline_report": args.baseline_report,
        "train_days": args.train_days,
        "test_days": args.test_days,
        "step_days": args.step_days,
        "trials_per_fold": args.trials_per_fold,
        "workers": args.workers,
        "chunk_trials": args.chunk_trials,
        "min_train_trades": args.min_train_trades,
        "adaptive_summary": summarize([fold["adaptive"] for fold in fold_payloads]),
        "baseline_summary": summarize([fold["baseline"] for fold in fold_payloads]),
        "buy_hold_oos": float(sum(fold["buy_hold"] for fold in fold_payloads)),
        "baseline_params": baseline,
        "folds": fold_payloads,
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2))
    write_markdown(out.with_suffix(".md"), payload)
    print(json.dumps(payload["adaptive_summary"], indent=2))
    print(json.dumps(payload["baseline_summary"], indent=2))
    print(out)
    print(out.with_suffix(".md"))


if __name__ == "__main__":
    main()
