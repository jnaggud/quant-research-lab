"""es_c11_ml.py — C11 strategy + ML META-LABEL (López de Prado style).

The four sleeves are the PRIMARY signal. A classifier then learns which of those
signals to actually TAKE, from the rich features at the signal bar. This replaces
the ~90 hand-tuned thresholds with a learned filter.

Leakage discipline (the audit's core lesson):
  * Meta-label = forward outcome (uses future) -> it is a TRAINING TARGET only,
    never a feature.
  * Chronological train/holdout split; the model is fit on TRAIN signals and
    evaluated ONCE on HOLDOUT signals. Features at the signal bar are causal.
  * Seed-stability MC over model seeds; 3 gates.

Compares FILTERED (ML) vs ALL (unfiltered base) on the same holdout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant import es_c11_backtest as BASE
from quant import strategy_c11 as C11

FEATURES = ["rsi", "stochk", "macd_hist", "adx", "atr_rel", "vwap_dist",
            "ret_z", "pv_z", "climax_vol", "range_pos", "regime", "h4_sig", "daily_sig"]
HOLD = 16            # ~4h forward window for the meta-label
COST_FRAC = 0.0006   # round-trip slippage+commission as a fraction of price


def _prep():
    frame = C11.build(BASE.load_15m())
    frame = C11.sleeve_signals(frame)
    sig = C11.combine_to_signal(frame, allow_shorts=True).to_numpy()
    c = frame["close"].to_numpy()
    fwd = np.full(len(c), np.nan)
    fwd[:-HOLD] = (c[HOLD:] - c[:-HOLD]) / c[:-HOLD]
    # meta-label: would the trade (in signal direction) clear costs?
    label = ((fwd * np.sign(sig) - COST_FRAC) > 0).astype(int)
    frame = frame.reset_index(drop=True)
    frame["signal"] = sig
    frame["meta_label"] = label
    frame["fwd"] = fwd
    return frame


def _bt(frame_slice: pd.DataFrame) -> dict:
    bt = frame_slice[["open", "high", "low", "close", "volume", "signal"]].copy()
    res = B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                         stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                         slippage_ticks=1.0, min_bars_between=2)
    return res["metrics"]


def main():
    frame = _prep()
    n = len(frame)
    sig_mask = frame["signal"].to_numpy() != 0
    n_sig = int(sig_mask.sum())
    cut = int(n * 0.6)
    train = frame.iloc[:cut]
    holdout = frame.iloc[cut + 200:]            # +embargo
    print(f"ES 15m bars {n}, primary signals {n_sig}; train {len(train)} / holdout {len(holdout)}")

    # training rows = signal bars in train with a defined label
    tr = train[(train["signal"] != 0) & train["meta_label"].notna()].dropna(subset=FEATURES)
    Xtr, ytr = tr[FEATURES].to_numpy(), tr["meta_label"].to_numpy()
    base_rate = ytr.mean()
    print(f"train signal rows {len(tr)}, profitable-label rate {base_rate:.2%}")

    # baseline: take ALL holdout signals
    base_metrics = _bt(holdout)

    # ML-filtered across seeds
    ho_sig = holdout[(holdout["signal"] != 0)].dropna(subset=FEATURES)
    rets, trades = [], []
    for seed in range(5):
        clf = RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                     random_state=seed, n_jobs=-1, class_weight="balanced")
        clf.fit(Xtr, ytr)
        proba = clf.predict_proba(ho_sig[FEATURES].to_numpy())[:, 1]
        take = proba > 0.5
        ho = holdout.copy()
        keep_idx = set(ho_sig.index[take])
        ho["signal"] = [s if i in keep_idx else 0.0
                        for i, s in zip(ho.index, ho["signal"])]
        m = _bt(ho)
        rets.append(m["total_return"]); trades.append(m["n_trades"])

    med = float(np.median(rets))
    pct_pos = 100 * np.mean([r > 0 for r in rets])
    med_tr = float(np.median(trades))
    print("\n=== C11 + ML meta-label, OOS (holdout) ===")
    print(f"BASE (take all signals):     OOS {base_metrics['total_return']*100:+.2f}%  "
          f"trades {base_metrics['n_trades']}  win {base_metrics['win_rate']*100:.0f}%  "
          f"PF {base_metrics['profit_factor']:.2f}")
    print(f"ML  (take filtered signals): OOS median {med*100:+.2f}%  stable {pct_pos:.0f}%  "
          f"median trades {med_tr:.0f}")
    print(f"per-seed OOS: {[f'{r*100:+.1f}%' for r in rets]}")
    gates = med > 0 and pct_pos >= 75 and med_tr >= 20
    print(f"GATES (ML): oos>0 {med>0} | stable≥75% {pct_pos>=75} | trades≥20 {med_tr>=20} | PASS {gates}")
    # feature importance (which inputs the filter relies on)
    imp = sorted(zip(FEATURES, clf.feature_importances_), key=lambda x: -x[1])[:6]
    print("top meta-features:", [(f, round(v, 3)) for f, v in imp])


if __name__ == "__main__":
    main()
