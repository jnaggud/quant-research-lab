"""Five-year C11 transport and X-derived reversal-filter research.

The production Pine is never read for mutation. C11 parameters come from the
frozen promotion report; only its date gate is disabled for transport testing.
New variants are selected on data before 2025 and evaluated on 2025+ once.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import multiprocessing as mp
import os
from pathlib import Path

import numpy as np
import pandas as pd

from quant.es_c11_robust import load_all_15m

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tv_c5_parity_engine import (  # noqa: E402
    INITIAL_CAPITAL, SignalBar, build_c5_signal_bars, build_features,
    run_tv_compatible_signal_bars,
)


SOURCE = Path("reports/c11_trend_carry_sleeve_200k_20260621.json")
OUTPUT = Path("reports/c11_multiyear_x_research_20260714.json")
_FEATURES: pd.DataFrame | None = None
_BASE_PARAMS: dict | None = None


def load_params() -> dict:
    params = dict(json.loads(SOURCE.read_text())["best"]["params"])
    params.update(use_date_range=False, trend_carry_exit_regime="none",
                  trend_carry_exit_on_macd_roll=False)
    return params


def x_context(feat: pd.DataFrame, spec: dict) -> tuple[np.ndarray, np.ndarray]:
    close, high, low = (feat[c].astype(float) for c in ("close", "high", "low"))
    volume, atr = feat["volume"].astype(float), feat["atr"].astype(float)
    window = spec["context_bars"]
    ma = close.rolling(30, min_periods=30).mean()
    side = np.sign(close - ma)
    crosses = pd.Series(side, index=feat.index).ne(pd.Series(side, index=feat.index).shift()).shift(1).rolling(window).sum()
    slope = (ma.shift(1) - ma.shift(1 + spec["slope_bars"])).abs() / atr.shift(1).replace(0, np.nan)
    path = close.diff().abs().shift(1).rolling(window).sum()
    efficiency = (close.shift(1) - close.shift(1 + window)).abs() / path.replace(0, np.nan)
    chop = ((crosses >= spec["min_crosses"]) &
            (slope <= spec["slope_atr_max"]) &
            (efficiency <= spec["efficiency_max"]))

    lookback = spec["level_lookback"]
    support = low.shift(1).rolling(lookback).min()
    approach = close.shift(spec["spike_bars"])
    spike = (approach - low) / atr.replace(0, np.nan)
    pre_volume = volume.shift(spec["spike_bars"])
    volume_ratio = pre_volume.rolling(24).mean() / pre_volume.rolling(96).mean()
    failed_break_long = ((low < support) & (close > support) &
                         (spike >= spec["spike_atr"]) &
                         (volume_ratio <= spec["volume_ratio_max"]) & chop)
    return chop.fillna(False).to_numpy(bool), failed_break_long.fillna(False).to_numpy(bool)


def apply_variant(base: list[SignalBar], feat: pd.DataFrame, spec: dict) -> list[SignalBar]:
    chop, reversal = x_context(feat, spec)
    mode = spec["x_mode"]
    out = []
    for i, bar in enumerate(base):
        veto_trend = mode in ("trend_veto", "hybrid") and chop[i]
        veto_all = mode == "all_momentum_veto" and chop[i]
        add_reversal = mode in ("mr_overlay", "hybrid") and reversal[i]
        out.append(replace(
            bar,
            core_long=bar.core_long and not veto_all,
            core_short=bar.core_short and not veto_all,
            participation_long=bar.participation_long and not (veto_trend or veto_all),
            trend_carry_long=bar.trend_carry_long and not (veto_trend or veto_all),
            cap_long=bar.cap_long or add_reversal,
        ))
    return out


def trade_metrics(result, index: pd.DatetimeIndex, start: str | None = None,
                  end: str | None = None) -> dict:
    trades = []
    for trade in result.trades:
        when = index[trade.exit_bar]
        if start is not None and when < pd.Timestamp(start, tz="UTC"):
            continue
        if end is not None and when >= pd.Timestamp(end, tz="UTC"):
            continue
        trades.append(trade)
    pnl = np.array([t.pnl for t in trades], dtype=float)
    wins = pnl[pnl > 0].sum() if len(pnl) else 0.0
    losses = -pnl[pnl < 0].sum() if len(pnl) else 0.0
    equity = INITIAL_CAPITAL + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[INITIAL_CAPITAL, equity])
    dd = (np.r_[INITIAL_CAPITAL, equity] / peak - 1.0).min()
    return {
        "net": float(pnl.sum()), "trades": int(len(pnl)),
        "win_rate": float(np.mean(pnl > 0)) if len(pnl) else 0.0,
        "profit_factor": float(wins / losses) if losses else (float("inf") if wins else 0.0),
        "max_drawdown": float(dd),
    }


def candidate_specs() -> list[dict]:
    specs = []
    candidate = 0
    for mode in ("none", "trend_veto", "all_momentum_veto", "mr_overlay", "hybrid"):
        for context in (16, 32, 64):
            for crosses in (4, 6, 8):
                for slope in (0.5, 1.0):
                    for efficiency in (0.2, 0.3):
                        for spike in (1.0, 1.5, 2.0):
                            candidate += 1
                            specs.append({
                                "id": candidate, "x_mode": mode,
                                "context_bars": context, "min_crosses": crosses,
                                "slope_bars": 16, "slope_atr_max": slope,
                                "efficiency_max": efficiency,
                                "level_lookback": 96, "spike_bars": 2,
                                "spike_atr": spike, "volume_ratio_max": 1.1,
                            })
                            if mode == "none":
                                return specs + _non_control_specs(candidate)
    return specs


def _non_control_specs(candidate: int) -> list[dict]:
    specs = []
    for mode in ("trend_veto", "all_momentum_veto", "mr_overlay", "hybrid"):
        for context in (16, 32, 64):
            for crosses in (4, 6, 8):
                for slope in (0.5, 1.0):
                    for efficiency in (0.2, 0.3):
                        for spike in (1.0, 1.5, 2.0):
                            candidate += 1
                            specs.append({
                                "id": candidate, "x_mode": mode,
                                "context_bars": context, "min_crosses": crosses,
                                "slope_bars": 16, "slope_atr_max": slope,
                                "efficiency_max": efficiency,
                                "level_lookback": 96, "spike_bars": 2,
                                "spike_atr": spike, "volume_ratio_max": 1.1,
                            })
    return specs


def _evaluate(spec: dict) -> dict:
    assert _FEATURES is not None and _BASE_PARAMS is not None
    params = dict(_BASE_PARAMS)
    base = build_c5_signal_bars(_FEATURES, params)
    bars = apply_variant(base, _FEATURES, spec)
    result = run_tv_compatible_signal_bars(bars, params)
    index = _FEATURES.index
    years = {str(year): trade_metrics(result, index, f"{year}-01-01", f"{year + 1}-01-01")
             for year in range(2021, 2027)}
    train = trade_metrics(result, index, "2021-01-01", "2023-01-01")
    validation = trade_metrics(result, index, "2023-01-01", "2025-01-01")
    holdout = trade_metrics(result, index, "2025-01-01", None)
    full = trade_metrics(result, index)
    yearly_pre = [years[str(y)]["net"] for y in (2021, 2022, 2023, 2024)]
    score = (min(yearly_pre) * 2.0 + np.mean(yearly_pre) +
             10_000.0 * min(train["profit_factor"], validation["profit_factor"]) -
             20_000.0 * abs(min(train["max_drawdown"], validation["max_drawdown"])))
    return {"spec": spec, "score_pre_2025": float(score), "train": train,
            "validation": validation, "holdout": holdout, "full": full,
            "years": years, "trades": [asdict(t) for t in result.trades]}


def ablations(feat: pd.DataFrame, params: dict) -> dict:
    variants = {
        "full_c11": {}, "no_shorts": {"allow_short": False},
        "no_cap": {"use_cap": False}, "no_participation": {"use_participation": False},
        "no_trend_carry": {"use_trend_carry": False},
        "core_only": {"use_cap": False, "use_participation": False,
                      "use_trend_carry": False, "use_carry_long": False},
    }
    out = {}
    for name, changes in variants.items():
        p = {**params, **changes}
        result = run_tv_compatible_signal_bars(build_c5_signal_bars(feat, p), p)
        out[name] = {"full": trade_metrics(result, feat.index),
                     "pre_2025": trade_metrics(result, feat.index, "2021-01-01", "2025-01-01"),
                     "holdout": trade_metrics(result, feat.index, "2025-01-01", None)}
    return out


def walk_forward(rows: list[dict], index: pd.DatetimeIndex) -> dict:
    top = sorted(rows, key=lambda r: r["score_pre_2025"], reverse=True)[:20]
    quarters = pd.date_range("2023-01-01", "2026-07-01", freq="QS", tz="UTC")
    pnl = []
    selections = []
    for start in quarters[:-1]:
        end = start + pd.DateOffset(months=3)
        train_start = start - pd.DateOffset(months=18)
        scored = []
        for row in top:
            trades = row["trades"]
            values = [t["pnl"] for t in trades
                      if train_start <= index[t["exit_bar"]] < start]
            if len(values) >= 20:
                gross_win = sum(v for v in values if v > 0)
                gross_loss = -sum(v for v in values if v < 0)
                pf = gross_win / gross_loss if gross_loss else 10.0
                scored.append((sum(values) + 5_000 * min(pf, 3.0), row))
        if not scored:
            continue
        selected = max(scored, key=lambda x: x[0])[1]
        values = [t["pnl"] for t in selected["trades"]
                  if start <= index[t["exit_bar"]] < end]
        pnl.extend(values)
        selections.append({"quarter": str(start.date()), "candidate": selected["spec"]["id"],
                           "x_mode": selected["spec"]["x_mode"], "net": float(sum(values)),
                           "trades": len(values)})
    a = np.array(pnl, dtype=float)
    equity = INITIAL_CAPITAL + np.cumsum(a)
    dd = (np.r_[INITIAL_CAPITAL, equity] /
          np.maximum.accumulate(np.r_[INITIAL_CAPITAL, equity]) - 1).min()
    return {"net": float(a.sum()), "trades": len(a), "max_drawdown": float(dd),
            "selections": selections}


def main() -> None:
    global _FEATURES, _BASE_PARAMS
    bars = load_all_15m().set_index("ts")
    _FEATURES = build_features(bars)
    _BASE_PARAMS = load_params()
    specs = candidate_specs()
    workers = min(32, os.cpu_count() or 1)
    print(f"bars={len(bars):,} candidates={len(specs):,} workers={workers}", flush=True)
    context = mp.get_context("fork") if "fork" in mp.get_all_start_methods() else mp.get_context()
    with context.Pool(workers) as pool:
        rows = list(pool.imap_unordered(_evaluate, specs, chunksize=1))
    ranked = sorted(rows, key=lambda r: r["score_pre_2025"], reverse=True)
    # Strip bulky trade lists from the persisted candidate table after adaptive analysis.
    adaptive = walk_forward(rows, _FEATURES.index)
    compact = [{k: v for k, v in row.items() if k != "trades"} for row in ranked]
    payload = {
        "data": {"bars": len(bars), "start": str(bars.index[0]), "end": str(bars.index[-1])},
        "method": {"selection": "2021-2024 only", "final_evaluation": "2025 onward",
                   "workers": workers, "candidates": len(specs)},
        "ablations": ablations(_FEATURES, _BASE_PARAMS),
        "best_pre_2025": compact[0], "top20": compact[:20],
        "all_candidates": compact, "quarterly_trailing_18m_selection": adaptive,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2, default=str))
    print(json.dumps({"output": str(OUTPUT), "best": compact[0],
                      "adaptive": adaptive}, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
