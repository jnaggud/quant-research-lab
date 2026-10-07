"""es_c11_robust.py — ROLLING-ORIGIN walk-forward for the C11 + ML meta-label.

The single-holdout +ML result (+42.89%) was suspicious because train and test were
both bull markets. This is the honest test: train on a rolling window, test on the
NEXT unseen quarter, roll forward through 2021->2026 (incl. the 2022 bear and 2023
chop). We report performance PER PERIOD and split by market direction, so we can
see whether the edge survives regimes it wasn't trained on.

Leakage guards: features causal; meta-label is a training target only; an embargo
(= the label's forward window) is dropped from the end of each train block so the
label window can't peek into the test block. Each test quarter is scored ONCE.
"""
from __future__ import annotations

import os

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant import strategy_c11 as C11

CACHE = Path(__file__).parent / "cache"
FEATURES = ["rsi", "stochk", "macd_hist", "adx", "atr_rel", "vwap_dist",
            "ret_z", "pv_z", "climax_vol", "range_pos", "regime", "h4_sig", "daily_sig"]
HOLD = 16
COST_FRAC = 0.0006


def load_all_15m() -> pd.DataFrame:
    """Load and concat ALL staged ES 1m parquets, resample to 15m, dedup by ts."""
    files = sorted(CACHE.glob("ES_continuous_minute_*.parquet"))
    if not files:
        raise SystemExit("no staged ES 1m parquet")
    frames = []
    for f in files:
        df = pl.read_parquet(f)
        adj = {c: c.replace("adj_", "") for c in df.columns if c.startswith("adj_")}
        if adj:
            df = df.drop([c.replace("adj_", "") for c in adj]).rename(adj)
        frames.append(df.select(["ts", "open", "high", "low", "close", "volume"]).to_pandas())
    p = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
    p = p.set_index(pd.DatetimeIndex(p["ts"]))
    bars = pd.DataFrame({
        "open": p["open"].resample("15min").first(), "high": p["high"].resample("15min").max(),
        "low": p["low"].resample("15min").min(), "close": p["close"].resample("15min").last(),
        "volume": p["volume"].resample("15min").sum()}).dropna()
    bars["ts"] = bars.index
    return bars.reset_index(drop=True)


def prep(allow_shorts: bool = True, bond_gate: bool = False):
    frame = C11.build(load_all_15m())
    frame = C11.sleeve_signals(frame)
    sig = C11.combine_to_signal(frame, allow_shorts=allow_shorts).to_numpy()
    if bond_gate:
        from quant import cross_asset as X
        risk_on = X.bond_regime(frame)            # daily ZN regime, causal
        sig = np.where((sig > 0) & (~risk_on), 0.0, sig)   # block ES longs in risk-off
    c = frame["close"].to_numpy()
    fwd = np.full(len(c), np.nan); fwd[:-HOLD] = (c[HOLD:] - c[:-HOLD]) / c[:-HOLD]
    frame = frame.reset_index(drop=True)
    frame["signal"] = sig
    frame["meta_label"] = ((fwd * np.sign(sig) - COST_FRAC) > 0).astype(int)
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    return frame


def _bt(seg: pd.DataFrame) -> dict:
    bt = seg[["open", "high", "low", "close", "volume", "signal"]].copy()
    m = B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                       stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                       slippage_ticks=1.0, min_bars_between=2)["metrics"]  # max-hold reverted (it backfired)
    return m


def main():
    import os
    allow_shorts = os.environ.get("C11_SHORTS", "1") == "1"
    use_bonds = os.environ.get("C11_BONDS", "0") == "1"
    bond_gate = os.environ.get("C11_BONDGATE", "0") == "1"
    print(f"[config] allow_shorts={allow_shorts} bonds_ml={use_bonds} bond_gate={bond_gate}")
    frame = prep(allow_shorts=allow_shorts, bond_gate=bond_gate)
    feats = list(FEATURES)
    if use_bonds:
        from quant import cross_asset as X
        frame = X.add_bond_features(frame)
        feats = feats + X.BOND_FEATURES
        print(f"[config] bond features added: {X.BOND_FEATURES}")
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]
    print(f"data {t0.date()} .. {t1.date()}  ({len(frame)} 15m bars)\n")

    train_years = 1.5
    test = pd.DateOffset(months=3)
    # first test starts after train_years of data
    start = (t0 + pd.DateOffset(months=int(train_years * 12))).normalize()
    rows = []
    cur = start
    while cur + test <= t1:
        tr = frame[(frame["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                   (frame["dt"] >= cur - pd.DateOffset(months=int(train_years * 12)))]
        te = frame[(frame["dt"] >= cur) & (frame["dt"] < cur + test)]
        if len(te) < 200 or len(tr) < 2000:
            cur += test; continue
        trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=feats)
        if len(trs) < 100:
            cur += test; continue
        # market direction of the test quarter
        bh = (te["close"].iloc[-1] - te["close"].iloc[0]) * B.ES.point_value / 100_000.0
        base = _bt(te)
        # ML meta-label (single seed; this is a temporal test, not a seed test)
        clf = RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                     random_state=0, n_jobs=-1, class_weight="balanced")
        clf.fit(trs[feats].to_numpy(), trs["meta_label"].to_numpy())
        tes = te[te["signal"] != 0].dropna(subset=feats)
        keep = set(tes.index[clf.predict_proba(tes[feats].to_numpy())[:, 1] > 0.5])
        te2 = te.copy()
        te2["signal"] = [s if i in keep else 0.0 for i, s in zip(te2.index, te2["signal"])]
        ml = _bt(te2)
        rows.append({"q": cur.date(), "mkt": bh, "base": base["total_return"],
                     "ml": ml["total_return"], "ml_tr": ml["n_trades"]})
        cur += test

    R = pd.DataFrame(rows)
    print(f"{'quarter':12} {'mkt%':>7} {'base%':>7} {'ML%':>7} {'ML_tr':>6}")
    for _, r in R.iterrows():
        print(f"{str(r['q']):12} {r['mkt']*100:>+6.1f} {r['base']*100:>+6.1f} "
              f"{r['ml']*100:>+6.1f} {int(r['ml_tr']):>6}")
    print("-" * 44)
    print(f"windows: {len(R)} | ML mean {R['ml'].mean()*100:+.2f}% median {R['ml'].median()*100:+.2f}%")
    print(f"ML % windows positive: {(R['ml']>0).mean()*100:.0f}%  (base: {(R['base']>0).mean()*100:.0f}%)")
    down = R[R['mkt'] < 0]
    print(f"DOWN-market windows: {len(down)} | ML positive in {((down['ml']>0).sum())}/{len(down)} "
          f"(mean {down['ml'].mean()*100:+.2f}%)" if len(down) else "no down-market windows in range")
    print(f"ML total (sum of window returns): {R['ml'].sum()*100:+.1f}%  vs base {R['base'].sum()*100:+.1f}%  "
          f"vs market {R['mkt'].sum()*100:+.1f}%")
    # gate: positive median AND >=60% windows positive AND survives down-markets
    robust = R['ml'].median() > 0 and (R['ml'] > 0).mean() >= 0.6 and (len(down) == 0 or (down['ml'] > 0).mean() >= 0.5)
    print(f"\nROBUST (median>0, ≥60% windows +, holds in down-markets): {robust}")

    # RISK-ADJUSTED comparison: compound per-quarter returns into equity curves, then
    # Sharpe (quarterly->annual) + max drawdown. The apples-to-apples test vs buy&hold:
    # a risk-managed book can win here even while trailing on raw return.
    print("\n=== RISK-ADJUSTED (compounded over the quarters) ===")
    print(f"{'series':10} {'total%':>8} {'Sharpe':>7} {'maxDD%':>7} {'Calmar':>7}")
    for col, name in [("ml", "STRATEGY"), ("base", "C11(noML)"), ("mkt", "buy&hold")]:
        eq = (1 + R[col]).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        sharpe = float(R[col].mean() / R[col].std() * np.sqrt(4)) if R[col].std() > 0 else 0.0
        tot = float(eq.iloc[-1] - 1)
        calmar = tot / abs(dd) if dd < 0 else float("inf")
        print(f"{name:10} {tot*100:>+7.1f} {sharpe:>7.2f} {dd*100:>7.1f} {calmar:>7.2f}")


if __name__ == "__main__":
    main()
