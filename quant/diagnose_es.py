"""diagnose_es.py — dissect the baseline null: bug, or genuine no-edge?

Checks, layer by layer:
  1. Data sanity — ES price range + buy-and-hold (is the series even tradeable / trending?)
  2. Feature sanity — composite_smooth distribution (does it ever reach the zone thresholds?)
  3. Signal counts per mode/threshold (is the signal firing a sane number of times?)
  4. Concrete backtests at MODERATE fixed params — long-only vs both-directions vs buy&hold
     (does trading actually lose, and WHY — trend-fighting?)
  5. Sample trades (sign/PnL sanity).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from quant import backtest as B
from quant import es_baseline as E
from quant import features as F
from quant import strategy as S


def main():
    bars = E.load_staged()
    pdf = bars.to_pandas()
    c = pdf["close"]
    print("=== 1. DATA SANITY ===")
    print(f"bars={len(pdf)}  {pdf['ts'].iloc[0]} .. {pdf['ts'].iloc[-1]}")
    print(f"close range: {c.min():.1f} .. {c.max():.1f}  first={c.iloc[0]:.1f} last={c.iloc[-1]:.1f}")
    bh = (c.iloc[-1] / c.iloc[0] - 1) * 100
    bh_dollars = (c.iloc[-1] - c.iloc[0]) * B.ES.point_value
    print(f"buy&hold: {bh:+.1f}%  (1 contract = ${bh_dollars:,.0f} on $100k = {bh_dollars/1000:+.1f}%)")

    feat = F.make_price_features(bars)
    fpd = feat.to_pandas()
    cs = fpd["composite_smooth"].dropna()
    print("\n=== 2. FEATURE SANITY: composite_smooth ===")
    print(f"count={len(cs)} mean={cs.mean():+.3f} std={cs.std():.3f} "
          f"min={cs.min():+.3f} max={cs.max():+.3f}")
    for q in (0.01, 0.05, 0.10, 0.50, 0.90, 0.95, 0.99):
        print(f"  q{int(q*100):02d} = {cs.quantile(q):+.3f}", end="")
    print()
    for thr in (0.1, 0.2, 0.3, 0.4, 0.5):
        frac = float((cs.abs() > thr).mean())
        print(f"  |composite|>{thr}: {frac*100:5.1f}% of bars")

    print("\n=== 3. SIGNAL COUNTS (per mode, osc_thr=0.2, vel_eps=0.01) ===")
    for mode in S.MODES:
        sig = S.make_signal(feat, mode=mode, osc_thr=0.2, vel_eps=0.01, direction="both")
        s = sig.to_pandas()["signal"]
        print(f"  {mode:18s}: longs={int((s>0).sum())} shorts={int((s<0).sum())}")

    print("\n=== 4. BACKTESTS at fixed moderate params (sl=40, tp=60) ===")
    sig = S.make_signal(feat, mode="zone_reversal", osc_thr=0.2, vel_eps=0.01, direction="both")
    for dirn, sg in [("both", sig),
                     ("long_only", S.make_signal(feat, mode="zone_reversal", osc_thr=0.2,
                                                 vel_eps=0.01, direction="long")),
                     ("short_only", S.make_signal(feat, mode="zone_reversal", osc_thr=0.2,
                                                  vel_eps=0.01, direction="short"))]:
        r = B.run_backtest(sg, contract=B.ES, entry_mode="next_bar_open",
                           stop_loss_pts=40, take_profit_pts=60, slippage_ticks=1, min_bars_between=2)
        m = r["metrics"]
        print(f"  zone_reversal {dirn:10s}: trades={m['n_trades']:>3} ret={m['total_return']*100:+.2f}% "
              f"win={m['win_rate']*100:.0f}% PF={m['profit_factor']:.2f} maxDD={m['max_drawdown']*100:.1f}%")

    # trend-follow flip: enter WITH the velocity (long on up-cross regardless of zone)
    sig_tf = S.make_signal(feat, mode="velocity_crossover", osc_thr=0.0, vel_eps=0.01, direction="long")
    r = B.run_backtest(sig_tf, contract=B.ES, entry_mode="next_bar_open",
                       stop_loss_pts=40, take_profit_pts=80, slippage_ticks=1, min_bars_between=2)
    m = r["metrics"]
    print(f"  velocity_crossover long-only: trades={m['n_trades']} ret={m['total_return']*100:+.2f}% "
          f"win={m['win_rate']*100:.0f}% PF={m['profit_factor']:.2f}")

    print("\n=== 5. SAMPLE TRADES (zone_reversal both) — PnL sign check ===")
    r = B.run_backtest(sig, contract=B.ES, entry_mode="next_bar_open",
                       stop_loss_pts=40, take_profit_pts=60, slippage_ticks=1, min_bars_between=2)
    for t in r["trades"][:6]:
        print(f"  dir={t['dir']:+d} entry={t['entry_px']:.2f} exit={t['exit_px']:.2f} "
              f"reason={t['reason']:11s} pnl=${t['pnl']:+.0f} bars={t['bars_held']}")
    print(f"  ... total {len(r['trades'])} trades")


if __name__ == "__main__":
    main()
