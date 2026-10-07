"""Serve the research studio with synthetic data by default."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from flask import Flask, jsonify, send_from_directory

from dashboard.demo import live_payload, synthetic_report
from dashboard.trader_metrics import summarize_report

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(ROOT / "studio"), static_url_path="/studio-assets")
app.config["DEMO_MODE"] = os.getenv("DASHBOARD_MODE", "demo") == "demo"
_TRADER_CACHE = {"at": 0.0, "payload": None}
_TRADER_LOCK = threading.Lock()


def _read_trader() -> dict:
    if app.config["DEMO_MODE"]:
        report = synthetic_report()
        return {"ok": True, "live": False, "demo": True,
                "source": "Synthetic ledger · illustrative results",
                "strategy": report["source"]["name"], **summarize_report(report)}
    with _TRADER_LOCK:
        if _TRADER_CACHE["payload"] and time.time() - _TRADER_CACHE["at"] < 60:
            return _TRADER_CACHE["payload"]
        live = True
        source = "TradingView live strategy report"
        try:
            command = ["node", str(ROOT.parent / "scripts/export_tv_c5_strategy_data.mjs"),
                       os.getenv("TRADINGVIEW_STRATEGY_ID", ""),
                       os.getenv("TRADINGVIEW_STRATEGY_NAME", "JD ES 15m C11")]
            completed = subprocess.run(command, cwd=ROOT.parent, env={**os.environ,
                "TRADINGVIEW_CDP_PORT": os.getenv("TRADINGVIEW_CDP_PORT", "9223")},
                capture_output=True, text=True, timeout=45, check=True)
            report = json.loads(completed.stdout)
            if not report.get("success"):
                raise ValueError("TradingView report unavailable")
        except (OSError, ValueError, subprocess.SubprocessError):
            fallback = os.getenv("QUANT_TV_REPORT_FILE")
            if not fallback:
                return {"ok": False, "live": False, "error": "Connect TradingView or configure QUANT_TV_REPORT_FILE."}
            live = False
            source = "Local report snapshot"
            report = json.loads(Path(fallback).read_text())
        payload = {"ok": True, "live": live, "demo": False, "source": source,
                   "strategy": report["source"]["name"], **summarize_report(report)}
        _TRADER_CACHE.update(at=time.time(), payload=payload)
        return payload


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index():
    return send_from_directory(ROOT / "studio", "index.html")


@app.get("/api/live")
def live():
    if app.config["DEMO_MODE"]:
        return jsonify(live_payload())
    from dashboard.live_dashboard import _read_live
    payload = _read_live()
    if isinstance(payload.get("history"), str):
        payload = {**payload, "history": json.loads(payload["history"])}
    return jsonify(payload)


@app.get("/api/trader")
def trader():
    try:
        return jsonify(_read_trader())
    except (OSError, ValueError, KeyError):
        return jsonify(ok=False, live=False, error="Local strategy report is missing or invalid."), 503


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="use your local TradingView connection")
    mode.add_argument("--demo", action="store_true", help="use synthetic inputs (default)")
    parser.add_argument("--port", type=int, default=int(os.getenv("DASHBOARD_PORT", "8060")))
    args = parser.parse_args()
    if args.live or args.demo:
        app.config["DEMO_MODE"] = args.demo
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
