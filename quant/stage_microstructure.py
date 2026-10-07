"""stage_microstructure.py — 15m order-flow features for the front ES future from
the trades schema (12-month entitlement window).

Per 15m bucket:
  buy_vol / sell_vol   aggressor-side volume (side 'B' = buy aggressor, 'A' = sell)
  imb                  (buy - sell) / (buy + sell)
  n_trades, avg_sz     trade count / mean size
  big_imb              imbalance of large prints only (size >= 10 lots)

Front ES future per day = max-volume ES outright from ohlcv-1d + definitions.
Parallel across cores (capped: ALL_SYMBOLS day frames are memory-heavy).
Writes quant/cache/es_microstructure_15m.parquet.
"""
from __future__ import annotations

import os

import glob
import multiprocessing as mp

import numpy as np
import pandas as pd

ROOT = os.getenv("DATABENTO_ROOT", "data/databento")
BIG = 10


def _front_es_id(d: str):
    import databento as db
    dp = glob.glob(f"{ROOT}/definition/*/glbx-mdp3-{d}.definition.dbn.zst")
    op = glob.glob(f"{ROOT}/ohlcv-1d/*/glbx-mdp3-{d}.ohlcv-1d.dbn.zst")
    if not dp or not op:
        return None
    defs = db.DBNStore.from_file(dp[0]).to_df(map_symbols=False).reset_index()
    fut = defs[(defs["instrument_class"] == "F") & (defs["asset"] == "ES")]
    # outrights only (single-leg): raw_symbol like ESZ5
    fut = fut[fut["raw_symbol"].str.len() <= 5]
    if fut.empty:
        return None
    o = db.DBNStore.from_file(op[0]).to_df(map_symbols=False).reset_index()
    v = o[o["instrument_id"].isin(set(fut["instrument_id"]))]
    if v.empty:
        return None
    return int(v.loc[v["volume"].idxmax(), "instrument_id"])


def day_features(d: str) -> pd.DataFrame | None:
    try:
        import databento as db
        tp = glob.glob(f"{ROOT}/trades/*/glbx-mdp3-{d}.trades.dbn.zst")
        if not tp:
            return None
        iid = _front_es_id(d)
        if iid is None:
            return None
        t = db.DBNStore.from_file(tp[0]).to_df(map_symbols=False).reset_index()
        t = t[t["instrument_id"] == iid]
        if t.empty:
            return None
        ts = pd.DatetimeIndex(t["ts_event"]).tz_convert("UTC").tz_localize(None)
        g = pd.DataFrame({"size": t["size"].to_numpy().astype(float), "side": t["side"].to_numpy()},
                         index=ts).sort_index()
        buy = g["size"].where(g["side"] == "B", 0.0)
        sell = g["size"].where(g["side"] == "A", 0.0)
        big_b = g["size"].where((g["side"] == "B") & (g["size"] >= BIG), 0.0)
        big_s = g["size"].where((g["side"] == "A") & (g["size"] >= BIG), 0.0)
        r = pd.DataFrame({
            "buy_vol": buy.resample("15min").sum(),
            "sell_vol": sell.resample("15min").sum(),
            "n_trades": g["size"].resample("15min").count(),
            "avg_sz": g["size"].resample("15min").mean(),
            "big_b": big_b.resample("15min").sum(),
            "big_s": big_s.resample("15min").sum(),
        }).dropna(subset=["n_trades"])
        r = r[r["n_trades"] > 0]
        tot = r["buy_vol"] + r["sell_vol"]
        r["imb"] = (r["buy_vol"] - r["sell_vol"]) / tot.replace(0, np.nan)
        bt = r["big_b"] + r["big_s"]
        r["big_imb"] = (r["big_b"] - r["big_s"]) / bt.replace(0, np.nan)
        r["ts"] = r.index
        return r.reset_index(drop=True)
    except Exception:
        return None


def main():
    dates = sorted({p.split("glbx-mdp3-")[1][:8]
                    for p in glob.glob(f"{ROOT}/trades/*/glbx-mdp3-*.trades.dbn.zst")})
    nproc = min(12, mp.cpu_count())      # day frames are RAM-heavy
    print(f"{len(dates)} trade days; {nproc} workers", flush=True)
    frames, done = [], 0
    with mp.Pool(nproc) as pool:
        for f in pool.imap_unordered(day_features, dates, chunksize=2):
            done += 1
            if f is not None:
                frames.append(f)
            if done % 25 == 0:
                print(f"  {done}/{len(dates)} ok={len(frames)}", flush=True)
    df = pd.concat(frames).sort_values("ts").reset_index(drop=True)
    out = "quant/cache/es_microstructure_15m.parquet"
    df.to_parquet(out)
    print(f"staged {len(df)} 15m rows ({df['ts'].min()} .. {df['ts'].max()}) -> {out}")


if __name__ == "__main__":
    main()
