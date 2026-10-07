#!/usr/bin/env python3
import os
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

ROOT = Path(__file__).resolve().parents[1]
PATTERN_FINDR = Path(os.getenv("PATTERN_FINDR_ROOT", "../Pattern_FindR"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
if str(PATTERN_FINDR) not in sys.path:
    sys.path.insert(0, str(PATTERN_FINDR))

from optimize_15m_mtf_reversal import load_json
from optimize_cl_15m_active_router_mp import directional_regime, make_regimes
from optimize_cl_15m_hybrid_sleeve_mp import CORE_PARAMS, add_research_features, build_features


DEFAULT_PARAMS_REPORT = ROOT / "reports/cl_15m_hybrid_sleeve_32k.json"
DEFAULT_DATA = ROOT / "tmp/tv_cl1_15m_loaded_full_raw.json"
DEFAULT_VELOCITY_CONFIG = (
    PATTERN_FINDR
    / "velocity_strategies/velocity_CL=F_15m_v15/velocity_config.json"
)


def load_ohlcv(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".json":
        return load_json(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    columns = {c.lower(): c for c in df.columns}
    if "datetime" in columns:
        df["datetime"] = pd.to_datetime(df[columns["datetime"]], utc=True)
        df = df.set_index("datetime")
    elif "time" in columns:
        time_col = df[columns["time"]]
        if np.issubdtype(time_col.dtype, np.number):
            df["datetime"] = pd.to_datetime(time_col, unit="s", utc=True)
        else:
            df["datetime"] = pd.to_datetime(time_col, utc=True)
        df = df.set_index("datetime")
    elif not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"{path} needs a datetime/time column or DatetimeIndex")
    df = df.rename(columns={v: k for k, v in columns.items()})
    return df[["open", "high", "low", "close", "volume"]].sort_index().astype(float)


def load_strategy_params(path: Path) -> dict:
    payload = json.loads(path.read_text())
    if "best" in payload and "params" in payload["best"]:
        params = dict(CORE_PARAMS)
        params.update(payload["best"]["params"])
        return params
    if "params" in payload:
        params = dict(CORE_PARAMS)
        params.update(payload["params"])
        return params
    params = dict(CORE_PARAMS)
    params.update(payload)
    return params


def load_velocity_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def add_legacy_velocity_marks(feat: pd.DataFrame, config: dict) -> pd.DataFrame:
    out = feat.copy()
    out["legacy_buy"] = False
    out["legacy_sell"] = False
    out["legacy_osc"] = np.nan
    out["legacy_velocity"] = np.nan
    out["legacy_acceleration"] = np.nan
    out["legacy_jerk"] = np.nan
    if not config:
        return out
    try:
        from novel_indicators import calculate_arwo, calculate_ewaf, calculate_vcmo
        from velocity_trading.indicators.velocity import calculate_velocity_signals
    except Exception as exc:
        out.attrs["legacy_velocity_error"] = str(exc)
        return out

    oscillator_type = config.get("oscillator_type", "vcmo")
    source = out[["open", "high", "low", "close", "volume"]].copy()
    if oscillator_type == "vcmo":
        source["osc_smooth"] = calculate_vcmo(source)
    elif oscillator_type == "arwo":
        source["osc_smooth"] = calculate_arwo(source)
    elif oscillator_type == "ewaf":
        source["osc_smooth"] = calculate_ewaf(source)
    else:
        source["osc_smooth"] = (source["close"].pct_change().rolling(10, min_periods=1).mean() * 100).fillna(0.0)

    marked = calculate_velocity_signals(
        source,
        signal_type=config.get("signal_type", "any_reversal"),
        oversold_threshold=float(config.get("oversold_threshold", -0.3)),
        overbought_threshold=float(config.get("overbought_threshold", 0.3)),
        velocity_threshold=float(config.get("vel_threshold", 0.0)),
        vel_smoothing=int(config.get("vel_smoothing", 1)),
        extreme_zone_mult=float(config.get("extreme_zone_mult", 1.5)),
        require_accel=bool(config.get("require_accel", False)),
        rsi_filter=config.get("rsi_filter", "none"),
        rsi_period=int(config.get("rsi_period", 14)),
        rsi_oversold=float(config.get("rsi_oversold", 30)),
        rsi_overbought=float(config.get("rsi_overbought", 70)),
        use_macd_confirm=bool(config.get("use_macd_confirm", False)),
        use_bb_filter=bool(config.get("use_bb_filter", False)),
    )
    for source_col, target_col in [
        ("buy_signal", "legacy_buy"),
        ("sell_signal", "legacy_sell"),
        ("osc_smooth", "legacy_osc"),
        ("velocity", "legacy_velocity"),
        ("acceleration", "legacy_acceleration"),
        ("jerk", "legacy_jerk"),
    ]:
        if source_col in marked:
            out[target_col] = marked[source_col].reindex(out.index)
    return out


def reduce_cluster(indices: list[int], values: np.ndarray, min_gap: int, prefer_low: bool) -> list[int]:
    if not indices:
        return []
    kept = []
    cluster = [indices[0]]
    for idx in indices[1:]:
        if idx - cluster[-1] <= min_gap:
            cluster.append(idx)
        else:
            best = min(cluster, key=lambda i: values[i]) if prefer_low else max(cluster, key=lambda i: values[i])
            kept.append(best)
            cluster = [idx]
    best = min(cluster, key=lambda i: values[i]) if prefer_low else max(cluster, key=lambda i: values[i])
    kept.append(best)
    return kept


def mark_truth_extrema(feat: pd.DataFrame, pivot_bars: int, lookahead_bars: int, min_move_atr: float, min_gap_bars: int) -> pd.DataFrame:
    out = feat.copy()
    lows = out["low"].to_numpy(float)
    highs = out["high"].to_numpy(float)
    atr = out["atr"].replace(0, np.nan).to_numpy(float)
    valley_candidates = []
    peak_candidates = []
    for i in range(pivot_bars, len(out) - max(pivot_bars, lookahead_bars)):
        local_low = np.nanmin(lows[i - pivot_bars : i + pivot_bars + 1])
        local_high = np.nanmax(highs[i - pivot_bars : i + pivot_bars + 1])
        forward_high = np.nanmax(highs[i + 1 : i + lookahead_bars + 1])
        forward_low = np.nanmin(lows[i + 1 : i + lookahead_bars + 1])
        move = min_move_atr * atr[i] if np.isfinite(atr[i]) else np.inf
        if lows[i] <= local_low and forward_high - lows[i] >= move:
            valley_candidates.append(i)
        if highs[i] >= local_high and highs[i] - forward_low >= move:
            peak_candidates.append(i)
    valleys = reduce_cluster(valley_candidates, lows, min_gap_bars, True)
    peaks = reduce_cluster(peak_candidates, highs, min_gap_bars, False)
    out["truth_valley"] = False
    out["truth_peak"] = False
    out.iloc[valleys, out.columns.get_loc("truth_valley")] = True
    out.iloc[peaks, out.columns.get_loc("truth_peak")] = True
    out.attrs["truth_method"] = "pivot"
    out.attrs["truth_prominence_threshold"] = None
    return out


def mark_truth_scipy_price(feat: pd.DataFrame, prominence_pct: float, distance: int) -> pd.DataFrame:
    out = feat.copy()
    avg_price = out["close"].mean()
    prominence_threshold = avg_price * (prominence_pct / 100.0)
    peak_indices, _ = find_peaks(out["high"].to_numpy(float), prominence=prominence_threshold, distance=distance)
    valley_indices, _ = find_peaks(-out["low"].to_numpy(float), prominence=prominence_threshold, distance=distance)
    out["truth_valley"] = False
    out["truth_peak"] = False
    if len(valley_indices):
        out.iloc[valley_indices, out.columns.get_loc("truth_valley")] = True
    if len(peak_indices):
        out.iloc[peak_indices, out.columns.get_loc("truth_peak")] = True
    out.attrs["truth_method"] = "scipy_price"
    out.attrs["truth_prominence_threshold"] = prominence_threshold
    return out


def mark_truth_scipy_oscillator(feat: pd.DataFrame, prominence: float, distance: int, lookahead: int) -> pd.DataFrame:
    out = feat.copy()
    oscillator = out["legacy_osc"].fillna(0.0).to_numpy(float)
    peak_indices, _ = find_peaks(oscillator, prominence=prominence, distance=distance)
    valley_indices, _ = find_peaks(-oscillator, prominence=prominence, distance=distance)
    out["truth_valley"] = False
    out["truth_peak"] = False
    for idx in valley_indices:
        start = max(0, idx - lookahead)
        out.iloc[start : idx + 1, out.columns.get_loc("truth_valley")] = True
    for idx in peak_indices:
        start = max(0, idx - lookahead)
        out.iloc[start : idx + 1, out.columns.get_loc("truth_peak")] = True
    out.attrs["truth_method"] = "scipy_oscillator"
    out.attrs["truth_prominence_threshold"] = prominence
    return out


def bool_series(values):
    return pd.Series(values).fillna(False).astype(bool).to_numpy(bool)


def compute_strategy_debug(feat: pd.DataFrame, params: dict) -> tuple[pd.DataFrame, list[dict]]:
    out = feat.copy()
    h4_signal, daily_signal = make_regimes(out, params)
    close = out["close"].to_numpy(float)
    high = out["high"].to_numpy(float)
    low = out["low"].to_numpy(float)
    volume = out["volume"].to_numpy(float)
    atr = out["atr"].to_numpy(float)
    adx = out["adx"].to_numpy(float)
    rsi = out["rsi"].to_numpy(float)
    stoch_k = out["stoch_k"].to_numpy(float)
    stoch_d = out["stoch_d"].to_numpy(float)
    macd = out["macdh"].to_numpy(float)
    ema21 = out["ema21"].to_numpy(float)
    ema55 = out["ema55"].to_numpy(float)
    vol_sma = out["vol_sma"].to_numpy(float)
    bb_upper = out["bb_upper"].to_numpy(float)
    bb_lower = out["bb_lower"].to_numpy(float)
    vwap = out["vwap"].to_numpy(float)
    prev_high = out["prev_day_high"].to_numpy(float)
    prev_low = out["prev_day_low"].to_numpy(float)
    atr_rel = out["atr_rel"].to_numpy(float)
    vol_rank = out["vol_rank"].to_numpy(float)
    vwap_dist = out["vwap_dist_atr"].to_numpy(float)
    adx_slope = out["adx_slope_8"].to_numpy(float)
    ny_hour = out["ny_hour"].to_numpy(int)

    core_vol_ok = volume >= params["vol_mult"] * vol_sma
    core_trend_state = adx >= params["trend_adx"]
    core_long = np.zeros(len(out), dtype=bool)
    core_short = np.zeros(len(out), dtype=bool)
    sleeve_long = np.zeros(len(out), dtype=bool)
    sleeve_short = np.zeros(len(out), dtype=bool)
    sleeve_allowed = np.zeros(len(out), dtype=bool)
    long_location = np.zeros(len(out), dtype=bool)
    short_location = np.zeros(len(out), dtype=bool)
    k_cross_up = np.zeros(len(out), dtype=bool)
    k_cross_down = np.zeros(len(out), dtype=bool)

    def in_session(hour, start, end):
        return start <= hour <= end if start <= end else hour >= start or hour <= end

    for i in range(1, len(out)):
        k_cross_up[i] = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
        k_cross_down[i] = stoch_k[i - 1] >= stoch_d[i - 1] and stoch_k[i] < stoch_d[i]
        core_long[i] = (
            core_trend_state[i]
            and directional_regime(params["trend_mode"], h4_signal[i], daily_signal[i], 1)
            and close[i] > ema55[i]
            and close[i] <= ema21[i] + params["pullback_atr"] * atr[i]
            and rsi[i] >= params["trend_long_rsi"]
            and macd[i] >= params["trend_macd_floor"]
            and core_vol_ok[i]
        )
        core_short[i] = (
            core_trend_state[i]
            and directional_regime(params["trend_mode"], h4_signal[i], daily_signal[i], -1)
            and close[i] < ema55[i]
            and close[i] >= ema21[i] - params["pullback_atr"] * atr[i]
            and rsi[i] <= params["trend_short_rsi"]
            and macd[i] <= -params["trend_macd_floor"]
            and core_vol_ok[i]
        )
        sleeve_allowed[i] = (
            params.get("use_sleeve", True)
            and not core_trend_state[i]
            and adx[i] <= params["sleeve_adx_max"]
            and adx_slope[i] <= params["sleeve_adx_slope_max"]
            and params["atr_rel_min"] <= atr_rel[i] <= params["atr_rel_max"]
            and params["vol_rank_min"] <= vol_rank[i] <= params["vol_rank_max"]
            and in_session(ny_hour[i], params["ny_start_hour"], params["ny_end_hour"])
        )
        near_prev_low = close[i] <= prev_low[i] + params["prev_level_atr"] * atr[i]
        near_prev_high = close[i] >= prev_high[i] - params["prev_level_atr"] * atr[i]
        long_location[i] = close[i] < bb_lower[i] + params["bb_atr"] * atr[i] or near_prev_low
        short_location[i] = close[i] > bb_upper[i] - params["bb_atr"] * atr[i] or near_prev_high
        sleeve_long[i] = (
            sleeve_allowed[i]
            and params.get("allow_sleeve_longs", True)
            and vwap_dist[i] <= -params["vwap_dist_atr"]
            and long_location[i]
            and rsi[i] <= params["sleeve_long_rsi"]
            and (k_cross_up[i] or stoch_k[i] <= params["sleeve_stoch"])
            and daily_signal[i] != -1
        )
        sleeve_short[i] = (
            sleeve_allowed[i]
            and params.get("allow_sleeve_shorts", True)
            and vwap_dist[i] >= params["vwap_dist_atr"]
            and short_location[i]
            and rsi[i] >= params["sleeve_short_rsi"]
            and (k_cross_down[i] or stoch_k[i] >= 100.0 - params["sleeve_stoch"])
            and daily_signal[i] != 1
        )

    out["h4_signal"] = h4_signal
    out["daily_signal"] = daily_signal
    out["core_trend_state"] = core_trend_state
    out["core_vol_ok"] = core_vol_ok
    out["core_long"] = core_long
    out["core_short"] = core_short
    out["sleeve_allowed"] = sleeve_allowed
    out["long_location"] = long_location
    out["short_location"] = short_location
    out["sleeve_long"] = sleeve_long
    out["sleeve_short"] = sleeve_short
    out["k_cross_up"] = k_cross_up
    out["k_cross_down"] = k_cross_down
    out["long_setup"] = core_long | sleeve_long
    out["short_setup"] = core_short | sleeve_short

    pos = 0
    kind = 0
    entry = entry_high = entry_low = 0.0
    entry_i = None
    last_exit = -100000
    trades = []
    position = np.zeros(len(out), dtype=int)
    active_kind = np.zeros(len(out), dtype=int)
    entry_blocked_position = np.zeros(len(out), dtype=bool)
    entry_blocked_cooldown = np.zeros(len(out), dtype=bool)
    long_entry = np.zeros(len(out), dtype=bool)
    short_entry = np.zeros(len(out), dtype=bool)
    exit_signal = np.zeros(len(out), dtype=bool)
    exit_reason = np.array([""] * len(out), dtype=object)

    for i in range(max(300, 1), len(out)):
        if pos:
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            bars_held = i - entry_i
            if kind == 1:
                stop_atr = params["stop_atr"]
                target_atr = params["target_atr"]
                trail_atr = params["trail_atr"]
                min_hold = params["min_hold"]
                max_hold = params["max_hold"]
            else:
                stop_atr = params["sleeve_stop_atr"]
                target_atr = params["sleeve_target_atr"]
                trail_atr = params["sleeve_trail_atr"]
                min_hold = params["sleeve_min_hold"]
                max_hold = params["sleeve_max_hold"]
            reason = None
            price = None
            if pos == 1:
                stop = max(entry - stop_atr * atr[i], entry_high - trail_atr * atr[i])
                target = entry + target_atr * atr[i]
                if low[i] <= stop:
                    reason, price = "risk_stop", stop
                elif high[i] >= target:
                    reason, price = "target", target
                elif bars_held >= max_hold:
                    reason, price = "time", close[i]
                elif kind == 1 and bars_held >= min_hold and h4_signal[i] == -1 and daily_signal[i] != 1:
                    reason, price = "core_regime", close[i]
                elif kind == 1 and bars_held >= min_hold and macd[i] < macd[i - 1] and rsi[i] < params["long_exit_rsi"]:
                    reason, price = "core_momentum", close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] >= vwap[i] + params["sleeve_exit_vwap_atr"] * atr[i]:
                    reason, price = "sleeve_vwap", close[i]
            else:
                stop = min(entry + stop_atr * atr[i], entry_low + trail_atr * atr[i])
                target = entry - target_atr * atr[i]
                if high[i] >= stop:
                    reason, price = "risk_stop", stop
                elif low[i] <= target:
                    reason, price = "target", target
                elif bars_held >= max_hold:
                    reason, price = "time", close[i]
                elif kind == 1 and bars_held >= min_hold and h4_signal[i] == 1 and daily_signal[i] != -1:
                    reason, price = "core_regime", close[i]
                elif kind == 1 and bars_held >= min_hold and macd[i] > macd[i - 1] and rsi[i] > params["short_exit_rsi"]:
                    reason, price = "core_momentum", close[i]
                elif kind == 2 and bars_held >= min_hold and close[i] <= vwap[i] - params["sleeve_exit_vwap_atr"] * atr[i]:
                    reason, price = "sleeve_vwap", close[i]
            if reason:
                trades.append(
                    {
                        "side": "long" if pos == 1 else "short",
                        "kind": "core" if kind == 1 else "sleeve",
                        "entry_time": out.index[entry_i].isoformat(),
                        "exit_time": out.index[i].isoformat(),
                        "entry": entry,
                        "exit": float(price),
                        "bars": bars_held,
                        "reason": reason,
                    }
                )
                exit_signal[i] = True
                exit_reason[i] = reason
                pos = 0
                kind = 0
                entry_i = None
                last_exit = i

        if pos == 0:
            cooldown_core = i - last_exit >= params["cooldown"]
            cooldown_sleeve = i - last_exit >= params["sleeve_cooldown"]
            if cooldown_core and core_long[i]:
                pos, kind, entry, entry_i = 1, 1, close[i], i
                entry_high, entry_low = high[i], low[i]
                long_entry[i] = True
            elif cooldown_core and core_short[i]:
                pos, kind, entry, entry_i = -1, 1, close[i], i
                entry_high, entry_low = high[i], low[i]
                short_entry[i] = True
            elif cooldown_sleeve and sleeve_long[i]:
                pos, kind, entry, entry_i = 1, 2, close[i], i
                entry_high, entry_low = high[i], low[i]
                long_entry[i] = True
            elif cooldown_sleeve and sleeve_short[i]:
                pos, kind, entry, entry_i = -1, 2, close[i], i
                entry_high, entry_low = high[i], low[i]
                short_entry[i] = True
            elif (core_long[i] or core_short[i]) and not cooldown_core:
                entry_blocked_cooldown[i] = True
            elif (sleeve_long[i] or sleeve_short[i]) and not cooldown_sleeve:
                entry_blocked_cooldown[i] = True
        else:
            if out["long_setup"].iloc[i] or out["short_setup"].iloc[i]:
                entry_blocked_position[i] = True
        position[i] = pos
        active_kind[i] = kind

    out["position"] = position
    out["active_kind"] = active_kind
    out["long_entry"] = long_entry
    out["short_entry"] = short_entry
    out["exit_signal"] = exit_signal
    out["exit_reason"] = exit_reason
    out["entry_blocked_position"] = entry_blocked_position
    out["entry_blocked_cooldown"] = entry_blocked_cooldown
    return out, trades


LONG_BLOCKERS = [
    "already_in_position",
    "cooldown",
    "core_trend_state_false",
    "core_direction_false",
    "core_price_below_ema55",
    "core_pullback_false",
    "core_rsi_low",
    "core_macd_low",
    "core_volume_low",
    "sleeve_allowed_false",
    "sleeve_vwap_not_deep",
    "sleeve_location_false",
    "sleeve_rsi_too_high",
    "sleeve_stoch_false",
    "sleeve_daily_bearish",
]


def long_blockers(row: pd.Series, params: dict) -> list[str]:
    blockers = []
    if row["position"] != 0:
        blockers.append("already_in_position")
    if row["entry_blocked_cooldown"]:
        blockers.append("cooldown")
    if not row["core_trend_state"]:
        blockers.append("core_trend_state_false")
    if not directional_regime(params["trend_mode"], int(row["h4_signal"]), int(row["daily_signal"]), 1):
        blockers.append("core_direction_false")
    if not row["close"] > row["ema55"]:
        blockers.append("core_price_below_ema55")
    if not row["close"] <= row["ema21"] + params["pullback_atr"] * row["atr"]:
        blockers.append("core_pullback_false")
    if not row["rsi"] >= params["trend_long_rsi"]:
        blockers.append("core_rsi_low")
    if not row["macdh"] >= params["trend_macd_floor"]:
        blockers.append("core_macd_low")
    if not row["core_vol_ok"]:
        blockers.append("core_volume_low")
    if not row["sleeve_allowed"]:
        blockers.append("sleeve_allowed_false")
    if not row["vwap_dist_atr"] <= -params["vwap_dist_atr"]:
        blockers.append("sleeve_vwap_not_deep")
    if not row["long_location"]:
        blockers.append("sleeve_location_false")
    if not row["rsi"] <= params["sleeve_long_rsi"]:
        blockers.append("sleeve_rsi_too_high")
    stoch_ok = row["stoch_k"] <= params["sleeve_stoch"] or bool(row.get("k_cross_up", False))
    if not stoch_ok:
        blockers.append("sleeve_stoch_false")
    if row["daily_signal"] == -1:
        blockers.append("sleeve_daily_bearish")
    return blockers


def nearest_true_index(mask: np.ndarray, center: int, before: int, after: int) -> int | None:
    start = max(0, center - before)
    end = min(len(mask), center + after + 1)
    hits = np.flatnonzero(mask[start:end])
    if len(hits) == 0:
        return None
    return int(start + hits[np.argmin(np.abs((start + hits) - center))])


def build_truth_report(debug: pd.DataFrame, params: dict, tolerance: int, context_start: str | None, context_end: str | None) -> tuple[dict, pd.DataFrame]:
    long_entries = debug["long_entry"].to_numpy(bool)
    exits = debug["exit_signal"].to_numpy(bool)
    valleys = np.flatnonzero(debug["truth_valley"].to_numpy(bool))
    peaks = np.flatnonzero(debug["truth_peak"].to_numpy(bool))
    rows = []
    blocker_counts = Counter()
    for idx in valleys:
        nearest = nearest_true_index(long_entries, idx, before=1, after=tolerance)
        missed = nearest is None
        blockers = [] if not missed else long_blockers(debug.iloc[idx], params)
        blocker_counts.update(blockers)
        rows.append(
            {
                "type": "truth_valley",
                "time": debug.index[idx].isoformat(),
                "price": float(debug["low"].iloc[idx]),
                "matched_strategy_time": debug.index[nearest].isoformat() if nearest is not None else "",
                "matched_lag_bars": int(nearest - idx) if nearest is not None else "",
                "missed": missed,
                "legacy_buy": bool(debug["legacy_buy"].iloc[idx]) if "legacy_buy" in debug else False,
                "legacy_osc": float(debug["legacy_osc"].iloc[idx]) if "legacy_osc" in debug and pd.notna(debug["legacy_osc"].iloc[idx]) else np.nan,
                "rsi": float(debug["rsi"].iloc[idx]),
                "adx": float(debug["adx"].iloc[idx]),
                "atr_rel": float(debug["atr_rel"].iloc[idx]),
                "vwap_dist_atr": float(debug["vwap_dist_atr"].iloc[idx]),
                "h4_signal": int(debug["h4_signal"].iloc[idx]),
                "daily_signal": int(debug["daily_signal"].iloc[idx]),
                "blockers": ", ".join(blockers),
            }
        )
    peak_exit_misses = 0
    for idx in peaks:
        nearest = nearest_true_index(exits, idx, before=1, after=tolerance)
        if nearest is None:
            peak_exit_misses += 1
    report_df = pd.DataFrame(rows)
    scoped = debug
    if context_start:
        scoped = scoped[scoped.index >= pd.Timestamp(context_start, tz="UTC")]
    if context_end:
        scoped = scoped[scoped.index <= pd.Timestamp(context_end, tz="UTC")]
    scoped_valleys = int(scoped["truth_valley"].sum())
    scoped_entries = int(scoped["long_entry"].sum())
    scoped_peaks = int(scoped["truth_peak"].sum())
    scoped_exits = int(scoped["exit_signal"].sum())
    summary = {
        "data_start": debug.index.min().isoformat(),
        "data_end": debug.index.max().isoformat(),
        "truth_method": debug.attrs.get("truth_method", "unknown"),
        "truth_prominence_threshold": debug.attrs.get("truth_prominence_threshold"),
        "bars": int(len(debug)),
        "truth_valleys": int(len(valleys)),
        "truth_peaks": int(len(peaks)),
        "strategy_long_entries": int(debug["long_entry"].sum()),
        "strategy_short_entries": int(debug["short_entry"].sum()),
        "strategy_exits": int(debug["exit_signal"].sum()),
        "missed_truth_valleys": int(report_df["missed"].sum()) if not report_df.empty else 0,
        "matched_truth_valleys": int((~report_df["missed"]).sum()) if not report_df.empty else 0,
        "missed_truth_peak_exits": int(peak_exit_misses),
        "top_long_entry_blockers": blocker_counts.most_common(15),
        "context": {
            "start": context_start,
            "end": context_end,
            "truth_valleys": scoped_valleys,
            "truth_peaks": scoped_peaks,
            "long_entries": scoped_entries,
            "exits": scoped_exits,
        },
    }
    return summary, report_df


def write_markdown(path: Path, summary: dict, misses: pd.DataFrame, trades: list[dict]) -> None:
    lines = [
        "# CL 15m Truth/Missed-Signal Diagnostic",
        "",
        "This report compares hindsight local extrema and legacy velocity reversal marks against the current CL hybrid sleeve gates.",
        "",
        "## Summary",
        "",
    ]
    for key in [
        "data_start",
        "data_end",
        "truth_method",
        "truth_prominence_threshold",
        "bars",
        "truth_valleys",
        "truth_peaks",
        "strategy_long_entries",
        "strategy_short_entries",
        "strategy_exits",
        "missed_truth_valleys",
        "matched_truth_valleys",
        "missed_truth_peak_exits",
    ]:
        lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "## Top Long Entry Blockers", ""])
    for name, count in summary["top_long_entry_blockers"]:
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Context Window", ""])
    for key, value in summary["context"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Recent Missed Truth Valleys", ""])
    if misses.empty:
        lines.append("- No truth valleys found.")
    else:
        sample = misses[misses["missed"]].tail(25)
        if sample.empty:
            lines.append("- No missed truth valleys in the sample.")
        for _, row in sample.iterrows():
            lines.append(f"- {row['time']} low={row['price']:.2f}; blockers={row['blockers']}")
    lines.extend(["", "## Recent Trades", ""])
    for trade in trades[-20:]:
        lines.append(f"- {trade['side']} {trade['kind']} {trade['entry_time']} -> {trade['exit_time']} reason={trade['reason']} entry={trade['entry']:.2f} exit={trade['exit']:.2f}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--params", type=Path, default=DEFAULT_PARAMS_REPORT)
    parser.add_argument("--velocity-config", type=Path, default=DEFAULT_VELOCITY_CONFIG)
    parser.add_argument("--pivot-bars", type=int, default=4)
    parser.add_argument("--lookahead-bars", type=int, default=24)
    parser.add_argument("--min-move-atr", type=float, default=1.2)
    parser.add_argument("--min-gap-bars", type=int, default=6)
    parser.add_argument("--truth-method", choices=["scipy_price", "scipy_oscillator", "pivot"], default="scipy_price")
    parser.add_argument("--prominence-pct", type=float, default=1.0)
    parser.add_argument("--osc-prominence", type=float, default=0.15)
    parser.add_argument("--peak-distance", type=int, default=5)
    parser.add_argument("--match-tolerance-bars", type=int, default=4)
    parser.add_argument("--context-start", default=None, help="UTC timestamp, e.g. 2026-05-18T00:00:00Z")
    parser.add_argument("--context-end", default=None, help="UTC timestamp, e.g. 2026-05-19T00:00:00Z")
    parser.add_argument("--out-prefix", type=Path, default=ROOT / "reports/cl_15m_truth_miss_diagnostic")
    args = parser.parse_args()

    raw = load_ohlcv(args.data)
    params = load_strategy_params(args.params)
    velocity_config = load_velocity_config(args.velocity_config)
    feat = add_research_features(build_features(raw))
    feat = add_legacy_velocity_marks(feat, velocity_config)
    if args.truth_method == "scipy_price":
        feat = mark_truth_scipy_price(feat, args.prominence_pct, args.peak_distance)
    elif args.truth_method == "scipy_oscillator":
        feat = mark_truth_scipy_oscillator(feat, args.osc_prominence, args.peak_distance, args.lookahead_bars)
    else:
        feat = mark_truth_extrema(feat, args.pivot_bars, args.lookahead_bars, args.min_move_atr, args.min_gap_bars)
    debug, trades = compute_strategy_debug(feat, params)
    summary, misses = build_truth_report(debug, params, args.match_tolerance_bars, args.context_start, args.context_end)

    args.out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = args.out_prefix.with_suffix(".json")
    csv_path = args.out_prefix.with_suffix(".csv")
    md_path = args.out_prefix.with_suffix(".md")
    debug_path = args.out_prefix.with_name(args.out_prefix.name + "_bars.csv")
    json_path.write_text(json.dumps({"summary": summary, "trades": trades}, indent=2))
    misses.to_csv(csv_path, index=False)
    cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "rsi",
        "adx",
        "macdh",
        "atr",
        "atr_rel",
        "vol_rank",
        "vwap_dist_atr",
        "h4_signal",
        "daily_signal",
        "truth_valley",
        "truth_peak",
        "legacy_buy",
        "legacy_sell",
        "core_long",
        "core_short",
        "sleeve_long",
        "sleeve_short",
        "k_cross_up",
        "k_cross_down",
        "long_entry",
        "short_entry",
        "exit_signal",
        "exit_reason",
        "position",
        "active_kind",
    ]
    debug[cols].to_csv(debug_path)
    write_markdown(md_path, summary, misses, trades)
    print(json.dumps(summary, indent=2))
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {debug_path}")


if __name__ == "__main__":
    main()
