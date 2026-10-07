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


BASE_PARAMS = {
    "allow_sleeve_longs": True,
    "allow_sleeve_shorts": True,
    "sleeve_adx_max": 24.111181455078224,
    "sleeve_adx_slope_max": 2.369942613878797,
    "atr_rel_min": 0.8130426484809107,
    "atr_rel_max": 1.1838094620099848,
    "vol_rank_min": 0.20068031699404018,
    "vol_rank_max": 0.9213924280365459,
    "vwap_dist_atr": 0.5432991795348431,
    "prev_level_atr": 1.8717803994832265,
    "bb_atr": 1.0289185256346374,
    "sleeve_long_rsi": 42.52113131638666,
    "sleeve_short_rsi": 74.21737222162857,
    "sleeve_stoch": 33.05609732630522,
    "sleeve_stop_atr": 4.170279319035829,
    "sleeve_target_atr": 2.198406120324361,
    "sleeve_trail_atr": 5.840965368951672,
    "sleeve_exit_vwap_atr": 0.3045559114252387,
    "sleeve_cooldown": 5,
    "sleeve_min_hold": 8,
    "sleeve_max_hold": 39,
    "ny_start_hour": 0,
    "ny_end_hour": 18,
    "use_sleeve": True,
}


def add_kinematic_features(feat, length):
    out = add_research_features(feat)
    atr_safe = out["atr"].replace(0, np.nan)
    velocity = (out["close"] - out["close"].shift(length)) / atr_safe
    acceleration = velocity - velocity.shift(length)
    jerk = acceleration - acceleration.shift(length)
    signed_dollar_flow = (out["close"] - out["close"].shift(1)) * out["volume"]
    flow_base = signed_dollar_flow.abs().rolling(96, min_periods=10).mean().replace(0, np.nan)
    impulse = signed_dollar_flow / flow_base
    out["kin_velocity"] = velocity
    out["kin_acceleration"] = acceleration
    out["kin_jerk"] = jerk
    out["kin_impulse"] = impulse
    return out.ffill().fillna(0.0)


def kinematic_gate(feat, params):
    v = feat["kin_velocity"].to_numpy(float)
    a = feat["kin_acceleration"].to_numpy(float)
    j = feat["kin_jerk"].to_numpy(float)
    impulse = feat["kin_impulse"].to_numpy(float)
    if params["kin_mode"] == "velocity_only":
        long_gate = v <= -params["vel_min"]
        short_gate = v >= params["vel_min"]
    elif params["kin_mode"] == "turn":
        long_gate = (v <= -params["vel_min"]) & ((a >= params["accel_min"]) | (j >= params["jerk_min"]))
        short_gate = (v >= params["vel_min"]) & ((a <= -params["accel_min"]) | (j <= -params["jerk_min"]))
    elif params["kin_mode"] == "impulse":
        long_gate = (v <= -params["vel_min"]) & (impulse <= -params["impulse_min"]) & ((a >= params["accel_min"]) | (j >= params["jerk_min"]))
        short_gate = (v >= params["vel_min"]) & (impulse >= params["impulse_min"]) & ((a <= -params["accel_min"]) | (j <= -params["jerk_min"]))
    else:
        long_gate = (v <= -params["vel_min"]) & (a >= params["accel_min"]) & (j >= params["jerk_min"]) & (impulse <= -params["impulse_min"])
        short_gate = (v >= params["vel_min"]) & (a <= -params["accel_min"]) & (j <= -params["jerk_min"]) & (impulse >= params["impulse_min"])
    return long_gate, short_gate


def backtest_kinematic(feat, params, start=300, end=None):
    filtered = feat.copy()
    if params["use_kinematic"]:
        long_gate, short_gate = kinematic_gate(filtered, params)
        filtered["kin_long_gate"] = long_gate
        filtered["kin_short_gate"] = short_gate
    else:
        filtered["kin_long_gate"] = True
        filtered["kin_short_gate"] = True
    return backtest_hybrid(filtered, params, start, end)


def suggest_params(trial):
    params = dict(BASE_PARAMS)
    params.update({
        "allow_sleeve_longs": trial.suggest_categorical("allow_sleeve_longs", [True, True, False]),
        "allow_sleeve_shorts": trial.suggest_categorical("allow_sleeve_shorts", [True, True, False]),
        "sleeve_adx_max": trial.suggest_float("sleeve_adx_max", 18.0, 28.0),
        "sleeve_adx_slope_max": trial.suggest_float("sleeve_adx_slope_max", -2.5, 4.0),
        "atr_rel_min": trial.suggest_float("atr_rel_min", 0.55, 1.05),
        "atr_rel_max": trial.suggest_float("atr_rel_max", 1.05, 1.85),
        "vol_rank_min": trial.suggest_float("vol_rank_min", 0.0, 0.55),
        "vol_rank_max": trial.suggest_float("vol_rank_max", 0.45, 1.0),
        "vwap_dist_atr": trial.suggest_float("vwap_dist_atr", 0.05, 1.8),
        "prev_level_atr": trial.suggest_float("prev_level_atr", 0.0, 2.5),
        "bb_atr": trial.suggest_float("bb_atr", 0.0, 1.6),
        "sleeve_long_rsi": trial.suggest_float("sleeve_long_rsi", 30.0, 48.0),
        "sleeve_short_rsi": trial.suggest_float("sleeve_short_rsi", 52.0, 78.0),
        "sleeve_stoch": trial.suggest_float("sleeve_stoch", 12.0, 42.0),
        "sleeve_stop_atr": trial.suggest_float("sleeve_stop_atr", 0.7, 4.8),
        "sleeve_target_atr": trial.suggest_float("sleeve_target_atr", 0.5, 5.0),
        "sleeve_trail_atr": trial.suggest_float("sleeve_trail_atr", 0.8, 6.0),
        "sleeve_exit_vwap_atr": trial.suggest_float("sleeve_exit_vwap_atr", -0.2, 0.9),
        "sleeve_cooldown": trial.suggest_int("sleeve_cooldown", 0, 16),
        "sleeve_min_hold": trial.suggest_int("sleeve_min_hold", 0, 8),
        "sleeve_max_hold": trial.suggest_int("sleeve_max_hold", 4, 48),
        "ny_start_hour": trial.suggest_int("ny_start_hour", 0, 16),
        "ny_end_hour": trial.suggest_int("ny_end_hour", 7, 23),
        "use_kinematic": True,
        "kin_mode": trial.suggest_categorical("kin_mode", ["velocity_only", "turn", "impulse", "strict"]),
        "kin_length": trial.suggest_int("kin_length", 2, 12),
        "vel_min": trial.suggest_float("vel_min", 0.0, 2.5),
        "accel_min": trial.suggest_float("accel_min", -1.5, 1.8),
        "jerk_min": trial.suggest_float("jerk_min", -1.5, 2.0),
        "impulse_min": trial.suggest_float("impulse_min", 0.0, 3.0),
    })
    return params


def objective_factory(raw, min_net, min_trades):
    feature_cache = {}
    buy_hold = buy_hold_pnl(raw, 300, len(raw))

    def get_feat(length):
        if length not in feature_cache:
            feature_cache[length] = add_kinematic_features(build_features(raw), length)
        return feature_cache[length]

    def objective(trial):
        params = suggest_params(trial)
        if params["atr_rel_min"] >= params["atr_rel_max"] or params["vol_rank_min"] >= params["vol_rank_max"]:
            raise optuna.TrialPruned()
        if params["sleeve_min_hold"] >= params["sleeve_max_hold"]:
            raise optuna.TrialPruned()
        if not (params["allow_sleeve_longs"] or params["allow_sleeve_shorts"]):
            raise optuna.TrialPruned()
        feat = get_feat(params["kin_length"])
        full = backtest_kinematic(feat, params, 300, len(feat))
        if full.net_profit < min_net or full.n_trades < min_trades or full.sleeve_trades < 20:
            raise optuna.TrialPruned()
        if full.sleeve_net < 0 or full.max_drawdown > 12.0:
            raise optuna.TrialPruned()
        score = (
            full.total_return * 1.45
            + (full.net_profit - buy_hold) / INITIAL_CAPITAL * 100.0 * 1.25
            + min(full.profit_factor, 3.0) * 28.0
            + min(full.sleeve_net / INITIAL_CAPITAL * 100.0, 35.0) * 1.5
            + full.positive_months / max(1, full.active_months) * 50.0
            + min(full.pre_march_net / INITIAL_CAPITAL * 100.0, 40.0) * 1.0
            - full.max_drawdown * 2.0
            - max(0.0, full.top_month_share - 0.44) * 130.0
            - max(0.0, full.max_stagnation_days - 55.0) * 1.1
            - max(0.0, full.max_winner_share - 0.13) * 160.0
        )
        trial.set_user_attr("full", asdict(full))
        return score

    return objective


def run_worker(worker_id, data_path, trials, seed, min_net, min_trades):
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    raw = load_json(data_path)
    sampler = optuna.samplers.TPESampler(seed=seed + worker_id, multivariate=True, group=True, n_startup_trials=min(220, max(60, trials // 5)))
    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=optuna.pruners.MedianPruner(n_startup_trials=min(220, max(60, trials // 5))))
    study.optimize(objective_factory(raw, min_net, min_trades), n_trials=trials, n_jobs=1, show_progress_bar=False)
    if not any(trial.state == optuna.trial.TrialState.COMPLETE for trial in study.trials):
        return None
    best = study.best_trial
    params = dict(best.params)
    params["use_sleeve"] = True
    params["use_kinematic"] = True
    raw = load_json(data_path)
    feat = add_kinematic_features(build_features(raw), params["kin_length"])
    return {
        "worker_id": worker_id,
        "score": best.value,
        "params": params,
        "metrics": {"full": asdict(backtest_kinematic(feat, params, 300, len(feat)))},
        "trials": len(study.trials),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--trials", type=int, default=64000)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--chunk-trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2026051824)
    parser.add_argument("--min-net", type=float, default=90000.0)
    parser.add_argument("--min-trades", type=int, default=285)
    parser.add_argument("--out", default="reports/cl_15m_kinematic_sleeve_64k.json")
    args = parser.parse_args()

    counts = []
    remaining = args.trials
    while remaining > 0:
        count = min(args.chunk_trials, remaining)
        counts.append(count)
        remaining -= count
    workers = max(1, min(args.workers, len(counts)))
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_worker, task_id, args.data, counts[task_id], args.seed, args.min_net, args.min_trades)
            for task_id in range(len(counts))
        ]
        for future in as_completed(futures):
            result = future.result()
            if result is None:
                continue
            results.append(result)
            full = result["metrics"]["full"]
            print(json.dumps({
                "worker_id": result["worker_id"],
                "score": result["score"],
                "net": full["net_profit"],
                "pf": full["profit_factor"],
                "dd": full["max_drawdown"],
                "trades": full["n_trades"],
                "sleeve_trades": full["sleeve_trades"],
                "sleeve_net": full["sleeve_net"],
                "kin": result["params"].get("use_kinematic"),
                "kin_length": result["params"].get("kin_length"),
            }), flush=True)

    if not results:
        raise SystemExit("No completed trials met the kinematic constraints; loosen thresholds or run more trials.")
    raw = load_json(args.data)
    payload = {
        "source_data": args.data,
        "requested_trials": args.trials,
        "completed_trials": sum(item["trials"] for item in results),
        "workers": workers,
        "base_params": BASE_PARAMS,
        "assumptions": {"objective": "Hybrid C1 plus optional velocity, acceleration, jerk, and price-volume impulse sleeve gates."},
        "buy_hold": buy_hold_pnl(raw, 300, len(raw)),
        "best": max(results, key=lambda item: item["score"]),
        "top10": sorted(results, key=lambda item: item["score"], reverse=True)[:10],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
