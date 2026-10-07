#!/usr/bin/env python3
"""Write a concise morning summary from the latest ES 15m champion monitor snapshot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_DIR = ROOT / "reports" / "c8_monitor"
OUT_DIR = MONITOR_DIR / "morning"


def money(value) -> str:
    return f"${float(value):,.2f}" if isinstance(value, (int, float)) else f"`{value}`"


def number(value, places: int = 3) -> str:
    return f"{float(value):.{places}f}" if isinstance(value, (int, float)) else f"`{value}`"


def table(rows: list[dict], columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(col, "")) for col in columns) + " |")
    return "\n".join(lines)


def parse_snapshot_time(snapshot_id: str) -> datetime | None:
    try:
        return datetime.strptime(snapshot_id, "%Y%m%d_%H%M%S").astimezone()
    except ValueError:
        return None


def write_summary(payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    snapshot_id = payload.get("snapshot_id", "unknown")
    snapshot_dt = parse_snapshot_time(snapshot_id)
    status = (payload.get("status") or {}).get("status", "UNKNOWN")
    triggers = (payload.get("status") or {}).get("triggers") or {}
    fired = [name for name, value in triggers.items() if value]
    strategies = payload.get("strategies") or {}
    tv = payload.get("tradingview") or {}
    data = payload.get("data") or {}
    exact = payload.get("exact_parity") or {}
    champ_key = (payload.get("champion") or {}).get("key", "c9_c1")
    champ_title = (payload.get("champion") or {}).get("title", "JD ES 15m C9 Core Forward Refine 200k C1 20260620")
    champ = strategies.get(champ_key) or {}
    champ_closed = champ.get("closed") or {}

    rows = []
    comparison_keys = ["trusted_c2", "c6", "c7", "c8_c1", "c8_c5"]
    if champ_key not in comparison_keys:
        comparison_keys.append(champ_key)

    for name in comparison_keys:
        item = strategies.get(name) or {}
        closed = item.get("closed") or {}
        month = item.get("current_month") or {}
        forward = item.get("forward") or {}
        rows.append(
            {
                "strategy": name,
                "net": money(closed.get("net")),
                "excess": money(closed.get("excess")),
                "trades": closed.get("trades", ""),
                "PF": number(closed.get("profit_factor")),
                "DD%": number(item.get("max_drawdown_pct"), 2),
                "month": money(month.get("net")),
                "forward": money(forward.get("net")),
            }
        )

    lines = [
        f"# Champion Morning Summary - {now.strftime('%Y-%m-%d')}",
        "",
        f"Generated: `{now.isoformat(timespec='seconds')}`",
        f"Latest monitor snapshot: `{snapshot_id}`",
        f"Snapshot age: `{str(now - snapshot_dt).split('.')[0]}`" if snapshot_dt else "Snapshot age: `unknown`",
        f"Monitor status: `{status}`",
        f"Champion: `{champ_title}`",
        "",
    ]

    if fired:
        lines.extend(["## Review Triggers", table([{"trigger": name} for name in fired], ["trigger"]), ""])
    else:
        lines.extend(["## Review Triggers", "None fired.", ""])

    deltas = exact.get("deltas") or {}
    lines.extend(
        [
            "## Champion Snapshot",
            f"- Net: {money(champ_closed.get('net'))}",
            f"- Corrected excess over buy-and-hold: {money(champ_closed.get('excess'))}",
            f"- Trades: `{champ_closed.get('trades')}`",
            f"- Profit factor: `{number(champ_closed.get('profit_factor'))}`",
            f"- Max drawdown: `{number(champ.get('max_drawdown_pct'), 2)}%`",
            f"- Current month net: {money((champ.get('current_month') or {}).get('net'))}",
            f"- Forward net since selection: {money((champ.get('forward') or {}).get('net'))}",
            "",
            "## Exact TV Parity",
            f"- Success: `{exact.get('success')}`",
            f"- Completed trade count delta: `{deltas.get('completed_trade_count')}`",
            f"- Completed net delta: `{deltas.get('completed_net')}`",
            f"- Completed PF delta: `{deltas.get('completed_profit_factor')}`",
            "",
            "## Strategy Comparison",
            table(rows, ["strategy", "net", "excess", "trades", "PF", "DD%", "month", "forward"]),
            "",
            "## TradingView",
            f"- Active source: `{tv.get('source_name')}`",
            f"- TV net: {money(tv.get('net'))}",
            f"- TV completed trades: `{tv.get('completed_trades')}`",
            f"- TV PF: `{number(tv.get('profit_factor'))}`",
            f"- TV max DD: {money(tv.get('max_drawdown'))}",
            f"- TV open P&L: {money(tv.get('open_pl'))}",
            "",
            "## Data Window",
            f"- First bar: `{data.get('first_bar')}`",
            f"- Last closed bar: `{data.get('last_closed_bar')}`",
            f"- Forward start: `{data.get('forward_start')}`",
            f"- Excluded latest bars: `{data.get('exclude_tail_bars')}`",
            "",
        ]
    )

    latest_trade = champ.get("latest_trade")
    lines.append("## Latest Completed Champion Trade")
    lines.append(table([latest_trade], list(latest_trade.keys())) if latest_trade else "No completed champion trade found.")
    lines.append("")

    out_path = OUT_DIR / f"{now.strftime('%Y%m%d')}.md"
    latest_path = OUT_DIR / "latest.md"
    text = "\n".join(lines)
    out_path.write_text(text)
    latest_path.write_text(text)
    return out_path


def main() -> None:
    latest = MONITOR_DIR / "latest.json"
    if not latest.exists():
        raise SystemExit(f"Missing monitor snapshot: {latest}")
    payload = json.loads(latest.read_text())
    out_path = write_summary(payload)
    print(out_path)


if __name__ == "__main__":
    main()
