#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from optimize_15m_mtf_reversal import load_json
from optimize_cl_15m_active_router_mp import build_features, directional_regime, make_regimes, trade_pnl
from optimize_cl_15m_hybrid_sleeve_mp import CORE_PARAMS, add_research_features


BASELINE_REPORT = Path("reports/cl_15m_hybrid_sleeve_32k.json")


def load_params(path):
    payload = json.loads(Path(path).read_text())
    params = dict(payload["best"]["params"])
    params["use_sleeve"] = True
    return params


def classify_context(row, params):
    labels = []
    if row["kind"] == "core":
        labels.append("core_trend")
    else:
        labels.append("sleeve_reversion")
    if row["adx"] >= CORE_PARAMS["trend_adx"]:
        labels.append("high_adx")
    elif row["adx"] <= params["sleeve_adx_max"]:
        labels.append("low_adx")
    if row["atr_rel"] > params["atr_rel_max"]:
        labels.append("atr_too_hot")
    elif row["atr_rel"] < params["atr_rel_min"]:
        labels.append("atr_too_quiet")
    if row["vol_rank"] > params["vol_rank_max"]:
        labels.append("volume_extreme")
    elif row["vol_rank"] < params["vol_rank_min"]:
        labels.append("volume_thin")
    if abs(row["vwap_dist_atr"]) > 1.5:
        labels.append("far_from_vwap")
    if row["entry_hour_ny"] < 7 or row["entry_hour_ny"] > 14:
        labels.append("outside_primary_ny")
    if row["h4_signal"] != row["side"]:
        labels.append("against_h4")
    if row["daily_signal"] != row["side"]:
        labels.append("against_daily")
    if row["mae"] > row["mfe"] * 2:
        labels.append("immediate_adverse")
    if row["mfe"] > abs(row["pnl"]) and row["pnl"] < 0:
        labels.append("gave_back_profit")
    return labels


def simulate_trades(feat, params, start=300, end=None):
    if end is None:
        end = len(feat)
    merged = dict(CORE_PARAMS)

    close = feat["close"].to_numpy(float)
    high = feat["high"].to_numpy(float)
    low = feat["low"].to_numpy(float)
    volume = feat["volume"].to_numpy(float)
    atrv = feat["atr"].to_numpy(float)
    adxv = feat["adx"].to_numpy(float)
    rsi_v = feat["rsi"].to_numpy(float)
    stoch_k = feat["stoch_k"].to_numpy(float)
    stoch_d = feat["stoch_d"].to_numpy(float)
    macd_v = feat["macdh"].to_numpy(float)
    ema21 = feat["ema21"].to_numpy(float)
    ema55 = feat["ema55"].to_numpy(float)
    vol_sma = feat["vol_sma"].to_numpy(float)
    bb_upper = feat["bb_upper"].to_numpy(float)
    bb_lower = feat["bb_lower"].to_numpy(float)
    vwap = feat["vwap"].to_numpy(float)
    prev_high = feat["prev_day_high"].to_numpy(float)
    prev_low = feat["prev_day_low"].to_numpy(float)
    atr_rel = feat["atr_rel"].to_numpy(float)
    vol_rank = feat["vol_rank"].to_numpy(float)
    vwap_dist = feat["vwap_dist_atr"].to_numpy(float)
    adx_slope = feat["adx_slope_8"].to_numpy(float)
    ny_hour = feat["ny_hour"].to_numpy(int)
    h4_signal, daily_signal = make_regimes(feat, merged)

    pos = 0
    kind = 0
    entry = 0.0
    entry_i = 0
    entry_high = 0.0
    entry_low = 0.0
    bars_held = 0
    last_trade = -100000
    trades = []

    for i in range(max(start, 300), end):
        if pos:
            bars_held += 1
            entry_high = max(entry_high, high[i])
            entry_low = min(entry_low, low[i])
            if kind == 1:
                stop_atr = merged["stop_atr"]
                target_atr = merged["target_atr"]
                trail_atr = merged["trail_atr"]
                max_hold = merged["max_hold"]
                min_hold = merged["min_hold"]
            else:
                stop_atr = params["sleeve_stop_atr"]
                target_atr = params["sleeve_target_atr"]
                trail_atr = params["sleeve_trail_atr"]
                max_hold = params["sleeve_max_hold"]
                min_hold = params["sleeve_min_hold"]

            exit_price = None
            exit_reason = None
            if pos == 1:
                stop = max(entry - stop_atr * atrv[i], entry_high - trail_atr * atrv[i])
                target = entry + target_atr * atrv[i]
                if low[i] <= stop:
                    exit_price, exit_reason = stop, "stop"
                elif high[i] >= target:
                    exit_price, exit_reason = target, "target"
                elif bars_held >= max_hold:
                    exit_price, exit_reason = close[i], "time"
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_regime_flip"] and h4_signal[i] == -1 and daily_signal[i] != 1:
                    exit_price, exit_reason = close[i], "regime_flip"
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_momentum"] and macd_v[i] < macd_v[i - 1] and rsi_v[i] < merged["long_exit_rsi"]:
                    exit_price, exit_reason = close[i], "momentum"
                elif kind == 2 and bars_held >= min_hold and close[i] >= vwap[i] + params["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price, exit_reason = close[i], "vwap_reversion"
            else:
                stop = min(entry + stop_atr * atrv[i], entry_low + trail_atr * atrv[i])
                target = entry - target_atr * atrv[i]
                if high[i] >= stop:
                    exit_price, exit_reason = stop, "stop"
                elif low[i] <= target:
                    exit_price, exit_reason = target, "target"
                elif bars_held >= max_hold:
                    exit_price, exit_reason = close[i], "time"
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_regime_flip"] and h4_signal[i] == 1 and daily_signal[i] != -1:
                    exit_price, exit_reason = close[i], "regime_flip"
                elif kind == 1 and bars_held >= min_hold and merged["exit_on_momentum"] and macd_v[i] > macd_v[i - 1] and rsi_v[i] > merged["short_exit_rsi"]:
                    exit_price, exit_reason = close[i], "momentum"
                elif kind == 2 and bars_held >= min_hold and close[i] <= vwap[i] - params["sleeve_exit_vwap_atr"] * atrv[i]:
                    exit_price, exit_reason = close[i], "vwap_reversion"

            if exit_price is not None:
                pnl = trade_pnl(entry, exit_price, pos)
                favorable_points = (entry_high - entry) if pos == 1 else (entry - entry_low)
                adverse_points = (entry - entry_low) if pos == 1 else (entry_high - entry)
                row = {
                    "entry_time": str(feat.index[entry_i]),
                    "exit_time": str(feat.index[i]),
                    "entry_i": entry_i,
                    "exit_i": i,
                    "side": pos,
                    "side_name": "long" if pos == 1 else "short",
                    "kind": "core" if kind == 1 else "sleeve",
                    "entry": entry,
                    "exit": exit_price,
                    "pnl": pnl,
                    "bars_held": bars_held,
                    "exit_reason": exit_reason,
                    "mfe": favorable_points * 1000.0,
                    "mae": adverse_points * 1000.0,
                    "entry_hour_ny": int(ny_hour[entry_i]),
                    "adx": float(adxv[entry_i]),
                    "adx_slope": float(adx_slope[entry_i]),
                    "rsi": float(rsi_v[entry_i]),
                    "stoch_k": float(stoch_k[entry_i]),
                    "macd_hist": float(macd_v[entry_i]),
                    "atr": float(atrv[entry_i]),
                    "atr_rel": float(atr_rel[entry_i]),
                    "vol_rank": float(vol_rank[entry_i]),
                    "volume_vs_sma": float(volume[entry_i] / (vol_sma[entry_i] or 1.0)),
                    "vwap_dist_atr": float(vwap_dist[entry_i]),
                    "h4_signal": int(h4_signal[entry_i]),
                    "daily_signal": int(daily_signal[entry_i]),
                }
                row["failure_tags"] = classify_context(row, params) if pnl < 0 else []
                trades.append(row)
                pos = 0
                kind = 0
                bars_held = 0
                last_trade = i

        if pos == 0 and i - last_trade >= min(merged["cooldown"], params["sleeve_cooldown"]):
            vol_ok = volume[i] >= merged["vol_mult"] * vol_sma[i]
            trend_state = adxv[i] >= merged["trend_adx"]
            core_long = (
                trend_state
                and directional_regime(merged["trend_mode"], h4_signal[i], daily_signal[i], 1)
                and close[i] > ema55[i]
                and close[i] <= ema21[i] + merged["pullback_atr"] * atrv[i]
                and rsi_v[i] >= merged["trend_long_rsi"]
                and macd_v[i] >= merged["trend_macd_floor"]
                and vol_ok
            )
            core_short = (
                trend_state
                and directional_regime(merged["trend_mode"], h4_signal[i], daily_signal[i], -1)
                and close[i] < ema55[i]
                and close[i] >= ema21[i] - merged["pullback_atr"] * atrv[i]
                and rsi_v[i] <= merged["trend_short_rsi"]
                and macd_v[i] <= -merged["trend_macd_floor"]
                and vol_ok
            )
            k_cross_up = stoch_k[i - 1] <= stoch_d[i - 1] and stoch_k[i] > stoch_d[i]
            k_cross_down = stoch_k[i - 1] >= stoch_d[i - 1] and stoch_k[i] < stoch_d[i]
            sleeve_allowed = (
                params["use_sleeve"]
                and not trend_state
                and adxv[i] <= params["sleeve_adx_max"]
                and adx_slope[i] <= params["sleeve_adx_slope_max"]
                and params["atr_rel_min"] <= atr_rel[i] <= params["atr_rel_max"]
                and params["vol_rank_min"] <= vol_rank[i] <= params["vol_rank_max"]
                and (params["ny_start_hour"] <= ny_hour[i] <= params["ny_end_hour"] if params["ny_start_hour"] <= params["ny_end_hour"] else ny_hour[i] >= params["ny_start_hour"] or ny_hour[i] <= params["ny_end_hour"])
            )
            near_prev_low = close[i] <= prev_low[i] + params["prev_level_atr"] * atrv[i]
            near_prev_high = close[i] >= prev_high[i] - params["prev_level_atr"] * atrv[i]
            long_location = close[i] < bb_lower[i] + params["bb_atr"] * atrv[i] or near_prev_low
            short_location = close[i] > bb_upper[i] - params["bb_atr"] * atrv[i] or near_prev_high
            sleeve_long = (
                sleeve_allowed
                and params["allow_sleeve_longs"]
                and vwap_dist[i] <= -params["vwap_dist_atr"]
                and long_location
                and rsi_v[i] <= params["sleeve_long_rsi"]
                and (k_cross_up or stoch_k[i] <= params["sleeve_stoch"])
                and daily_signal[i] != -1
            )
            sleeve_short = (
                sleeve_allowed
                and params["allow_sleeve_shorts"]
                and vwap_dist[i] >= params["vwap_dist_atr"]
                and short_location
                and rsi_v[i] >= params["sleeve_short_rsi"]
                and (k_cross_down or stoch_k[i] >= 100.0 - params["sleeve_stoch"])
                and daily_signal[i] != 1
            )

            if core_long:
                pos, kind = 1, 1
            elif core_short:
                pos, kind = -1, 1
            elif i - last_trade >= params["sleeve_cooldown"] and sleeve_long:
                pos, kind = 1, 2
            elif i - last_trade >= params["sleeve_cooldown"] and sleeve_short:
                pos, kind = -1, 2
            if pos:
                entry = close[i]
                entry_i = i
                entry_high = high[i]
                entry_low = low[i]
                bars_held = 0

    return trades


def write_markdown(path, trades, worst, summary):
    lines = [
        "# CL1! Worst Trade Analysis",
        "",
        f"- Trades analyzed: `{len(trades)}`",
        f"- Losing trades: `{summary['losing_trades']}`",
        f"- Net PnL: `${summary['net_pnl']:,.2f}`",
        f"- Gross loss: `${summary['gross_loss']:,.2f}`",
        "",
        "## Most Common Failure Tags",
        "",
    ]
    for tag, count in summary["tag_counts"]:
        lines.append(f"- `{tag}`: {count}")
    lines.extend(["", "## Worst Trades", "", "| Rank | Entry | Side | Kind | PnL | Exit | MAE | MFE | Tags |", "|---:|---|---|---|---:|---|---:|---:|---|"])
    for rank, trade in enumerate(worst, start=1):
        lines.append(
            f"| {rank} | {trade['entry_time']} | {trade['side_name']} | {trade['kind']} | "
            f"${trade['pnl']:,.2f} | {trade['exit_reason']} | ${trade['mae']:,.2f} | ${trade['mfe']:,.2f} | "
            f"{', '.join(trade['failure_tags'])} |"
        )
    lines.extend([
        "",
        "## Practical Improvement Targets",
        "",
        "- If `against_h4` or `against_daily` dominates, tighten higher-timeframe alignment for that sleeve or side.",
        "- If `gave_back_profit` dominates, test earlier partial exits or tighter profit-protection trailing.",
        "- If `immediate_adverse` dominates, improve entry timing rather than exits.",
        "- If `outside_primary_ny` dominates, restrict or separately optimize ETH/RTH sessions.",
    ])
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tmp/tv_cl1_15m_loaded_full_raw.json")
    parser.add_argument("--baseline-report", default=str(BASELINE_REPORT))
    parser.add_argument("--worst", type=int, default=30)
    parser.add_argument("--out-prefix", default="reports/cl_15m_worst_trade_analysis")
    args = parser.parse_args()

    feat = add_research_features(build_features(load_json(args.data)))
    params = load_params(args.baseline_report)
    trades = simulate_trades(feat, params, 300, len(feat))
    losing = [trade for trade in trades if trade["pnl"] < 0]
    worst = sorted(losing, key=lambda item: item["pnl"])[: args.worst]
    tag_counter = Counter(tag for trade in losing for tag in trade["failure_tags"])
    reason_counter = Counter(trade["exit_reason"] for trade in losing)
    summary = {
        "trades": len(trades),
        "losing_trades": len(losing),
        "net_pnl": sum(trade["pnl"] for trade in trades),
        "gross_loss": sum(trade["pnl"] for trade in losing),
        "tag_counts": tag_counter.most_common(20),
        "exit_reason_counts": reason_counter.most_common(),
        "worst_avg_mae": float(np.mean([trade["mae"] for trade in worst] or [0.0])),
        "worst_avg_mfe": float(np.mean([trade["mfe"] for trade in worst] or [0.0])),
    }
    payload = {"source_data": args.data, "baseline_report": args.baseline_report, "summary": summary, "worst_trades": worst, "all_trades": trades}

    json_path = Path(args.out_prefix).with_suffix(".json")
    md_path = Path(args.out_prefix).with_suffix(".md")
    csv_path = Path(args.out_prefix).with_suffix(".csv")
    json_path.write_text(json.dumps(payload, indent=2))
    if trades:
        with csv_path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(trades[0].keys()))
            writer.writeheader()
            writer.writerows(trades)
    write_markdown(md_path, trades, worst, summary)
    print(json.dumps(summary, indent=2))
    print(json_path)
    print(md_path)
    print(csv_path)


if __name__ == "__main__":
    main()
