"""options_bands.py — combine option "areas of interest" (max-pain magnet, call/put
walls) with the price-stretch bands to find where ES is likely to move directionally.

Three honest tests (all with a train/holdout split so nothing is in-sample-only):
  1. MAX-PAIN PINNING — is the forward move biased back toward max-pain? (price above
     pain -> falls, below -> rises). Measured as corr(fwd_ret, signed_dist_to_pain).
  2. WALL REVERSION — near the call wall (resistance) does price revert down; near the
     put wall (support) does it bounce? forward return conditioned on wall proximity.
  3. STRETCH x WALL — the synthesis: is a stretched bar reverting MORE when it's also
     sitting at the opposing wall than stretch alone? (the higher-conviction turn).

Daily option levels are mapped onto the ES 15m grid (a day's levels apply to that day).
Levels are volume-weighted now; swap to OI when the statistics download lands.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from quant.es_c11_robust import load_all_15m

CACHE = Path(__file__).parent / "cache"
K = 16      # forward horizon (bars)
MA = 96


def build():
    opt = pd.read_parquet(CACHE / "es_options_daily.parquet")
    opt["date"] = pd.to_datetime(opt["date"]).dt.tz_localize(None).dt.normalize()
    bars = load_all_15m()
    b = bars.copy()
    b["date"] = pd.DatetimeIndex(b["ts"]).tz_localize(None).normalize()
    c = b["close"].astype(float)
    b["z"] = (c - c.rolling(MA).mean()) / c.rolling(MA).std()
    b["fwd"] = c.shift(-K) / c - 1.0
    m = b.merge(opt[["date", "call_wall", "put_wall", "max_pain"]], on="date", how="inner")
    cc = m["close"].astype(float)
    m["d_pain"] = (cc - m["max_pain"]) / cc            # +: above pain
    m["d_call"] = (m["call_wall"] - cc) / cc           # +: below the call wall (room up)
    m["d_put"] = (cc - m["put_wall"]) / cc             # +: above the put wall (room down)
    return m.dropna(subset=["z", "fwd", "d_pain", "d_call", "d_put"]).reset_index(drop=True)


def main():
    m = build()
    cut = int(len(m) * 0.6)
    tr, te = m.iloc[:cut], m.iloc[cut:]
    print(f"merged 15m+option-levels: {len(m)} bars\n")

    # 1. Max-pain pinning
    print("=== 1. MAX-PAIN PINNING: corr(forward return, signed distance above pain) ===")
    print("   (negative corr = pinning: above pain -> falls, below -> rises)")
    print(f"   train corr = {tr['fwd'].corr(tr['d_pain']):+.3f} | holdout corr = {te['fwd'].corr(te['d_pain']):+.3f}")
    for lo, hi, lbl in [(-1, -0.01, "well BELOW pain"), (-0.01, 0.01, "AT pain"), (0.01, 1, "well ABOVE pain")]:
        seg = te[(te["d_pain"] > lo) & (te["d_pain"] <= hi)]
        if len(seg) > 50:
            print(f"     holdout {lbl:16}: n={len(seg):5d}  avg fwd = {seg['fwd'].mean()*1e4:+6.1f} bps")

    # 2. Wall reversion (holdout): near call wall vs near put wall
    print("\n=== 2. WALL PROXIMITY (holdout) — avg forward return near each wall ===")
    near_call = te[te["d_call"].abs() < 0.003]
    near_put = te[te["d_put"].abs() < 0.003]
    print(f"   near CALL wall (<0.3%): n={len(near_call):5d}  avg fwd={near_call['fwd'].mean()*1e4:+6.1f} bps (expect <0 if resistance)")
    print(f"   near PUT  wall (<0.3%): n={len(near_put):5d}  avg fwd={near_put['fwd'].mean()*1e4:+6.1f} bps (expect >0 if support)")

    # 3. Stretch x wall synthesis (holdout): reversion of stretched bars, at wall vs not
    print("\n=== 3. STRETCH x WALL (holdout) — does a wall sharpen the reversal? ===")
    hi_at_wall = te[(te["z"] >= 1.5) & (te["d_call"].abs() < 0.005)]
    hi_no_wall = te[(te["z"] >= 1.5) & (te["d_call"].abs() >= 0.005)]
    lo_at_wall = te[(te["z"] <= -1.5) & (te["d_put"].abs() < 0.005)]
    lo_no_wall = te[(te["z"] <= -1.5) & (te["d_put"].abs() >= 0.005)]
    print(f"   stretched UP (z>=1.5) + at call wall : n={len(hi_at_wall):5d}  avg fwd={hi_at_wall['fwd'].mean()*1e4:+6.1f} bps")
    print(f"   stretched UP (z>=1.5) + NO wall      : n={len(hi_no_wall):5d}  avg fwd={hi_no_wall['fwd'].mean()*1e4:+6.1f} bps")
    print(f"   stretched DN (z<=-1.5)+ at put wall  : n={len(lo_at_wall):5d}  avg fwd={lo_at_wall['fwd'].mean()*1e4:+6.1f} bps")
    print(f"   stretched DN (z<=-1.5)+ NO wall      : n={len(lo_no_wall):5d}  avg fwd={lo_no_wall['fwd'].mean()*1e4:+6.1f} bps")


if __name__ == "__main__":
    main()
