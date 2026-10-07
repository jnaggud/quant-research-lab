"""features.py — causal feature engineering for the ES pipeline.

Ports the *causal* indicator math from Pattern_FindR's `oscillator_predictor_page.py`
/ `novel_indicators.py` (post-lookahead-remediation, `center=False`) and the
options-structure analytics from `polygon_manager.py`, rebuilt clean and fed by
our own Black-76 `greeks.py` (Databento serves no IV/greeks).

GUARANTEES (docs/architecture.md §3):
  * Every feature is CAUSAL — value at bar t uses only bars ≤ t. No center=True,
    no `.bfill()`, no negative shifts. Proven by the causality self-test below
    (features computed on data[:t] match features computed on the full series).
  * Pure functions; work on a bars frame [ts, open, high, low, close, volume].

Internally uses pandas for clean `.rolling/.ewm` (the "pandas bridge" the audit
recommended over a fragile pandas_ta port); returns a Polars DataFrame.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from . import greeks


# --------------------------------------------------------------------------------------
# Causal indicator primitives (pandas Series in/out)
# --------------------------------------------------------------------------------------

def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0.0)
    loss = (-d).clip(lower=0.0)
    rs = _wilder(gain, n) / _wilder(loss, n).replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def williams_r(h, l, c, n: int = 14) -> pd.Series:
    hh = h.rolling(n).max()
    ll = l.rolling(n).min()
    return -100.0 * (hh - c) / (hh - ll).replace(0, np.nan)


def cci(h, l, c, n: int = 20) -> pd.Series:
    tp = (h + l + c) / 3.0
    sma = tp.rolling(n).mean()
    md = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * md.replace(0, np.nan))


def stoch_k(h, l, c, n: int = 14) -> pd.Series:
    ll = l.rolling(n).min()
    hh = h.rolling(n).max()
    return 100.0 * (c - ll) / (hh - ll).replace(0, np.nan)


def roc(c, n: int = 10) -> pd.Series:
    return (c / c.shift(n) - 1.0) * 100.0


def momentum(c, n: int = 10) -> pd.Series:
    return c - c.shift(n)


def macd_hist(c, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.Series:
    macd = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    signal = macd.ewm(span=sig, adjust=False).mean()
    return macd - signal


def bb_position(c, n: int = 20, k: float = 2.0) -> pd.Series:
    sma = c.rolling(n).mean()
    sd = c.rolling(n).std()
    return (c - sma) / (k * sd.replace(0, np.nan))


def atr(h, l, c, n: int = 14) -> pd.Series:
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def adx(h, l, c, n: int = 14) -> pd.Series:
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm = pd.Series(plus_dm, index=h.index)
    minus_dm = pd.Series(minus_dm, index=h.index)
    tr = atr(h, l, c, n)
    plus_di = 100.0 * _wilder(plus_dm, n) / tr.replace(0, np.nan)
    minus_di = 100.0 * _wilder(minus_dm, n) / tr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder(dx, n)


def mfi(h, l, c, v, n: int = 14) -> pd.Series:
    tp = (h + l + c) / 3.0
    mf = tp * v
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    return 100.0 - 100.0 / (1.0 + pos / neg.replace(0, np.nan))


# --------------------------------------------------------------------------------------
# Composite oscillator + velocity/acceleration/jerk (the reused strategy core)
# --------------------------------------------------------------------------------------

# weights for the composite blend (sum=1); each component normalized to ~[-1,1]
_COMPOSITE_WEIGHTS = {
    "rsi": 0.20, "stoch": 0.15, "williams": 0.10, "cci": 0.10,
    "macd": 0.15, "roc": 0.10, "mfi": 0.10, "bb": 0.10,
}


def _norm_components(df: pd.DataFrame) -> dict[str, pd.Series]:
    h, l, c, v = df["high"], df["low"], df["close"], df["volume"]
    return {
        "rsi": (rsi(c) - 50.0) / 50.0,
        "stoch": (stoch_k(h, l, c) - 50.0) / 50.0,
        "williams": (williams_r(h, l, c) + 50.0) / 50.0,
        "cci": (cci(h, l, c) / 200.0).clip(-1, 1),
        "macd": np.tanh(macd_hist(c) / (c.rolling(50).std().replace(0, np.nan))),
        "roc": np.tanh(roc(c) / 5.0),
        "mfi": (mfi(h, l, c, v) - 50.0) / 50.0,
        "bb": bb_position(c).clip(-1, 1),
    }


def composite_oscillator(df: pd.DataFrame, smooth: int = 3) -> pd.DataFrame:
    """Add composite, composite_smooth (trailing mean, center=False), and the
    velocity / acceleration / jerk derivatives. All causal."""
    comp_parts = _norm_components(df)
    comp = sum(_COMPOSITE_WEIGHTS[k] * comp_parts[k].fillna(0.0) for k in _COMPOSITE_WEIGHTS)
    comp = comp.clip(-1, 1)
    comp_s = comp.rolling(smooth).mean()           # TRAILING — never center=True
    vel = comp_s.diff()
    acc = vel.diff()
    jerk = acc.diff()
    out = df.copy()
    out["composite"] = comp
    out["composite_smooth"] = comp_s
    out["velocity"] = vel
    out["acceleration"] = acc
    out["jerk"] = jerk
    return out


# --------------------------------------------------------------------------------------
# Full price-feature factory
# --------------------------------------------------------------------------------------

def make_price_features(bars, lags: tuple[int, ...] = (1, 2, 3, 5)) -> pl.DataFrame:
    """Build the causal feature matrix from a bars frame (Polars or pandas).

    Returns a Polars DataFrame: original OHLCV + indicators + composite/velocity
    stack + a few returns/vol/lag features. (Extend as needed — keep it causal.)
    """
    pdf = bars.to_pandas() if isinstance(bars, pl.DataFrame) else bars.copy()
    pdf = pdf.reset_index(drop=True)
    c, h, l, v = pdf["close"], pdf["high"], pdf["low"], pdf["volume"]

    f = pdf.copy()
    # returns / vol
    f["ret_1"] = c.pct_change()
    f["logret_1"] = np.log(c / c.shift(1))
    f["vol_10"] = f["ret_1"].rolling(10).std()
    f["vol_30"] = f["ret_1"].rolling(30).std()
    # trend
    for n in (10, 20, 50, 200):
        f[f"sma_{n}"] = c.rolling(n).mean()
        f[f"dist_sma_{n}"] = (c - f[f"sma_{n}"]) / f[f"sma_{n}"]
    f["ema_12"] = c.ewm(span=12, adjust=False).mean()
    f["ema_26"] = c.ewm(span=26, adjust=False).mean()
    # oscillators
    f["rsi_14"] = rsi(c, 14)
    f["williams_14"] = williams_r(h, l, c, 14)
    f["cci_20"] = cci(h, l, c, 20)
    f["stoch_14"] = stoch_k(h, l, c, 14)
    f["roc_10"] = roc(c, 10)
    f["macd_hist"] = macd_hist(c)
    f["bb_pos"] = bb_position(c)
    f["adx_14"] = adx(h, l, c, 14)
    f["mfi_14"] = mfi(h, l, c, v, 14)
    f["atr_14"] = atr(h, l, c, 14)
    # volume
    f["rvol_20"] = v / v.rolling(20).mean()
    f["vol_velocity"] = f["rvol_20"].diff()
    # composite + derivatives
    f = composite_oscillator(f)
    # lags of the headline signal
    for lag in lags:
        f[f"composite_lag{lag}"] = f["composite_smooth"].shift(lag)
        f[f"ret_lag{lag}"] = f["ret_1"].shift(lag)

    return pl.from_pandas(f)


# --------------------------------------------------------------------------------------
# Options-structure features (max pain / GEX / walls / PCR / ATM IV)
# --------------------------------------------------------------------------------------

def make_options_features(chain: pd.DataFrame, F: float, T: float, r: float = 0.045,
                          multiplier: float = 50.0) -> dict:
    """Compute point-in-time options-structure features for one expiry/underlying.

    `chain` rows: [strike, cp ('C'/'P'), open_interest, volume, mid]. `mid` is the
    option price used to back out IV via Black-76. F=underlying future, T=DTE/365.
    Returns scalar features usable as ES directional inputs (all point-in-time —
    no lookahead, they describe the current chain only). multiplier=$50 for ES.
    """
    ch = chain.copy()
    ch["cp"] = ch["cp"].astype(str).str.upper().str[0]
    calls = ch[ch["cp"] == "C"]
    puts = ch[ch["cp"] == "P"]
    out: dict[str, float] = {}

    # Put/Call ratios
    out["pcr_oi"] = float(puts["open_interest"].sum() / max(calls["open_interest"].sum(), 1))
    out["pcr_vol"] = float(puts["volume"].sum() / max(calls["volume"].sum(), 1))

    # Max pain: strike minimizing total option-holder payoff (dealer-favorable pin)
    strikes = np.sort(ch["strike"].unique())
    if len(strikes):
        # for each candidate settle S, total holder payoff =
        #   sum_K callOI(K)*max(S-K,0) + putOI(K)*max(K-S,0); min = max-pain pin
        coi = calls.set_index("strike")["open_interest"]
        poi = puts.set_index("strike")["open_interest"]
        tot = []
        for S in strikes:
            cp_pay = (np.maximum(S - coi.index.values, 0.0) * coi.values).sum()
            pp_pay = (np.maximum(poi.index.values - S, 0.0) * poi.values).sum()
            tot.append(cp_pay + pp_pay)
        max_pain = float(strikes[int(np.argmin(tot))])
        out["max_pain"] = max_pain
        out["max_pain_dist"] = float((F - max_pain) / F)

    # Walls = strikes with the most OI
    if len(calls):
        out["call_wall"] = float(calls.loc[calls["open_interest"].idxmax(), "strike"])
        out["call_wall_dist"] = float((out["call_wall"] - F) / F)
    if len(puts):
        out["put_wall"] = float(puts.loc[puts["open_interest"].idxmax(), "strike"])
        out["put_wall_dist"] = float((out["put_wall"] - F) / F)

    # IV + dealer gamma (GEX): IV per contract from mid, then gamma*OI*mult (sign:
    # dealers short calls / long puts convention → +call_gamma, -put_gamma).
    if "mid" in ch.columns and T > 0:
        iv = greeks.implied_vol(ch["mid"].to_numpy(), F, ch["strike"].to_numpy(), T, r,
                                ch["cp"].map({"C": 1, "P": -1}).to_numpy())
        g = greeks.greeks(F, ch["strike"].to_numpy(), T, r, np.nan_to_num(iv, nan=0.20),
                          ch["cp"].map({"C": 1, "P": -1}).to_numpy())
        gamma = np.asarray(g["gamma"])
        oi = ch["open_interest"].to_numpy()
        sign = np.where(ch["cp"].values == "C", 1.0, -1.0)
        gex = float(np.nansum(gamma * oi * sign) * multiplier * F)
        out["net_gamma"] = gex
        # ATM IV = IV at the strike nearest F
        atm_idx = int(np.argmin(np.abs(ch["strike"].to_numpy() - F)))
        out["atm_iv"] = float(iv[atm_idx]) if np.isfinite(iv[atm_idx]) else float("nan")
    return out


# --------------------------------------------------------------------------------------
# Self-test — causality + sanity (synthetic, no drive I/O)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    rng = np.random.default_rng(7)
    n = 600
    price = 6000 + np.cumsum(rng.normal(0, 5, n))
    hi = price + np.abs(rng.normal(0, 3, n))
    lo = price - np.abs(rng.normal(0, 3, n))
    vol = rng.integers(1000, 5000, n).astype(float)
    bars = pd.DataFrame({"open": price, "high": hi, "low": lo, "close": price, "volume": vol})

    full = make_price_features(bars).to_pandas()
    print("feature columns:", len(full.columns))
    print("sample:", [c for c in full.columns if c in
                      ("composite_smooth", "velocity", "rsi_14", "adx_14", "atr_14")])

    # CAUSALITY PROOF: features at bar t-1 must be identical whether computed on the
    # full series or only on data[:t]. Test several cut points.
    feat_cols = ["composite_smooth", "velocity", "acceleration", "rsi_14",
                 "macd_hist", "adx_14", "mfi_14", "atr_14", "dist_sma_50"]
    max_err = 0.0
    for t in (300, 400, 500):
        partial = make_price_features(bars.iloc[:t]).to_pandas()
        a = full.loc[t - 1, feat_cols].to_numpy(dtype=float)
        b = partial.loc[t - 1, feat_cols].to_numpy(dtype=float)
        diff = np.nanmax(np.abs(a - b))
        max_err = max(max_err, diff if np.isfinite(diff) else 0.0)
    print(f"causality max |full - partial| at t-1 = {max_err:.2e}")
    assert max_err < 1e-9, "LOOKAHEAD DETECTED — a feature changed when future bars were added"

    # velocity must equal diff of composite_smooth
    v_err = np.nanmax(np.abs((full["composite_smooth"].diff() - full["velocity"]).to_numpy()))
    assert v_err < 1e-12

    # options features sanity
    strikes = np.arange(5800, 6201, 25.0)
    chain = pd.DataFrame({
        "strike": np.r_[strikes, strikes],
        "cp": ["C"] * len(strikes) + ["P"] * len(strikes),
        "open_interest": rng.integers(10, 5000, 2 * len(strikes)).astype(float),
        "volume": rng.integers(0, 2000, 2 * len(strikes)).astype(float),
    })
    # synth mids from a flat 18% vol so IV recovery works
    F, T, r = 6000.0, 21 / 365, 0.045
    cpsign = chain["cp"].map({"C": 1, "P": -1}).to_numpy()
    chain["mid"] = greeks.price(F, chain["strike"].to_numpy(), T, r, 0.18, cpsign)
    of = make_options_features(chain, F, T, r)
    print("options features:", {k: round(v, 4) for k, v in of.items()})
    assert 5800 <= of["max_pain"] <= 6200
    assert abs(of["atm_iv"] - 0.18) < 1e-3, "ATM IV recovery off"
    print("features.py self-test PASSED")
