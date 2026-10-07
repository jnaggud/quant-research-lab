"""es_c11_gex_filter.py — options-structure REGIME FILTERS on the C11 signal.

Instead of trading option levels outright (rejected: edges are bps-sized), test
whether they improve the promoted C11 strategy as vetoes/gates. Variants come
straight from the sign-stable raw edges in es_options_weekly_signal:

  wall-veto : cancel longs at the call wall, shorts at the put wall
  pain-veto : cancel longs stretched ABOVE weekly max-pain, shorts below
  gex-shorts: allow core shorts only in negative-gamma tape (gex_z < 0)
  flip-side : allow shorts only below the gamma flip
  combo     : wall-veto + pain-veto

Honest test: rolling ~quarterly windows over the full 2021-2026 span (base vs
filtered on identical bars), plus compounded risk-adjusted stats. Windows are
backtested in PARALLEL across all cores.
"""
from __future__ import annotations

import multiprocessing as mp

import numpy as np
import pandas as pd

from quant import backtest as B
from quant.es_c11_robust import load_all_15m, prep
from quant.options_join import join_bars

NEAR = 0.003
PAIN = 0.004


def variants(m: pd.DataFrame) -> dict[str, np.ndarray]:
    sig = m["signal"].to_numpy().copy()
    at_call = m["d_call"].abs().to_numpy() < NEAR
    at_put = m["d_put"].abs().to_numpy() < NEAR
    above_pain = m["d_pain"].to_numpy() > PAIN
    below_pain = m["d_pain"].to_numpy() < -PAIN
    neg_gex = m["gex_z"].to_numpy() < 0
    below_flip = m["d_flip"].to_numpy() < 0

    out = {"base": sig}
    v = sig.copy(); v[(v > 0) & at_call] = 0; v[(v < 0) & at_put] = 0
    out["wall-veto"] = v
    v = sig.copy(); v[(v > 0) & above_pain] = 0; v[(v < 0) & below_pain] = 0
    out["pain-veto"] = v
    v = sig.copy(); v[(v < 0) & ~neg_gex] = 0
    out["gex-shorts"] = v
    v = sig.copy(); v[(v < 0) & ~below_flip] = 0
    out["flip-side"] = v
    v = out["wall-veto"].copy(); v[(v > 0) & above_pain] = 0; v[(v < 0) & below_pain] = 0
    out["combo"] = v
    return out


def _bt_args(args):
    seg_ohlcv, sig = args
    b = seg_ohlcv.copy()
    b["signal"] = sig
    m = B.run_backtest(b, contract=B.ES, entry_mode="next_bar_open", direction="both",
                       stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
                       slippage_ticks=1.0, min_bars_between=2)["metrics"]
    return m["total_return"], m["n_trades"]


def main():
    frame = prep(allow_shorts=True)
    m = join_bars(frame)
    m = m.dropna(subset=["d_call", "d_put", "d_pain"]).reset_index(drop=True)
    m["gex_z"] = m["gex_z"].fillna(0.0)
    m["d_flip"] = m["d_flip"].fillna(0.0)
    sigs = variants(m)
    print(f"bars {len(m)} | base signal bars: {(sigs['base']!=0).sum()} "
          f"(long {(sigs['base']>0).sum()}, short {(sigs['base']<0).sum()})")
    for k, v in sigs.items():
        if k != "base":
            print(f"  {k:10} removes {(v==0).sum()-(sigs['base']==0).sum():5d} signal bars")

    # quarterly windows
    step = 2000
    starts = list(range(6000, len(m) - step + 1, step))
    ohlcv = m[["open", "high", "low", "close", "volume"]]
    jobs, keys = [], []
    for name, sig in sigs.items():
        for i in starts:
            jobs.append((ohlcv.iloc[i:i + step], sig[i:i + step]))
            keys.append((name, i))
    with mp.Pool(min(mp.cpu_count(), len(jobs))) as pool:
        res = pool.map(_bt_args, jobs, chunksize=4)

    R = pd.DataFrame([{"variant": k[0], "i": k[1], "ret": r[0], "trades": r[1]}
                      for k, r in zip(keys, res)])
    mkt = [(ohlcv["close"].iloc[i + step - 1] - ohlcv["close"].iloc[i]) * B.ES.point_value / 1e5
           for i in starts]
    print(f"\nwindows {len(starts)} | market total {(np.prod(1+np.array(mkt))-1)*100:+.1f}%")
    print(f"{'variant':12} {'total%':>8} {'mean%':>7} {'pos%':>5} {'Sharpe':>7} {'maxDD%':>7} {'trades':>7}")
    for name in sigs:
        r = R[R["variant"] == name].sort_values("i")["ret"]
        eq = (1 + r).cumprod()
        dd = float((eq / eq.cummax() - 1).min())
        sh = float(r.mean() / r.std() * np.sqrt(4)) if r.std() > 0 else 0.0
        print(f"{name:12} {(eq.iloc[-1]-1)*100:>+7.1f} {r.mean()*100:>+6.2f} "
              f"{(r>0).mean()*100:>4.0f}% {sh:>7.2f} {dd*100:>7.1f} "
              f"{int(R[R['variant']==name]['trades'].sum()):>7}")


if __name__ == "__main__":
    main()
