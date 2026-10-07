import numpy as np
import pandas as pd

from dashboard.realtime_inference import infer_market_state, prepare_bars


def records(n=700):
    rng = np.random.default_rng(4)
    close = 5000 + np.cumsum(rng.normal(0.08, 2.0, n))
    ts = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return [{"time": int(t.timestamp()), "open": c - .2, "high": c + 1,
             "low": c - 1, "close": c, "volume": 1000 + i % 100}
            for i, (t, c) in enumerate(zip(ts, close))]


def test_prepare_bars_excludes_live_bar():
    frame = prepare_bars(records(300))
    assert len(frame) == 299


def test_inference_probabilities_are_bounded_and_causal():
    full = prepare_bars(records())
    snap, history = infer_market_state(full)
    assert all(0 <= value <= 1 for value in [snap.trend_probability,
        snap.chop_probability, snap.stress_probability, snap.risk_multiplier])
    partial_snap, _ = infer_market_state(full.iloc[:-20])
    changed = full.copy()
    changed.iloc[-20:, changed.columns.get_loc("close")] += 1000
    check_snap, _ = infer_market_state(changed.iloc[:-20])
    assert partial_snap.to_dict() == check_snap.to_dict()
    assert len(history) <= 384
