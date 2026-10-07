"""viz_model.py — visual inspection of the full ES model on price action:
candles + sigma stretch-bands + option levels (call/put wall, max-pain) + signals.
Saves a PNG. Usage: python -m quant.viz_model [n_bars] [out.png]
"""
from __future__ import annotations

import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from quant.es_options_levels_signal import make_signal
from quant.options_bands import build

MA = 96


def main(n=600, out="es_model_view.png"):
    m = build().reset_index(drop=True)
    c = m["close"].astype(float)
    m["ma"] = c.rolling(MA).mean()
    m["sd"] = c.rolling(MA).std()
    m["sig"] = make_signal(m, stretch_gate=1.0)
    w = m.iloc[-int(n):].reset_index(drop=True)
    x = np.arange(len(w))

    fig, ax = plt.subplots(figsize=(20, 10))
    # sigma bands (shaded)
    for k, a in [(1, 0.06), (2, 0.05), (3, 0.04)]:
        ax.fill_between(x, w["ma"] - k * w["sd"], w["ma"] + k * w["sd"],
                        color="steelblue", alpha=a, zorder=0)
    ax.plot(x, w["ma"], color="gray", lw=1, label="MA(96)", zorder=1)

    # candles
    for i, r in w.iterrows():
        up = r["close"] >= r["open"]
        col = "#26a69a" if up else "#ef5350"
        ax.plot([i, i], [r["low"], r["high"]], color=col, lw=0.6, zorder=2)
        ax.add_patch(plt.Rectangle((i - 0.3, min(r["open"], r["close"])), 0.6,
                     max(abs(r["close"] - r["open"]), 0.25), color=col, zorder=3))

    # option levels (step lines, change daily)
    ax.plot(x, w["call_wall"], color="crimson", lw=1.3, drawstyle="steps-mid", label="call wall (resistance)", zorder=4)
    ax.plot(x, w["put_wall"], color="green", lw=1.3, drawstyle="steps-mid", label="put wall (support)", zorder=4)
    ax.plot(x, w["max_pain"], color="purple", lw=1.1, ls="--", drawstyle="steps-mid", label="max pain (magnet)", zorder=4)

    # signal markers
    lo = w[w["sig"] > 0]; sh = w[w["sig"] < 0]
    ax.scatter(lo.index, lo["low"] - 3, marker="^", color="lime", s=40, zorder=5, label="long signal")
    ax.scatter(sh.index, sh["high"] + 3, marker="v", color="red", s=40, zorder=5, label="short signal")

    # x labels = dates
    ts = pd.DatetimeIndex(w["ts"])
    ticks = np.linspace(0, len(w) - 1, 10).astype(int)
    ax.set_xticks(ticks)
    ax.set_xticklabels([ts[t].strftime("%m-%d %H:%M") for t in ticks], rotation=30, fontsize=8)
    ax.set_title(f"ES 15m — stretch bands (MA±1/2/3σ) + option levels + signals  |  {ts[0].date()} → {ts[-1].date()}", fontsize=13)
    # clip y to the price action (walls can sit at far-OTM strikes off-screen)
    lo_p, hi_p = w["low"].min(), w["high"].max()
    pad = (hi_p - lo_p) * 0.35 + 5
    ax.set_ylim(lo_p - pad, hi_p + pad)
    ax.set_ylabel("price"); ax.legend(loc="upper left", fontsize=9); ax.grid(alpha=0.15)
    fig.tight_layout(); fig.savefig(out, dpi=110)
    print(f"saved {out}  ({len(w)} bars, {ts[0]} .. {ts[-1]})")
    print(f"  long signals in window: {int((w['sig']>0).sum())}, short: {int((w['sig']<0).sum())}")


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if len(a) > 0 else 600, a[1] if len(a) > 1 else "es_model_view.png")
