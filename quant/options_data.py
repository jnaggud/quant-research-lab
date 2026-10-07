"""options_data.py — build a DAILY ES options chain from already-downloaded data.

For daily options-structure features (max-pain / gamma-walls / PCR / ATM-IV) we do
NOT need the heavy mbp-1 quote stream — a daily snapshot suffices, and it comes from
schemas we already have:
  definition  -> per option: instrument_id, raw_symbol, C/P, strike, expiration, underlying
  ohlcv-1d    -> per instrument: daily close (the option price for IV) + volume
  statistics  -> per instrument: open interest (stat_type OpenInterest)

We then compute IV (Black-76) from the option close + the underlying future close +
DTE, and feed quant.features.make_options_features.

Reads use the fast path (to_df(map_symbols=False)); the option<->symbol map is taken
once from the definition file (which carries strike/expiration/class as RECORD fields,
no symbology needed) plus a symbology lookup for the raw_symbol/root tag.
"""
from __future__ import annotations

import os

import glob
import re
from datetime import date, datetime

import databento as db
import numpy as np
import pandas as pd

from quant import features as F

ROOT = os.getenv("DATABENTO_ROOT", "data/databento")
STAT_OPEN_INTEREST = 9   # Databento StatType.OPEN_INTEREST
_OUTRIGHT = re.compile(r"^([A-Z0-9]+?)[FGHJKMNQUVXZ]\d+$")


def _file(schema: str, d: str) -> str | None:
    p = glob.glob(f"{ROOT}/{schema}/*/glbx-mdp3-{d}.{schema}.dbn.zst")
    return p[0] if p else None


def _read(schema: str, d: str, map_symbols: bool = False) -> pd.DataFrame | None:
    f = _file(schema, d)
    if not f:
        return None
    return db.DBNStore.from_file(f).to_df(map_symbols=map_symbols).reset_index()


def es_chain(d: str, root: str = "ES") -> tuple[pd.DataFrame, float, float] | None:
    """Return (chain_df, F_underlying, T_years) for the nearest ES option expiry on date d.

    chain_df columns: strike, cp ('C'/'P'), open_interest, volume, mid.
    """
    # FAST path: definition records natively carry asset/class/strike/expiry/
    # underlying_id — no symbology mapping needed.
    defs = _read("definition", d, map_symbols=False)
    if defs is None or "asset" not in defs.columns:
        return None
    opt = defs[(defs["asset"] == root) & (defs["instrument_class"].isin(["C", "P"]))].copy()
    if opt.empty:
        return None
    opt["expiry"] = pd.to_datetime(opt["expiration"], utc=True, errors="coerce")
    # front-month underlying = the most-populated underlying_id; nearest expiry
    und_id = opt["underlying_id"].value_counts().idxmax()
    opt = opt[opt["underlying_id"] == und_id]
    nearest = opt["expiry"].dropna().min()
    opt = opt[opt["expiry"] == nearest]
    if opt.empty:
        return None

    # option + underlying-future daily closes from ohlcv-1d (join on instrument_id)
    o = _read("ohlcv-1d", d)
    if o is None or "instrument_id" not in o.columns:
        return None
    closes = o.set_index("instrument_id")["close"]
    vols = o.set_index("instrument_id")["volume"] if "volume" in o.columns else pd.Series(dtype=float)
    if und_id not in closes.index:
        return None
    F_under = float(closes[und_id])

    # open interest from statistics
    st = _read("statistics", d)
    oi_map = {}
    if st is not None and "stat_type" in st and "instrument_id" in st:
        oo = st[st["stat_type"] == STAT_OPEN_INTEREST]
        qty_col = "quantity" if "quantity" in oo else ("price" if "price" in oo else None)
        if qty_col:
            oi_map = oo.groupby("instrument_id")[qty_col].last().to_dict()

    rows = []
    asof = datetime.strptime(d, "%Y%m%d").date()
    T = max((nearest.date() - asof).days, 1) / 365.0
    for _, r in opt.iterrows():
        iid = r["instrument_id"]
        px = closes.get(iid, np.nan)
        if not np.isfinite(px) or px <= 0:
            continue
        rows.append({"strike": float(r["strike_price"]), "cp": r["instrument_class"],
                     "open_interest": float(oi_map.get(iid, 0.0)),
                     "volume": float(vols.get(iid, 0.0)), "mid": float(px)})
    if not rows:
        return None
    return pd.DataFrame(rows), F_under, T


def options_features(d: str, root: str = "ES") -> dict | None:
    res = es_chain(d, root)
    if res is None:
        return None
    chain, F_under, T = res
    feats = F.make_options_features(chain, F_under, T, multiplier=50.0)
    feats["_underlying"] = F_under
    feats["_dte_days"] = round(T * 365)
    feats["_n_contracts"] = len(chain)
    feats["_total_oi"] = float(chain["open_interest"].sum())
    return feats


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "20260626"
    print(f"building ES options chain for {d} ...", flush=True)
    f = options_features(d)
    if f is None:
        print("could not build chain (data may not be on disk for that date)")
    else:
        for k, v in f.items():
            print(f"  {k}: {round(v, 4) if isinstance(v, float) else v}")
