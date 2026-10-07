#!/usr/bin/env python3
"""Write a concise morning summary from the latest C7 monitor snapshot."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_DIR = ROOT / "reports" / "c7_monitor"
OUT_DIR = MONITOR_DIR / "morning"


def money(value) -> str:
    return f"${float(value):,.2f}" if isinstance(value, (int, float)) else f"`{value}`"


def number(value, places: int = 3) -> str:
    return f"{float(value):.{places}f}" if isinstance(value, (int, float)) else f"`{value}`"


def table(rows: list[dict], columns: list[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
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

    rows = []
    for name in ("trusted_c2", "c6", "c7"):
        item = strategies.get(name) or {}
        closed = item.get("closed") or {}
        june = item.get("june") or {}
        rows.append(
            {
                "strategy": name,
                "net": money(closed.get("net")),
                "buy_hold": money(closed.get("buy_hold")),
                "excess": money(closed.get("excess")),
                "trades": closed.get("trades", ""),
                "PF": number(closed.get("profit_factor")),
                "DD%": number(item.get("max_drawdown_pct"), 2),
                "June": money(june.get("net")),
            }
        )

    c7 = strategies.get("c7") or {}
    c7_closed = c7.get("closed") or {}
    latest_trade = c7.get("latest_trade")

    lines = [
        f"# C7 Morning Summary - {now.strftime('%Y-%m-%d')}",
        "",
        f"Generated: `{now.isoformat(timespec='seconds')}`",
        f"Latest monitor snapshot: `{snapshot_id}`",
        f"Snapshot age: `{str(now - snapshot_dt).split('.')[0]}`" if snapshot_dt else "Snapshot age: `unknown`",
        f"Monitor status: `{status}`",
        "",
    ]

    if fired:
        lines.extend(["## Review Triggers", table([{"trigger": name} for name in fired], ["trigger"]), ""])
    else:
        lines.extend(["## Review Triggers", "None fired.", ""])

    lines.extend(
        [
            "## C7 Snapshot",
            f"- C7 net: {money(c7_closed.get('net'))}",
            f"- C7 buy-and-hold comparison: {money(c7_closed.get('buy_hold'))}",
            f"- C7 excess over buy-and-hold: {money(c7_closed.get('excess'))}",
            f"- C7 trades: `{c7_closed.get('trades')}`",
            f"- C7 profit factor: `{number(c7_closed.get('profit_factor'))}`",
            f"- C7 max drawdown: `{number(c7.get('max_drawdown_pct'), 2)}%`",
            "",
            "## Strategy Comparison",
            table(rows, ["strategy", "net", "buy_hold", "excess", "trades", "PF", "DD%", "June"]),
            "",
            "## TradingView",
            f"- Active source: `{tv.get('source_name')}`",
            f"- TV net: {money(tv.get('net'))}",
            f"- TV trades: `{tv.get('trades')}`",
            f"- TV PF: `{tv.get('profit_factor')}`",
            f"- TV max DD: {money(tv.get('max_drawdown'))}",
            f"- TV buy/hold: {money(tv.get('buy_hold_return'))}",
            "",
            "## Data Window",
            f"- First bar: `{data.get('first_bar')}`",
            f"- Last closed bar: `{data.get('last_closed_bar')}`",
            f"- Excluded latest bars: `{data.get('exclude_tail_bars')}`",
            "",
        ]
    )

    lines.append("## Latest Local C7 Trade")
    if latest_trade:
        lines.append(table([latest_trade], list(latest_trade.keys())))
    else:
        lines.append("No local C7 trade found in latest monitor snapshot.")
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
