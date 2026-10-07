"""es_c11_hmm.py — C11 strategy with the EMA regime REPLACED by a causal Markov
(HMM) regime. Same sleeves, same validator, same small param set — so the only
change vs es_c11_backtest is the regime source. Lets us read the OOS delta from
the Markov upgrade.

The HMM is fit on the TRAIN split only; the regime is decoded with forward
filtering (causal). Then the strategy's regime / h4_sig / daily_sig are all set
to the HMM regime and the sleeves recomputed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl

from quant import backtest as B
from quant import es_c11_backtest as BASE
from quant import regime_hmm as HMM
from quant import strategy_c11 as C11
from quant import validate as V


def build_hmm_frame(n_states: int = 3, train_frac: float = 0.6) -> pd.DataFrame:
    bars = BASE.load_15m()
    pdf = C11.add_regime(bars)          # gives ts index; we overwrite regime below
    pdf = C11.add_features(pdf)
    close = pdf["close"].to_numpy()
    cut = int(len(close) * train_frac)
    model, sign = HMM.fit(close[:cut], n_states=n_states, seed=0)
    reg = HMM.regime_series(model, sign, close)     # causal regime in {+1,0,-1}
    pdf["regime"] = reg
    pdf["h4_sig"] = reg
    pdf["daily_sig"] = reg
    pdf = C11.sleeve_signals(pdf)
    return pdf


def main():
    frame = build_hmm_frame()
    feat = pl.from_pandas(frame.reset_index(drop=True))
    n = feat.height
    print(f"ES 15m bars: {n} | HMM regime mix: {frame['regime'].value_counts().to_dict()}")

    res = V.run_validation(BASE.evaluate, BASE.SPACE, feat, embargo=200,
                           n_seeds=5, n_trials=50, inner_k=4)
    v = res["verdict"]
    print("\n=== C11 + HMM regime, OOS ===")
    print(f"median OOS = {v['median_oos']*100:+.2f}% | seed-stable = {v['pct_positive']:.0f}% | "
          f"median trades = {v['median_trades']:.0f} | train CV = {res['train_return']*100:+.2f}%")
    print(f"GATES: PASS {v['PASS']}  flags={v['flags']}")
    print("per-seed OOS:", [f"{s['oos_return']*100:+.1f}%" for s in res["mc"]["per_seed"]])


if __name__ == "__main__":
    main()
