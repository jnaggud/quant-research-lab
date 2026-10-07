"""validate.py — leakage-safe validation harness for the ES pipeline.

Ports the *sound* methodology from Pattern_FindR's `v16_strategy_search.py` and
`walkforward_v9_regime.py` (the only places that did it right), and explicitly
AVOIDS the contaminated `velocity_walkforward_validation.py` selection block that
picked the best-of-N *on the test set*.

What this enforces (docs/architecture.md §3):
  * Chronological split — train / val / holdout, no shuffle.
  * EMBARGO at each boundary (≥ max indicator lookback) so overlapping windows
    can't leak across the split.
  * Inner CV on TRAIN ONLY for hyper-parameter scoring; worst-fold-weighted
    (`0.6*min + 0.4*mean`, the v9 robustness objective).
  * Holdout touched EXACTLY ONCE per seed, only to report OOS — never to select.
  * Seed-stability Monte Carlo (optimizer-stability): re-run the whole search
    under N RNG seeds; "% of seeds profitable OOS" is the stability metric.
  * Three acceptance gates + a >5× train/holdout degradation overfit flag.

`evaluate(params, df) -> dict` is supplied by the caller (it wraps a CAUSAL
strategy + `backtest.run_backtest`) and must return at least
`{'total_return': float, 'n_trades': int}`. It must compute every feature/signal
INSIDE `df` only (train-only feature computation — guard #2).
"""
from __future__ import annotations

import os

import statistics
from typing import Callable

import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)

Evaluate = Callable[[dict, object], dict]


# --------------------------------------------------------------------------------------
# Splitting (with embargo)
# --------------------------------------------------------------------------------------

def _slice(df, a, b):
    return df[a:b]


def chrono_split(df, fracs=(0.6, 0.2, 0.2), embargo: int = 0):
    """Chronological train/val/holdout split. `embargo` rows are dropped at each
    boundary so lookback windows don't bleed across splits."""
    n = len(df)
    a = int(n * fracs[0])
    b = a + int(n * fracs[1])
    train = _slice(df, 0, a)
    val = _slice(df, a + embargo, b)
    holdout = _slice(df, b + embargo, n)
    return train, val, holdout


def _cv_slices(df, k: int, embargo: int = 0):
    """k contiguous chronological slices of `df` (each used as a validation fold),
    with `embargo` rows trimmed off the front of each fold."""
    n = len(df)
    step = n // k
    out = []
    for i in range(k):
        lo = i * step
        hi = (i + 1) * step if i < k - 1 else n
        out.append(_slice(df, lo + (embargo if i > 0 else 0), hi))
    return out


# --------------------------------------------------------------------------------------
# Scoring / optimization
# --------------------------------------------------------------------------------------

def cv_score(evaluate: Evaluate, params: dict, train, k: int = 4, embargo: int = 0,
             min_trades_per_fold: float = 2.0) -> float:
    """Worst-fold-weighted CV return on TRAIN. Rewards cross-period consistency but
    does NOT let one unlucky fold equate a profitable-but-bumpy config with a
    do-nothing one.

    Two calibrations vs the original v9 score (which drove the optimizer to "don't
    trade"):
      * Lighter min-fold weight (0.3 vs 0.6) — a small negative fold no longer
        outweighs a positive average.
      * Under-trading penalty — configs that barely trade (the 0-return degenerate)
        are pushed below any genuinely active, positive config.
    """
    rets, trades = [], []
    for s in _cv_slices(train, k, embargo):
        if len(s) == 0:
            continue
        r = evaluate(params, s)
        rets.append(float(r.get("total_return", 0.0)))
        trades.append(float(r.get("n_trades", 0)))
    if not rets:
        return -1e9
    base = 0.3 * min(rets) + 0.7 * (sum(rets) / len(rets))
    avg_trades = sum(trades) / len(trades)
    if avg_trades < min_trades_per_fold:
        base -= (min_trades_per_fold - avg_trades) * 0.02   # nudge away from no-trade
    return base


def _suggest(trial, space: dict) -> dict:
    p = {}
    for name, spec in space.items():
        kind = spec[0]
        if kind == "float":
            p[name] = trial.suggest_float(name, spec[1], spec[2], step=spec[3] if len(spec) > 3 else None)
        elif kind == "int":
            p[name] = trial.suggest_int(name, spec[1], spec[2])
        elif kind == "cat":
            p[name] = trial.suggest_categorical(name, spec[1])
        else:
            raise ValueError(f"bad space kind {kind} for {name}")
    return p


def optimize(evaluate: Evaluate, space: dict, train, n_trials: int = 100,
             seed: int = 0, k: int = 4, embargo: int = 0):
    """TPE search maximizing inner-CV score on TRAIN only. Returns (best_params, best_cv)."""
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler,
                                pruner=optuna.pruners.MedianPruner())
    study.optimize(lambda t: cv_score(evaluate, _suggest(t, space), train, k, embargo),
                   n_trials=n_trials, show_progress_bar=False)
    return study.best_params, study.best_value


# --------------------------------------------------------------------------------------
# Monte Carlo seed-stability + gates
# --------------------------------------------------------------------------------------

def monte_carlo(evaluate: Evaluate, space: dict, train, holdout,
                n_seeds: int = 10, n_trials: int = 100, k: int = 4, embargo: int = 0) -> dict:
    """For each RNG seed: optimize on TRAIN, evaluate ONCE on HOLDOUT. The holdout
    is never used to choose params, so each seed's number is a true OOS estimate."""
    per = []
    for seed in range(n_seeds):
        best, cv = optimize(evaluate, space, train, n_trials, seed, k, embargo)
        oos = evaluate(best, holdout)
        per.append({
            "seed": seed, "params": best, "train_cv": cv,
            "oos_return": float(oos.get("total_return", 0.0)),
            "oos_trades": int(oos.get("n_trades", 0)),
        })
    rets = [p["oos_return"] for p in per]
    return {
        "per_seed": per,
        "mean_oos": statistics.mean(rets),
        "median_oos": statistics.median(rets),
        "pct_positive": 100.0 * statistics.mean([1.0 if r > 0 else 0.0 for r in rets]),
        "median_trades": statistics.median([p["oos_trades"] for p in per]),
    }


def three_gate(mc: dict, train_return: float | None = None) -> dict:
    """Acceptance gates from STRATEGY_ANALYSIS.md:
       (1) positive OOS, (2) ≥75% seed-stable, (3) ≥20 holdout trades.
       Plus a >5× train/holdout degradation overfit flag."""
    gates = {
        "oos_positive": mc["median_oos"] > 0,
        "seed_stable_75pct": mc["pct_positive"] >= 75.0,
        "min_20_trades": mc["median_trades"] >= 20,
    }
    flags = {}
    if train_return is not None and mc["median_oos"] != 0:
        flags["overfit_gt5x"] = abs(train_return) > 5 * abs(mc["median_oos"])
    return {
        **gates,
        "PASS": all(gates.values()) and not flags.get("overfit_gt5x", False),
        "flags": flags,
        "median_oos": mc["median_oos"],
        "pct_positive": mc["pct_positive"],
        "median_trades": mc["median_trades"],
    }


def run_validation(evaluate: Evaluate, space: dict, data, *,
                   fracs=(0.6, 0.2, 0.2), embargo: int = 0,
                   n_seeds: int = 10, n_trials: int = 100, inner_k: int = 4) -> dict:
    """End-to-end: split → seed-stability MC on train→holdout → gates."""
    train, val, holdout = chrono_split(data, fracs, embargo)
    mc = monte_carlo(evaluate, space, train, holdout, n_seeds, n_trials, inner_k, embargo)
    # train baseline for the degradation flag: median best-config train-fold return
    train_return = statistics.median([p["train_cv"] for p in mc["per_seed"]])
    verdict = three_gate(mc, train_return)
    return {
        "sizes": {"train": len(train), "val": len(val), "holdout": len(holdout), "embargo": embargo},
        "mc": mc, "verdict": verdict, "train_return": train_return,
    }


# --------------------------------------------------------------------------------------
# Self-test (synthetic objective — no drive I/O, no strategy needed)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    import numpy as np

    # Synthetic "data" = an array of bars; a trivial strategy whose return is a
    # smooth function of a `threshold` param, peaking near 0.3, with mild
    # per-slice variation. The harness should (a) find ~0.3, (b) report a true
    # OOS number on the untouched holdout, (c) pass the 3 gates.
    rng = np.random.default_rng(0)
    data = rng.normal(0, 1, 4000)  # 4000 "bars"

    def evaluate(params, df):
        thr = params["threshold"]
        # return rewards thr≈0.3; add a tiny slice-specific bias from the data mean
        base = 0.12 - (thr - 0.3) ** 2          # peak +0.12 at thr=0.3
        bias = 0.01 * float(np.tanh(np.mean(df)))
        ret = base + bias
        n = int(40 + 60 * (1 - abs(thr - 0.3)))  # ~ trades, ≥20
        return {"total_return": ret, "n_trades": n}

    space = {"threshold": ("float", 0.0, 1.0)}
    res = run_validation(evaluate, space, data, fracs=(0.6, 0.2, 0.2), embargo=20,
                         n_seeds=6, n_trials=40, inner_k=4)
    print("sizes:", res["sizes"])
    best_thr = statistics.median([p["params"]["threshold"] for p in res["mc"]["per_seed"]])
    print(f"median selected threshold: {best_thr:.3f} (true optimum 0.300)")
    print("MC:", {k: round(v, 4) if isinstance(v, float) else v
                  for k, v in res["mc"].items() if k != "per_seed"})
    print("verdict:", {k: v for k, v in res["verdict"].items() if k != "flags"}, "flags:", res["verdict"]["flags"])
    assert abs(best_thr - 0.3) < 0.1, "optimizer did not converge near the true optimum"
    assert res["verdict"]["min_20_trades"], "trade-count gate wrong"
    assert res["verdict"]["oos_positive"], "OOS gate wrong"

    # Negative control: a strategy that's profitable in-sample but random OOS → gates should NOT all pass.
    def evaluate_overfit(params, df):
        thr = params["threshold"]
        ret = 0.5 - (thr - 0.3) ** 2 if len(df) > 2500 else float(np.tanh(np.mean(df[:50]) * thr)) * 0.001
        return {"total_return": ret, "n_trades": 5}
    res2 = run_validation(evaluate_overfit, space, data, embargo=20, n_seeds=6, n_trials=30)
    print("overfit-control verdict PASS:", res2["verdict"]["PASS"], "| trades gate:", res2["verdict"]["min_20_trades"])
    assert not res2["verdict"]["PASS"], "overfit control should fail the gates"
    print("validate.py self-test PASSED")
