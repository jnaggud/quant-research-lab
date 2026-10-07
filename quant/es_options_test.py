"""es_options_test.py — does ES options SENTIMENT predict forward ES direction, OOS?

Merges the daily options-sentiment frame (quant.stage_options) with ES daily
returns and runs a rolling-origin walk-forward: train a simple logistic model on a
trailing window (options features -> forward-5d ES up/down), predict the next block,
and score OOS directional accuracy + a long/flat backtest vs buy-&-hold.

Features are CAUSAL (levels + trailing z-scored changes). Logistic (not RF) to
resist the overfitting that sank the richer price models. Honest read only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

CACHE = Path(__file__).parent / "cache"
FWD = 5  # forward horizon (trading days)


def load_es_daily() -> pd.DataFrame:
    import polars as pl
    files = sorted(CACHE.glob("ES_continuous_minute_*.parquet"))
    frames = []
    for f in files:
        df = pl.read_parquet(f)
        adj = {c: c.replace("adj_", "") for c in df.columns if c.startswith("adj_")}
        if adj:
            df = df.drop([c.replace("adj_", "") for c in adj]).rename(adj)
        frames.append(df.select(["ts", "close"]).to_pandas())
    p = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
    p = p.set_index(pd.DatetimeIndex(p["ts"]))
    d = p["close"].resample("1D").last().dropna()
    return d.to_frame("es_close")


def build():
    opt = pd.read_parquet(CACHE / "es_options_daily.parquet")
    opt["date"] = pd.to_datetime(opt["date"]).dt.tz_localize(None).dt.normalize()
    es = load_es_daily()
    es.index = pd.DatetimeIndex(es.index).tz_localize(None).normalize()
    es = es.reset_index().rename(columns={"index": "date", "ts": "date"})
    es["date"] = pd.to_datetime(es["date"]).dt.normalize()
    m = opt.merge(es, on="date", how="inner").sort_values("date").reset_index(drop=True)
    # causal features: levels + 5d change + 20d z-score
    for col in ["atm_iv", "pcr_vol", "iv_skew"]:
        m[f"{col}_chg"] = m[col].diff(5)
        z = (m[col] - m[col].rolling(20).mean()) / m[col].rolling(20).std()
        m[f"{col}_z"] = z
    m["fwd_ret"] = m["es_close"].shift(-FWD) / m["es_close"] - 1
    m["y"] = (m["fwd_ret"] > 0).astype(int)
    return m


FEATS = ["atm_iv", "pcr_vol", "iv_skew", "atm_iv_chg", "pcr_vol_chg",
         "iv_skew_chg", "atm_iv_z", "pcr_vol_z", "iv_skew_z"]


def main():
    m = build()
    m = m.dropna(subset=FEATS + ["fwd_ret"]).reset_index(drop=True)
    print(f"merged options+ES daily: {len(m)} rows, {m.date.min().date()}..{m.date.max().date()}")
    n = len(m)
    train_win = 252         # ~1y trailing
    step = 63               # ~quarter test blocks
    rows = []
    i = train_win
    while i + step <= n:
        tr = m.iloc[i - train_win:i]
        te = m.iloc[i:i + step]
        Xtr, ytr = tr[FEATS].to_numpy(), tr["y"].to_numpy()
        if len(np.unique(ytr)) < 2:
            i += step; continue
        sc = StandardScaler().fit(Xtr)
        clf = LogisticRegression(max_iter=500, C=0.5).fit(sc.transform(Xtr), ytr)
        proba = clf.predict_proba(sc.transform(te[FEATS].to_numpy()))[:, 1]
        pred_up = proba > 0.5
        acc = (pred_up == te["y"].to_numpy().astype(bool)).mean()
        # long-only-when-predicted-up backtest over the block (per-day fwd/FWD compounded proxy)
        daily_ret = te["es_close"].pct_change().fillna(0).to_numpy()
        strat = np.where(np.roll(pred_up, 1), daily_ret, 0.0)  # act on prior day's signal
        rows.append({"start": te["date"].iloc[0].date(), "acc": acc,
                     "strat": float(np.prod(1 + strat) - 1),
                     "mkt": float(np.prod(1 + daily_ret) - 1),
                     "days_long": int(pred_up.sum())})
        i += step
    R = pd.DataFrame(rows)
    print(f"\n{'block':12} {'OOS_acc':>8} {'strat%':>8} {'mkt%':>8} {'long_d':>7}")
    for _, r in R.iterrows():
        print(f"{str(r['start']):12} {r['acc']*100:>7.0f}% {r['strat']*100:>+7.1f} {r['mkt']*100:>+7.1f} {r['days_long']:>7}")
    print("-" * 48)
    print(f"blocks {len(R)} | mean OOS directional acc {R['acc'].mean()*100:.1f}% (50% = coin flip)")
    print(f"strat total {(np.prod(1+R['strat'])-1)*100:+.1f}% vs buy&hold {(np.prod(1+R['mkt'])-1)*100:+.1f}%")
    print(f"blocks with acc>52%: {(R['acc']>0.52).mean()*100:.0f}%")
    # coefficient signs from a full-sample fit (interpretation only, not OOS)
    sc = StandardScaler().fit(m[FEATS]); clf = LogisticRegression(max_iter=500, C=0.5).fit(sc.transform(m[FEATS]), m["y"])
    print("\nfull-sample coef (sign = direction of forward-up odds):")
    for f, c in sorted(zip(FEATS, clf.coef_[0]), key=lambda x: -abs(x[1])):
        print(f"  {f:14} {c:+.3f}")


if __name__ == "__main__":
    main()
