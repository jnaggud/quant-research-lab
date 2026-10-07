"""stage_options.py — stage a DAILY ES options-sentiment feature frame to SSD.

OI is unavailable (statistics schema not downloaded, ~205 GB), so we build the
OI-FREE signals that only need definition + ohlcv-1d (both on disk):
  pcr_vol     put/call VOLUME ratio (positioning/sentiment)
  atm_iv      ATM implied vol (Black-76), interpolated at K=F (fear gauge)
  iv_skew     OTM-put IV minus OTM-call IV (directional tail fear)
  put/call_iv average IV each side
These are the cheap options signals; if they add ES edge, OI is worth chasing.

Writes quant/cache/es_options_daily.parquet. Run with the download PAUSED (fast HDD).
"""
from __future__ import annotations

import os

import glob
from datetime import datetime

import numpy as np
import pandas as pd

from quant import greeks as G
from quant import options_data as O

DEF_GLOB = os.path.join(os.getenv("DATABENTO_ROOT", "data/databento"), 'definition/*/glbx-mdp3-*.definition.dbn.zst')


def _iv_frame(chain: pd.DataFrame, F: float, T: float) -> pd.DataFrame:
    c = chain.copy()
    c["m"] = c["strike"] / F
    c = c[(c["m"] >= 0.85) & (c["m"] <= 1.20)]   # only near-money needed for ATM-IV + skew
    ivs = []
    for _, r in c.iterrows():
        try:
            iv = G.implied_vol(r["mid"], F, r["strike"], T, 0.0, r["cp"])
        except Exception:
            iv = np.nan
        ivs.append(iv)
    c["iv"] = pd.to_numeric(pd.Series(ivs, index=c.index), errors="coerce")
    return c[c["iv"].notna() & (c["iv"] > 0.01) & (c["iv"] < 3.0)]


def _interp_at(c: pd.DataFrame, m0: float, cp: str | None = None) -> float:
    d = c if cp is None else c[c["cp"] == cp]
    d = d.sort_values("m")
    if len(d) < 3:
        return np.nan
    return float(np.interp(m0, d["m"].to_numpy(dtype=float), d["iv"].to_numpy(dtype=float)))


def features_for(d: str) -> dict | None:
    res = O.es_chain(d)
    if res is None:
        return None
    chain, F, T = res
    if len(chain) < 8:
        return None
    chain = chain.copy()
    # walls weighted by VOLUME (near-spot activity = dynamic S/R). Tested: OI-weighted
    # walls sit at sticky far strikes price rarely touches, and broke the signal.
    chain["w"] = chain["volume"]
    puts, calls = chain[chain.cp == "P"], chain[chain.cp == "C"]
    pcr_vol = puts["volume"].sum() / max(calls["volume"].sum(), 1.0)
    pcr_oi = puts["open_interest"].sum() / max(calls["open_interest"].sum(), 1.0)
    # near-money call wall (resistance) / put wall (support) by weight, + max-pain magnet
    ca = calls[(calls.strike > F) & (calls.strike <= F * 1.07)]
    pu = puts[(puts.strike < F) & (puts.strike >= F * 0.93)]
    call_wall = float(ca.loc[ca["w"].idxmax(), "strike"]) if len(ca) and ca["w"].max() > 0 else np.nan
    put_wall = float(pu.loc[pu["w"].idxmax(), "strike"]) if len(pu) and pu["w"].max() > 0 else np.nan
    strikes = np.sort(chain["strike"].unique())
    if len(strikes) and chain["w"].sum() > 0:
        pain = [(calls["w"] * np.maximum(s - calls["strike"], 0)).sum() +
                (puts["w"] * np.maximum(puts["strike"] - s, 0)).sum() for s in strikes]
        max_pain = float(strikes[int(np.argmin(pain))])
    else:
        max_pain = np.nan
    c = _iv_frame(chain, F, T)
    if len(c) < 8:
        return None
    atm_iv = _interp_at(c, 1.0)
    put_iv_95 = _interp_at(c, 0.95, "P")     # OTM put
    call_iv_105 = _interp_at(c, 1.05, "C")   # OTM call
    iv_skew = (put_iv_95 - call_iv_105) if np.isfinite(put_iv_95) and np.isfinite(call_iv_105) else np.nan
    return {
        "date": pd.Timestamp(datetime.strptime(d, "%Y%m%d").date()),
        "F": F, "dte": round(T * 365), "n": len(chain),
        "pcr_vol": float(pcr_vol), "pcr_oi": float(pcr_oi), "atm_iv": atm_iv, "iv_skew": iv_skew,
        "put_iv": float(c[c.cp == "P"]["iv"].mean()), "call_iv": float(c[c.cp == "C"]["iv"].mean()),
        "call_wall": call_wall, "put_wall": put_wall, "max_pain": max_pain,
    }


def _safe(d):
    try:
        return features_for(d)
    except Exception:
        return None


def main(start="2021-01-01", end="2026-06-30"):
    import multiprocessing as mp
    dates = sorted({p.split("glbx-mdp3-")[1][:8] for p in glob.glob(DEF_GLOB)})
    s, e = start.replace("-", ""), end.replace("-", "")
    dates = [d for d in dates if s <= d <= e]
    nproc = max(1, mp.cpu_count() or 8)   # use all cores
    print(f"{len(dates)} definition dates in range {start}..{end}; {nproc} workers", flush=True)
    rows, done = [], 0
    with mp.Pool(nproc) as pool:
        for f in pool.imap_unordered(_safe, dates, chunksize=4):
            done += 1
            if f:
                rows.append(f)
            if done % 200 == 0:
                print(f"  {done}/{len(dates)}  ok={len(rows)}", flush=True)
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out = "quant/cache/es_options_daily.parquet"
    df.to_parquet(out)
    print(f"staged {len(df)} days -> {out}")
    print(df.tail(4).to_string())
    print("\nfeature coverage (non-NaN):")
    for col in ["pcr_vol", "atm_iv", "iv_skew"]:
        print(f"  {col}: {df[col].notna().mean()*100:.0f}%")


if __name__ == "__main__":
    import sys
    main(*(sys.argv[1:3] if len(sys.argv) > 2 else []))
