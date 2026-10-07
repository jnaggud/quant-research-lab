"""options_join.py — merge the daily weekly-complex options frame onto 15m ES bars
WITHOUT lookahead.

Day-d option features come from day-d daily files (settlement volume, closes, OI),
which are only fully known after the session settles (~21:00 UTC). So a 15m bar may
only see features from the latest option date whose session ended BEFORE the bar:
we stamp each feature row available at date+22:00 UTC and merge_asof backward.
(The v1 tests merged same-day, which leaked the day's own settlement volume into
its intraday bars.)

Adds causal derived columns:
  d_call/d_put       relative distance to the front-week volume walls
  d_pain             relative signed distance above the nearest-expiry max pain
  d_flip             relative signed distance above the gamma-flip level
  gex_z              net GEX / trailing 1y std (past-only)
  iv_ratio           atm_iv / trailing 1y median atm_iv (past-only)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).parent / "cache"
AVAIL_HOUR = 22          # UTC hour after which day-d settle data is usable

OPT_COLS = ["call_wall", "put_wall", "call_wall_wk", "put_wall_wk", "max_pain",
            "max_pain_wk", "gamma_flip", "net_gex", "atm_iv", "iv_skew",
            "pcr_vol", "pcr_oi", "dte_near"]


import os


def load_daily() -> pd.DataFrame:
    fname = os.environ.get("ES_OPT_FRAME", "es_options_weekly_daily.parquet")
    opt = pd.read_parquet(CACHE / fname)
    opt["date"] = pd.to_datetime(opt["date"]).dt.tz_localize(None).dt.normalize()
    opt = opt.sort_values("date").reset_index(drop=True)
    # past-only normalizations (computed on the daily frame BEFORE the bar join)
    opt["gex_z"] = opt["net_gex"] / opt["net_gex"].rolling(252, min_periods=60).std()
    opt["iv_ratio"] = opt["atm_iv"] / opt["atm_iv"].rolling(252, min_periods=60).median()
    opt["avail_ts"] = opt["date"] + pd.Timedelta(hours=AVAIL_HOUR)
    return opt


def join_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: 15m frame with a 'ts' column (tz-aware or naive UTC). Returns bars +
    option features from the latest AVAILABLE session + derived distances."""
    b = bars.copy()
    ts = pd.DatetimeIndex(b["ts"])
    b["_ts"] = ts.tz_localize(None) if ts.tz is not None else ts
    b = b.sort_values("_ts")
    opt = load_daily()
    cols = OPT_COLS + ["gex_z", "iv_ratio", "avail_ts"]
    m = pd.merge_asof(b, opt[cols], left_on="_ts", right_on="avail_ts",
                      direction="backward", tolerance=pd.Timedelta(days=5))
    c = m["close"].astype(float)
    m["d_call"] = (m["call_wall_wk"] - c) / c        # +: wall above (room up)
    m["d_put"] = (c - m["put_wall_wk"]) / c          # +: wall below (room down)
    m["d_pain"] = (c - m["max_pain"]) / c            # +: above the pin
    m["d_flip"] = (c - m["gamma_flip"]) / c          # +: above the flip (long-gamma side)
    return m.drop(columns=["_ts", "avail_ts"])
