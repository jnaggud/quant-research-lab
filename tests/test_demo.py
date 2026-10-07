"""Public demo checks: offline operation, data integrity, and report reconciliation."""
import subprocess
import numpy as np
import pytest
from dashboard.demo import synthetic_bars, synthetic_report
from dashboard.visual_server import app


def test_synthetic_bars_are_reproducible_and_valid():
    bars = synthetic_bars()
    assert bars == synthetic_bars()
    assert all(b["high"] >= max(b["open"], b["close"]) for b in bars)
    assert all(b["low"] <= min(b["open"], b["close"]) for b in bars)
    assert all(b["volume"] >= 0 for b in bars)
    assert np.diff([b["time"] for b in bars]).tolist() == [900] * (len(bars) - 1)


def test_demo_works_without_external_processes(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The public demo must not invoke TradingView or external processes")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setitem(app.config, "DEMO_MODE", True)
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/studio-assets/studio.js").status_code == 200
    feed = client.get("/api/live").get_json()
    assert feed["ok"] and feed["demo"] and not feed["live"]
    assert feed["snapshot"]["bars_used"] == 767
    report = client.get("/api/trader").get_json()
    assert report["demo"] and not report["live"]
    expected = sum(t["tp"]["v"] for t in synthetic_report()["reportData"]["trades"])
    assert report["stats"]["net_profit"] == pytest.approx(expected)
    assert report["equity"][-1]["equity"] == pytest.approx(50_000 + expected)
    assert report["recent_trades"][0]["bars"] == 6


def test_live_mode_does_not_silently_substitute_demo(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("TradingView unavailable")
    monkeypatch.setattr(subprocess, "run", unavailable)
    monkeypatch.setitem(app.config, "DEMO_MODE", False)
    monkeypatch.delenv("QUANT_TV_REPORT_FILE", raising=False)
    report = app.test_client().get("/api/trader").get_json()
    assert not report["ok"] and not report["live"]
    assert not report.get("demo")
