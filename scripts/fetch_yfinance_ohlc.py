#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import pandas as pd
import yfinance as yf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", default="60d")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--out", required=True)
    parser.add_argument("--prepost", action="store_true")
    args = parser.parse_args()

    df = yf.download(
        args.symbol,
        period=args.period,
        interval=args.interval,
        auto_adjust=False,
        progress=False,
        prepost=args.prepost,
        threads=False,
    )
    if df.empty:
        raise SystemExit(f"No data returned for {args.symbol} {args.period} {args.interval}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower().replace(" ", "_") for col in df.columns]
    else:
        df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]

    df = df.rename(columns={"adj_close": "adj_close"})
    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise SystemExit(f"Missing columns: {missing}; got {list(df.columns)}")

    df = df[required].dropna().sort_index()
    if df.empty:
        raise SystemExit("No usable OHLCV rows after cleanup")

    bars = []
    for timestamp, row in df.iterrows():
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        bars.append({
            "time": int(timestamp.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        })

    payload = {
        "symbol": args.symbol,
        "resolution": args.interval,
        "period": args.period,
        "source": "yfinance",
        "bar_count": len(bars),
        "start_utc": pd.to_datetime(bars[0]["time"], unit="s", utc=True).isoformat(),
        "end_utc": pd.to_datetime(bars[-1]["time"], unit="s", utc=True).isoformat(),
        "bars": bars,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps({k: payload[k] for k in ["symbol", "resolution", "period", "bar_count", "start_utc", "end_utc"]}, indent=2))


if __name__ == "__main__":
    main()
