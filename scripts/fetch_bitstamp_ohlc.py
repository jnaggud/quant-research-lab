#!/usr/bin/env python3
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


def to_ts(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def fetch_chunk(pair, step, start, end):
    params = urlencode({"step": step, "limit": 1000, "start": start, "end": end})
    url = f"https://www.bitstamp.net/api/v2/ohlc/{pair}/?{params}"
    with urlopen(url, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"]["ohlc"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default="btcusd")
    parser.add_argument("--step", type=int, default=900)
    parser.add_argument("--start", default="2025-09-30T00:00:00Z")
    parser.add_argument("--end", default="2026-05-07T23:59:59Z")
    parser.add_argument("--out", default="tmp/bitstamp_btcusd_15m_20250930_20260507.json")
    args = parser.parse_args()

    start = to_ts(args.start)
    end = to_ts(args.end)
    cursor = start
    bars = {}
    while cursor <= end:
        chunk_end = min(end, cursor + args.step * 999)
        for bar in fetch_chunk(args.pair, args.step, cursor, chunk_end):
            ts = int(bar["timestamp"])
            bars[ts] = {
                "time": ts,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar["volume"]),
            }
        cursor = chunk_end + args.step
        time.sleep(0.2)

    ordered = [bars[key] for key in sorted(bars)]
    payload = {
        "source": f"bitstamp:{args.pair}",
        "step": args.step,
        "bar_count": len(ordered),
        "start": datetime.fromtimestamp(ordered[0]["time"], timezone.utc).isoformat() if ordered else None,
        "end": datetime.fromtimestamp(ordered[-1]["time"], timezone.utc).isoformat() if ordered else None,
        "bars": ordered,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: payload[k] for k in ["source", "step", "bar_count", "start", "end"]}, indent=2))


if __name__ == "__main__":
    main()
