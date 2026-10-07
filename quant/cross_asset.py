"""cross_asset.py — bond / macro cross-asset features for the ES models.

Every price-only ES experiment hit the same ceiling: ES price carries no macro
context. Treasury futures (ZN = 10-year) do. This module loads staged ZN, aligns
it to the ES 15m grid, and builds CAUSAL cross-asset features:

  zn_ret_4/20      : ZN momentum (rates direction; bonds up = yields down)
  zn_trend         : ZN vs its EMA (persistent rates regime)
  es_zn_corr_96    : rolling 1-day ES<->ZN return correlation (risk-on/off regime;
                     the SIGN flipping is itself a regime signal)
  stock_bond_div   : ES up while ZN up (or both down) over the last day — unusual
                     co-movement that often precedes equity wobbles (e.g. 2024-06)
  zn_ret_z         : z-scored ZN return (rate-shock magnitude; flags 2022-style selloffs)

These become extra inputs to the ML meta-label (and could feed the HMM regime).
All windows are trailing/`shift` — no lookahead.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

CACHE = Path(__file__).parent / "cache"

BOND_FEATURES = ["zn_ret_4", "zn_ret_20", "zn_trend", "es_zn_corr_96",
                 "stock_bond_div", "zn_ret_z"]


def load_root_15m(root: str) -> pd.DataFrame:
    """Load + concat all staged 1m parquets for `root`, resample to 15m."""
    files = sorted(CACHE.glob(f"{root}_continuous_minute_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no staged {root} 1m parquet")
    frames = []
    for f in files:
        df = pl.read_parquet(f)
        adj = {c: c.replace("adj_", "") for c in df.columns if c.startswith("adj_")}
        if adj:
            df = df.drop([c.replace("adj_", "") for c in adj]).rename(adj)
        frames.append(df.select(["ts", "close"]).to_pandas())
    p = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
    p = p.set_index(pd.DatetimeIndex(p["ts"]))
    c = p["close"].resample("15min").last().dropna()
    return c.to_frame("zn_close")


def add_bond_features(es_frame: pd.DataFrame) -> pd.DataFrame:
    """Add bond/cross-asset feature columns to an ES 15m frame (must have ts + close).
    ES frame is returned unchanged plus BOND_FEATURES (NaN where ZN is missing)."""
    zn = load_root_15m("ZN")
    es = es_frame.copy()
    es_idx = pd.DatetimeIndex(es["ts"])
    # align ZN onto the ES timestamp grid
    znc = zn["zn_close"].reindex(es_idx, method="ffill")

    zr = znc.pct_change()
    er = pd.Series(es["close"].to_numpy(), index=es_idx).pct_change()

    feats = pd.DataFrame(index=es_idx)
    feats["zn_ret_4"] = znc.pct_change(4)
    feats["zn_ret_20"] = znc.pct_change(20)
    feats["zn_trend"] = (znc > znc.ewm(span=96, adjust=False).mean()).astype(float) * 2 - 1
    feats["es_zn_corr_96"] = er.rolling(96).corr(zr)
    # divergence: both moving same direction over the last day (risk regime stress)
    es_dir = np.sign(er.rolling(96).sum())
    zn_dir = np.sign(zr.rolling(96).sum())
    feats["stock_bond_div"] = (es_dir == zn_dir).astype(float)
    feats["zn_ret_z"] = (zr - zr.rolling(96).mean()) / zr.rolling(96).std().replace(0, np.nan)

    for col in BOND_FEATURES:
        es[col] = feats[col].to_numpy()
    return es


def bond_regime(es_frame: pd.DataFrame) -> np.ndarray:
    """DAILY bond-derived risk regime, mapped to the ES 15m grid (causal).

    +True  (risk-on / equity-supportive): ZN above its 50-DAY EMA — i.e. bonds
            firm / yields not spiking. Equities historically do fine here.
    +False (risk-off): ZN below its 50-day EMA — rates rising, the 2022-style
            headwind where ES longs get run over.

    Uses the PRIOR COMPLETED daily bar (shift) so there is no lookahead. This runs
    at the timeframe where the macro signal actually lives (daily), unlike feeding
    bonds into a 15m ML meta-label (which was just noise)."""
    zn = load_root_15m("ZN")["zn_close"]
    zn_daily = zn.resample("1D").last().dropna()
    ema = zn_daily.ewm(span=50, adjust=False).mean()
    risk_on_daily = (zn_daily > ema).shift(1)          # prior completed day -> causal
    es_idx = pd.DatetimeIndex(es_frame["ts"])
    mapped = risk_on_daily.reindex(es_idx, method="ffill")
    return mapped.fillna(True).to_numpy().astype(bool)


if __name__ == "__main__":
    # smoke: requires staged ZN + ES
    from quant import es_c11_robust as R
    frame = R.prep()
    n0 = len(frame)
    f = add_bond_features(frame)
    cov = f[BOND_FEATURES].notna().all(axis=1).mean()
    print(f"ES bars {n0}; bond features added, non-NaN coverage {cov:.1%}")
    print(f[["ts"] + BOND_FEATURES].dropna().tail(3).to_string())
    print("cross_asset smoke OK")
