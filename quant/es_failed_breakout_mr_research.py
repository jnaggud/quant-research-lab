"""Robust research harness for the standalone ES failed-breakout MR strategy.

The candidate grid contains round, interpretable settings. Candidates are ranked
only on temporal folds inside the first 60% of history. The final 40% is touched
once for the selected finalists. Parallel workers use all logical CPUs when the
platform supports fork, sharing the read-only one-minute bars copy-on-write.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import multiprocessing as mp
import os
from pathlib import Path

import numpy as np
import pandas as pd

from quant.strategy_failed_breakout_mr import (
    MRParams, build_features, load_all_1m, run_backtest,
)


REPORT = Path("reports/es_failed_breakout_mr_research_20260714.json")
_BARS: pd.DataFrame | None = None


def _fold_metrics(frame: pd.DataFrame, params: MRParams, end: int, direction: str) -> dict:
    folds = np.array_split(np.arange(end), 4)
    rows = []
    for idx in folds:
        if len(idx) < 1000:
            continue
        m = run_backtest(frame.iloc[idx[0]:idx[-1] + 1], params,
                         direction=direction)["metrics"]
        rows.append(m)
    returns = np.array([r["total_return"] for r in rows], dtype=float)
    trades = sum(r["n_trades"] for r in rows)
    score = 0.3 * returns.min() + 0.7 * returns.mean() if len(returns) else -1e9
    if trades < 30:
        score = -1e9
    return {
        "cv_score": float(score),
        "cv_mean": float(returns.mean()) if len(returns) else 0.0,
        "cv_min": float(returns.min()) if len(returns) else 0.0,
        "cv_positive": float((returns > 0).mean()) if len(returns) else 0.0,
        "cv_trades": int(trades),
    }


def _screen_one(spec: dict) -> dict:
    assert _BARS is not None
    base = MRParams(**spec)
    frame = build_features(_BARS, base)
    train_end = int(len(frame) * 0.6)
    best = None
    for rr in (0.5, 1.0, 1.5):
        for direction in ("both", "long", "short"):
            p = replace(base, reward_risk=rr)
            result = {
                **_fold_metrics(frame, p, train_end, direction),
                "params": asdict(p), "direction": direction,
            }
            if best is None or result["cv_score"] > best["cv_score"]:
                best = result
    return best


def candidate_specs() -> list[dict]:
    specs = []
    profiles = [
        # Full article checklist.
        dict(volume_ratio_max=1.05, climax_volume_min=1.5,
             min_crosses=6, ma_slope_atr_max=0.75, efficiency_max=0.25),
        # Permit flat-to-mildly-rising pre-spike volume.
        dict(volume_ratio_max=1.15, climax_volume_min=1.25,
             min_crosses=6, ma_slope_atr_max=1.0, efficiency_max=0.30),
        # Price-action-only control: fast failed break without context filters.
        dict(volume_ratio_max=10.0, climax_volume_min=0.0,
             min_crosses=0, ma_slope_atr_max=999.0, efficiency_max=1.0),
    ]
    for level_type in ("rolling", "prior_rth", "overnight", "session_union"):
        for trigger_delay in (0, 1):
            for spike_atr in (1.0, 1.5, 2.0):
                for profile in profiles:
                    specs.append(asdict(replace(
                        MRParams(), level_type=level_type,
                        trigger_delay=trigger_delay, spike_atr=spike_atr,
                        **profile,
                    )))
    return specs


def _select_diverse(screened: list[dict], n: int = 6) -> list[dict]:
    """Take top candidates while avoiding six tiny variations of one setup."""
    selected = []
    seen = set()
    for row in sorted(screened, key=lambda x: x["cv_score"], reverse=True):
        if row["cv_trades"] < 30:
            continue
        p = row["params"]
        key = (p["level_type"], p["trigger_delay"],
               p["volume_ratio_max"] >= 9, row["direction"])
        if key in seen:
            continue
        selected.append(row)
        seen.add(key)
        if len(selected) >= n:
            break
    return selected


def _holdout(row: dict, bars: pd.DataFrame) -> dict:
    p = MRParams(**row["params"])
    frame = build_features(bars, p)
    cut = int(len(frame) * 0.6)
    hold = frame.iloc[cut:].reset_index(drop=True)
    result = run_backtest(hold, p, direction=row["direction"])
    m = result["metrics"]
    # Half-year blocks expose temporal dependence without selecting parameters.
    dt = pd.DatetimeIndex(hold["ts"]).tz_localize(None)
    blocks = []
    for _, block in hold.groupby(dt.to_period("2Q")):
        bm = run_backtest(block.reset_index(drop=True), p,
                          direction=row["direction"])["metrics"]
        blocks.append(float(bm["total_return"]))
    return {
        **row,
        "holdout": m,
        "holdout_blocks": blocks,
        "holdout_block_positive": float(np.mean(np.array(blocks) > 0)) if blocks else 0.0,
    }


def main() -> None:
    global _BARS
    _BARS = load_all_1m()
    specs = candidate_specs()
    workers = min(32, os.cpu_count() or 1, len(specs))
    print(f"bars {len(_BARS):,} | candidates {len(specs)} | workers {workers}", flush=True)

    # Fork keeps the 1.8M-row source frame shared. Fall back to spawn on platforms
    # without fork, where a smaller worker count avoids duplicating the dataset.
    methods = mp.get_all_start_methods()
    if "fork" in methods:
        context = mp.get_context("fork")
    else:
        context = mp.get_context("spawn")
        workers = min(workers, 4)
    with context.Pool(workers) as pool:
        screened = list(pool.imap_unordered(_screen_one, specs, chunksize=1))

    finalists = _select_diverse(screened)
    tested = [_holdout(row, _BARS) for row in finalists]
    payload = {
        "bars": len(_BARS),
        "start": str(_BARS["ts"].iloc[0]),
        "end": str(_BARS["ts"].iloc[-1]),
        "train_fraction": 0.6,
        "candidates": len(specs),
        "workers": workers,
        "top_train": sorted(screened, key=lambda x: x["cv_score"], reverse=True)[:10],
        "finalists": tested,
    }
    REPORT.write_text(json.dumps(payload, indent=2, default=str))

    print(f"\n{'level':14} {'dir':>5} {'delay':>5} {'spike':>5} {'rr':>4} "
          f"{'CV%':>7} {'HO%':>7} {'trades':>7} {'PF':>6} {'blocks+':>7}")
    for row in tested:
        p, h = row["params"], row["holdout"]
        print(f"{p['level_type']:14} {row['direction']:>5} {p['trigger_delay']:5d} {p['spike_atr']:5.1f} "
              f"{p['reward_risk']:4.1f} {row['cv_mean']*100:+7.2f} "
              f"{h['total_return']*100:+7.2f} {h['n_trades']:7d} "
              f"{h['profit_factor']:6.2f} {row['holdout_block_positive']*100:6.0f}%")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
