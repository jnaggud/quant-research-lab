"""es_baseline.py — first real end-to-end ES validation on staged data.

Pipeline:  staged continuous ES  ->  features (causal)  ->  velocity signal
           ->  backtest (engine B, ES contract, costs+gaps)  ->  v16 validation
           ->  3 acceptance gates.

This is the integration test of the whole stack on REAL data. Expectation per the
audit: the honest ES edge is near-zero — the win here is a TRUSTWORTHY number, not
a big return. If the gates fail, that's the harness working, not a bug.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from quant import backtest as B
from quant import features as F
from quant import strategy as S
from quant import validate as V

CACHE = Path(__file__).parent / "cache"


def load_staged(root: str = "ES", timespan: str = "day") -> pl.DataFrame:
    files = sorted(CACHE.glob(f"{root}_continuous_{timespan}_*.parquet"))
    if not files:
        raise SystemExit(f"no staged data for {root} {timespan}; run quant.stage_es first")
    df = pl.read_parquet(files[-1])
    # use back-adjusted OHLC (roll gaps removed) as the tradeable continuous series
    adj = {c: c.replace("adj_", "") for c in df.columns if c.startswith("adj_")}
    if adj:
        df = df.drop([c.replace("adj_", "") for c in adj]).rename(adj)
    return df.select(["ts", "open", "high", "low", "close", "volume"])


def evaluate(params: dict, df) -> dict:
    """One config on one data slice → metrics. df is a feature-frame slice.

    Direction has a SINGLE source of truth: the signal carries both sides, and the
    backtest's `direction` (a tuned param) decides which to take.
    """
    sig = S.make_signal(df, mode=params["mode"], osc_thr=params["osc_thr"],
                        vel_eps=params["vel_eps"], direction="both")
    res = B.run_backtest(
        sig, contract=B.ES, entry_mode="next_bar_open", direction=params["direction"],
        stop_loss_pts=params["sl"], take_profit_pts=params["tp"],
        trailing_pts=(params["trail"] if params["trail"] > 0 else None),
        slippage_ticks=1.0, min_bars_between=2,
    )
    m = res["metrics"]
    return {"total_return": m["total_return"], "n_trades": m["n_trades"], "score": m["total_return"]}


SPACE = {
    "mode": ("cat", ["velocity_zone", "zone_reversal", "any_reversal", "velocity_crossover"]),
    "direction": ("cat", ["long", "both"]),
    "osc_thr": ("float", 0.10, 0.60),
    "vel_eps": ("float", 0.0, 0.05),
    "sl": ("float", 10.0, 80.0),
    "tp": ("float", 10.0, 120.0),
    "trail": ("float", 0.0, 60.0),
}


def main():
    bars = load_staged()
    print(f"loaded {bars.height} continuous ES daily bars "
          f"({bars['ts'].min()} .. {bars['ts'].max()})")
    feat = F.make_price_features(bars)
    print(f"features: {len(feat.columns)} cols")
    # features are causal (proven), so a small embargo suffices to keep fold
    # boundaries clean; a 200-bar embargo would devour a few-hundred-bar daily set.
    res = V.run_validation(evaluate, SPACE, feat, embargo=10,
                           n_seeds=6, n_trials=60, inner_k=4)
    print("\n=== ES DAILY BASELINE ===")
    print("split sizes:", res["sizes"])
    print("train median CV return:", round(res["train_return"], 4))
    print("MC:", {k: (round(v, 4) if isinstance(v, float) else v)
                  for k, v in res["mc"].items() if k != "per_seed"})
    v = res["verdict"]
    print("VERDICT:", {k: v[k] for k in ("oos_positive", "seed_stable_75pct",
                                         "min_20_trades", "PASS")})
    print("median OOS return:", round(v["median_oos"], 4),
          "| seed-stable %:", v["pct_positive"],
          "| median holdout trades:", v["median_trades"])
    print("overfit flag:", v["flags"])
    # show the per-seed selected configs (do they agree? agreement = robustness)
    print("\nper-seed OOS:")
    for p in res["mc"]["per_seed"]:
        print(f"  seed {p['seed']}: ret={p['oos_return']:+.4f} trades={p['oos_trades']:>3} "
              f"mode={p['params']['mode']} osc_thr={p['params']['osc_thr']:.2f} "
              f"sl={p['params']['sl']:.0f} tp={p['params']['tp']:.0f}")


if __name__ == "__main__":
    main()
