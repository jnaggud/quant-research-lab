"""es_options_levels_signal.py — turn the option-level edges into a tradeable signal
and test it OOS through the cost-aware backtest engine.

Signal (from the OOS-stable findings in options_bands):
  LONG  near the PUT wall (support) or well BELOW max-pain (pinned up)
  SHORT near the CALL wall (resistance) or well ABOVE max-pain (pinned down)
Optionally gated by price stretch (only act when z confirms).

Honest read: holdout backtest with 1-tick slippage + commission, vs buy&hold, plus a
rolling-origin walk-forward so it isn't one lucky split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant import backtest as B
from quant.options_bands import build


def make_signal(m, near=0.003, pain=0.004, stretch_gate=0.0):
    dput, dcall, dpain, z = m["d_put"], m["d_call"], m["d_pain"], m["z"]
    long = (dput.abs() < near) | (dpain < -pain)
    short = (dcall.abs() < near) | (dpain > pain)
    if stretch_gate > 0:
        long = long & (z <= -stretch_gate)
        short = short & (z >= stretch_gate)
    return np.where(long & ~short, 1.0, np.where(short & ~long, -1.0, 0.0))


def _bt(seg, sig):
    b = seg[["open", "high", "low", "close", "volume"]].copy()
    b["signal"] = sig
    return B.run_backtest(b, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=40.0, take_profit_pts=40.0, trailing_pts=None,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def main():
    m = build().reset_index(drop=True)
    cut = int(len(m) * 0.6)
    bh = (m["close"].iloc[-1] - m["close"].iloc[cut]) * B.ES.point_value / 1e5
    print(f"merged bars {len(m)} | holdout buy&hold {bh*100:+.1f}%\n")

    print("=== HOLDOUT backtests of option-level signals ===")
    print(f"{'variant':40} {'OOS%':>8} {'trades':>7} {'win':>5} {'PF':>6}")
    variants = {
        "walls+pain (no gate)": dict(),
        "walls+pain + stretch gate 1.0": dict(stretch_gate=1.0),
        "walls+pain + stretch gate 1.5": dict(stretch_gate=1.5),
        "put-wall LONG only": "putlong",
    }
    for name, kw in variants.items():
        if kw == "putlong":
            sig = np.where(m["d_put"].abs() < 0.003, 1.0, 0.0)
        else:
            sig = make_signal(m, **kw)
        mo = _bt(m.iloc[cut:], sig[cut:])
        print(f"{name:40} {mo['total_return']*100:>+7.1f} {mo['n_trades']:>7} "
              f"{mo['win_rate']*100:>4.0f}% {mo['profit_factor']:>5.2f}")

    # rolling-origin walk-forward on the best (gated) signal
    print("\n=== ROLLING-ORIGIN (gate 1.0), quarterly blocks ===")
    sig = make_signal(m, stretch_gate=1.0)
    m2 = m.copy(); m2["signal"] = sig
    step = 2000
    rows = []
    i = 6000
    while i + step <= len(m2):
        seg = m2.iloc[i:i + step]
        mo = _bt(seg, seg["signal"].to_numpy())
        mk = (seg["close"].iloc[-1] - seg["close"].iloc[0]) * B.ES.point_value / 1e5
        rows.append({"strat": mo["total_return"], "mkt": mk, "trades": mo["n_trades"]})
        i += step
    R = pd.DataFrame(rows)
    print(f"blocks {len(R)} | strat mean {R['strat'].mean()*100:+.2f}% | "
          f"blocks positive {(R['strat']>0).mean()*100:.0f}% | "
          f"strat total {(np.prod(1+R['strat'])-1)*100:+.1f}% vs mkt {(np.prod(1+R['mkt'])-1)*100:+.1f}%")


if __name__ == "__main__":
    main()
