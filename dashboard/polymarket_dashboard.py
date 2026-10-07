"""Live dashboard and paper engine for JD PM BTC 15m Late Favorite C1."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time

from flask import Flask, jsonify, send_from_directory
import requests

from polymarket.JD_PM_BTC_15m_Late_Favorite_C1 import STRATEGY_NAME, decide
from scripts.run_jd_pm_btc_15m_late_favorite_c1_paper import (
    DEFAULT_LOG, best_ask, current_market, load_state, poll_once,
)
from scripts.summarize_jd_pm_btc_15m_late_favorite_c1 import summarize


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard/polymarket_studio"
CONFIG = ROOT / "polymarket/JD_PM_BTC_15m_Late_Favorite_C1.json"
LOG = ROOT / DEFAULT_LOG
HISTORY: deque[dict] = deque(maxlen=720)
ENGINE = {"running": False, "last_poll": None, "error": None}
LOCK = threading.Lock()
app = Flask(__name__, static_folder=str(STATIC), static_url_path="/polymarket-assets")


def _records() -> list[dict]:
    signals, resolutions = {}, {}
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            record = json.loads(line)
            if record["type"] == "signal":
                signals[record["slug"]] = record
            elif record["type"] == "resolution":
                resolutions[record["slug"]] = record
    rows = []
    equity = 0.0
    for slug, signal in sorted(signals.items(), key=lambda item: item[1]["observed_at"]):
        resolution = resolutions.get(slug)
        pnl = float(resolution["pnl"]) if resolution else None
        if pnl is not None:
            equity += pnl
        rows.append({**signal, "resolved": resolution is not None,
                     "winner": resolution.get("winner") if resolution else None,
                     "won": resolution.get("won") if resolution else None,
                     "fee": resolution.get("fee") if resolution else None,
                     "pnl": pnl, "equity": equity})
    return rows


def _backtest() -> dict:
    report = json.loads((ROOT / "reports/JD_PM_BTC_15m_Late_Favorite_C1_backtest_20260715.json").read_text())
    candidate = next(item for item in report if item["entry_seconds"] == 600)
    return candidate["favorite_baseline"]["holdout"]


def _paper_loop() -> None:
    signaled, unresolved = load_state(LOG)
    session = requests.Session()
    ENGINE["running"] = True
    while True:
        try:
            poll_once(session, LOG, signaled, unresolved)
            ENGINE.update(last_poll=datetime.now(timezone.utc).isoformat(), error=None)
        except Exception as error:
            ENGINE["error"] = str(error)
        time.sleep(5)


def _live_snapshot() -> dict:
    now_float = time.time()
    now, now_ms = int(now_float), int(now_float * 1000)
    session = requests.Session()
    market = current_market(session, now)
    if not market:
        raise RuntimeError("current recurring BTC market not found")
    up_ask, up_size, up_age = best_ask(session, market["up_token"], now_ms)
    down_ask, down_size, down_age = best_ask(session, market["down_token"], now_ms)
    elapsed = now - market["start_ts"]
    quote_age = max(up_age, down_age)
    signal = decide(elapsed_seconds=elapsed, up_ask=up_ask, down_ask=down_ask,
                    quote_age_seconds=quote_age)
    favorite = "Up" if up_ask >= down_ask else "Down"
    favorite_ask = max(up_ask, down_ask)
    if elapsed < 585:
        decision = "WAITING"
        reason = f"Decision window opens in {585 - elapsed}s"
    elif elapsed <= 615:
        decision = "BUY " + signal.side.upper() if signal else "PASS"
        reason = signal.reason if signal else "Price, timing, or quote freshness gate failed"
    else:
        decision = "WINDOW CLOSED"
        reason = "Waiting for the next 15-minute contract"
    point = {"time": datetime.now(timezone.utc).isoformat(), "up": up_ask,
             "down": down_ask, "elapsed": elapsed}
    with LOCK:
        if not HISTORY or HISTORY[-1]["time"] != point["time"]:
            HISTORY.append(point)
        history = list(HISTORY)
    return {**market, "elapsed_seconds": elapsed, "remaining_seconds": max(0, 900 - elapsed),
            "up_ask": up_ask, "down_ask": down_ask, "up_size": up_size,
            "down_size": down_size, "quote_age_seconds": quote_age,
            "favorite": favorite, "favorite_ask": favorite_ask,
            "decision": decision, "reason": reason, "history": history}


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/state")
def state():
    try:
        live = _live_snapshot()
        live_error = None
    except Exception as error:
        live, live_error = None, str(error)
    rows = _records()
    status = summarize(LOG, CONFIG)
    return jsonify({"ok": live is not None, "strategy": STRATEGY_NAME,
                    "mode": "PAPER ONLY", "live": live, "live_error": live_error,
                    "engine": ENGINE.copy(), "forward": status, "trades": rows[-100:],
                    "backtest": _backtest(), "received_at": datetime.now(timezone.utc).isoformat()})


def start_engine() -> None:
    if not ENGINE["running"]:
        threading.Thread(target=_paper_loop, name="polymarket-paper-c1", daemon=True).start()


if __name__ == "__main__":
    start_engine()
    app.run(host="127.0.0.1", port=int(os.getenv("POLYMARKET_DASHBOARD_PORT", "8061")),
            debug=False, threaded=True)
