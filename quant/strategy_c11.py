"""strategy_c11.py — Python port + ML/Markov upgrade of the "JD ES 15m C11 Trend
Carry" Pine strategy.

The Pine original is a long-biased, multi-sleeve, regime-aware ES 15m system with
~90 optimizer-tuned (6-decimal) parameters — i.e. heavily curve-fit. We keep its
GOOD IDEAS and discard the overfit knobs:

  KEEP : multi-timeframe regime (4H + daily), four behavioural "sleeves"
         (core trend, capitulation dip-buy, participation, trend-carry), rich
         feature set, ATR risk, long bias.
  DROP : the 90 hand-tuned thresholds — replaced by (a) round defaults for the
         raw sleeve booleans and (b) an ML meta-label that *learns* which signals
         to take, validated OUT-OF-SAMPLE through quant.validate.

This module produces (i) the MTF regime, (ii) the four raw sleeve long signals +
a core short, all CAUSAL, on a 15m bar frame. quant.regime_hmm adds the Markov
regime; the ML meta-label is trained in quant.es_c11_backtest.

All higher-timeframe values use the PRIOR completed HTF bar (shift) — the Pine
`request.security(..., [1], lookahead_off)` discipline — so no repainting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl


# --------------------------------------------------------------------------------------
# MTF regime (resample 15m -> 4H / daily, EMA crossover, shifted back causally)
# --------------------------------------------------------------------------------------

def _htf_ema_signal(df: pd.DataFrame, rule: str, fast: int, slow: int) -> pd.Series:
    """+1/-1 EMA-cross regime on a higher timeframe, mapped back to 15m bars using
    only the PRIOR completed HTF bar (no lookahead)."""
    htf_close = df["close"].resample(rule, label="right", closed="right").last().dropna()
    ef = htf_close.ewm(span=fast, adjust=False).mean()
    es = htf_close.ewm(span=slow, adjust=False).mean()
    sig = np.where(ef > es, 1.0, -1.0)
    sig = pd.Series(sig, index=htf_close.index).shift(1)          # prior completed HTF bar
    return sig.reindex(df.index, method="ffill")


def add_regime(bars) -> pd.DataFrame:
    """Add h4_sig, daily_sig, regime to a 15m bar frame (ts-indexed)."""
    pdf = bars.to_pandas() if isinstance(bars, pl.DataFrame) else bars.copy()
    pdf = pdf.set_index(pd.DatetimeIndex(pdf["ts"])).sort_index()
    pdf["h4_sig"] = _htf_ema_signal(pdf, "4h", 11, 27)
    pdf["daily_sig"] = _htf_ema_signal(pdf, "1D", 9, 80)
    # combined regime: agree -> that direction, disagree -> 0 (flat/neutral)
    pdf["regime"] = np.where(pdf["h4_sig"] == pdf["daily_sig"], pdf["h4_sig"], 0.0)
    return pdf


# --------------------------------------------------------------------------------------
# Feature set (the Pine indicators, causal)
# --------------------------------------------------------------------------------------

def add_features(pdf: pd.DataFrame) -> pd.DataFrame:
    c, h, l, v = pdf["close"], pdf["high"], pdf["low"], pdf["volume"]
    out = pdf.copy()
    # oscillators
    d = c.diff()
    rs = d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean() / \
        (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
    out["rsi"] = 100 - 100 / (1 + rs)
    ll, hh = l.rolling(14).min(), h.rolling(14).max()
    out["stochk"] = 100 * (c - ll) / (hh - ll).replace(0, np.nan)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    # ATR + ADX
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=c.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=c.index)
    atrw = tr.ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1/14, adjust=False).mean() / atrw.replace(0, np.nan)
    mdi = 100 * minus_dm.ewm(alpha=1/14, adjust=False).mean() / atrw.replace(0, np.nan)
    out["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1/14, adjust=False).mean()
    # EMAs / VWAP-ish / BB / vol
    for n in (8, 21, 55, 144):
        out[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    # rolling VWAP proxy (anchored daily is messy intraday; use 96-bar rolling vwap)
    tp = (h + l + c) / 3
    out["vwap"] = (tp * v).rolling(96).sum() / v.rolling(96).sum()
    out["vwap_dist"] = (c - out["vwap"]) / out["atr"]
    out["atr_rel"] = out["atr"] / out["atr"].rolling(192).mean()
    out["vol_sma"] = v.rolling(48).mean()
    ret1 = c.pct_change()
    out["ret_z"] = (ret1 - ret1.rolling(96).mean()) / ret1.rolling(96).std().replace(0, np.nan)
    pv = (c.diff() * v).rolling(4).sum()
    out["pv_z"] = pv / pv.rolling(96).std().replace(0, np.nan)
    out["climax_vol"] = v / v.rolling(96).mean()
    out["range_pos"] = (c - l) / (h - l).replace(0, np.nan)
    out["low24"] = l.rolling(24).min().shift(1)
    out["low96"] = l.rolling(96).min().shift(1)
    bb_basis = c.rolling(40).mean()
    out["bb_lower"] = bb_basis - 2.0 * c.rolling(40).std()
    return out


# --------------------------------------------------------------------------------------
# The four sleeves (raw boolean long signals + core short). Round defaults.
# --------------------------------------------------------------------------------------

def sleeve_signals(f: pd.DataFrame, p: dict | None = None) -> pd.DataFrame:
    """Add core_long, core_short, cap_long, participation_long, trend_carry_long
    boolean columns. `p` overrides the (round, NON-overfit) thresholds."""
    p = {**DEFAULTS, **(p or {})}
    c, h, l, v = f["close"], f["high"], f["low"], f["volume"]
    reg, h4, dly = f["regime"], f["h4_sig"], f["daily_sig"]
    out = f.copy()

    long_filter_55 = c > f["ema55"]
    vol_ok = v >= p["vol_mult"] * f["vol_sma"]
    ext_ok = (c - f["ema21"]) <= p["max_ext_atr"] * f["atr"]
    vwap_ok = (c - f["vwap"]) <= p["max_vwap_atr"] * f["atr"]

    # Core (trend, both directions)
    out["core_long"] = ((reg == 1) & (c > f["ema21"]) & (f["rsi"] >= p["core_rsi_min"]) &
                        (f["rsi"] <= p["core_rsi_max"]) & (f["macd_hist"] >= p["macd_floor"]) &
                        (f["adx"] >= p["adx_min"]) & ext_ok & vwap_ok & vol_ok)
    # Short gate: require a CLEAR daily-bear regime (not just a 4H pullback) and
    # price below the slower MA in a trending tape — so shorts don't fire into an
    # uptrend's dips (the 2024-06 failure: shorts run over in a +9% quarter).
    out["core_short"] = ((reg == -1) & (dly == -1) & (c < f["ema55"]) &
                         (f["rsi"] <= p["core_short_rsi_max"]) &
                         (f["macd_hist"] <= -p["macd_floor"]) &
                         (f["adx"] >= p["adx_min"]) & vol_ok)

    # Capitulation (deep dip + exhaustion in a not-bearish regime)
    deep = ((f["vwap_dist"] <= -p["cap_vwap_atr"]) | (c <= f["bb_lower"]) |
            (l <= f["low24"] - p["cap_lowbreak_atr"] * f["atr"]))
    exhaustion = ((f["rsi"] <= p["cap_rsi_max"]) & (f["stochk"] <= p["cap_stoch_max"]) &
                  (f["ret_z"] <= -p["cap_ret_z"]) & (f["climax_vol"] >= p["cap_vol_mult"]) &
                  (f["adx"] >= p["cap_adx_min"]))
    out["cap_long"] = (dly != -1) & deep & exhaustion

    # Participation (join an up-regime trend)
    out["participation_long"] = ((dly == 1) & (c > f["ema55"]) & (f["rsi"] >= p["part_rsi_min"]) &
                                 (f["rsi"] <= p["part_rsi_max"]) & (f["macd_hist"] >= p["macd_floor"]) &
                                 (f["adx"] >= p["part_adx_min"]) & vol_ok)

    # Trend-carry (ride an established uptrend; strong MACD, low vol-rel)
    out["trend_carry_long"] = ((h4 == 1) & (dly != -1) & long_filter_55 &
                               (f["rsi"] >= p["tc_rsi_min"]) & (f["rsi"] <= p["tc_rsi_max"]) &
                               (f["macd_hist"] >= p["tc_macd_floor"]) &
                               (f["atr_rel"] <= p["tc_atr_rel_max"]) &
                               (f["adx"] >= p["tc_adx_min"]) & vol_ok)

    # Range / mean-reversion (the NEW sleeve for CHOP regimes): in a low-trend,
    # range-bound tape (low ADX, contained ATR, not a bear regime) buy oversold
    # dips toward the lower band — i.e. FADE the move instead of chasing it.
    # Designed for the regime CLASS (chop), not any specific quarter.
    out["range_long"] = ((f["adx"] <= p["range_adx_max"]) & (dly != -1) &
                         (f["atr_rel"] <= p["range_atr_rel_max"]) &
                         (f["rsi"] <= p["range_rsi_max"]) &
                         (c <= f["bb_lower"] + p["range_bb_atr"] * f["atr"]) &
                         (f["range_pos"] >= p["range_reclaim"]))     # reclaiming off the low
    return out


# round, deliberately non-overfit defaults (the ML meta-label + optimizer refine these)
DEFAULTS = dict(
    vol_mult=0.8, max_ext_atr=3.0, max_vwap_atr=2.0,
    core_rsi_min=35.0, core_rsi_max=65.0, core_short_rsi_max=50.0,
    macd_floor=0.0, adx_min=20.0,
    cap_vwap_atr=3.0, cap_lowbreak_atr=1.0, cap_rsi_max=40.0, cap_stoch_max=25.0,
    cap_ret_z=0.5, cap_vol_mult=1.0, cap_adx_min=10.0,
    part_rsi_min=47.0, part_rsi_max=62.0, part_adx_min=10.0,
    tc_rsi_min=47.0, tc_rsi_max=75.0, tc_macd_floor=0.5, tc_atr_rel_max=1.9, tc_adx_min=12.0,
    # range / mean-reversion sleeve (chop regime)
    range_adx_max=18.0, range_atr_rel_max=1.3, range_rsi_max=38.0,
    range_bb_atr=0.5, range_reclaim=0.3,
)

SLEEVES = ["trend_carry_long", "cap_long", "participation_long", "range_long",
           "core_long", "core_short"]


def combine_to_signal(f: pd.DataFrame, allow_shorts: bool = True) -> pd.Series:
    """Priority-ordered combination -> +1/-1/0 signal (trend-carry first, like the Pine)."""
    sig = pd.Series(0.0, index=f.index)
    sig = np.where(f["trend_carry_long"], 1.0, sig)
    sig = np.where((sig == 0) & f["cap_long"], 1.0, sig)
    sig = np.where((sig == 0) & f["participation_long"], 1.0, sig)
    sig = np.where((sig == 0) & f.get("range_long", False), 1.0, sig)
    sig = np.where((sig == 0) & f["core_long"], 1.0, sig)
    if allow_shorts:
        sig = np.where((sig == 0) & f["core_short"], -1.0, sig)
    return pd.Series(sig, index=f.index)


def build(bars) -> pd.DataFrame:
    """Full pipeline: bars(15m) -> regime + features + sleeves (pandas, ts-indexed)."""
    pdf = add_regime(bars)
    pdf = add_features(pdf)
    pdf = sleeve_signals(pdf)
    return pdf


if __name__ == "__main__":
    # smoke test on synthetic 15m bars
    idx = pd.date_range("2024-01-01", periods=2000, freq="15min", tz="UTC")
    rng = np.random.default_rng(0)
    px = 5000 + np.cumsum(rng.normal(0, 2, len(idx)))
    bars = pd.DataFrame({"ts": idx, "open": px, "high": px + 1, "low": px - 1,
                         "close": px, "volume": rng.integers(100, 1000, len(idx)).astype(float)})
    f = build(bars)
    sig = combine_to_signal(f)
    print("regime counts:", f["regime"].value_counts().to_dict())
    print("sleeve fire counts:", {s: int(f[s].sum()) for s in SLEEVES})
    print("signal: long", int((sig > 0).sum()), "short", int((sig < 0).sum()))
    print("strategy_c11 smoke OK")
