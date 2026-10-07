"""Forward paper verifier for JD PM BTC 15m Late Favorite C1."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import requests

from polymarket.JD_PM_BTC_15m_Late_Favorite_C1 import STRATEGY_NAME, decide
from polymarket.btc_15m_research import crypto_taker_fee


GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DEFAULT_LOG = Path("data/polymarket_crypto/paper/JD_PM_BTC_15m_Late_Favorite_C1.jsonl")


def request_json(session: requests.Session, url: str, **kwargs):
    response = session.get(url, timeout=15, **kwargs)
    response.raise_for_status()
    return response.json()


def current_market(session: requests.Session, now: int) -> dict | None:
    start = now - now % 900
    slug = f"btc-updown-15m-{start}"
    events = request_json(session, f"{GAMMA}/events", params={"slug": slug})
    if not events:
        return None
    market = events[0]["markets"][0]
    tokens = json.loads(market["clobTokenIds"])
    return {"slug": slug, "start_ts": start, "end_ts": start + 900,
            "condition_id": market["conditionId"], "up_token": tokens[0],
            "down_token": tokens[1]}


def best_ask(session: requests.Session, token: str, now_ms: int) -> tuple[float, float, int]:
    book = request_json(session, f"{CLOB}/book", params={"token_id": token})
    asks = [(float(level["price"]), float(level["size"])) for level in book.get("asks", [])]
    if not asks:
        raise RuntimeError(f"no asks for token {token}")
    price, size = min(asks)
    timestamp_ms = int(book.get("timestamp") or now_ms)
    return price, size, max(0, (now_ms - timestamp_ms) // 1000)


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def load_state(path: Path) -> tuple[set[str], dict[str, dict]]:
    signaled, unresolved = set(), {}
    if not path.exists():
        return signaled, unresolved
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record["type"] == "signal":
            signaled.add(record["slug"])
            unresolved[record["slug"]] = record
        elif record["type"] == "resolution":
            unresolved.pop(record["slug"], None)
    return signaled, unresolved


def resolve_pending(session: requests.Session, path: Path, unresolved: dict[str, dict], now: int) -> None:
    for slug, signal in list(unresolved.items()):
        if now < signal["end_ts"] + 30:
            continue
        events = request_json(session, f"{GAMMA}/events", params={"slug": slug})
        if not events:
            continue
        market = events[0]["markets"][0]
        prices = list(map(float, json.loads(market["outcomePrices"])))
        if max(prices) < .99:
            continue
        winner = "Up" if prices[0] > prices[1] else "Down"
        won = winner == signal["side"]
        shares = signal["shares"]
        cost = shares * signal["ask"]
        fee = crypto_taker_fee(shares, signal["ask"])
        append_record(path, {"type": "resolution", "strategy": STRATEGY_NAME,
            "slug": slug, "resolved_at": datetime.now(timezone.utc).isoformat(),
            "winner": winner, "won": won, "fee": fee,
            "pnl": (shares if won else 0) - cost - fee})
        unresolved.pop(slug, None)


def poll_once(session: requests.Session, path: Path, signaled: set[str],
              unresolved: dict[str, dict]) -> None:
    now_float = time.time()
    now, now_ms = int(now_float), int(now_float * 1000)
    resolve_pending(session, path, unresolved, now)
    market = current_market(session, now)
    if not market or market["slug"] in signaled:
        return
    elapsed = now - market["start_ts"]
    if not 585 <= elapsed <= 615:
        return
    up_ask, up_size, up_age = best_ask(session, market["up_token"], now_ms)
    down_ask, down_size, down_age = best_ask(session, market["down_token"], now_ms)
    signal = decide(elapsed_seconds=elapsed, up_ask=up_ask, down_ask=down_ask,
                    quote_age_seconds=max(up_age, down_age))
    if signal is None:
        return
    displayed_size = up_size if signal.side == "Up" else down_size
    shares = min(signal.shares, displayed_size)
    record = {"type": "signal", "strategy": STRATEGY_NAME,
        "observed_at": datetime.now(timezone.utc).isoformat(), **market,
        "elapsed_seconds": elapsed, "side": signal.side, "ask": signal.limit_price,
        "shares": shares, "displayed_size": displayed_size,
        "up_ask": up_ask, "down_ask": down_ask,
        "quote_age_seconds": max(up_age, down_age), "paper": True}
    append_record(path, record)
    signaled.add(market["slug"])
    unresolved[market["slug"]] = record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    signaled, unresolved = load_state(args.log)
    session = requests.Session()
    while True:
        try:
            poll_once(session, args.log, signaled, unresolved)
        except (requests.RequestException, RuntimeError) as error:
            print(f"network error: {error}", flush=True)
        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
