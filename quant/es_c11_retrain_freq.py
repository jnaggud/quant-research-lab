"""es_c11_retrain_freq.py — does FASTER meta-label retraining help? (regime-adaptation
experiment A)

If real-time / regime-aware adaptation has merit, more frequent refits of the ML
meta-label should beat slower ones. If the curve is flat (or inverted), adaptation
adds nothing and C12 ships with fixed rules (the Pattern_FindR v10-v15 lesson).

Design: monthly TEST windows over 2022-12..2026-06. The RF meta-label is refit
every k months (k = 1, 3, 6, never) on the trailing 18 months (embargo = label
window). Two arms per k: plain ML and ML+veto (shorts only when gex_z<0, no longs
>0.4% above weekly max-pain). Identical bars, costs, and engine everywhere.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant.es_c11_robust import FEATURES, HOLD, prep
from quant.options_join import join_bars

PAIN = 0.004
FREQS = {"1mo": 1, "3mo": 3, "6mo": 6, "never": 10_000}


def _bt(seg: pd.DataFrame) -> dict:
    bt = seg[["open", "high", "low", "close", "volume", "signal"]].copy()
    return B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def _apply(te, keep):
    out = te.copy()
    out["signal"] = [s if i in keep else 0.0 for i, s in zip(out.index, out["signal"])]
    return out


def main():
    frame = prep(allow_shorts=True)
    frame = join_bars(frame)
    frame["gex_z"] = frame["gex_z"].fillna(0.0)
    frame = frame.dropna(subset=["d_pain", "d_call", "d_put"]).reset_index(drop=True)
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]
    start = (t0 + pd.DateOffset(months=18)).normalize()
    months = []
    cur = start
    while cur + pd.DateOffset(months=1) <= t1:
        months.append(cur)
        cur += pd.DateOffset(months=1)
    print(f"data {t0.date()}..{t1.date()} | {len(months)} monthly test windows from {start.date()}\n")

    results = {}
    for fname, k in FREQS.items():
        clf, fitted_at = None, None
        rows = []
        for mi, mstart in enumerate(months):
            if clf is None or mi - fitted_at >= k:
                tr = frame[(frame["dt"] < mstart - pd.Timedelta(hours=HOLD)) &
                           (frame["dt"] >= mstart - pd.DateOffset(months=18))]
                trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=FEATURES)
                if len(trs) < 100:
                    continue
                clf = RandomForestClassifier(n_estimators=200, max_depth=4,
                                             min_samples_leaf=50, random_state=0,
                                             n_jobs=-1, class_weight="balanced")
                clf.fit(trs[FEATURES].to_numpy(), trs["meta_label"].to_numpy())
                fitted_at = mi
            te = frame[(frame["dt"] >= mstart) & (frame["dt"] < mstart + pd.DateOffset(months=1))]
            if len(te) < 100:
                continue
            tes = te[te["signal"] != 0].dropna(subset=FEATURES)
            keep = set(tes.index[clf.predict_proba(tes[FEATURES].to_numpy())[:, 1] > 0.5])
            veto = set(i for i in keep
                       if not ((te.loc[i, "signal"] < 0 and te.loc[i, "gex_z"] >= 0) or
                               (te.loc[i, "signal"] > 0 and te.loc[i, "d_pain"] > PAIN)))
            rows.append({"m": mstart.date(),
                         "mkt": (te["close"].iloc[-1] - te["close"].iloc[0]) * B.ES.point_value / 1e5,
                         "ml": _bt(_apply(te, keep))["total_return"],
                         "veto": _bt(_apply(te, veto))["total_return"]})
        results[fname] = pd.DataFrame(rows)
        print(f"[{fname}] done: {len(rows)} months", flush=True)

    print(f"\n{'freq':7} {'arm':6} {'total%':>8} {'mean%':>7} {'pos%':>5} {'Sharpe':>7} {'maxDD%':>7}")
    for fname, R in results.items():
        for col in ["ml", "veto"]:
            r = R[col]
            eq = (1 + r).cumprod()
            dd = float((eq / eq.cummax() - 1).min())
            sh = float(r.mean() / r.std() * np.sqrt(12)) if r.std() > 0 else 0.0
            print(f"{fname:7} {col:6} {(eq.iloc[-1]-1)*100:>+7.1f} {r.mean()*100:>+6.2f} "
                  f"{(r>0).mean()*100:>4.0f}% {sh:>7.2f} {dd*100:>7.1f}")
    mk = results["3mo"]["mkt"]
    print(f"market  (same months): total {((1+mk).prod()-1)*100:+.1f}%")


if __name__ == "__main__":
    main()
