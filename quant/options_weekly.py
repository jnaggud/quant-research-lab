"""options_weekly.py — ES options chain across the FULL weekly complex.

The v1 chain (`options_data.es_chain`) filtered `asset == "ES"`, which is only the
QUARTERLY options — median 44 DTE, walls 2-5% from spot, effectively untradeable
(see reports/es_options_levels_validation_20260707.md). The definitions carry the
whole weekly complex (E1A-E5D Mon-Thu, EW1-EW4 Fri, EW month-end) with expiries
0-6 days out. Selecting options BY UNDERLYING (`underlying_id` of the front ES
future) picks up every root robustly across years.

Data caveat discovered 2026-07-07: the statistics download is scoped to the 43
major roots by PARENT symbology, and `ES.OPT` covers only the quarterly root —
so OPEN INTEREST exists on disk for quarterlies only. Hence:
  * weekly walls / max-pain are VOLUME-weighted (ohlcv-1d is ALL_SYMBOLS)
  * net GEX / gamma-flip use real OI from the quarterly chain (dte<=90)
A scoped statistics job for the ~25 weekly roots would upgrade GEX to the full
complex later.

All features are computed from day-d data only; consumers must apply them to day
d+1 bars (previous-session chain -> next session), which also removes the same-day
volume lookahead the v1 tests had.
"""
from __future__ import annotations

import os

import glob
from datetime import datetime

import databento as db
import numpy as np
import pandas as pd

from quant import greeks as G

ROOT = os.getenv("DATABENTO_ROOT", "data/databento")
STAT_OPEN_INTEREST = 9
MULT = 50.0                # ES options multiplier ($ per point)
DTE_MAX = 120              # frame horizon (quarterlies included for GEX, roll-safe)
WEEK = 7                   # "front week" wall horizon
NEAR_BAND = 0.07           # wall search band around spot


def _file(schema: str, d: str) -> str | None:
    p = glob.glob(f"{ROOT}/{schema}/*/glbx-mdp3-{d}.{schema}.dbn.zst")
    return p[0] if p else None


def _read(schema: str, d: str) -> pd.DataFrame | None:
    f = _file(schema, d)
    if not f:
        return None
    return db.DBNStore.from_file(f).to_df(map_symbols=False).reset_index()


def _read_statistics(d: str) -> pd.DataFrame | None:
    """Main statistics (43 major roots) + the scoped weekly-roots supplement
    (statistics-weekly/, downloaded 2026-07-07) concatenated."""
    frames = [x for x in (_read("statistics", d),) if x is not None]
    wk = glob.glob(f"{ROOT}/statistics-weekly/*/glbx-mdp3-{d}.statistics.dbn.zst")
    if wk:
        frames.append(db.DBNStore.from_file(wk[0]).to_df(map_symbols=False).reset_index())
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def es_weekly_frame(d: str) -> tuple[pd.DataFrame, float] | None:
    """All options on ANY ES future for date d (weekly + quarterly roots).

    Options are pooled across underlyings — around the quarterly roll the
    near-dated weeklies sit on the OLD front future while listings pile onto the
    next one, so restricting to a single "front" underlying loses whichever side
    is active. F is the close of the max-volume ES future (basis between
    adjacent quarters is small vs the levels we extract).

    Returns (frame, F). frame: strike, cp, dte, T, oi, volume, mid (NaN if the
    contract didn't trade), one row per contract with dte in [1, DTE_MAX].
    """
    defs = _read("definition", d)
    if defs is None or "asset" not in defs.columns:
        return None
    fut_ids = set(defs.loc[(defs["instrument_class"] == "F") & (defs["asset"] == "ES"),
                           "instrument_id"])
    if not fut_ids:
        return None
    opt = defs[defs["instrument_class"].isin(["C", "P"]) &
               defs["underlying_id"].isin(fut_ids)].copy()
    if opt.empty:
        return None

    asof = datetime.strptime(d, "%Y%m%d").date()
    opt["expiry"] = pd.to_datetime(opt["expiration"], utc=True, errors="coerce")
    opt["dte"] = (opt["expiry"].dt.date - asof).map(lambda x: x.days if pd.notna(x) else np.nan)
    opt = opt[(opt["dte"] >= 1) & (opt["dte"] <= DTE_MAX)]
    if opt.empty:
        return None

    o = _read("ohlcv-1d", d)
    if o is None or "instrument_id" not in o.columns:
        return None
    closes = o.drop_duplicates("instrument_id").set_index("instrument_id")["close"]
    vols = (o.drop_duplicates("instrument_id").set_index("instrument_id")["volume"]
            if "volume" in o.columns else pd.Series(dtype=float))
    # front ES future = max daily volume among the option-underlying futures
    und_vol = vols[vols.index.isin(set(opt["underlying_id"]))]
    if und_vol.empty:
        return None
    front = int(und_vol.idxmax())
    if front not in closes.index:
        return None
    F = float(closes[front])

    st = _read_statistics(d)
    oi = pd.Series(dtype=float)
    if st is not None and "stat_type" in st and "instrument_id" in st:
        oo = st[st["stat_type"] == STAT_OPEN_INTEREST]
        qty = "quantity" if "quantity" in oo else ("price" if "price" in oo else None)
        if qty:
            oi = oo.groupby("instrument_id")[qty].last()

    iid = opt["instrument_id"]
    frame = pd.DataFrame({
        "strike": opt["strike_price"].astype(float).to_numpy(),
        "cp": opt["instrument_class"].to_numpy(),
        "dte": opt["dte"].astype(int).to_numpy(),
        "oi": iid.map(oi).fillna(0.0).astype(float).to_numpy(),
        "volume": iid.map(vols).fillna(0.0).astype(float).to_numpy(),
        "mid": iid.map(closes).astype(float).to_numpy(),
    })
    frame["T"] = frame["dte"] / 365.0
    frame.loc[frame["mid"] <= 0, "mid"] = np.nan
    return frame, F


def _fill_iv(ch: pd.DataFrame, F: float, r: float = 0.0) -> pd.DataFrame:
    """Solve IV for traded contracts, then interpolate by moneyness within each
    (dte, cp) bucket so OI-only strikes still get a vol (for gamma)."""
    ch = ch.copy()
    ch["m"] = ch["strike"] / F
    traded = ch["mid"].notna() & (ch["m"] >= 0.70) & (ch["m"] <= 1.30)
    ch["iv"] = np.nan
    if traded.sum() >= 4:
        t = ch[traded]
        iv = G.implied_vol(t["mid"].to_numpy(), F, t["strike"].to_numpy(),
                           t["T"].to_numpy(), r, t["cp"].to_numpy())
        ch.loc[traded, "iv"] = iv
    ch.loc[(ch["iv"] <= 0.01) | (ch["iv"] >= 3.0), "iv"] = np.nan
    for (dte, cp), g in ch.groupby(["dte", "cp"]):
        src = g[g["iv"].notna()].sort_values("m")
        dst = g[g["iv"].isna()]
        if len(src) >= 3 and len(dst):
            ch.loc[dst.index, "iv"] = np.interp(
                dst["m"].to_numpy(), src["m"].to_numpy(), src["iv"].to_numpy())
    return ch


def _walls(sub: pd.DataFrame, F: float, w: str) -> tuple[float, float]:
    """(call_wall, put_wall) = max-weight strikes within NEAR_BAND of spot."""
    ca = sub[(sub.cp == "C") & (sub.strike > F) & (sub.strike <= F * (1 + NEAR_BAND))]
    pu = sub[(sub.cp == "P") & (sub.strike < F) & (sub.strike >= F * (1 - NEAR_BAND))]
    cw = float(ca.loc[ca[w].idxmax(), "strike"]) if len(ca) and ca[w].max() > 0 else np.nan
    pw = float(pu.loc[pu[w].idxmax(), "strike"]) if len(pu) and pu[w].max() > 0 else np.nan
    return cw, pw


def _max_pain(sub: pd.DataFrame, w: str) -> float:
    strikes = np.sort(sub["strike"].unique())
    if not len(strikes) or sub[w].sum() <= 0:
        return np.nan
    calls, puts = sub[sub.cp == "C"], sub[sub.cp == "P"]
    pain = [(calls[w] * np.maximum(s - calls["strike"], 0)).sum() +
            (puts[w] * np.maximum(puts["strike"] - s, 0)).sum() for s in strikes]
    return float(strikes[int(np.argmin(pain))])


def _gex_profile(ch: pd.DataFrame, F: float):
    """Net dealer GEX at spot ($ per 1% move) + gamma-flip level (GEX(S)=0 near F).

    Convention: dealers long calls' gamma, short puts' (calls +, puts −).
    Uses OI-carrying contracts — on current data that is the quarterly chain."""
    g = ch[(ch["oi"] > 0) & ch["iv"].notna()]
    if len(g) < 8:
        return np.nan, np.nan
    K = g["strike"].to_numpy()[:, None]
    T = g["T"].to_numpy()[:, None]
    iv = g["iv"].to_numpy()[:, None]
    oi = g["oi"].to_numpy()[:, None]
    sign = np.where(g["cp"].to_numpy() == "C", 1.0, -1.0)[:, None]
    S = (F * np.linspace(0.93, 1.07, 141))[None, :]
    with np.errstate(all="ignore"):
        d1 = (np.log(S / K) + 0.5 * iv * iv * T) / (iv * np.sqrt(T))
        gamma = np.exp(-0.5 * d1 * d1) / (np.sqrt(2 * np.pi) * S * iv * np.sqrt(T))
    prof = np.nansum(sign * gamma * oi * MULT * S * S * 0.01, axis=0)
    Sg = S[0]
    net_at_spot = float(np.interp(F, Sg, prof))
    cross = np.where(np.diff(np.sign(prof)) != 0)[0]
    if len(cross) == 0:
        return net_at_spot, np.nan
    flips = np.array([Sg[i] - prof[i] * (Sg[i + 1] - Sg[i]) / (prof[i + 1] - prof[i])
                      for i in cross])
    return net_at_spot, float(flips[np.argmin(np.abs(flips - F))])


def features_for(d: str) -> dict | None:
    res = es_weekly_frame(d)
    if res is None:
        return None
    ch, F = res
    ch = _fill_iv(ch, F)

    # nearest expiry = nearest dte with real trading (stub listings can't hijack)
    traded_per_dte = ch[ch["mid"].notna()].groupby("dte").size()
    live = traded_per_dte[traded_per_dte >= 20]
    if live.empty:
        return None
    near = ch[ch["dte"] == int(live.index.min())]
    week = ch[ch["dte"] <= WEEK]                                # the whole front week
    cw_n, pw_n = _walls(near, F, "volume")
    cw_w, pw_w = _walls(week, F, "volume")
    net_gex, flip = _gex_profile(ch, F)

    ivn = near[near["iv"].notna() & near["mid"].notna()]        # traded-only for IV stats
    def _iv_at(m0, cp=None):
        s = ivn if cp is None else ivn[ivn.cp == cp]
        s = s.sort_values("m")
        return float(np.interp(m0, s["m"], s["iv"])) if len(s) >= 3 else np.nan
    atm_iv = _iv_at(1.0)
    skew = _iv_at(0.97, "P") - _iv_at(1.03, "C") if len(ivn) >= 6 else np.nan

    puts, calls = week[week.cp == "P"], week[week.cp == "C"]
    qt = ch[ch["oi"] > 0]                                       # OI-carrying = quarterly
    return {
        "date": pd.Timestamp(datetime.strptime(d, "%Y%m%d").date()),
        "F": F, "dte_near": int(near["dte"].min()), "n_week": len(week),
        "pcr_vol": float(puts["volume"].sum() / max(calls["volume"].sum(), 1.0)),
        "pcr_oi": float(qt[qt.cp == "P"]["oi"].sum() / max(qt[qt.cp == "C"]["oi"].sum(), 1.0)),
        "atm_iv": atm_iv, "iv_skew": skew,
        "call_wall": cw_n, "put_wall": pw_n,
        "call_wall_wk": cw_w, "put_wall_wk": pw_w,
        "max_pain": _max_pain(near, "volume"),
        "max_pain_wk": _max_pain(week, "volume"),
        "net_gex": net_gex, "gamma_flip": flip,
    }


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "20260626"
    f = features_for(d)
    if f is None:
        print(f"no chain for {d}")
    else:
        for k, v in f.items():
            print(f"  {k}: {round(v, 4) if isinstance(v, float) else v}")
