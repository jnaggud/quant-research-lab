"""es_c11_regime_params.py — regime experiments C+D: per-regime parameter banks
and the regime-feature ablation.

C: does a PER-REGIME ML probability threshold (fit train-only via inner
chronological CV) beat the fixed global 0.5? Three arms isolate the effect:
   glob0.5      control (promoted setup)
   glob_tuned   ONE threshold tuned by inner CV  -> does tuning help at all?
   per_regime   a threshold PER regime {-1,0,+1} -> does regime-conditioning add?

D: ablation — RF trained WITHOUT the regime features (regime, h4_sig, daily_sig).
If performance holds, the RF's regime-awareness is redundant; if it drops, the
meta-label already conditions on regime implicitly (and explicit param banks are
double-dipping).

Rolling-origin quarterly harness, identical to es_c11_options_ml.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant.es_c11_robust import FEATURES, HOLD, prep

COST_FRAC = 0.0006
GRID = [0.40, 0.45, 0.50, 0.55, 0.60]
NOREG = [f for f in FEATURES if f not in ("regime", "h4_sig", "daily_sig")]


def _bt(seg):
    bt = seg[["open", "high", "low", "close", "volume", "signal"]].copy()
    return B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def _apply(te, keep):
    out = te.copy()
    out["signal"] = [s if i in keep else 0.0 for i, s in zip(out.index, out["signal"])]
    return out


def _rf(seed=0):
    return RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                  random_state=seed, n_jobs=-1, class_weight="balanced")


def _tune(trs: pd.DataFrame, feats: list[str], by_regime: bool) -> dict:
    """Inner 4-fold chronological CV on train signal rows -> threshold(s).
    Objective: summed net forward pnl (fwd*sign - cost) of taken signals."""
    n = len(trs)
    folds = np.array_split(np.arange(n), 4)
    scores = {}          # (regime_or_None, theta) -> list of fold scores
    for k in range(4):
        val = folds[k]
        fit = np.concatenate([folds[j] for j in range(4) if j != k])
        a, b = trs.iloc[fit], trs.iloc[val]
        clf = _rf().fit(a[feats].to_numpy(), a["meta_label"].to_numpy())
        p = clf.predict_proba(b[feats].to_numpy())[:, 1]
        pnl = (b["fwd_net"]).to_numpy()
        regs = b["regime"].to_numpy()
        for th in GRID:
            take = p > th
            keys = [(None, th)] + ([(r, th) for r in (-1.0, 0.0, 1.0)] if by_regime else [])
            for key in keys:
                msk = take if key[0] is None else (take & (regs == key[0]))
                scores.setdefault(key, []).append(pnl[msk].sum())
    if not by_regime:
        best = max(GRID, key=lambda th: np.mean(scores[(None, th)]))
        return {None: best}
    return {r: max(GRID, key=lambda th: np.mean(scores[(r, th)]))
            for r in (-1.0, 0.0, 1.0)}


def main():
    frame = prep(allow_shorts=True)
    c = frame["close"].to_numpy()
    fwd = np.full(len(c), np.nan)
    fwd[:-HOLD] = (c[HOLD:] - c[:-HOLD]) / c[:-HOLD]
    frame["fwd_net"] = fwd * np.sign(frame["signal"].to_numpy()) - COST_FRAC
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]

    cur = (t0 + pd.DateOffset(months=18)).normalize()
    rows = []
    while cur + pd.DateOffset(months=3) <= t1:
        tr = frame[(frame["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                   (frame["dt"] >= cur - pd.DateOffset(months=18))]
        te = frame[(frame["dt"] >= cur) & (frame["dt"] < cur + pd.DateOffset(months=3))]
        trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=FEATURES + ["fwd_net"])
        if len(te) < 200 or len(trs) < 100:
            cur += pd.DateOffset(months=3); continue
        res = {"q": cur.date()}

        clf = _rf().fit(trs[FEATURES].to_numpy(), trs["meta_label"].to_numpy())
        tes = te[te["signal"] != 0].dropna(subset=FEATURES)
        p = clf.predict_proba(tes[FEATURES].to_numpy())[:, 1]

        res["glob0.5"] = _bt(_apply(te, set(tes.index[p > 0.5])))["total_return"]

        th_g = _tune(trs, FEATURES, by_regime=False)[None]
        res["glob_tuned"] = _bt(_apply(te, set(tes.index[p > th_g])))["total_return"]
        res["th_g"] = th_g

        th_r = _tune(trs, FEATURES, by_regime=True)
        regs = tes["regime"].to_numpy()
        thr = np.array([th_r.get(r, 0.5) for r in regs])
        res["per_regime"] = _bt(_apply(te, set(tes.index[p > thr])))["total_return"]
        res["th_r"] = tuple(th_r.values())

        clf2 = _rf().fit(trs[NOREG].to_numpy(), trs["meta_label"].to_numpy())
        tes2 = te[te["signal"] != 0].dropna(subset=NOREG)
        p2 = clf2.predict_proba(tes2[NOREG].to_numpy())[:, 1]
        res["no_regime_feats"] = _bt(_apply(te, set(tes2.index[p2 > 0.5])))["total_return"]

        rows.append(res)
        print(f"  {res['q']} th_g={res['th_g']:.2f} th_r={res['th_r']}", flush=True)
        cur += pd.DateOffset(months=3)

    R = pd.DataFrame(rows)
    print(f"\n{'arm':16} {'total%':>8} {'mean%':>7} {'pos%':>5} {'Sharpe':>7} {'maxDD%':>7}")
    for col in ["glob0.5", "glob_tuned", "per_regime", "no_regime_feats"]:
        r = R[col]
        eq = (1 + r).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        sh = float(r.mean() / r.std() * np.sqrt(4)) if r.std() > 0 else 0.0
        print(f"{col:16} {(eq.iloc[-1]-1)*100:>+7.1f} {r.mean()*100:>+6.2f} "
              f"{(r>0).mean()*100:>4.0f}% {sh:>7.2f} {dd*100:>7.1f}")


if __name__ == "__main__":
    main()
