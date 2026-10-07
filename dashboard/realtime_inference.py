"""Causal market-state inference for the live ES monitoring dashboard."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.special import expit


@dataclass(frozen=True)
class InferenceSnapshot:
    timestamp: str
    price: float
    direction: str
    direction_probability: float
    trend_probability: float
    chop_probability: float
    stress_probability: float
    volatility_percentile: float
    risk_multiplier: float
    confidence: float
    state: str
    bars_used: int

    def to_dict(self) -> dict:
        return asdict(self)


def prepare_bars(records: list[dict], exclude_live_bar: bool = True) -> pd.DataFrame:
    frame = pd.DataFrame(records)
    required = {"time", "open", "high", "low", "close", "volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"bars missing columns: {sorted(required - set(frame.columns))}")
    frame = frame[list(required)].copy()
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    frame = frame.sort_values("time").drop_duplicates("time").set_index("time")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    if exclude_live_bar and len(frame):
        frame = frame.iloc[:-1]
    if len(frame) < 200:
        raise ValueError(f"need at least 200 closed bars, received {len(frame)}")
    return frame


def infer_market_state(frame: pd.DataFrame) -> tuple[InferenceSnapshot, pd.DataFrame]:
    """Infer causal trend/chop/stress state using observations through each bar."""
    x = frame.copy()
    close, high, low, volume = x["close"], x["high"], x["low"], x["volume"]
    previous = close.shift(1)
    tr = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    x["return"] = close.pct_change()
    x["ema20"] = close.ewm(span=20, adjust=False).mean()
    x["ema60"] = close.ewm(span=60, adjust=False).mean()
    x["realized_vol"] = x["return"].rolling(32).std() * np.sqrt(26 * 252)
    x["vol_percentile"] = x["realized_vol"].rolling(384, min_periods=96).rank(pct=True)
    path = close.diff().abs().rolling(32).sum()
    x["efficiency"] = (close - close.shift(32)).abs() / path.replace(0, np.nan)
    side = np.sign(close - x["ema20"])
    x["crosses"] = side.ne(side.shift()).rolling(32).sum()
    x["gap_atr"] = (x["ema20"] - x["ema60"]).abs() / x["atr"].replace(0, np.nan)
    x["range_atr"] = (high - low) / x["atr"].replace(0, np.nan)
    vol_mean = volume.rolling(96).mean()
    vol_std = volume.rolling(96).std().replace(0, np.nan)
    x["volume_z"] = (volume - vol_mean) / vol_std

    x["trend_probability"] = expit(-1.4 + 1.5 * x["gap_atr"] + 3.0 * x["efficiency"] - 0.09 * x["crosses"])
    x["chop_probability"] = expit(-0.8 + 0.13 * x["crosses"] - 3.0 * x["efficiency"] - 0.6 * x["gap_atr"])
    negative_shock = (-x["return"] / x["return"].rolling(96).std().replace(0, np.nan)).clip(lower=0)
    x["stress_probability"] = expit(-3.2 + 3.4 * x["vol_percentile"] +
                                     0.7 * x["range_atr"] + 0.25 * x["volume_z"].clip(lower=0) +
                                     0.35 * negative_shock)
    direction_score = ((x["ema20"] - x["ema60"]) / x["atr"].replace(0, np.nan) +
                       (close - close.shift(16)) / (4 * x["atr"].replace(0, np.nan)))
    x["bull_probability"] = expit(direction_score)
    x["risk_multiplier"] = (1 - 0.65 * x["stress_probability"] -
                            0.15 * x["chop_probability"]).clip(0.25, 1.0)

    valid = x.dropna(subset=["trend_probability", "chop_probability", "stress_probability",
                             "vol_percentile", "bull_probability", "risk_multiplier"])
    if valid.empty:
        raise ValueError("insufficient history for inference features")
    row = valid.iloc[-1]
    probabilities = {"TREND": row.trend_probability, "CHOP": row.chop_probability,
                     "STRESS": row.stress_probability}
    state = max(probabilities, key=probabilities.get)
    bull = float(row.bull_probability)
    snapshot = InferenceSnapshot(
        timestamp=valid.index[-1].isoformat(), price=float(row.close),
        direction="BULLISH" if bull >= 0.5 else "BEARISH",
        direction_probability=float(bull if bull >= 0.5 else 1 - bull),
        trend_probability=float(row.trend_probability), chop_probability=float(row.chop_probability),
        stress_probability=float(row.stress_probability), volatility_percentile=float(row.vol_percentile),
        risk_multiplier=float(row.risk_multiplier), confidence=float(probabilities[state]),
        state=state, bars_used=int(len(frame)))
    return snapshot, x.tail(384)
