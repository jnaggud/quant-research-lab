"""Build honest ES strategy returns and run the portfolio simulation lab."""
from __future__ import annotations

import os

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from quant import backtest as B
from quant.es_c11_robust import FEATURES, HOLD, prep
from quant.options_join import join_bars
from quant.portfolio_simulation import SimulationSpec, simulate
from quant.strategy_failed_breakout_mr import (
    MRParams, build_features, load_all_1m, run_backtest as run_mr,
)


MR_RESEARCH = Path("reports/es_failed_breakout_mr_research_20260714.json")
CACHE = Path("quant/cache/es_portfolio_daily_oos.parquet")
OUTPUT = Path("reports/es_portfolio_simulation_20260714.json")
CAPITAL = 100_000.0


def _standard_backtest(frame: pd.DataFrame) -> dict:
    bars = frame[["open", "high", "low", "close", "volume", "signal"]].reset_index(drop=True)
    bars["exit_signal"] = 0
    if len(bars):
        bars.loc[len(bars) - 1, "exit_signal"] = 1
    return B.run_backtest(
        bars, contract=B.ES, entry_mode="next_bar_open", direction="both",
        stop_loss_pts=80.0, take_profit_pts=160.0, trailing_pts=120.0,
        slippage_ticks=1.0, min_bars_between=2,
    )


def _daily_mtm_from_result(result: dict, frame: pd.DataFrame, prefix: str,
                           slippage_ticks: float = 1.0) -> pd.DataFrame:
    """Daily P&L increments including conservative open-position liquidation."""
    n = len(frame)
    if not n:
        return pd.DataFrame(columns=[f"{prefix}_return", f"{prefix}_trades"])
    close = frame["close"].to_numpy(float)
    ts = pd.DatetimeIndex(frame["ts"])
    realized_delta = np.zeros(n, dtype=float)
    open_liquidation = np.zeros(n, dtype=float)
    trade_count = np.zeros(n, dtype=int)
    exit_slip = slippage_ticks * B.ES.tick
    for trade in result["trades"]:
        entry_i, exit_i = int(trade["entry_i"]), int(trade["exit_i"])
        if exit_i >= n or entry_i >= n:
            continue
        direction = int(trade["dir"])
        if exit_i > entry_i:
            liquidation_price = close[entry_i:exit_i] - exit_slip * direction
            open_liquidation[entry_i:exit_i] = (
                (liquidation_price - float(trade["entry_px"])) * direction * B.ES.point_value
                - 2 * B.ES.commission
            )
        realized_delta[exit_i] += float(trade["pnl"])
        trade_count[exit_i] += 1
    mtm_pnl = np.cumsum(realized_delta) + open_liquidation

    intraday = pd.DataFrame({
        "date": ts.date, "mtm_pnl": mtm_pnl, "trades": trade_count,
    })
    daily = intraday.groupby("date").agg(
        mtm_pnl=("mtm_pnl", "last"), trades=("trades", "sum"))
    daily_increment = daily["mtm_pnl"].diff().fillna(daily["mtm_pnl"])
    daily[f"{prefix}_return"] = daily_increment / CAPITAL
    daily[f"{prefix}_trades"] = daily.pop("trades")
    return daily[[f"{prefix}_return", f"{prefix}_trades"]]


def build_daily_panel() -> pd.DataFrame:
    research = json.loads(MR_RESEARCH.read_text())
    selected = max(research["finalists"], key=lambda row: row["cv_score"])
    mr_params = MRParams(**selected["params"])
    one_minute = load_all_1m()
    mr_frame = build_features(one_minute, mr_params)
    mr_hold_start = pd.Timestamp(one_minute["ts"].iloc[int(len(one_minute) * 0.6)])

    c11 = prep(allow_shorts=True)
    c11 = join_bars(c11)
    c11["gex_z"] = c11["gex_z"].fillna(0.0)
    c11 = c11.dropna(subset=["d_pain", "d_call", "d_put"]).reset_index(drop=True)
    c11["dt"] = pd.DatetimeIndex(c11["ts"])
    t0, t1 = c11["dt"].iloc[0], c11["dt"].iloc[-1]

    pieces = []
    cur = (t0 + pd.DateOffset(months=18)).normalize()
    while cur + pd.DateOffset(months=3) <= t1:
        nxt = cur + pd.DateOffset(months=3)
        train = c11[(c11["dt"] < cur - pd.Timedelta(hours=HOLD)) &
                    (c11["dt"] >= cur - pd.DateOffset(months=18))]
        test = c11[(c11["dt"] >= cur) & (c11["dt"] < nxt)].copy()
        training_signals = train[(train["signal"] != 0) & train["meta_label"].notna()].dropna(
            subset=FEATURES)
        if len(test) < 200 or len(training_signals) < 100:
            cur = nxt
            continue

        clf = RandomForestClassifier(
            n_estimators=200, max_depth=4, min_samples_leaf=50,
            random_state=0, n_jobs=-1, class_weight="balanced",
        )
        clf.fit(training_signals[FEATURES].to_numpy(),
                training_signals["meta_label"].to_numpy())
        test_signals = test[test["signal"] != 0].dropna(subset=FEATURES)
        probability = clf.predict_proba(test_signals[FEATURES].to_numpy())[:, 1]
        keep = set(test_signals.index[probability > 0.5])
        # Final research rule: short only when quarterly-OI net GEX is negative.
        keep_gex = {i for i in keep
                    if not (test.loc[i, "signal"] < 0 and test.loc[i, "gex_z"] >= 0)}

        base_result = _standard_backtest(test)
        gated = test.copy()
        gated["signal"] = [signal if i in keep_gex else 0.0
                           for i, signal in zip(gated.index, gated["signal"])]
        ml_gex_result = _standard_backtest(gated)

        mr_test = mr_frame[(mr_frame["ts"] >= cur) & (mr_frame["ts"] < nxt)].reset_index(drop=True)
        mr_result = run_mr(mr_test, mr_params, direction=selected["direction"],
                           force_close_end=True)

        date_index = pd.Index(sorted(set(pd.DatetimeIndex(test["ts"]).date)), name="date")
        quarter = pd.DataFrame(index=date_index)
        for daily in (
            _daily_mtm_from_result(base_result, test.reset_index(drop=True), "c11_base"),
            _daily_mtm_from_result(ml_gex_result, gated.reset_index(drop=True), "c11_ml_gex"),
            _daily_mtm_from_result(mr_result, mr_test.reset_index(drop=True), "mr"),
        ):
            quarter = quarter.join(daily, how="left")
        pieces.append(quarter.fillna(0.0))
        cur = nxt

    panel = pd.concat(pieces).sort_index()
    panel = panel[~panel.index.duplicated(keep="first")]

    # Causal daily market regime: prior 20-day volatility and prior 63-day trend.
    prices = c11.copy()
    prices["date"] = pd.DatetimeIndex(prices["ts"]).date
    daily_close = prices.groupby("date")["close"].last().reindex(panel.index)
    market_return = daily_close.pct_change()
    volatility = market_return.rolling(20).std().shift(1)
    trend = (daily_close / daily_close.shift(63) - 1.0).shift(1)
    rolling_vol_median = volatility.expanding(60).median()
    high_vol = volatility > rolling_vol_median
    downtrend = trend < 0
    panel["market_return"] = market_return.fillna(0.0)
    panel["regime_2"] = downtrend.fillna(False).astype(int)
    panel["regime_4"] = (2 * downtrend.astype(int) + high_vol.astype(int)).fillna(0).astype(int)
    trend_band = pd.Series(np.where(trend < -0.02, 2, np.where(trend > 0.02, 0, 1)),
                           index=panel.index)
    panel["regime_6"] = (2 * trend_band + high_vol.astype(int)).fillna(0).astype(int)
    panel["regime"] = panel["regime_4"]

    # Only the MR holdout may enter a joint simulation.
    panel = panel[pd.to_datetime(panel.index, utc=True) >= mr_hold_start.normalize()]
    panel.to_parquet(CACHE)
    return panel


def historical_summary(panel: pd.DataFrame, weights: np.ndarray,
                       strategies: list[str]) -> dict:
    daily = panel[[f"{name}_return" for name in strategies]].to_numpy() @ weights
    equity = 1.0 + np.cumsum(daily)
    drawdown = equity / np.maximum.accumulate(equity) - 1
    return {
        "days": int(len(daily)),
        "total_return": float(daily.sum()),
        "max_drawdown": float(drawdown.min()),
        "annualized_sharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() else 0.0,
    }


def main() -> None:
    panel = build_daily_panel()
    strategies = ["c11_base", "c11_ml_gex", "mr"]
    returns = panel[[f"{name}_return" for name in strategies]].to_numpy(float)
    trades = panel[[f"{name}_trades" for name in strategies]].to_numpy(float)
    regimes = panel["regime"].to_numpy(int)
    print(f"daily OOS panel {len(panel)} days: {panel.index[0]} .. {panel.index[-1]}")
    print("regimes:", panel["regime"].value_counts().sort_index().to_dict())

    books = {
        "c11_ml_gex": np.array([0.0, 1.0, 0.0]),
        "c11_ml_gex_half_risk": np.array([0.0, 0.5, 0.0]),
        "c11_plus_25pct_mr": np.array([0.0, 1.0, 0.25]),
    }
    scenarios = {
        "baseline": SimulationSpec(n_paths=100_000, horizon_days=756),
        "moderate_execution": SimulationSpec(
            n_paths=100_000, horizon_days=756,
            extra_slippage_ticks=1.0,
            missed_trade_probability=0.05,
        ),
        "dependence_stress": SimulationSpec(
            n_paths=100_000, horizon_days=756,
            synchronized_loss_probability=0.25,
        ),
        "severe_execution_and_dependence": SimulationSpec(
            n_paths=100_000, horizon_days=756,
            extra_slippage_ticks=2.0,
            missed_trade_probability=0.10,
            synchronized_loss_probability=0.50,
            gap_shock_probability=0.005,
            gap_shock_multiplier=2.0,
        ),
    }

    payload = {
        "strategies": strategies,
        "panel": {
            "days": len(panel), "start": str(panel.index[0]), "end": str(panel.index[-1]),
            "daily_return_correlation": panel[[f"{n}_return" for n in strategies]].corr().to_dict(),
        },
        "runs": {},
    }
    for book_name, weights in books.items():
        payload["runs"][book_name] = {
            "weights": dict(zip(strategies, weights.tolist())),
            "historical": historical_summary(panel, weights, strategies),
            "scenarios": {},
        }
        for scenario_name, spec in scenarios.items():
            print(f"running {book_name}/{scenario_name}: {spec.n_paths:,} paths on 32 cores", flush=True)
            _, summary = simulate(returns, trades, regimes, weights, spec,
                                  seed=20260714, workers=32)
            payload["runs"][book_name]["scenarios"][scenario_name] = {
                "spec": spec.__dict__, "summary": summary,
            }
            print(f"  P(profit)={summary['probability_profitable']:.1%} "
                  f"median={summary['return_quantiles']['0.5']:+.1%} "
                  f"P(DD>30%)={summary['probability_drawdown_30pct']:.1%}")

    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
