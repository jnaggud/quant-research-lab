"""es_options_weekly_signal.py — retest the option-levels signal on WEEKLY walls.

The quarterly-wall version was rejected 2026-07-07 (walls 2-5% out, the wall legs
never fired, everything degenerated to max-pain pinning). This is the same honest
test with the weekly complex: volume walls ~1% from spot, next-session application
(no same-day settle lookahead), cost-aware engine, holdout + rolling-origin WF.

Also runs the raw edge checks (wall proximity / pain pinning) train vs holdout.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant import backtest as B
from quant.es_c11_robust import load_all_15m
from quant.options_join import join_bars

MA = 96
K = 16


def build() -> pd.DataFrame:
    m = join_bars(load_all_15m())
    c = m["close"].astype(float)
    m["z"] = (c - c.rolling(MA).mean()) / c.rolling(MA).std()
    m["fwd"] = c.shift(-K) / c - 1.0
    return m.dropna(subset=["d_call", "d_put", "d_pain", "z"]).reset_index(drop=True)


def _bt(seg, sig):
    b = seg[["open", "high", "low", "close", "volume"]].copy()
    b["signal"] = sig
    return B.run_backtest(b, contract=B.ES, entry_mode="next_bar_open", direction="both",
                          stop_loss_pts=40.0, take_profit_pts=40.0, trailing_pts=None,
                          slippage_ticks=1.0, min_bars_between=2)["metrics"]


def edges(m: pd.DataFrame):
    cut = int(len(m) * 0.6)
    tr, te = m.iloc[:cut], m.iloc[cut:]
    print("=== RAW EDGES (train | holdout), fwd 16-bar bps ===")
    for name, msk in [
        ("near CALL wall (<0.3%)", lambda d: d["d_call"].abs() < 0.003),
        ("near PUT  wall (<0.3%)", lambda d: d["d_put"].abs() < 0.003),
        ("above pain >0.4%", lambda d: d["d_pain"] > 0.004),
        ("below pain >0.4%", lambda d: d["d_pain"] < -0.004),
        ("below gamma flip", lambda d: d["d_flip"] < 0),
        ("neg GEX (gex_z<-1)", lambda d: d["gex_z"] < -1),
    ]:
        a, b_ = tr[msk(tr)], te[msk(te)]
        print(f"  {name:24} n={len(a):6d}|{len(b_):6d}  "
              f"fwd={a['fwd'].mean()*1e4:+6.1f}|{b_['fwd'].mean()*1e4:+6.1f}")
    print(f"  pain-pinning corr:      train {tr['fwd'].corr(tr['d_pain']):+.3f} | "
          f"holdout {te['fwd'].corr(te['d_pain']):+.3f}")


def make_signal(m, near=0.003, pain=0.004, stretch_gate=0.0):
    long = (m["d_put"].abs() < near) | (m["d_pain"] < -pain)
    short = (m["d_call"].abs() < near) | (m["d_pain"] > pain)
    if stretch_gate > 0:
        long = long & (m["z"] <= -stretch_gate)
        short = short & (m["z"] >= stretch_gate)
    return np.where(long & ~short, 1.0, np.where(short & ~long, -1.0, 0.0))


def main():
    m = build()
    cut = int(len(m) * 0.6)
    bh = (m["close"].iloc[-1] - m["close"].iloc[cut]) * B.ES.point_value / 1e5
    print(f"merged bars {len(m)} | holdout buy&hold {bh*100:+.1f}%\n")
    edges(m)

    print("\n=== HOLDOUT backtests (weekly walls, next-session levels) ===")
    print(f"{'variant':40} {'OOS%':>8} {'trades':>7} {'win':>5} {'PF':>6}")
    variants = {
        "walls+pain (no gate)": dict(),
        "walls+pain + stretch gate 1.0": dict(stretch_gate=1.0),
        "walls only (no pain)": "walls",
        "wall-bounce long only": "putlong",
    }
    for name, kw in variants.items():
        if kw == "walls":
            sig = np.where(m["d_put"].abs() < 0.003, 1.0,
                           np.where(m["d_call"].abs() < 0.003, -1.0, 0.0))
        elif kw == "putlong":
            sig = np.where(m["d_put"].abs() < 0.003, 1.0, 0.0)
        else:
            sig = make_signal(m, **kw)
        mo = _bt(m.iloc[cut:], sig[cut:])
        print(f"{name:40} {mo['total_return']*100:>+7.1f} {mo['n_trades']:>7} "
              f"{mo['win_rate']*100:>4.0f}% {mo['profit_factor']:>5.2f}")

    print("\n=== ROLLING-ORIGIN (no gate), ~quarterly blocks ===")
    sig = make_signal(m)
    step = 2000
    rows, i = [], 6000
    while i + step <= len(m):
        seg = m.iloc[i:i + step]
        mo = _bt(seg, sig[i:i + step])
        mk = (seg["close"].iloc[-1] - seg["close"].iloc[0]) * B.ES.point_value / 1e5
        rows.append({"strat": mo["total_return"], "mkt": mk})
        i += step
    R = pd.DataFrame(rows)
    print(f"blocks {len(R)} | positive {(R['strat']>0).mean()*100:.0f}% | "
          f"total {(np.prod(1+R['strat'])-1)*100:+.1f}% vs mkt {(np.prod(1+R['mkt'])-1)*100:+.1f}%")


if __name__ == "__main__":
    main()
