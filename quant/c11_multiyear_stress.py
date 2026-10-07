"""Stress the pre-2025-selected C11 X-veto candidate on five-year data."""
from __future__ import annotations

import os

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.c11_multiyear_x_research import (
    INITIAL_CAPITAL, apply_variant, load_params, trade_metrics,
)
from quant.es_c11_robust import load_all_15m
from quant.portfolio_simulation import SimulationSpec, simulate

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tv_c5_parity_engine import (  # noqa: E402
    build_c5_signal_bars, build_features, run_tv_compatible_signal_bars,
)


RESEARCH = Path("reports/c11_multiyear_x_research_20260714.json")
OUTPUT = Path("reports/c11_multiyear_x_stress_20260714.json")


def adjusted_metrics(pnl: np.ndarray) -> dict:
    equity = INITIAL_CAPITAL + np.cumsum(pnl)
    path = np.r_[INITIAL_CAPITAL, equity]
    dd = path / np.maximum.accumulate(path) - 1.0
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {"net": float(pnl.sum()), "trades": len(pnl),
            "profit_factor": float(wins / losses) if losses else float("inf"),
            "max_drawdown": float(dd.min()), "ending_equity": float(path[-1])}


def main() -> None:
    selected = json.loads(RESEARCH.read_text())["best_pre_2025"]["spec"]
    raw = load_all_15m().set_index("ts")
    feat = build_features(raw)
    params = load_params()
    base = build_c5_signal_bars(feat, params)
    result = run_tv_compatible_signal_bars(apply_variant(base, feat, selected), params)
    pnl = np.array([t.pnl for t in result.trades], dtype=float)
    exit_time = pd.DatetimeIndex([feat.index[t.exit_bar] for t in result.trades])

    execution = {}
    for extra_ticks in (0, 1, 2, 4, 8):
        execution[f"extra_ticks_{extra_ticks}"] = adjusted_metrics(pnl - 25.0 * extra_ticks)
    execution["double_commission"] = adjusted_metrics(pnl - 5.0)

    rolling = []
    starts = pd.date_range("2021-07-01", "2026-01-01", freq="QS", tz="UTC")
    for start in starts:
        end = start + pd.DateOffset(months=6)
        values = pnl[(exit_time >= start) & (exit_time < end)]
        if len(values):
            rolling.append({"start": str(start.date()), "net": float(values.sum()),
                            "trades": len(values), "positive": bool(values.sum() > 0)})

    daily = pd.DataFrame({"date": exit_time.tz_convert("America/Chicago").date,
                          "pnl": pnl, "trades": 1}).groupby("date").sum()
    all_days = pd.date_range(pd.Timestamp(raw.index[0].date()),
                             pd.Timestamp(raw.index[-1].date()), freq="D")
    daily = daily.reindex(all_days.date, fill_value=0.0)
    market = raw.assign(date=raw.index.tz_convert("America/Chicago").date).groupby("date")["close"].last()
    market = market.reindex(daily.index).ffill()
    ret = market.pct_change()
    vol = ret.rolling(20).std().shift(1)
    trend = (market / market.shift(63) - 1).shift(1)
    regimes = (2 * (trend < 0).astype(int) +
               (vol > vol.expanding(60).median()).astype(int)).fillna(0).to_numpy(int)
    returns = (daily[["pnl"]].to_numpy(float) / INITIAL_CAPITAL)
    trades = daily[["trades"]].to_numpy(float)
    scenarios = {
        "baseline": SimulationSpec(n_paths=1_000_000, horizon_days=756,
            mean_block_days=20, slippage_cost_per_trade_return=25.0 / INITIAL_CAPITAL),
        "execution_stress": SimulationSpec(n_paths=1_000_000, horizon_days=756,
            mean_block_days=20, extra_slippage_ticks=2.0,
            missed_trade_probability=0.10,
            gap_shock_probability=0.005, gap_shock_multiplier=2.0,
            slippage_cost_per_trade_return=25.0 / INITIAL_CAPITAL),
    }
    monte_carlo = {}
    for name, spec in scenarios.items():
        print(f"{name}: {spec.n_paths:,} paths on 32 workers", flush=True)
        _, summary = simulate(returns, trades, regimes, np.array([1.0]), spec,
                              seed=20260714, workers=32)
        monte_carlo[name] = {"spec": asdict(spec), "summary": summary}

    family = json.loads(RESEARCH.read_text())["all_candidates"]
    mode_family = [row for row in family if row["spec"]["x_mode"] == selected["x_mode"]]
    family_robustness = {
        "candidates": len(mode_family),
        "full_net_median": float(np.median([r["full"]["net"] for r in mode_family])),
        "holdout_net_median": float(np.median([r["holdout"]["net"] for r in mode_family])),
        "holdout_positive_fraction": float(np.mean([r["holdout"]["net"] > 0 for r in mode_family])),
        "holdout_pf_median": float(np.median([r["holdout"]["profit_factor"] for r in mode_family])),
    }
    payload = {
        "selected_spec": selected,
        "reconstruction": trade_metrics(result, feat.index),
        "execution": execution,
        "rolling_six_month": {"windows": rolling, "positive_fraction": float(np.mean([r["positive"] for r in rolling])),
                              "worst_net": min(r["net"] for r in rolling)},
        "parameter_family": family_robustness,
        "monte_carlo": monte_carlo,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
