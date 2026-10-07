"""Build a machine-readable audit from existing immutable strategy results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/quant_desk_methods_audit_20260714.json"


def main() -> None:
    exact = json.loads((ROOT / "reports/tv_c11_exact_simulation_20260714.json").read_text())
    long = json.loads((ROOT / "reports/c11_multiyear_x_stress_20260714.json").read_text())
    x_tv = json.loads((ROOT / "reports/tv_c11x_chop_veto_c1_20260714.json").read_text())
    frozen = ROOT / "archives/c11_frozen_20260714/JD_ES_15m_C11_Trend_Carry_200k_C1_UNCHANGED.pine"
    baseline = long["monte_carlo"]["baseline"]["summary"]
    stressed = long["monte_carlo"]["execution_stress"]["summary"]
    payload = {
        "integrity": {"c11_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
                      "production_strategy_modified": False},
        "evidence": {
            "exact_tradingview": exact["historical"],
            "five_year_transport": long["reconstruction"],
            "x_chop_veto_exact_tv": x_tv,
            "three_year_simulation": {
                "baseline": baseline,
                "execution_stress": stressed,
                "delta_probability_drawdown_30pct":
                    stressed["probability_drawdown_30pct"] - baseline["probability_drawdown_30pct"],
                "delta_probability_ruin_50pct":
                    stressed["probability_ruin_50pct"] - baseline["probability_ruin_50pct"],
            },
        },
        "method_decisions": [
            {"method": "proper scoring and reliability curves", "decision": "use_now",
             "application": "calibrate any ML trade-quality probabilities by time fold"},
            {"method": "empirical LOB execution model", "decision": "use_now",
             "application": "replace fixed slippage assumptions with spread/depth/fill distributions"},
            {"method": "EVT and jump stress", "decision": "use_now",
             "application": "capital sizing and reverse stress tests, not entry signals"},
            {"method": "regime block bootstrap", "decision": "already_in_use",
             "application": "path and drawdown uncertainty"},
            {"method": "particle or logit-state filter", "decision": "monitor_only",
             "application": "smooth latent risk state; no fast parameter retraining"},
            {"method": "t/vine copulas", "decision": "portfolio_only",
             "application": "joint tails after several independently validated sleeves exist"},
            {"method": "importance sampling", "decision": "conditional",
             "application": "rare-event precision after a validated path model exists"},
            {"method": "Quant GAN / neural SDE", "decision": "defer",
             "application": "high model risk and no immediate evidence of better C11 decisions"},
            {"method": "toy prediction-market ABM", "decision": "reject",
             "application": "not calibrated to ES order-book mechanics"},
        ],
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(OUT)


if __name__ == "__main__":
    main()
