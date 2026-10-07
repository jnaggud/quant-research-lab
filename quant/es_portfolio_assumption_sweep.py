"""Predeclared portfolio-simulation assumption sweep and final precision runs."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from quant.es_portfolio_simulation import build_daily_panel
from quant.portfolio_simulation import SimulationSpec, simulate


OUTPUT = Path("reports/es_portfolio_assumption_sweep_20260714.json")
STRATEGIES = ["c11_base", "c11_ml_gex", "mr"]


def _case(group: str, label: str, spec: SimulationSpec,
          *, regime_column: str = "regime_4", risk: float = 0.5) -> dict:
    return {
        "group": group, "label": label, "spec": spec,
        "regime_column": regime_column, "risk": risk,
    }


def cases() -> list[dict]:
    base = SimulationSpec(n_paths=20_000, horizon_days=756, mean_block_days=20)
    out = []
    for value in (5, 10, 20, 40, 60):
        out.append(_case("block_days", str(value), replace(base, mean_block_days=value)))
    for value in (252, 756, 1260):
        out.append(_case("horizon_days", str(value), replace(base, horizon_days=value)))
    for value in (2, 4, 6):
        out.append(_case("regime_states", str(value), base, regime_column=f"regime_{value}"))
    for value in ("regime", "stationary", "moving", "circular", "crisis_weighted"):
        out.append(_case("bootstrap_method", value, replace(base, bootstrap_method=value)))
    for value in ("fixed_notional", "compound"):
        out.append(_case("equity_mode", value, replace(base, equity_mode=value)))
    for value in (0.0, 0.25, 0.50, 0.75):
        out.append(_case("loss_synchronization", str(value),
                         replace(base, synchronized_loss_probability=value)))
    for value in (0.0, 1.0, 2.0, 4.0):
        out.append(_case("extra_slippage_ticks", str(value),
                         replace(base, extra_slippage_ticks=value)))
    for value in (0.0, 0.05, 0.10, 0.20):
        out.append(_case("missed_trade_probability", str(value),
                         replace(base, missed_trade_probability=value)))
    for value in (0.0, 0.002, 0.005, 0.010):
        out.append(_case("gap_probability", str(value),
                         replace(base, gap_shock_probability=value,
                                 gap_shock_multiplier=2.0)))
    for value in (1.0, 2.0, 3.0):
        out.append(_case("gap_multiplier", str(value),
                         replace(base, gap_shock_probability=0.005,
                                 gap_shock_multiplier=value)))
    for value in (0.25, 0.50, 0.75, 1.0):
        out.append(_case("c11_risk", str(value), base, risk=value))
    return out


def _mc_interval(probability: float, n: int) -> tuple[float, float]:
    error = 1.96 * np.sqrt(probability * (1 - probability) / n)
    return max(0.0, probability - error), min(1.0, probability + error)


def main() -> None:
    panel = build_daily_panel()
    returns = panel[[f"{name}_return" for name in STRATEGIES]].to_numpy(float)
    trades = panel[[f"{name}_trades" for name in STRATEGIES]].to_numpy(float)

    results = []
    planned = cases()
    print(f"assumption sweep: {len(planned)} cases x 20,000 paths on 32 cores", flush=True)
    for i, case in enumerate(planned, 1):
        regimes = panel[case["regime_column"]].to_numpy(int)
        weights = np.array([0.0, case["risk"], 0.0])
        _, summary = simulate(
            returns, trades, regimes, weights, case["spec"],
            seed=20260714 + i, workers=32,
        )
        row = {
            "group": case["group"], "label": case["label"],
            "regime_column": case["regime_column"], "risk": case["risk"],
            "spec": asdict(case["spec"]), "summary": summary,
        }
        results.append(row)
        print(f"[{i:02d}/{len(planned)}] {case['group']}={case['label']}: "
              f"median {summary['return_quantiles']['0.5']:+.1%}, "
              f"P(DD>30%) {summary['probability_drawdown_30pct']:.1%}", flush=True)

    envelopes = {}
    for group in sorted({row["group"] for row in results}):
        subset = [row["summary"] for row in results if row["group"] == group]
        medians = [s["return_quantiles"]["0.5"] for s in subset]
        dd30 = [s["probability_drawdown_30pct"] for s in subset]
        profitable = [s["probability_profitable"] for s in subset]
        envelopes[group] = {
            "median_return_min": min(medians), "median_return_max": max(medians),
            "probability_dd30_min": min(dd30), "probability_dd30_max": max(dd30),
            "probability_profitable_min": min(profitable),
            "probability_profitable_max": max(profitable),
        }

    # Final precision comes after the model sweep. These are fixed specifications,
    # not selected for producing the highest return.
    precision_specs = {
        "half_risk_baseline": SimulationSpec(
            n_paths=1_000_000, horizon_days=756, mean_block_days=20,
            bootstrap_method="regime",
        ),
        "half_risk_dependence_stress": SimulationSpec(
            n_paths=1_000_000, horizon_days=756, mean_block_days=20,
            bootstrap_method="regime", synchronized_loss_probability=0.25,
        ),
    }
    precision = {}
    for name, spec in precision_specs.items():
        print(f"precision run {name}: 1,000,000 paths", flush=True)
        _, summary = simulate(
            returns, trades, panel["regime_4"].to_numpy(int),
            np.array([0.0, 0.5, 0.0]), spec, seed=20260714, workers=32,
        )
        for metric in ("probability_profitable", "probability_drawdown_30pct",
                       "probability_drawdown_50pct", "probability_ruin_50pct"):
            summary[metric + "_mc_95"] = _mc_interval(summary[metric], spec.n_paths)
        precision[name] = {"spec": asdict(spec), "summary": summary}
        print(f"  median {summary['return_quantiles']['0.5']:+.1%}, "
              f"P(DD>30%) {summary['probability_drawdown_30pct']:.2%}")

    payload = {
        "panel": {"days": len(panel), "start": str(panel.index[0]),
                  "end": str(panel.index[-1])},
        "strategies": STRATEGIES,
        "sweep_paths": sum(row["summary"]["paths"] for row in results),
        "sweep": results,
        "envelopes": envelopes,
        "precision": precision,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
