"""es_c11_regime_source.py — regime-adaptation experiment B: HMM vs EMA regime.

Four arms through the same rolling-origin C11+ML harness (quarterly tests,
18mo train, RF meta-label refit per quarter):

  ema         control — C11's EMA-crossover MTF regime (the promoted setup)
  hmm_static  regime/h4/daily REPLACED by a 3-state Gaussian HMM fit ONCE on the
              18 months preceding the first test window, decoded causally
  hmm_feat    EMA regime kept; HMM filtered state + bull/bear posteriors added
              as ML FEATURES (regime info, no hard gate)
  hmm_refit   HMM REFIT each quarter on the trailing 18mo (regime-model
              adaptation — the 'retrain the detector in real time' arm)

HMM causality: fit train-only, forward-filtered decode (state t sees obs 1..t).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant import regime_hmm as HMM
from quant import strategy_c11 as C11
from quant.es_c11_robust import FEATURES, HOLD, load_all_15m

COST_FRAC = 0.0006
HMM_FEATS = ["hmm_reg", "hmm_p_bull", "hmm_p_bear"]


def _decode_fast(model, close: np.ndarray):
    """Vectorized causal forward filter (same math as HMM.decode_causal)."""
    X = HMM._obs(close)
    Xf = np.where(np.isnan(X), np.nanmean(X, axis=0), X)
    logB = model._compute_log_likelihood(Xf)
    log_A = np.log(model.transmat_ + 1e-12)
    T, S = logB.shape
    log_alpha = np.empty((T, S))
    log_alpha[0] = np.log(model.startprob_ + 1e-12) + logB[0]
    for t in range(1, T):
        log_alpha[t] = logsumexp(log_alpha[t - 1][:, None] + log_A, axis=0) + logB[t]
    post = np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))
    return np.argmax(post, axis=1), post


def _finish(frame: pd.DataFrame) -> pd.DataFrame:
    """sleeves + combined signal + meta-label on a frame with regime cols set."""
    frame = C11.sleeve_signals(frame)
    sig = C11.combine_to_signal(frame, allow_shorts=True).to_numpy()
    c = frame["close"].to_numpy()
    fwd = np.full(len(c), np.nan)
    fwd[:-16] = (c[16:] - c[:-16]) / c[:-16]
    frame = frame.reset_index(drop=True)
    frame["signal"] = sig
    frame["meta_label"] = ((fwd * np.sign(sig) - COST_FRAC) > 0).astype(int)
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    return frame


def _bt(seg):
    bt = seg[["open", "high", "low", "close", "volume", "signal"]].copy()
    return B.run_backtest(bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def _roll(frame: pd.DataFrame, feats: list[str], label: str) -> pd.DataFrame:
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]
    cur = (t0 + pd.DateOffset(months=18)).normalize()
    rows = []
    while cur + pd.DateOffset(months=3) <= t1:
        tr = frame[(frame["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                   (frame["dt"] >= cur - pd.DateOffset(months=18))]
        te = frame[(frame["dt"] >= cur) & (frame["dt"] < cur + pd.DateOffset(months=3))]
        trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=feats)
        if len(te) < 200 or len(trs) < 100:
            cur += pd.DateOffset(months=3); continue
        clf = RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                     random_state=0, n_jobs=-1, class_weight="balanced")
        clf.fit(trs[feats].to_numpy(), trs["meta_label"].to_numpy())
        tes = te[te["signal"] != 0].dropna(subset=feats)
        keep = set(tes.index[clf.predict_proba(tes[feats].to_numpy())[:, 1] > 0.5])
        out = te.copy()
        out["signal"] = [s if i in keep else 0.0 for i, s in zip(out.index, out["signal"])]
        m = _bt(out)
        rows.append({"q": cur.date(), "ret": m["total_return"], "tr": m["n_trades"],
                     "mkt": (te["close"].iloc[-1] - te["close"].iloc[0]) * B.ES.point_value / 1e5})
        cur += pd.DateOffset(months=3)
    R = pd.DataFrame(rows)
    print(f"[{label}] {len(R)} quarters done", flush=True)
    return R


def main():
    bars = load_all_15m()
    base = C11.add_regime(bars)
    base = C11.add_features(base)
    close = base["close"].to_numpy()
    dt = pd.DatetimeIndex(base["ts"])
    first_test = (dt[0] + pd.DateOffset(months=18)).normalize()
    fit_mask = dt < first_test

    arms = {}

    # --- ema control
    arms["ema"] = (_finish(base.copy()), FEATURES)

    # --- hmm_static: replace regime columns, refit sleeves
    model, sign = HMM.fit(close[fit_mask], n_states=3, seed=0)
    states, post = _decode_fast(model, close)
    reg = np.array([sign.get(int(s), 0) for s in states], dtype=float)
    f = base.copy()
    f["regime"] = reg; f["h4_sig"] = reg; f["daily_sig"] = reg
    arms["hmm_static"] = (_finish(f), FEATURES)

    # --- hmm_feat: EMA sleeves + HMM columns as ML features
    order = np.argsort(model.means_[:, 0])
    f = base.copy()
    f["hmm_reg"] = reg
    f["hmm_p_bear"] = post[:, order[0]]
    f["hmm_p_bull"] = post[:, order[-1]]
    arms["hmm_feat"] = (_finish(f), FEATURES + HMM_FEATS)

    # --- hmm_refit: refit per quarter on trailing 18mo, decode causally, stitch regime
    reg_r = np.full(len(close), np.nan)
    cur = first_test
    t1 = dt[-1]
    while cur <= t1:
        trm = (dt < cur) & (dt >= cur - pd.DateOffset(months=18))
        tem = (dt >= cur) & (dt < cur + pd.DateOffset(months=3))
        if trm.sum() > 2000 and tem.sum() > 0:
            m_q, s_q = HMM.fit(close[trm], n_states=3, seed=0)
            # decode from series start for a proper filtered state at the quarter
            st_q, _ = _decode_fast(m_q, close[: np.where(tem)[0][-1] + 1])
            sl = np.where(tem)[0]
            reg_r[sl] = [s_q.get(int(s), 0) for s in st_q[sl]]
        cur += pd.DateOffset(months=3)
    f = base.copy()
    reg_r = pd.Series(reg_r).fillna(0.0).to_numpy()
    f["regime"] = reg_r; f["h4_sig"] = reg_r; f["daily_sig"] = reg_r
    arms["hmm_refit"] = (_finish(f), FEATURES)

    print(f"bars {len(base)} | first test {first_test.date()}\n", flush=True)
    print(f"{'arm':12} {'total%':>8} {'mean%':>7} {'pos%':>5} {'Sharpe':>7} {'maxDD%':>7} {'trades':>7}")
    for name, (frame, feats) in arms.items():
        R = _roll(frame, feats, name)
        r = R["ret"]
        eq = (1 + r).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        sh = float(r.mean() / r.std() * np.sqrt(4)) if r.std() > 0 else 0.0
        print(f"{name:12} {(eq.iloc[-1]-1)*100:>+7.1f} {r.mean()*100:>+6.2f} "
              f"{(r>0).mean()*100:>4.0f}% {sh:>7.2f} {dd*100:>7.1f} {int(R['tr'].sum()):>7}")


if __name__ == "__main__":
    main()
