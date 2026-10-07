"""Summarize forward-paper evidence and evaluate the C1 promotion gate."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path


DEFAULT_LOG = Path("data/polymarket_crypto/paper/JD_PM_BTC_15m_Late_Favorite_C1.jsonl")
DEFAULT_CONFIG = Path("polymarket/JD_PM_BTC_15m_Late_Favorite_C1.json")


def summarize(log_path: Path, config_path: Path) -> dict:
    config = json.loads(config_path.read_text())
    signals, resolutions = {}, {}
    if log_path.exists():
        for line in log_path.read_text().splitlines():
            record = json.loads(line)
            if record["type"] == "signal":
                signals[record["slug"]] = record
            elif record["type"] == "resolution":
                resolutions[record["slug"]] = record
    resolved = [resolutions[slug] for slug in signals if slug in resolutions]
    pnl = [float(record["pnl"]) for record in resolved]
    equity, peak, max_drawdown = 0.0, 0.0, 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    observed = sorted(datetime.fromisoformat(x["observed_at"]) for x in signals.values())
    days = (observed[-1] - observed[0]).days + 1 if observed else 0
    weekly = defaultdict(float)
    for slug, resolution in resolutions.items():
        if slug in signals:
            date = datetime.fromisoformat(signals[slug]["observed_at"])
            year, week, _ = date.isocalendar()
            weekly[f"{year}-W{week:02d}"] += float(resolution["pnl"])
    profitable_week_fraction = (sum(x > 0 for x in weekly.values()) / len(weekly)
                                if weekly else 0.0)
    gate = config["forward_gate"]
    daily_run_rate = sum(pnl) / days if days else 0.0
    checks = {
        "minimum_signals": len(signals) >= gate["minimum_signals"],
        "minimum_calendar_days": days >= gate["minimum_calendar_days"],
        "all_signals_resolved": len(resolved) == len(signals) and bool(signals),
        "positive_net_pnl": sum(pnl) > gate["minimum_net_pnl_after_fees"],
        "profitable_weeks": profitable_week_fraction >= gate["minimum_profitable_weeks_fraction"],
        "drawdown_limit": abs(max_drawdown) <= gate["maximum_allowed_drawdown_usd"],
        "displayed_liquidity": bool(signals) and all(float(x["shares"]) > 0 for x in signals.values()),
    }
    return {"strategy": config["strategy_name"], "status": "PASS" if all(checks.values()) else "NOT_READY",
            "signals": len(signals), "resolved": len(resolved), "calendar_days": days,
            "net_pnl": sum(pnl), "win_rate": (sum(x["won"] for x in resolved) / len(resolved)
                                               if resolved else 0.0),
            "projected_monthly_revenue": daily_run_rate * (365.25 / 12),
            "projected_yearly_revenue": daily_run_rate * 365.25,
            "projection_sample_size": len(resolved),
            "projection_status": "ESTABLISHING" if len(resolved) < 100 else "FORWARD RUN RATE",
            "max_drawdown": max_drawdown, "profitable_week_fraction": profitable_week_fraction,
            "weekly_pnl": dict(sorted(weekly.items())), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = summarize(args.log, args.config)
    rendered = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
