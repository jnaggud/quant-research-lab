#!/usr/bin/env python3
import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path


def safe_div(a, b):
    return a / b if b else 0.0


def condition_flags(trade):
    flags = []
    if trade["kind"] == "core":
        flags.append("core_trend")
    else:
        flags.append("sleeve_reversion")
    if trade["adx"] >= 26.27168114440552:
        flags.append("high_adx")
    if trade["adx"] <= 24.111181455078224:
        flags.append("low_adx")
    if trade["atr_rel"] > 1.1838094620099848:
        flags.append("atr_too_hot")
    if trade["atr_rel"] < 0.8130426484809107:
        flags.append("atr_too_quiet")
    if trade["vol_rank"] > 0.9213924280365459:
        flags.append("volume_extreme")
    if trade["vol_rank"] < 0.20068031699404018:
        flags.append("volume_thin")
    if abs(trade["vwap_dist_atr"]) > 1.5:
        flags.append("far_from_vwap")
    if trade["entry_hour_ny"] < 7 or trade["entry_hour_ny"] > 14:
        flags.append("outside_primary_ny")
    if trade["h4_signal"] != trade["side"]:
        flags.append("against_h4")
    if trade["daily_signal"] != trade["side"]:
        flags.append("against_daily")
    if trade["mfe"] > abs(trade["pnl"]) and trade["pnl"] < 0:
        flags.append("gave_back_profit")
    if trade["mae"] > trade["mfe"] * 2 and trade["pnl"] < 0:
        flags.append("immediate_adverse")
    return flags


def bucket_hour(hour):
    if 0 <= hour <= 5:
        return "overnight_00_05"
    if 6 <= hour <= 8:
        return "pre_ny_06_08"
    if 9 <= hour <= 11:
        return "ny_morning_09_11"
    if 12 <= hour <= 14:
        return "ny_midday_12_14"
    if 15 <= hour <= 18:
        return "post_ny_15_18"
    return "late_19_23"


def bucket_value(value, cuts, labels):
    for cut, label in zip(cuts, labels):
        if value <= cut:
            return label
    return labels[-1]


def summarize_trades(trades):
    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] <= 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = sum(trade["pnl"] for trade in losses)
    return {
        "trades": len(trades),
        "net": sum(trade["pnl"] for trade in trades),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "win_rate": safe_div(len(wins), len(trades)) * 100.0,
        "profit_factor": safe_div(gross_profit, abs(gross_loss)),
        "avg_trade": safe_div(sum(trade["pnl"] for trade in trades), len(trades)),
        "avg_mae": safe_div(sum(trade["mae"] for trade in trades), len(trades)),
        "avg_mfe": safe_div(sum(trade["mfe"] for trade in trades), len(trades)),
    }


def group_summary(trades, key_func, min_trades):
    groups = defaultdict(list)
    for trade in trades:
        groups[key_func(trade)].append(trade)
    rows = []
    for key, items in groups.items():
        if len(items) >= min_trades:
            row = summarize_trades(items)
            row["key"] = key
            rows.append(row)
    return sorted(rows, key=lambda row: row["net"])


def filter_impact(trades, flags, min_removed):
    baseline = summarize_trades(trades)
    rows = []
    for flag in flags:
        removed = [trade for trade in trades if flag in trade["flags"]]
        kept = [trade for trade in trades if flag not in trade["flags"]]
        if len(removed) < min_removed or not kept:
            continue
        kept_summary = summarize_trades(kept)
        removed_summary = summarize_trades(removed)
        rows.append({
            "filter": flag,
            "removed_trades": len(removed),
            "removed_net": removed_summary["net"],
            "kept_net": kept_summary["net"],
            "net_delta": kept_summary["net"] - baseline["net"],
            "kept_pf": kept_summary["profit_factor"],
            "kept_win_rate": kept_summary["win_rate"],
        })
    return sorted(rows, key=lambda row: row["net_delta"], reverse=True)


def combo_filter_impact(trades, flags, min_removed):
    baseline = summarize_trades(trades)
    rows = []
    for left, right in itertools.combinations(flags, 2):
        removed = [trade for trade in trades if left in trade["flags"] and right in trade["flags"]]
        kept = [trade for trade in trades if not (left in trade["flags"] and right in trade["flags"])]
        if len(removed) < min_removed or not kept:
            continue
        kept_summary = summarize_trades(kept)
        removed_summary = summarize_trades(removed)
        rows.append({
            "filter": f"{left} AND {right}",
            "removed_trades": len(removed),
            "removed_net": removed_summary["net"],
            "kept_net": kept_summary["net"],
            "net_delta": kept_summary["net"] - baseline["net"],
            "kept_pf": kept_summary["profit_factor"],
            "kept_win_rate": kept_summary["win_rate"],
        })
    return sorted(rows, key=lambda row: row["net_delta"], reverse=True)


def write_table(lines, title, rows, columns, max_rows=15):
    lines.extend(["", f"## {title}", "", "| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"])
    for row in rows[:max_rows]:
        rendered = []
        for column in columns:
            value = row[column]
            if isinstance(value, float):
                if "rate" in column or "pf" in column:
                    rendered.append(f"{value:.2f}")
                else:
                    rendered.append(f"${value:,.2f}" if any(token in column for token in ["net", "delta", "gross", "avg"]) else f"{value:.2f}")
            else:
                rendered.append(str(value))
        lines.append("| " + " | ".join(rendered) + " |")


def write_markdown(path, payload):
    summary = payload["summary"]
    lines = [
        "# CL1! Deep Failure Investigation",
        "",
        f"- Trades: `{summary['trades']}`",
        f"- Net: `${summary['net']:,.2f}`",
        f"- Win rate: `{summary['win_rate']:.2f}%`",
        f"- Profit factor: `{summary['profit_factor']:.3f}`",
        "",
        "## Interpretation",
        "",
        "This report separates pre-entry filterable conditions from ex-post failure behavior. Filters can be tested directly; ex-post labels identify exit/entry timing issues but cannot be used as live filters without a predictive proxy.",
    ]
    write_table(lines, "Worst Single Conditions To Filter", payload["filter_impact"], ["filter", "removed_trades", "removed_net", "kept_net", "net_delta", "kept_pf", "kept_win_rate"])
    write_table(lines, "Worst Two-Condition Intersections", payload["combo_filter_impact"], ["filter", "removed_trades", "removed_net", "kept_net", "net_delta", "kept_pf", "kept_win_rate"])
    write_table(lines, "Worst Groups By Session", payload["by_session"], ["key", "trades", "net", "win_rate", "profit_factor", "avg_mae", "avg_mfe"])
    write_table(lines, "Worst Groups By Side/Kind", payload["by_side_kind"], ["key", "trades", "net", "win_rate", "profit_factor", "avg_mae", "avg_mfe"])
    write_table(lines, "Worst Groups By Exit Reason", payload["by_exit_reason"], ["key", "trades", "net", "win_rate", "profit_factor", "avg_mae", "avg_mfe"])
    write_table(lines, "Worst VWAP Distance Buckets", payload["by_vwap_bucket"], ["key", "trades", "net", "win_rate", "profit_factor", "avg_mae", "avg_mfe"])
    write_table(lines, "Worst ATR Regime Buckets", payload["by_atr_bucket"], ["key", "trades", "net", "win_rate", "profit_factor", "avg_mae", "avg_mfe"])
    lines.extend([
        "",
        "## Next Tests",
        "",
        "1. Convert the best pre-entry filter rows into candidate strategy branches and run walk-forward validation.",
        "2. For `gave_back_profit`, test predictive proxies such as MFE-based trailing after 0.8–1.2 ATR favorable excursion.",
        "3. For `immediate_adverse`, test entry delay/confirmation filters rather than wider stops.",
    ])
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="reports/cl_15m_worst_trade_analysis.json")
    parser.add_argument("--out", default="reports/cl_15m_deep_failure_investigation.json")
    parser.add_argument("--min-trades", type=int, default=8)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text())
    trades = payload["all_trades"]
    for trade in trades:
        trade["flags"] = condition_flags(trade)
        trade["session"] = bucket_hour(trade["entry_hour_ny"])
        trade["vwap_bucket"] = bucket_value(abs(trade["vwap_dist_atr"]), [0.5, 1.0, 1.5, 2.5], ["vwap_0_0.5", "vwap_0.5_1", "vwap_1_1.5", "vwap_1.5_2.5", "vwap_gt_2.5"])
        trade["atr_bucket"] = bucket_value(trade["atr_rel"], [0.8, 1.0, 1.2, 1.5], ["atr_lt_0.8", "atr_0.8_1", "atr_1_1.2", "atr_1.2_1.5", "atr_gt_1.5"])
        trade["vol_bucket"] = bucket_value(trade["vol_rank"], [0.2, 0.5, 0.8, 0.92], ["vol_lt_0.2", "vol_0.2_0.5", "vol_0.5_0.8", "vol_0.8_0.92", "vol_gt_0.92"])

    pre_entry_flags = [
        "core_trend", "sleeve_reversion", "high_adx", "low_adx", "atr_too_hot", "atr_too_quiet",
        "volume_extreme", "volume_thin", "far_from_vwap", "outside_primary_ny", "against_h4", "against_daily",
    ]
    output = {
        "source": args.input,
        "summary": summarize_trades(trades),
        "flag_counts": Counter(flag for trade in trades for flag in trade["flags"]).most_common(),
        "filter_impact": filter_impact(trades, pre_entry_flags, args.min_trades),
        "combo_filter_impact": combo_filter_impact(trades, pre_entry_flags, args.min_trades),
        "by_session": group_summary(trades, lambda trade: trade["session"], args.min_trades),
        "by_side_kind": group_summary(trades, lambda trade: f"{trade['side_name']}_{trade['kind']}", args.min_trades),
        "by_exit_reason": group_summary(trades, lambda trade: trade["exit_reason"], args.min_trades),
        "by_vwap_bucket": group_summary(trades, lambda trade: trade["vwap_bucket"], args.min_trades),
        "by_atr_bucket": group_summary(trades, lambda trade: trade["atr_bucket"], args.min_trades),
        "by_volume_bucket": group_summary(trades, lambda trade: trade["vol_bucket"], args.min_trades),
    }
    out = Path(args.out)
    out.write_text(json.dumps(output, indent=2))
    write_markdown(out.with_suffix(".md"), output)
    print(json.dumps(output["summary"], indent=2))
    print(out)
    print(out.with_suffix(".md"))


if __name__ == "__main__":
    main()
