#!/usr/bin/env python3
"""c12_gex_veto_parity.py — C12 candidate: C11 champion + GEX short-gate, on the
TV-parity engine and TradingView-exported bars.

The gate (from es_options_v2/veto-robustness research): core SHORTS are allowed
only when the prior session's net dealer GEX z-score is negative. Longs untouched.
Daily flag from quant/cache/es_options_weekly_daily.parquet, applied next session
(available at session date + 22:00 UTC).

Compares C11 (worker 143 champion params) vs C12 on identical TV bars through the
identical execution model, and prints the promotion-gate deltas.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from tv_c5_parity_engine import (apply_tv_daily_security, apply_tv_h4_security,
                                 build_c5_signal_bars, build_features,
                                 default_c5_params, load_bars,
                                 run_tv_compatible_signal_bars)

REPORT = "reports/c11_trend_carry_sleeve_200k_20260621.json"
BARS = "reports/tv_es1_15m_bars_20260620.json"
DAILY = "reports/tv_es1_1d_bars_20260620.json"
H4 = "reports/tv_es1_240m_bars_20260620.json"
OPTFRAME = "quant/cache/es_options_weekly_daily.parquet"
WORKER = 143


def champion_params() -> dict:
    rep = json.loads(Path(REPORT).read_text())
    items = rep.get("top10_promotion_gate_pass") or rep.get("top10")
    return next(x for x in items if x["worker_id"] == WORKER)["params"]


def gex_veto_lookup() -> tuple[pd.Series, float]:
    """Sorted series: avail_ts (UTC naive) -> True when shorts are VETOED
    (gex_z >= 0, i.e. positive/neutral dealer gamma)."""
    opt = pd.read_parquet(OPTFRAME).sort_values("date").reset_index(drop=True)
    gex_z = opt["net_gex"] / opt["net_gex"].rolling(252, min_periods=60).std()
    avail = pd.to_datetime(opt["date"]).dt.tz_localize(None) + pd.Timedelta(hours=22)
    veto = pd.Series((gex_z >= 0).to_numpy(), index=avail).dropna()
    return veto, float((gex_z >= 0).mean())


def veto_flags_for(bars: list, veto: pd.Series) -> np.ndarray:
    times = []
    for b in bars:
        t = pd.Timestamp(b.time)
        times.append(t.tz_localize(None) if t.tz is not None else t)
    idx = veto.index.searchsorted(pd.DatetimeIndex(times), side="right") - 1
    flags = np.zeros(len(bars), dtype=bool)
    ok = idx >= 0
    flags[ok] = veto.to_numpy()[idx[ok]]
    return flags


def metrics(res) -> dict:
    eq = np.cumsum([t.pnl for t in res.trades]) if res.trades else np.array([0.0])
    peak = np.maximum.accumulate(np.maximum(eq, 0))
    dd = float((eq - peak).min())
    return {"net": round(res.net_profit, 2), "pf": round(res.profit_factor, 3),
            "trades": res.n_trades, "maxDD$": round(dd, 2)}


def main():
    params = champion_params()
    raw = load_bars(BARS)
    feat = build_features(raw)
    run_params = default_c5_params()
    run_params.update(params)
    feat = apply_tv_daily_security(feat, DAILY, run_params)
    feat = apply_tv_h4_security(feat, H4, run_params)
    bars = build_c5_signal_bars(feat, run_params)

    veto, veto_share = gex_veto_lookup()
    flags = veto_flags_for(bars, veto)
    n_short_sig = sum(1 for b in bars if b.core_short)
    n_vetoed = sum(1 for b, f in zip(bars, flags) if b.core_short and f)
    print(f"bars {len(bars)} | positive-gamma sessions {veto_share*100:.0f}% | "
          f"core_short signal bars {n_short_sig}, vetoed {n_vetoed}")

    base = run_tv_compatible_signal_bars(bars, run_params)

    import copy
    bars12 = [copy.replace(b, core_short=False) if f and b.core_short else b
              for b, f in zip(bars, flags)] if hasattr(copy, "replace") else None
    if bars12 is None:                      # py<3.13 fallback
        from dataclasses import replace
        bars12 = [replace(b, core_short=False) if f and b.core_short else b
                  for b, f in zip(bars, flags)]
    c12 = run_tv_compatible_signal_bars(bars12, run_params)

    mb, mc = metrics(base), metrics(c12)
    print(f"\n{'':8} {'net$':>10} {'PF':>7} {'maxDD$':>10} {'trades':>7}")
    print(f"{'C11':8} {mb['net']:>10} {mb['pf']:>7} {mb['maxDD$']:>10} {mb['trades']:>7}")
    print(f"{'C12':8} {mc['net']:>10} {mc['pf']:>7} {mc['maxDD$']:>10} {mc['trades']:>7}")
    gates = {"net >= C11": mc["net"] >= mb["net"],
             "PF >= C11": mc["pf"] >= mb["pf"],
             "maxDD <= C11": mc["maxDD$"] >= mb["maxDD$"],
             "trades sane": mc["trades"] >= 0.5 * mb["trades"]}
    print("\ngates:", gates, "| PASS" if all(gates.values()) else "| FAIL")

    out = {"params_worker": WORKER, "veto_rule": "core_short only if prior-session gex_z<0",
           "veto_share": veto_share, "n_short_signal_bars": n_short_sig,
           "n_vetoed": n_vetoed, "c11": mb, "c12": mc, "gates": gates}
    Path("reports/c12_gex_veto_parity_20260707.json").write_text(
        json.dumps(out, indent=2, default=lambda o: bool(o) if isinstance(o, np.bool_) else str(o)))
    print("\nwrote reports/c12_gex_veto_parity_20260707.json")


if __name__ == "__main__":
    main()
