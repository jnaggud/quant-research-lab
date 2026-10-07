"""Reconstruct and stress-test the frozen TradingView C11 report."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.portfolio_simulation import SimulationSpec, simulate


ARCHIVE = Path("archives/c11_frozen_20260714")
PINE = Path("pine_strategies/JD_ES_15m_C11_Trend_Carry_200k_C1.pine")
FROZEN_PINE = ARCHIVE / "JD_ES_15m_C11_Trend_Carry_200k_C1_UNCHANGED.pine"
REPORT = ARCHIVE / "tv_c11_current_report_20260714.json"
BARS = ARCHIVE / "tv_es1_full_15m_bars_20260714.json"
OUTPUT = Path("reports/tv_c11_exact_simulation_20260714.json")
CACHE = Path("quant/cache/tv_c11_exact_daily_20260714.parquet")
CAPITAL = 50_000.0
POINT_VALUE = 50.0
EXPECTED_PNL = 126_905.0
EXPECTED_PINE_SHA256 = "f78e404927533c2f37e3b391f3d0e82f98eadeafdb8a90edf637ef90de8611d6"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs() -> tuple[dict, pd.DataFrame]:
    report = json.loads(REPORT.read_text())["reportData"]
    raw_bars = json.loads(BARS.read_text())
    if not raw_bars.get("success") or len(raw_bars["bars"]) < 20_000:
        raise ValueError("TradingView bar export is incomplete")
    bars = pd.DataFrame(raw_bars["bars"])
    bars["ts"] = pd.to_datetime(bars["time"], unit="s", utc=True)
    bars = bars.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    return report, bars


def build_daily_panel() -> tuple[pd.DataFrame, dict]:
    report, bars = load_inputs()
    ts_ns = bars["ts"].astype("int64").to_numpy()
    close = bars["close"].to_numpy(float)
    realized = np.zeros(len(bars), dtype=float)
    unrealized = np.zeros(len(bars), dtype=float)
    trade_count = np.zeros(len(bars), dtype=int)
    missing = []

    for number, trade in enumerate(report["trades"], 1):
        entry_ns = int(trade["e"]["tm"]) * 1_000_000
        exit_ns = int(trade["x"]["tm"]) * 1_000_000
        entry_i = int(np.searchsorted(ts_ns, entry_ns))
        exit_i = int(np.searchsorted(ts_ns, exit_ns))
        if (entry_i >= len(bars) or exit_i >= len(bars) or
                ts_ns[entry_i] != entry_ns or ts_ns[exit_i] != exit_ns):
            missing.append(number)
            continue
        direction = 1.0 if trade["e"]["tp"] == "le" else -1.0
        entry_price = float(trade["e"]["p"])
        commission = float(trade.get("cm", 0.0))
        if exit_i > entry_i:
            unrealized[entry_i:exit_i] += (
                (close[entry_i:exit_i] - entry_price) * direction * POINT_VALUE
                - commission
            )
        realized[exit_i] += float(trade["tp"]["v"])
        trade_count[exit_i] += 1

    if missing:
        raise ValueError(f"{len(missing)} trade timestamps missing from bars: {missing[:10]}")
    if not np.isclose(realized.sum(), EXPECTED_PNL):
        raise ValueError(f"realized P&L mismatch: {realized.sum()} != {EXPECTED_PNL}")

    bar_panel = pd.DataFrame({
        "date": bars["ts"].dt.tz_convert("America/Chicago").dt.date,
        "close": close,
        "equity_pnl": np.cumsum(realized) + unrealized,
        "trades": trade_count,
    })
    daily = bar_panel.groupby("date").agg(
        close=("close", "last"), equity_pnl=("equity_pnl", "last"),
        c11_trades=("trades", "sum"),
    )
    daily["c11_return"] = daily["equity_pnl"].diff().fillna(daily["equity_pnl"]) / CAPITAL
    market_return = daily["close"].pct_change()
    volatility = market_return.rolling(20).std().shift(1)
    trend = (daily["close"] / daily["close"].shift(63) - 1.0).shift(1)
    high_vol = volatility > volatility.expanding(60).median()
    downtrend = trend < 0
    daily["regime_2"] = downtrend.fillna(False).astype(int)
    daily["regime_4"] = (2 * downtrend.astype(int) + high_vol.astype(int)).fillna(0).astype(int)
    trend_band = pd.Series(np.where(trend < -0.02, 2, np.where(trend > 0.02, 0, 1)),
                           index=daily.index)
    daily["regime_6"] = (2 * trend_band + high_vol.astype(int)).fillna(0).astype(int)

    first_entry = pd.to_datetime(report["trades"][0]["e"]["tm"], unit="ms", utc=True)
    daily = daily[pd.to_datetime(daily.index) >= first_entry.tz_convert("America/Chicago").tz_localize(None).normalize()]
    daily.index = pd.to_datetime(daily.index)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(CACHE)
    metadata = {
        "trades": len(report["trades"]), "realized_pnl": float(realized.sum()),
        "pine_sha256": sha256(PINE), "frozen_pine_sha256": sha256(FROZEN_PINE),
        "bar_count": len(bars), "missing_trade_timestamps": len(missing),
    }
    return daily, metadata


def historical_summary(panel: pd.DataFrame) -> dict:
    equity = CAPITAL + panel["c11_return"].cumsum() * CAPITAL
    drawdown = equity / equity.cummax() - 1.0
    returns = panel["c11_return"].to_numpy(float)
    return {
        "days": len(panel), "start": str(panel.index[0].date()),
        "end": str(panel.index[-1].date()), "total_pnl": float(returns.sum() * CAPITAL),
        "total_return": float(returns.sum()), "max_drawdown": float(drawdown.min()),
        "annualized_sharpe": float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() else 0.0,
    }


def planned_cases() -> list[tuple[str, str, SimulationSpec, str, float]]:
    base = SimulationSpec(n_paths=20_000, horizon_days=756, mean_block_days=20,
                          slippage_cost_per_trade_return=25.0 / CAPITAL)
    cases = []
    for value in (5, 10, 20, 40, 60):
        cases.append(("block_days", str(value), replace(base, mean_block_days=value), "regime_4", 1.0))
    for value in (252, 756, 1260):
        cases.append(("horizon_days", str(value), replace(base, horizon_days=value), "regime_4", 1.0))
    for value in (2, 4, 6):
        cases.append(("regime_states", str(value), base, f"regime_{value}", 1.0))
    for value in ("regime", "stationary", "moving", "circular", "crisis_weighted"):
        cases.append(("bootstrap_method", value, replace(base, bootstrap_method=value), "regime_4", 1.0))
    for value in ("fixed_notional", "compound"):
        cases.append(("equity_mode", value, replace(base, equity_mode=value), "regime_4", 1.0))
    for value in (0.0, 0.25, 0.50, 0.75):
        cases.append(("loss_synchronization", str(value), replace(base, synchronized_loss_probability=value), "regime_4", 1.0))
    for value in (0.0, 1.0, 2.0, 4.0):
        cases.append(("extra_slippage_ticks", str(value), replace(base, extra_slippage_ticks=value), "regime_4", 1.0))
    for value in (0.0, 0.05, 0.10, 0.20):
        cases.append(("missed_trade_probability", str(value), replace(base, missed_trade_probability=value), "regime_4", 1.0))
    for value in (0.0, 0.002, 0.005, 0.010):
        cases.append(("gap_probability", str(value), replace(base, gap_shock_probability=value), "regime_4", 1.0))
    for value in (1.0, 2.0, 3.0):
        cases.append(("gap_multiplier", str(value), replace(base, gap_shock_probability=0.005, gap_shock_multiplier=value), "regime_4", 1.0))
    for value in (0.25, 0.50, 0.75, 1.0):
        cases.append(("position_size", str(value), base, "regime_4", value))
    return cases


def main() -> None:
    panel, metadata = build_daily_panel()
    if metadata["pine_sha256"] != EXPECTED_PINE_SHA256 or metadata["frozen_pine_sha256"] != EXPECTED_PINE_SHA256:
        raise ValueError("C11 Pine checksum changed")
    returns = panel[["c11_return"]].to_numpy(float)
    trades = panel[["c11_trades"]].to_numpy(float)
    sweep = []
    cases = planned_cases()
    print(f"exact C11: {len(panel)} days, {len(cases)} cases x 20,000 paths, 32 workers", flush=True)
    for i, (group, label, spec, regime_column, risk) in enumerate(cases, 1):
        _, summary = simulate(returns, trades, panel[regime_column].to_numpy(int),
                              np.array([risk]), spec, seed=20260714 + i, workers=32)
        sweep.append({"group": group, "label": label, "risk": risk,
                      "regime_column": regime_column, "spec": asdict(spec), "summary": summary})
        print(f"[{i:02d}/{len(cases)}] {group}={label}: median {summary['return_quantiles']['0.5']:+.1%}, P(DD>30%) {summary['probability_drawdown_30pct']:.1%}", flush=True)

    precision = {}
    for name, spec in {
        "full_size_baseline": SimulationSpec(n_paths=1_000_000, horizon_days=756,
            slippage_cost_per_trade_return=25.0 / CAPITAL),
        "full_size_severe_stress": SimulationSpec(n_paths=1_000_000, horizon_days=756,
            extra_slippage_ticks=2.0, missed_trade_probability=0.10,
            synchronized_loss_probability=0.50, gap_shock_probability=0.005,
            gap_shock_multiplier=2.0, slippage_cost_per_trade_return=25.0 / CAPITAL),
    }.items():
        print(f"precision {name}: 1,000,000 paths", flush=True)
        _, summary = simulate(returns, trades, panel["regime_4"].to_numpy(int),
                              np.array([1.0]), spec, seed=20260714, workers=32)
        precision[name] = {"spec": asdict(spec), "summary": summary}

    groups = sorted({row["group"] for row in sweep})
    envelopes = {}
    for group in groups:
        rows = [row["summary"] for row in sweep if row["group"] == group]
        envelopes[group] = {
            "median_return_min": min(r["return_quantiles"]["0.5"] for r in rows),
            "median_return_max": max(r["return_quantiles"]["0.5"] for r in rows),
            "probability_dd30_min": min(r["probability_drawdown_30pct"] for r in rows),
            "probability_dd30_max": max(r["probability_drawdown_30pct"] for r in rows),
        }
    payload = {"integrity": metadata, "historical": historical_summary(panel),
               "sweep": sweep, "envelopes": envelopes, "precision": precision}
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
