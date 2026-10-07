#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


TRADINGVIEW_SOURCES = [
    {"symbol": "NYMEX:CL1!", "role": "primary", "features": ["15m OHLCV", "front-month crude trend", "session behavior"]},
    {"symbol": "NYMEX:CL2!", "role": "term_structure", "features": ["front-second spread", "roll/contango/backwardation"]},
    {"symbol": "NYMEX:CL3!", "role": "term_structure", "features": ["curve slope", "inventory expectation proxy"]},
    {"symbol": "NYMEX:BZ1!", "role": "cross_market", "features": ["Brent confirmation", "Brent/WTI spread"]},
    {"symbol": "NYMEX:RB1!", "role": "energy_complex", "features": ["gasoline demand impulse", "refined product confirmation"]},
    {"symbol": "NYMEX:HO1!", "role": "energy_complex", "features": ["distillate confirmation", "crack-spread proxy"]},
    {"symbol": "NYMEX:NG1!", "role": "energy_complex", "features": ["energy volatility/risk proxy"]},
    {"symbol": "TVC:DXY", "role": "macro", "features": ["USD pressure", "commodity headwind/tailwind"]},
    {"symbol": "TVC:US10Y", "role": "macro", "features": ["rates regime", "risk/liquidity proxy"]},
    {"symbol": "CME_MINI:ES1!", "role": "risk", "features": ["risk-on/off confirmation", "equity volatility proxy"]},
    {"symbol": "CBOE:VIX", "role": "risk", "features": ["risk-off regime", "volatility shock filter"]},
    {"symbol": "COMEX:GC1!", "role": "macro", "features": ["safe-haven pressure", "USD sensitivity proxy"]},
    {"symbol": "AMEX:USO", "role": "flow_proxy", "features": ["ETF flow proxy", "cash-session oil proxy"]},
    {"symbol": "TVC:SPX", "role": "risk", "features": ["broad risk trend"]},
]

VENDOR_SOURCES = [
    {"name": "EIA petroleum status", "frequency": "weekly", "features": ["crude inventory surprise", "gasoline/distillate surprise", "Cushing stocks"]},
    {"name": "API inventory", "frequency": "weekly", "features": ["pre-EIA inventory expectation", "event risk flag"]},
    {"name": "CFTC COT", "frequency": "weekly", "features": ["managed-money positioning", "producer hedge pressure"]},
    {"name": "News/sentiment API", "frequency": "intraday", "features": ["OPEC/geopolitical shock flags", "headline intensity"]},
    {"name": "Options/skew API", "frequency": "intraday/daily", "features": ["implied vol regime", "put/call skew", "tail-risk pricing"]},
    {"name": "Order-flow/tick API", "frequency": "intraday", "features": ["delta", "cumulative delta", "liquidity sweeps", "absorption"]},
    {"name": "Economic calendar API", "frequency": "scheduled", "features": ["CPI/FOMC/NFP blackouts", "EIA event windows"]},
]


def write_markdown(path, payload):
    lines = [
        "# CL1! Data Source Inventory",
        "",
        "This inventory separates data we can source from TradingView from external vendor data that can be joined into the Python optimizer.",
        "",
        "## TradingView Candidates",
        "",
        "| Symbol | Role | Candidate Features |",
        "|---|---|---|",
    ]
    for item in payload["tradingview_sources"]:
        lines.append(f"| `{item['symbol']}` | {item['role']} | {', '.join(item['features'])} |")
    lines.extend([
        "",
        "## Vendor Candidates",
        "",
        "| Source | Frequency | Candidate Features |",
        "|---|---|---|",
    ])
    for item in payload["vendor_sources"]:
        lines.append(f"| {item['name']} | {item['frequency']} | {', '.join(item['features'])} |")
    lines.extend([
        "",
        "## Integration Plan",
        "",
        "1. Export/load each TradingView symbol on the same 15m timestamp grid.",
        "2. Add lagged features only; never use data before it was published.",
        "3. Add event blackout flags for EIA, FOMC, CPI, NFP, and major OPEC windows.",
        "4. Optimize with walk-forward validation and compare against the current fixed CL baseline.",
        "5. Promote external data only if it improves out-of-sample net PnL, drawdown, and fold consistency.",
        "",
        "## Highest-Value First Tests",
        "",
        "- CL term structure: `CL1! - CL2!`, `CL2! - CL3!`.",
        "- Energy confirmation: Brent/WTI, RB, HO.",
        "- Event controls: EIA/API inventory windows and scheduled macro blackout flags.",
        "- Risk regime: DXY, ES1!, VIX.",
    ])
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/cl_15m_data_source_inventory.json")
    args = parser.parse_args()
    payload = {"tradingview_sources": TRADINGVIEW_SOURCES, "vendor_sources": VENDOR_SOURCES}
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=2))
    write_markdown(out.with_suffix(".md"), payload)
    print(out)
    print(out.with_suffix(".md"))


if __name__ == "__main__":
    main()
