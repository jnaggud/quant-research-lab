"""stage_options_weekly.py — stage the WEEKLY-complex daily ES options frame to SSD.

Successor to stage_options.py: uses quant.options_weekly (full weekly complex,
volume walls near spot, quarterly-OI GEX + gamma flip). One row per trading day.

Writes quant/cache/es_options_weekly_daily.parquet. Uses ALL cores.
"""
from __future__ import annotations

import glob
import multiprocessing as mp

import pandas as pd

import os

DEF_GLOB = os.path.join(os.getenv("DATABENTO_ROOT", "data/databento"), 'definition/*/glbx-mdp3-*.definition.dbn.zst')
OUT = os.environ.get("ES_OPT_STAGE_OUT", "quant/cache/es_options_weekly_daily.parquet")


def _safe(d):
    try:
        from quant.options_weekly import features_for
        return features_for(d)
    except Exception:
        return None


def main(start="2021-01-01", end="2026-06-30"):
    dates = sorted({p.split("glbx-mdp3-")[1][:8] for p in glob.glob(DEF_GLOB)})
    s, e = start.replace("-", ""), end.replace("-", "")
    dates = [d for d in dates if s <= d <= e]
    nproc = max(1, mp.cpu_count() or 8)
    print(f"{len(dates)} definition dates in {start}..{end}; {nproc} workers", flush=True)
    rows, done = [], 0
    with mp.Pool(nproc) as pool:
        for f in pool.imap_unordered(_safe, dates, chunksize=4):
            done += 1
            if f:
                rows.append(f)
            if done % 100 == 0:
                print(f"  {done}/{len(dates)}  ok={len(rows)}", flush=True)
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.to_parquet(OUT)
    print(f"staged {len(df)} days -> {OUT}")
    print(df.tail(3).to_string())
    print("\ncoverage (non-NaN) and wall distance sanity:")
    for col in ["atm_iv", "iv_skew", "call_wall", "put_wall", "net_gex", "gamma_flip"]:
        print(f"  {col}: {df[col].notna().mean()*100:.0f}%")
    for col in ["call_wall", "put_wall", "call_wall_wk", "put_wall_wk", "max_pain"]:
        dist = ((df[col] - df["F"]) / df["F"]).abs()
        print(f"  |{col}-F|/F median: {dist.median()*100:.2f}%")


if __name__ == "__main__":
    import sys
    main(*(sys.argv[1:3] if len(sys.argv) > 2 else []))
