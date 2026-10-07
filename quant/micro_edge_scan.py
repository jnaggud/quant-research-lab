"""micro_edge_scan.py — FIRST-PASS edge scan of the order-flow features (no backtest).

Joins es_microstructure_15m.parquet onto the ES 15m continuous bars and measures,
train (first 60%) vs holdout (last 40%):
  * corr(feature, fwd 4-bar / 16-bar return)
  * decile spread: mean fwd return of top vs bottom feature decile
  * persistence: does 15m imbalance predict the NEXT bar's imbalance (sanity)

Features are point-in-time (the bar's own trades) — they predict FORWARD bars, so
the signal bar's own flow is complete when acted on next bar open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant.es_c11_robust import load_all_15m

FEATS = ["imb", "big_imb", "avg_sz", "n_trades"]


def main():
    micro = pd.read_parquet("quant/cache/es_microstructure_15m.parquet")
    bars = load_all_15m()
    b = bars.copy()
    ts = pd.DatetimeIndex(b["ts"])
    b["ts"] = ts.tz_localize(None) if ts.tz is not None else ts
    m = b.merge(micro, on="ts", how="inner")
    c = m["close"].astype(float)
    m["fwd4"] = c.shift(-4) / c - 1.0
    m["fwd16"] = c.shift(-16) / c - 1.0
    # flow z-scores (past-only rolling normalization where scale matters)
    m["nt_z"] = ((m["n_trades"] - m["n_trades"].rolling(96).mean()) /
                 m["n_trades"].rolling(96).std())
    m = m.dropna(subset=FEATS + ["fwd4", "fwd16"]).reset_index(drop=True)
    cut = int(len(m) * 0.6)
    tr, te = m.iloc[:cut], m.iloc[cut:]
    print(f"joined 15m rows: {len(m)}  ({m['ts'].iloc[0]} .. {m['ts'].iloc[-1]})")
    print(f"train {len(tr)} | holdout {len(te)}\n")

    print(f"{'feature':10} {'corr f4 tr|ho':>16} {'corr f16 tr|ho':>16} {'decile spread f16 (bps) tr|ho':>30}")
    for f in FEATS + ["nt_z"]:
        c4t, c4h = tr[f].corr(tr["fwd4"]), te[f].corr(te["fwd4"])
        c16t, c16h = tr[f].corr(tr["fwd16"]), te[f].corr(te["fwd16"])
        def spread(d):
            q = d[f].quantile([0.1, 0.9])
            lo = d[d[f] <= q.loc[0.1]]["fwd16"].mean()
            hi = d[d[f] >= q.loc[0.9]]["fwd16"].mean()
            return (hi - lo) * 1e4
        print(f"{f:10} {c4t:+.3f} | {c4h:+.3f}   {c16t:+.3f} | {c16h:+.3f}   "
              f"{spread(tr):+8.1f} | {spread(te):+8.1f}")

    # conditional: strong big-print imbalance + stretch
    z = (m["close"] - m["close"].rolling(96).mean()) / m["close"].rolling(96).std()
    m2 = m.assign(z=z).dropna(subset=["z"])
    te2 = m2.iloc[int(len(m2) * 0.6):]
    print("\nconditional (holdout, fwd16 bps):")
    for name, msk in [
        ("big_imb>0.5 & z<-1 (flow buys the dip)", (te2.big_imb > 0.5) & (te2.z < -1)),
        ("big_imb<-0.5 & z>1 (flow sells the rip)", (te2.big_imb < -0.5) & (te2.z > 1)),
        ("big_imb>0.5 (alone)", te2.big_imb > 0.5),
        ("big_imb<-0.5 (alone)", te2.big_imb < -0.5),
    ]:
        s = te2[msk]
        print(f"  {name:42} n={len(s):5d}  fwd16={s['fwd16'].mean()*1e4:+6.1f}")


if __name__ == "__main__":
    main()
