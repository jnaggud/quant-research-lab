"""es_c11_options_ml.py — do options-structure features improve C11+ML?

The C11 system's edge lives in the ML meta-label (the raw sleeves with round
defaults are negative over 2021-2026), so options ideas must be tested ON TOP of
C11+ML, not the raw signal. Rolling-origin walk-forward (the es_c11_robust
harness): train 1.5y, test next quarter, roll 2021->2026. Per quarter we fit:

  ml        RandomForest on the original 13 features (control)
  ml+opt    same + 9 options-structure features (weekly walls, pain, GEX, IV)
  ml+veto   control ML, then hard sign-stable vetoes (shorts only in neg-gamma
            tape; no longs stretched above weekly max-pain)

RF fits use n_jobs=-1 (all cores). Leakage: options features joined next-session
(options_join), embargo = label window, per-quarter fit on train only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant.es_c11_robust import FEATURES, HOLD, prep
from quant.options_join import join_bars

OPT_FEATS = ["d_pain", "d_call", "d_put", "d_flip", "gex_z",
             "atm_iv", "iv_skew", "pcr_vol", "iv_ratio"]
PAIN = 0.004


def _bt(seg: pd.DataFrame) -> dict:
    bt = seg[["open", "high", "low", "close", "volume", "signal"]].copy()
    return B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def _rf():
    return RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                  random_state=0, n_jobs=-1, class_weight="balanced")


def _apply(te: pd.DataFrame, keep_idx: set) -> pd.DataFrame:
    out = te.copy()
    out["signal"] = [s if i in keep_idx else 0.0 for i, s in zip(out.index, out["signal"])]
    return out


def main():
    frame = prep(allow_shorts=True)
    frame = join_bars(frame)
    frame["gex_z"] = frame["gex_z"].fillna(0.0)
    frame["d_flip"] = frame["d_flip"].fillna(0.0)
    frame = frame.dropna(subset=["d_pain", "d_call", "d_put"]).reset_index(drop=True)
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]
    print(f"data {t0.date()} .. {t1.date()}  ({len(frame)} 15m bars)\n")

    train_years, test = 1.5, pd.DateOffset(months=3)
    cur = (t0 + pd.DateOffset(months=int(train_years * 12))).normalize()
    rows = []
    while cur + test <= t1:
        tr = frame[(frame["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                   (frame["dt"] >= cur - pd.DateOffset(months=int(train_years * 12)))]
        te = frame[(frame["dt"] >= cur) & (frame["dt"] < cur + test)]
        if len(te) < 200 or len(tr) < 2000:
            cur += test; continue
        trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=FEATURES + OPT_FEATS)
        if len(trs) < 100:
            cur += test; continue
        bh = (te["close"].iloc[-1] - te["close"].iloc[0]) * B.ES.point_value / 1e5
        tes = te[te["signal"] != 0].dropna(subset=FEATURES + OPT_FEATS)

        res = {"q": cur.date(), "mkt": bh}
        for name, feats in [("ml", FEATURES), ("ml_opt", FEATURES + OPT_FEATS)]:
            clf = _rf()
            clf.fit(trs[feats].to_numpy(), trs["meta_label"].to_numpy())
            keep = set(tes.index[clf.predict_proba(tes[feats].to_numpy())[:, 1] > 0.5])
            if name == "ml":
                keep_ml = keep
                imp_ml = clf
            m = _bt(_apply(te, keep))
            res[name], res[name + "_tr"] = m["total_return"], m["n_trades"]
        # hard vetoes on top of control ML
        veto = set(i for i in keep_ml
                   if not ((te.loc[i, "signal"] < 0 and te.loc[i, "gex_z"] >= 0) or
                           (te.loc[i, "signal"] > 0 and te.loc[i, "d_pain"] > PAIN)))
        m = _bt(_apply(te, veto))
        res["ml_veto"], res["ml_veto_tr"] = m["total_return"], m["n_trades"]
        rows.append(res)
        cur += test

    R = pd.DataFrame(rows)
    print(f"{'quarter':12} {'mkt%':>7} {'ml%':>7} {'ml+opt%':>8} {'ml+veto%':>9} {'tr':>4}")
    for _, r in R.iterrows():
        print(f"{str(r['q']):12} {r['mkt']*100:>+6.1f} {r['ml']*100:>+6.1f} "
              f"{r['ml_opt']*100:>+7.1f} {r['ml_veto']*100:>+8.1f} {int(r['ml_opt_tr']):>4}")
    print("-" * 55)
    down = R[R["mkt"] < 0]
    print(f"{'series':10} {'total%':>8} {'mean%':>7} {'pos%':>5} {'Sharpe':>7} {'maxDD%':>7} {'downQ+':>7}")
    for col in ["mkt", "ml", "ml_opt", "ml_veto"]:
        r = R[col]
        eq = (1 + r).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        sh = float(r.mean() / r.std() * np.sqrt(4)) if r.std() > 0 else 0.0
        dq = f"{(down[col]>0).sum()}/{len(down)}" if len(down) else "-"
        print(f"{col:10} {(eq.iloc[-1]-1)*100:>+7.1f} {r.mean()*100:>+6.2f} "
              f"{(r>0).mean()*100:>4.0f}% {sh:>7.2f} {dd*100:>7.1f} {dq:>7}")

    # what the options-aware model leaned on (last quarter's fit)
    clf = _rf().fit(trs[FEATURES + OPT_FEATS].to_numpy(), trs["meta_label"].to_numpy())
    imp = sorted(zip(FEATURES + OPT_FEATS, clf.feature_importances_), key=lambda x: -x[1])
    print("\ntop features (last train window):", [(f, round(v, 3)) for f, v in imp[:8]])
    opt_share = sum(v for f, v in zip(FEATURES + OPT_FEATS, clf.feature_importances_)
                    if f in OPT_FEATS)
    print(f"options-features importance share: {opt_share:.1%}")


if __name__ == "__main__":
    main()
