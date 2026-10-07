"""es_trend.py — test richer signal FAMILIES on staged ES daily, OOS.

Runs each strategy family through the same trustworthy validator (chrono split +
inner-CV + seed-stability MC + 3 gates). The oscillator reversal already failed
OOS; here we test trend-following / breakout / momentum (which RIDE the +130%
trend instead of fading it) plus a trend-filtered reversal. Buy-&-hold is the
benchmark to beat. No Databento, no HDD — reads the SSD cache only.
"""
from __future__ import annotations

from quant import backtest as B
from quant import es_baseline as E
from quant import features as F
from quant import strategy as S
from quant import validate as V

# family -> (signal builder, signal-param search space)
FAMILIES = {
    "osc_reversal": (
        lambda df, **k: S.make_signal(df, **k),
        {"mode": ("cat", ["velocity_zone", "zone_reversal", "any_reversal"]),
         "osc_thr": ("float", 0.10, 0.60), "vel_eps": ("float", 0.0, 0.05)},
    ),
    "ma_state": (
        lambda df, **k: S.make_trend_signal(df, mode="ma_state", **k),
        {"fast": ("int", 5, 50), "slow": ("int", 20, 200)},
    ),
    "ma_cross": (
        lambda df, **k: S.make_trend_signal(df, mode="ma_cross", **k),
        {"fast": ("int", 5, 50), "slow": ("int", 20, 200)},
    ),
    "breakout": (
        lambda df, **k: S.make_trend_signal(df, mode="breakout", **k),
        {"lookback": ("int", 10, 60)},
    ),
    "momentum": (
        lambda df, **k: S.make_trend_signal(df, mode="momentum", **k),
        {"mom_n": ("int", 5, 60)},
    ),
    "trend_filt_rev": (
        lambda df, **k: S.make_trend_signal(df, mode="trend_filtered_reversal", **k),
        {"osc_thr": ("float", 0.10, 0.60)},
    ),
}

EXEC_SPACE = {
    "bt_direction": ("cat", ["long", "both"]),
    "sl": ("float", 15.0, 100.0),
    "tp": ("float", 20.0, 200.0),
    "trail": ("float", 0.0, 80.0),
}


def make_evaluate(fn, sig_keys):
    def evaluate(params, df):
        sig = fn(df, **{k: params[k] for k in sig_keys})
        res = B.run_backtest(
            sig, contract=B.ES, entry_mode="next_bar_open", direction=params["bt_direction"],
            stop_loss_pts=params["sl"], take_profit_pts=params["tp"],
            trailing_pts=(params["trail"] if params["trail"] > 0 else None),
            slippage_ticks=1.0, min_bars_between=1,
        )
        m = res["metrics"]
        return {"total_return": m["total_return"], "n_trades": m["n_trades"]}
    return evaluate


def main():
    bars = E.load_staged()
    feat = F.make_price_features(bars)
    n = feat.height
    # holdout buy&hold benchmark (last ~third), $ on 1 contract / $100k
    ho = feat.tail(int(n * 0.2)).to_pandas()
    bh = (ho["close"].iloc[-1] - ho["close"].iloc[0]) * B.ES.point_value / 100_000.0
    print(f"loaded {n} ES daily bars | holdout buy&hold ≈ {bh*100:+.1f}% (1 contract/$100k)\n")

    print(f"{'family':16s} {'OOS%':>7} {'stable%':>8} {'trades':>7} {'train%':>7}  PASS")
    print("-" * 60)
    results = {}
    for name, (fn, space) in FAMILIES.items():
        sig_keys = list(space.keys())
        ev = make_evaluate(fn, sig_keys)
        res = V.run_validation(ev, {**space, **EXEC_SPACE}, feat,
                               embargo=10, n_seeds=5, n_trials=40, inner_k=4)
        v = res["verdict"]
        results[name] = res
        flag = "OVERFIT" if v["flags"].get("overfit_gt5x") else ""
        print(f"{name:16s} {v['median_oos']*100:>+6.2f} {v['pct_positive']:>7.0f} "
              f"{v['median_trades']:>7.0f} {res['train_return']*100:>+6.2f}  "
              f"{'✅PASS' if v['PASS'] else '✗'} {flag}")

    print("\nlegend: OOS% = median held-out return | stable% = seeds profitable | "
          "train% = median train CV | gates: OOS>0, stable≥75%, trades≥20")
    winners = [n for n, r in results.items() if r["verdict"]["PASS"]]
    print("\nPASSING families:", winners or "NONE (no daily edge survives OOS — expected; "
          "the real edge is options-structure + intraday)")


if __name__ == "__main__":
    main()
