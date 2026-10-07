"""es_c11_veto_robust.py — robustness of the ml+veto overlay (task from
es_options_v2_research §4): RF seed-MC + veto-threshold sensitivity grid.

1. SEED-MC: rolling quarterly ml+veto with RF seeds 0..4 — the promoted result
   must not be a lucky seed (gate: >=75% of seeds positive total, median > control).
2. GRID: gex_z short-gate cut in {-0.5, 0, +0.5, off} x pain long-veto in
   {0.2%, 0.4%, 0.8%, off}, applied POST-ML (seed 0) — the chosen (0, 0.4%) cell
   must sit on a plateau, not a spike.

Backtests fan out across all cores.
"""
from __future__ import annotations

import multiprocessing as mp

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant.es_c11_robust import FEATURES, HOLD, prep
from quant.options_join import join_bars

GEX_CUTS = [-0.5, 0.0, 0.5, None]
PAIN_CUTS = [0.002, 0.004, 0.008, None]


def _bt_job(args):
    seg, sig = args
    b = seg.copy()
    b["signal"] = sig
    m = B.run_backtest(b, contract=B.ES, entry_mode="next_bar_open", direction="both",
                       stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                       slippage_ticks=1.0, min_bars_between=2)["metrics"]
    return m["total_return"]


def main():
    frame = prep(allow_shorts=True)
    frame = join_bars(frame)
    frame["gex_z"] = frame["gex_z"].fillna(0.0)
    frame = frame.dropna(subset=["d_pain", "d_call", "d_put"]).reset_index(drop=True)
    frame["dt"] = pd.DatetimeIndex(frame["ts"])
    t0, t1 = frame["dt"].iloc[0], frame["dt"].iloc[-1]

    # collect per-quarter (te, proba-per-seed) once
    quarters = []
    cur = (t0 + pd.DateOffset(months=18)).normalize()
    while cur + pd.DateOffset(months=3) <= t1:
        tr = frame[(frame["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                   (frame["dt"] >= cur - pd.DateOffset(months=18))]
        te = frame[(frame["dt"] >= cur) & (frame["dt"] < cur + pd.DateOffset(months=3))]
        trs = tr[(tr["signal"] != 0) & tr["meta_label"].notna()].dropna(subset=FEATURES)
        if len(te) >= 200 and len(trs) >= 100:
            quarters.append((cur, trs, te))
        cur += pd.DateOffset(months=3)
    print(f"{len(quarters)} quarters", flush=True)

    # fit RFs (n_jobs=-1) and cache per-seed probabilities per quarter
    proba = {}          # (qi, seed) -> (tes_index, p)
    for qi, (cur, trs, te) in enumerate(quarters):
        tes = te[te["signal"] != 0].dropna(subset=FEATURES)
        X, y = trs[FEATURES].to_numpy(), trs["meta_label"].to_numpy()
        Xt = tes[FEATURES].to_numpy()
        for seed in range(5):
            clf = RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=50,
                                         random_state=seed, n_jobs=-1, class_weight="balanced")
            clf.fit(X, y)
            proba[(qi, seed)] = (tes.index, clf.predict_proba(Xt)[:, 1])
        print(f"  fitted q{qi} {cur.date()}", flush=True)

    def veto_keep(te, idx, p, gex_cut, pain_cut):
        keep = set(idx[p > 0.5])
        out = set()
        for i in keep:
            s = te.loc[i, "signal"]
            if gex_cut is not None and s < 0 and te.loc[i, "gex_z"] >= gex_cut:
                continue
            if pain_cut is not None and s > 0 and te.loc[i, "d_pain"] > pain_cut:
                continue
            out.add(i)
        return out

    # assemble all backtest jobs
    jobs, keys = [], []
    for qi, (cur, trs, te) in enumerate(quarters):
        ohlcv = te[["open", "high", "low", "close", "volume"]]
        # seed-MC at the chosen thresholds (gex 0.0, pain 0.004) + control (no veto)
        for seed in range(5):
            idx, p = proba[(qi, seed)]
            for tag, keep in [("ml", set(idx[p > 0.5])),
                              ("veto", veto_keep(te, idx, p, 0.0, 0.004))]:
                sig = np.array([s if i in keep else 0.0 for i, s in zip(te.index, te["signal"])])
                jobs.append((ohlcv, sig)); keys.append(("seed", seed, tag, qi))
        # threshold grid on seed 0
        idx, p = proba[(qi, 0)]
        for g in GEX_CUTS:
            for pc in PAIN_CUTS:
                keep = veto_keep(te, idx, p, g, pc)
                sig = np.array([s if i in keep else 0.0 for i, s in zip(te.index, te["signal"])])
                jobs.append((ohlcv, sig)); keys.append(("grid", g, pc, qi))

    print(f"{len(jobs)} backtests fanning out ...", flush=True)
    with mp.Pool(mp.cpu_count()) as pool:
        rets = pool.map(_bt_job, jobs, chunksize=8)
    R = pd.DataFrame([{"k0": k[0], "k1": k[1], "k2": k[2], "qi": k[3], "ret": r}
                      for k, r in zip(keys, rets)])

    print("\n=== SEED-MC (thresholds gex 0.0 / pain 0.4%) ===")
    print(f"{'seed':5} {'ml total%':>10} {'veto total%':>12}")
    veto_tot = []
    for seed in range(5):
        row = {}
        for tag in ("ml", "veto"):
            r = R[(R.k0 == "seed") & (R.k1 == seed) & (R.k2 == tag)].sort_values("qi")["ret"]
            row[tag] = (1 + r).prod() - 1
        veto_tot.append(row["veto"])
        print(f"{seed:5} {row['ml']*100:>+9.1f} {row['veto']*100:>+11.1f}")
    print(f"veto: median {np.median(veto_tot)*100:+.1f}% | seeds positive "
          f"{100*np.mean([v > 0 for v in veto_tot]):.0f}%")

    print("\n=== VETO THRESHOLD GRID (seed 0, compounded total %) ===")
    hdr = "".join(f"{('pain ' + format(pc*100, '.1f') + '%') if pc else 'pain off':>12}"
                  for pc in PAIN_CUTS)
    print(f"{'gex cut':10}{hdr}")
    for g in GEX_CUTS:
        cells = []
        for pc in PAIN_CUTS:
            r = R[(R.k0 == "grid") & (R.k1.isna() if g is None else (R.k1 == g)) &
                  (R.k2.isna() if pc is None else (R.k2 == pc))].sort_values("qi")["ret"]
            cells.append(f"{((1+r).prod()-1)*100:>+11.1f}")
        print(f"{('gex ' + str(g)) if g is not None else 'gex off':10}" + "".join(cells))


if __name__ == "__main__":
    main()
