"""Download recurring BTC 15-minute Polymarket and Binance spot history."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import requests


GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
BINANCE_HOSTS = ("https://api.binance.com", "https://api.binance.us")
SERIES_ID = 10192


def get_json(session, method, url, **kwargs):
    for attempt in range(6):
        try:
            response = session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(0.5 * 2 ** attempt)


def fetch_events(limit: int) -> list[dict]:
    session = requests.Session()
    out = []
    seen = set()
    offset = 0
    end_date_max = None
    while len(out) < limit:
        page_limit = min(100, limit - len(out))
        params = {
            "series_id": SERIES_ID, "closed": "true", "limit": page_limit,
            "offset": offset, "order": "endDate", "ascending": "false"}
        if end_date_max:
            params["end_date_max"] = end_date_max
        page = get_json(session, "GET", f"{GAMMA}/events", params={
            **params})
        if not page:
            break
        for event in page:
            market = event["markets"][0]
            if market["id"] in seen:
                continue
            seen.add(market["id"])
            tokens = json.loads(market["clobTokenIds"])
            prices = list(map(float, json.loads(market["outcomePrices"])))
            end = int(datetime.fromisoformat(market["endDate"].replace("Z", "+00:00")).timestamp())
            out.append({"event_id": event["id"], "market_id": market["id"],
                        "condition_id": market["conditionId"], "slug": event["slug"],
                        "start_ts": end - 900, "end_ts": end, "up_token": tokens[0],
                        "down_token": tokens[1], "outcome": int(prices[0] > prices[1]),
                        "volume": float(market.get("volume") or 0),
                        "fees_enabled": bool(market.get("feesEnabled"))})
        print(f"events {len(out):,}/{limit:,}", flush=True)
        offset += page_limit
        if offset >= 2000 and len(out) < limit:
            oldest_end = min(x["end_ts"] for x in out)
            end_date_max = datetime.fromtimestamp(oldest_end - 1, timezone.utc).isoformat()
            offset = 0
    return sorted(out, key=lambda x: x["start_ts"])


def fetch_price_batch(batch: list[dict]) -> dict:
    session = requests.Session()
    body = {"markets": [x["up_token"] for x in batch],
            "start_ts": min(x["start_ts"] for x in batch),
            "end_ts": max(x["end_ts"] for x in batch), "fidelity": 1}
    return get_json(session, "POST", f"{CLOB}/batch-prices-history", json=body)["history"]


def fetch_trade_history(market: dict) -> tuple[str, list[dict]]:
    session = requests.Session()
    trades = get_json(session, "GET", f"{DATA_API}/trades", params={
        "market": market["condition_id"], "limit": 10000, "takerOnly": "false"})
    points = []
    for trade in trades:
        price = float(trade["price"])
        up_price = price if trade["outcome"].lower() == "up" else 1 - price
        points.append({"t": int(trade["timestamp"]), "p": up_price})
    points.sort(key=lambda x: x["t"])
    return market["up_token"], points


def fetch_binance(start_ms: int, end_ms: int) -> list:
    last_error = None
    for host in BINANCE_HOSTS:
        session = requests.Session()
        out = []
        cursor = start_ms
        try:
            while cursor < end_ms:
                rows = get_json(session, "GET", f"{host}/api/v3/klines", params={
                    "symbol": "BTCUSDT", "interval": "1m", "startTime": cursor,
                    "endTime": end_ms, "limit": 1000})
                if not rows:
                    break
                out.extend(rows)
                cursor = int(rows[-1][0]) + 60_000
                print(f"spot minutes {len(out):,} via {host}", flush=True)
            if out:
                return out
        except requests.RequestException as error:
            last_error = error
    raise RuntimeError("all Binance spot-data hosts failed") from last_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--markets", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--out", type=Path, default=Path("data/polymarket_crypto/btc_15m"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    markets_path = args.out / "markets.json"
    histories_path = args.out / "up_price_history.json"
    if markets_path.exists() and histories_path.exists():
        events = json.loads(markets_path.read_text())
        histories = json.loads(histories_path.read_text())
        if len(events) < args.markets:
            raise RuntimeError("saved market index is incomplete; remove it before retrying")
        events = events[-args.markets:]
        print(f"resuming with {len(events):,} saved markets and {len(histories):,} histories")
    else:
        events = fetch_events(args.markets)
        markets_path.write_text(json.dumps(events, indent=2))
        batches = [events[i:i + 20] for i in range(0, len(events), 20)]
        histories = {}
        with ThreadPoolExecutor(max_workers=min(32, args.workers)) as pool:
            futures = [pool.submit(fetch_price_batch, batch) for batch in batches]
            for i, future in enumerate(as_completed(futures), 1):
                histories.update(future.result())
                print(f"price batches {i:,}/{len(batches):,}", flush=True)
        histories_path.write_text(json.dumps(histories))
    missing = [event for event in events if not histories.get(event["up_token"])]
    if missing:
        print(f"reconstructing {len(missing):,} histories from public trades", flush=True)
        with ThreadPoolExecutor(max_workers=min(32, args.workers)) as pool:
            futures = [pool.submit(fetch_trade_history, market) for market in missing]
            for i, future in enumerate(as_completed(futures), 1):
                token, points = future.result()
                if points:
                    histories[token] = points
                if i % 100 == 0 or i == len(futures):
                    print(f"trade histories {i:,}/{len(futures):,}", flush=True)
        histories_path.write_text(json.dumps(histories))
    rows = fetch_binance((events[0]["start_ts"] - 7200) * 1000,
                         (events[-1]["end_ts"] + 60) * 1000)
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time",
               "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
    import pandas as pd
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(args.out / "btcusdt_1m.csv.gz", index=False, compression="gzip")
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "markets": len(events),
                "price_histories": len(histories), "spot_minutes": len(frame), "workers": args.workers}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
