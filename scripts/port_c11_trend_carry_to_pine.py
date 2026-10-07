#!/usr/bin/env python3
"""Render the selected C11 trend-carry candidate from the validated C9 Pine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def f(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def b(value: object) -> str:
    return "true" if bool(value) else "false"


def pine_string(value: object, *, fallback: str = "none") -> str:
    return str(value if value is not None else fallback)


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"template text not found: {old}")
    return source.replace(old, new, 1)


def find_item(report: dict, worker: int | None, rank: int) -> tuple[int, dict]:
    items = report.get("top10_promotion_gate_pass") or report.get("top10") or []
    for idx, item in enumerate(items, 1):
        if worker is not None and item["worker_id"] == worker:
            return idx, item
        if worker is None and idx == rank:
            return idx, item
    raise SystemExit(f"candidate not found: worker={worker} rank={rank}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/c11_trend_carry_sleeve_200k_20260621.json")
    parser.add_argument("--template", default="pine_strategies/JD_ES_15m_C9_Core_Forward_Refine_200k_C1.pine")
    parser.add_argument("--out", default="pine_strategies/JD_ES_15m_C11_Trend_Carry_200k_C1.pine")
    parser.add_argument("--worker", type=int, default=143)
    parser.add_argument("--rank", type=int, default=1)
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text())
    rank, item = find_item(report, args.worker, args.rank)
    params = item["params"]
    metrics = item["metrics"]
    title = "JD ES 15m C11 Trend Carry 200k C1 20260621"
    source = Path(args.template).read_text()

    source = replace_once(
        source,
        'strategy("JD ES 15m C9 Core Forward Refine 200k C1 20260620"',
        f'strategy("{title}"',
    )
    source = replace_once(
        source,
        "// Source: reports/c9_core_forward_refine_200k_20260620.json best candidate, worker 68.",
        f"// Source: {args.report} promotion rank {rank}, worker {item['worker_id']}.",
    )
    source = replace_once(
        source,
        "// Python reference: closed net $112185.00, trades 443, PF 1.692, max DD 9.12%.",
        (
            f"// Python reference: closed net ${metrics['closed']['net']:.2f}, "
            f"trades {metrics['closed']['trades']}, PF {metrics['closed']['profit_factor']:.3f}, "
            f"max DD {metrics['max_drawdown']:.2f}%, forward ${metrics['forward']['net']:.2f}."
        ),
    )
    source = replace_once(
        source,
        "// Engine: ES 15m TV-parity C9 candidate with C8 cap/participation and refined core-long filters.",
        "// Engine: C9-preserving C11 candidate with an added regime-aware trend-carry sleeve.",
    )

    trend_inputs = "\n".join(
        [
            f'useTrendCarry = input.bool({b(params["use_trend_carry"])}, "Use trend-carry sleeve")',
            f'trendCarryPriority = input.bool({b(params.get("trend_carry_priority"))}, "Trend-carry sleeve priority")',
            f'trendCarryRegime = input.string("{pine_string(params.get("trend_carry_regime"))}", "Trend-carry regime", options=["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"])',
            f'trendCarryFilter = input.string("{pine_string(params.get("trend_carry_filter"))}", "Trend-carry local filter", options=["none", "ema21", "ema55", "ema144", "stack", "vwap"])',
            f'trendCarryRsiMin = input.float({f(params["trend_carry_rsi_min"])}, "Trend-carry RSI min", step=0.1)',
            f'trendCarryRsiMax = input.float({f(params["trend_carry_rsi_max"])}, "Trend-carry RSI max", step=0.1)',
            f'trendCarryMacdFloor = input.float({f(params["trend_carry_macd_floor"])}, "Trend-carry MACD floor", step=0.1)',
            f'trendCarryVolMult = input.float({f(params["trend_carry_vol_mult"])}, "Trend-carry volume multiplier", step=0.01)',
            f'trendCarryAdxMin = input.float({f(params["trend_carry_adx_min"])}, "Trend-carry ADX min", step=0.1)',
            f'trendCarryMaxExtensionAtr = input.float({f(params["trend_carry_max_extension_atr"])}, "Trend-carry max extension ATR", step=0.1)',
            f'trendCarryMaxVwapDistAtr = input.float({f(params["trend_carry_max_vwap_dist_atr"])}, "Trend-carry max VWAP distance ATR", step=0.1)',
            f'trendCarryAtrRelMax = input.float({f(params["trend_carry_atr_rel_max"])}, "Trend-carry ATR relative max", step=0.01)',
            f'trendCarryStopAtr = input.float({f(params["trend_carry_stop_atr"])}, "Trend-carry hard stop ATR", step=0.1)',
            f'trendCarryTrailAtr = input.float({f(params["trend_carry_trail_atr"])}, "Trend-carry trail ATR", step=0.1)',
            f'trendCarryCooldown = input.int({int(params["trend_carry_cooldown"])}, "Trend-carry cooldown bars", minval=0)',
            f'trendCarryMinHold = input.int({int(params["trend_carry_min_hold"])}, "Trend-carry minimum hold bars", minval=0)',
            f'trendCarryMaxHold = input.int({int(params["trend_carry_max_hold"])}, "Trend-carry maximum hold bars", minval=1)',
            f'trendCarryExitFilter = input.string("{pine_string(params.get("trend_carry_exit_filter"))}", "Trend-carry exit filter", options=["none", "ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"])',
            f'trendCarryExitRsi = input.float({f(params["trend_carry_exit_rsi"])}, "Trend-carry exit RSI", step=0.1)',
            f'trendCarryExitRegime = input.string("{pine_string(params.get("trend_carry_exit_regime"))}", "Trend-carry exit regime", options=["none", "h4_down", "daily_bear", "either_down", "both_down"])',
            f'trendCarryExitOnMacdRoll = input.bool({b(params.get("trend_carry_exit_on_macd_roll"))}, "Trend-carry MACD-roll exit")',
            f'trendCarryExitAtrRelMax = input.float({f(params["trend_carry_exit_atr_rel_max"])}, "Trend-carry exit ATR relative max", step=0.01)',
        ]
    )
    source = replace_once(
        source,
        'participationExitOnMacdRoll = input.bool(true, "Participation MACD-roll exit")',
        'participationExitOnMacdRoll = input.bool(true, "Participation MACD-roll exit")\n' + trend_inputs,
    )

    trend_logic = "\n".join(
        [
            'trendCarryRegimeOk = (trendCarryRegime == "h4_up" and h4Signal == 1) or (trendCarryRegime == "daily_up" and dailySignal == 1) or (trendCarryRegime == "both_up" and h4Signal == 1 and dailySignal == 1) or (trendCarryRegime == "h4_up_daily_not_bear" and h4Signal == 1 and dailySignal != -1) or (trendCarryRegime == "either_up" and (h4Signal == 1 or dailySignal == 1))',
            'trendCarryFilterOk = trendCarryFilter == "none" ? true : trendCarryFilter == "ema21" ? close > ema21 : trendCarryFilter == "ema55" ? close > ema55 : trendCarryFilter == "ema144" ? close > ema144 : trendCarryFilter == "stack" ? ema8 > ema21 and ema21 > ema55 and close > ema8 : close > vwapValue',
            "trendCarryExtensionOk = close - ema21 <= trendCarryMaxExtensionAtr * atrValue",
            "trendCarryVwapOk = close - vwapValue <= trendCarryMaxVwapDistAtr * atrValue",
            "trendCarryAtrOk = atrRel <= trendCarryAtrRelMax",
            "trendCarryLong = inRange and useTrendCarry and trendCarryRegimeOk and trendCarryFilterOk and trendCarryExtensionOk and trendCarryVwapOk and trendCarryAtrOk and rsiValue >= trendCarryRsiMin and rsiValue <= trendCarryRsiMax and macdHist >= trendCarryMacdFloor and volume >= trendCarryVolMult * volSma and adxValue >= trendCarryAdxMin",
            'trendCarryFilterExit = (trendCarryExitFilter == "ema21" and close < ema21) or (trendCarryExitFilter == "ema55" and close < ema55) or (trendCarryExitFilter == "ema144" and close < ema144) or (trendCarryExitFilter == "vwap" and close < vwapValue) or (trendCarryExitFilter == "h4_down" and h4Signal != 1) or (trendCarryExitFilter == "daily_bear" and dailySignal == -1)',
            'trendCarryRegimeExit = (trendCarryExitRegime == "h4_down" and h4Signal != 1) or (trendCarryExitRegime == "daily_bear" and dailySignal == -1) or (trendCarryExitRegime == "either_down" and (h4Signal != 1 or dailySignal == -1)) or (trendCarryExitRegime == "both_down" and h4Signal != 1 and dailySignal == -1)',
            "trendCarryCloseExit = trendCarryRegimeExit or trendCarryFilterExit or rsiValue < trendCarryExitRsi or atrRel > trendCarryExitAtrRelMax or (trendCarryExitOnMacdRoll and macdHist < macdHist[1] and rsiValue < trendCarryRsiMin)",
        ]
    )
    source = replace_once(
        source,
        "participationCloseExit = h4Signal != 1 or participationFilterExit or rsiValue < participationExitRsi or (participationExitOnMacdRoll and macdHist < macdHist[1] and rsiValue < participationRsiMin)",
        "participationCloseExit = h4Signal != 1 or participationFilterExit or rsiValue < participationExitRsi or (participationExitOnMacdRoll and macdHist < macdHist[1] and rsiValue < participationRsiMin)\n" + trend_logic,
    )

    source = replace_once(
        source,
        "participationReady = na(lastExitBar) or bar_index - lastExitBar >= participationCooldown",
        "participationReady = na(lastExitBar) or bar_index - lastExitBar >= participationCooldown\ntrendCarryReady = na(lastExitBar) or bar_index - lastExitBar >= trendCarryCooldown",
    )
    source = replace_once(
        source,
        'else if canEnter and coreReady and coreLong\n    strategy.entry("Core Long", strategy.long)',
        'else if canEnter and trendCarryPriority and trendCarryReady and trendCarryLong\n    strategy.entry("Trend Carry Long", strategy.long)\n    entryBar := bar_index\n    activeKind := 4\n    entryHigh := high\n    entryLow := low\nelse if canEnter and coreReady and coreLong\n    strategy.entry("Core Long", strategy.long)',
    )
    source = replace_once(
        source,
        'else if canEnter and coreReady and coreShort\n    strategy.entry("Core Short", strategy.short)',
        'else if canEnter and trendCarryReady and trendCarryLong\n    strategy.entry("Trend Carry Long", strategy.long)\n    entryBar := bar_index\n    activeKind := 4\n    entryHigh := high\n    entryLow := low\nelse if canEnter and coreReady and coreShort\n    strategy.entry("Core Short", strategy.short)',
    )
    source = replace_once(
        source,
        "participationLongStop = math.max(strategy.position_avg_price - participationStopAtr * atrValue, entryHigh - participationTrailAtr * atrValue)",
        "participationLongStop = math.max(strategy.position_avg_price - participationStopAtr * atrValue, entryHigh - participationTrailAtr * atrValue)\ntrendCarryLongStop = math.max(strategy.position_avg_price - trendCarryStopAtr * atrValue, entryHigh - trendCarryTrailAtr * atrValue)",
    )
    source = replace_once(
        source,
        'if strategy.position_size > 0 and activeKind == 3\n    strategy.exit("Participation Long Risk", "Participation Long", stop=participationLongStop)',
        'if strategy.position_size > 0 and activeKind == 3\n    strategy.exit("Participation Long Risk", "Participation Long", stop=participationLongStop)\nif strategy.position_size > 0 and activeKind == 4\n    strategy.exit("Trend Carry Long Risk", "Trend Carry Long", stop=trendCarryLongStop)',
    )
    source = replace_once(
        source,
        'if strategy.position_size > 0 and activeKind == 3 and (not inRange or barsHeld >= participationMaxHold or (barsHeld >= participationMinHold and participationCloseExit))\n    strategy.close("Participation Long", comment="Participation exit")',
        'if strategy.position_size > 0 and activeKind == 3 and (not inRange or barsHeld >= participationMaxHold or (barsHeld >= participationMinHold and participationCloseExit))\n    strategy.close("Participation Long", comment="Participation exit")\nif strategy.position_size > 0 and activeKind == 4 and (not inRange or barsHeld >= trendCarryMaxHold or (barsHeld >= trendCarryMinHold and trendCarryCloseExit))\n    strategy.close("Trend Carry Long", comment="Trend-carry exit")',
    )
    source = replace_once(
        source,
        "activeLongStop = strategy.position_size > 0 and activeKind == 1 ? coreLongStop : strategy.position_size > 0 and activeKind == 2 ? capLongStop : strategy.position_size > 0 and activeKind == 3 ? participationLongStop : na",
        "activeLongStop = strategy.position_size > 0 and activeKind == 1 ? coreLongStop : strategy.position_size > 0 and activeKind == 2 ? capLongStop : strategy.position_size > 0 and activeKind == 3 ? participationLongStop : strategy.position_size > 0 and activeKind == 4 ? trendCarryLongStop : na",
    )
    source = replace_once(
        source,
        'plotshape(showSignals and canEnter and participationReady and participationLong, "Participation long", shape.triangleup, location.belowbar, color=color.new(color.aqua, 0), size=size.tiny, text="PL")',
        'plotshape(showSignals and canEnter and participationReady and participationLong, "Participation long", shape.triangleup, location.belowbar, color=color.new(color.aqua, 0), size=size.tiny, text="PL")\nplotshape(showSignals and canEnter and trendCarryReady and trendCarryLong, "Trend-carry long", shape.triangleup, location.belowbar, color=color.new(color.blue, 0), size=size.tiny, text="TL")',
    )

    Path(args.out).write_text(source)
    print(
        json.dumps(
            {
                "pine": args.out,
                "title": title,
                "rank": rank,
                "worker": item["worker_id"],
                "closed_net": metrics["closed"]["net"],
                "profit_factor": metrics["closed"]["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "forward": metrics["forward"]["net"],
                "trades": metrics["closed"]["trades"],
                "trend_carry_trades": metrics["closed"]["trend_carry_trades"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
