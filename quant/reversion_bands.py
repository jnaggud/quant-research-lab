"""reversion_bands.py — empirical mean-reversion / peak-valley probability map for ES.

Idea (transparent, few-parameter, hard to overfit):
  * Normalize price stretch: z = (close - MA_n) / rolling_std_n  (CAUSAL — trailing).
  * Bin z into FIXED-WIDTH horizontal bands (e.g. 0.5 sigma each).
  * For each band, measure the empirical REVERSION probability from history:
      reverted = the next-K-bar move goes AGAINST the stretch
                 (stretched up -> falls = a peak; stretched down -> rises = a valley)
  * Expect: high bands -> high P(peak/revert-down); low bands -> high P(valley/revert-up).

The make-or-break is OOS CALIBRATION: fit band probabilities on TRAIN, then check they
stay true on a later HOLDOUT. If a 70%-revert band in train is ~70% in test, it's a real,
stable structure; if it decays to ~50%, it was noise. We also report the avg forward
return per band (the actual $ edge) and a simple fade backtest through the engine.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant import backtest as B
from quant.es_c11_robust import load_all_15m

BANDS = np.arange(-4.0, 4.001, 0.5)   # fixed-width 0.5-sigma bands


def build(bars: pd.DataFrame, ma_n: int = 96, k: int = 16) -> pd.DataFrame:
    """Per-bar stretch z (causal), forward-K return, reversion label, and band."""
    c = bars["close"].astype(float)
    ma = c.rolling(ma_n).mean()
    sd = c.rolling(ma_n).std()
    z = (c - ma) / sd
    fwd = c.shift(-k) / c - 1.0
    reverted = (fwd * np.sign(z) < 0).astype(float)   # moved back toward the mean
    df = pd.DataFrame({"ts": bars["ts"].to_numpy(), "close": c.to_numpy(),
                       "z": z.to_numpy(), "fwd": fwd.to_numpy(),
                       "reverted": reverted.to_numpy()})
    df["band"] = pd.cut(df["z"], BANDS)
    return df.dropna(subset=["z", "fwd", "band"]).reset_index(drop=True)


def band_map(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("band", observed=True).agg(
        n=("reverted", "size"), p_revert=("reverted", "mean"),
        avg_fwd_bps=("fwd", lambda s: s.mean() * 1e4)).reset_index()
    return g


def main():
    bars = load_all_15m()
    df = build(bars)
    print(f"ES 15m bars used: {len(df)}  (ma=96, fwd K=16)\n")

    # in-sample band map
    print("=== BAND MAP (full sample) — z-band -> P(revert toward mean), avg fwd return ===")
    print(f"{'band':>16} {'n':>7} {'P_revert':>9} {'avg_fwd_bps':>12}")
    for _, r in band_map(df).iterrows():
        print(f"{str(r['band']):>16} {int(r['n']):>7} {r['p_revert']*100:>8.1f}% {r['avg_fwd_bps']:>+11.1f}")

    # OOS calibration: fit band stats on train (first 60%), check on holdout (last 40%)
    cut = int(len(df) * 0.6)
    tr, te = df.iloc[:cut], df.iloc[cut:]
    mtr = band_map(tr).set_index("band")["p_revert"]
    mte = band_map(te).set_index("band")
    print("\n=== OOS CALIBRATION — does train P(revert) hold in the holdout? ===")
    print(f"{'band':>16} {'train_P':>8} {'test_P':>8} {'test_n':>7} {'test_fwd_bps':>13}")
    cal_err = []
    for band in mtr.index:
        if band in mte.index and mte.loc[band, "n"] >= 50:
            tp, ep, en, ef = mtr[band], mte.loc[band, "p_revert"], mte.loc[band, "n"], mte.loc[band, "avg_fwd_bps"]
            cal_err.append(abs(tp - ep))
            print(f"{str(band):>16} {tp*100:>7.1f}% {ep*100:>7.1f}% {int(en):>7} {ef:>+12.1f}")
    print(f"\nmean |train−test| P(revert) gap: {np.mean(cal_err)*100:.1f}pp  (small = stable/real)")

    # OOS backtest of several band-signal variants on the holdout
    z = df["z"].to_numpy()
    variants = {
        "fade extremes (short hi / long lo)": np.where(z >= 2.0, -1.0, np.where(z <= -2.0, 1.0, 0.0)),
        "dip-buy long-only (long z<=-2)":     np.where(z <= -2.0, 1.0, 0.0),
        "dip-buy shallow (long z<=-1)":       np.where(z <= -1.0, 1.0, 0.0),
        "momentum long-only (long z>=+1)":    np.where(z >= 1.0, 1.0, 0.0),
        "momentum full (long hi / short lo)": np.where(z >= 1.0, 1.0, np.where(z <= -1.0, -1.0, 0.0)),
    }
    bars_ho = bars.iloc[-len(df):].iloc[cut:][["open", "high", "low", "close", "volume"]].reset_index(drop=True)
    bh = (bars_ho["close"].iloc[-1] - bars_ho["close"].iloc[0]) * B.ES.point_value / 1e5
    print("\n=== OOS band-signal backtests (HOLDOUT) — vs buy&hold %+.1f%% ===" % (bh * 100))
    print(f"{'variant':38} {'OOS%':>8} {'trades':>7} {'win':>5} {'PF':>6}")
    for name, sig in variants.items():
        b = bars_ho.copy()
        b["signal"] = sig[cut:]
        m = B.run_backtest(b, contract=B.ES, entry_mode="next_bar_open", direction="both",
                           stop_loss_pts=60.0, take_profit_pts=60.0, trailing_pts=None,
                           slippage_ticks=1.0, min_bars_between=2)["metrics"]
        print(f"{name:38} {m['total_return']*100:>+7.1f} {m['n_trades']:>7} "
              f"{m['win_rate']*100:>4.0f}% {m['profit_factor']:>5.2f}")


if __name__ == "__main__":
    main()
