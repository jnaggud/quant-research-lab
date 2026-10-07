"""es_c11_backtest.py — honest OOS backtest of the C11 multi-sleeve strategy on
ES 15m, in three escalating versions:

  base : the ported sleeves + EMA-crossover regime (the Pine architecture).
  +hmm : EMA regime replaced/augmented by a Markov (HMM) regime (quant.regime_hmm).
  +ml  : an ML meta-label that learns which sleeve signals to take.

Every version runs through the SAME validator (chrono split + inner-CV + seed-MC +
3 gates), so the comparison is leakage-safe and the numbers are believable. We
optimize only a SMALL parameter set (vs the Pine's ~90) to avoid re-overfitting.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from quant import backtest as B
from quant import strategy_c11 as C11
from quant import validate as V

CACHE = Path(__file__).parent / "cache"


def load_15m() -> pd.DataFrame:
    """Load staged ES 1m continuous (back-adjusted) and resample to 15m bars."""
    files = sorted(CACHE.glob("ES_continuous_minute_*.parquet"))
    if not files:
        raise SystemExit("no staged ES 1m; run: python -m quant.stage_es --timespan minute ...")
    df = pl.read_parquet(files[-1])
    adj = {c: c.replace("adj_", "") for c in df.columns if c.startswith("adj_")}
    if adj:
        df = df.drop([c.replace("adj_", "") for c in adj]).rename(adj)
    p = df.select(["ts", "open", "high", "low", "close", "volume"]).to_pandas()
    p = p.set_index(pd.DatetimeIndex(p["ts"])).sort_index()
    o = p["open"].resample("15min").first()
    h = p["high"].resample("15min").max()
    l = p["low"].resample("15min").min()
    c = p["close"].resample("15min").last()
    v = p["volume"].resample("15min").sum()
    bars = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}).dropna()
    bars["ts"] = bars.index
    return bars.reset_index(drop=True)


# ---- precompute the strategy frame ONCE (causal); evaluate just thresholds + exits ----
_FEAT = {"frame": None}


def _frame():
    if _FEAT["frame"] is None:
        bars = load_15m()
        _FEAT["frame"] = C11.build(bars)        # regime + features + sleeves(default thresholds)
        _FEAT["bars"] = bars
    return _FEAT["frame"]


def evaluate(params: dict, df_slice) -> dict:
    """df_slice is a slice of the prebuilt strategy frame (a Polars/pandas view).
    We re-derive the sleeves on the slice with the tuned thresholds, combine to a
    signal, and backtest with point stops/trails. CAUSAL — sleeves use only slice rows."""
    f = df_slice.to_pandas() if isinstance(df_slice, pl.DataFrame) else df_slice
    f = C11.sleeve_signals(f, p={
        "vol_mult": params["vol_mult"], "adx_min": params["adx_min"],
        "macd_floor": params["macd_floor"], "tc_macd_floor": params["tc_macd_floor"],
        "tc_atr_rel_max": params["tc_atr_rel_max"],
    })
    sig = C11.combine_to_signal(f, allow_shorts=bool(params["allow_shorts"]))
    bt = f[["open", "high", "low", "close", "volume"]].copy()
    bt["signal"] = sig.to_numpy()
    res = B.run_backtest(
        bt, contract=B.ES, entry_mode="next_bar_open", direction="both",
        stop_loss_pts=params["sl"], take_profit_pts=(params["tp"] if params["tp"] > 0 else None),
        trailing_pts=(params["trail"] if params["trail"] > 0 else None),
        slippage_ticks=1.0, min_bars_between=2,
    )
    m = res["metrics"]
    return {"total_return": m["total_return"], "n_trades": m["n_trades"]}


SPACE = {
    "allow_shorts": ("cat", [0, 1]),
    "vol_mult": ("float", 0.5, 1.2),
    "adx_min": ("float", 8.0, 30.0),
    "macd_floor": ("float", -3.0, 2.0),
    "tc_macd_floor": ("float", -1.0, 2.0),
    "tc_atr_rel_max": ("float", 1.2, 3.0),
    "sl": ("float", 20.0, 160.0),
    "tp": ("float", 0.0, 300.0),
    "trail": ("float", 0.0, 200.0),
}


def main():
    frame = _frame()
    feat = pl.from_pandas(frame.reset_index(drop=True))
    n = feat.height
    ho = frame.tail(int(n * 0.2))
    bh = (ho["close"].iloc[-1] - ho["close"].iloc[0]) * B.ES.point_value / 100_000.0
    print(f"ES 15m bars: {n}  ({frame['ts'].iloc[0]} .. {frame['ts'].iloc[-1]})")
    print(f"regime mix: {frame['regime'].value_counts().to_dict()}")
    print(f"holdout buy&hold ≈ {bh*100:+.1f}% (1 contract/$100k)\n")

    res = V.run_validation(evaluate, SPACE, feat, embargo=200,
                           n_seeds=5, n_trials=50, inner_k=4)
    v = res["verdict"]
    print("=== C11 BASE (sleeves + EMA regime), OOS ===")
    print("split:", res["sizes"])
    print(f"median OOS = {v['median_oos']*100:+.2f}% | seed-stable = {v['pct_positive']:.0f}% | "
          f"median trades = {v['median_trades']:.0f} | train CV = {res['train_return']*100:+.2f}%")
    print(f"GATES: oos>0 {v['oos_positive']} | stable≥75% {v['seed_stable_75pct']} | "
          f"trades≥20 {v['min_20_trades']} | PASS {v['PASS']}  flags={v['flags']}")
    print("\nper-seed:")
    for s in res["mc"]["per_seed"]:
        print(f"  seed {s['seed']}: OOS={s['oos_return']*100:+.2f}% trades={s['oos_trades']} "
              f"shorts={s['params']['allow_shorts']} sl={s['params']['sl']:.0f} tp={s['params']['tp']:.0f}")


if __name__ == "__main__":
    main()
