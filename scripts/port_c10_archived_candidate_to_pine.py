#!/usr/bin/env python3
"""Render an archived C10 candidate from the validated C9 Pine template."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def f(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def b(value: bool) -> str:
    return "true" if bool(value) else "false"


def timestamp_ms(value: str) -> int:
    text = value.replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).astimezone(timezone.utc).timestamp() * 1000)


def find_item(report: dict, rank: int | None, worker: int | None) -> tuple[int, dict]:
    for idx, item in enumerate(report["top10"], 1):
        if worker is not None and item["worker_id"] == worker:
            return idx, item
        if rank is not None and idx == rank:
            return idx, item
    raise SystemExit(f"candidate not found: rank={rank} worker={worker}")


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"template text not found: {old}")
    return source.replace(old, new, 1)


def replace_line(source: str, prefix: str, new_line: str) -> str:
    lines = source.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            lines[idx] = new_line
            return "\n".join(lines) + "\n"
    raise ValueError(f"line prefix not found: {prefix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/c10_participation_carry_refine_200k_20260621.json")
    parser.add_argument("--template", default="pine_strategies/JD_ES_15m_C9_Core_Forward_Refine_200k_C1.pine")
    parser.add_argument("--out", default="pine_strategies/JD_ES_15m_C10_Participation_Carry_Archived_W44.pine")
    parser.add_argument("--rank", type=int, default=2)
    parser.add_argument("--worker", type=int, default=44)
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text())
    rank, item = find_item(report, args.rank, args.worker)
    params = item["params"]
    metrics = item["metrics"]
    title = "JD ES 15m C10 Participation Carry Archived W44 20260621"
    source = Path(args.template).read_text()

    source = replace_once(
        source,
        'strategy("JD ES 15m C9 Core Forward Refine 200k C1 20260620"',
        f'strategy("{title}"',
    )
    source = replace_once(
        source,
        "// Source: reports/c9_core_forward_refine_200k_20260620.json best candidate, worker 68.",
        f"// Source: {args.report} rank {rank}, worker {item['worker_id']}.",
    )
    source = replace_once(
        source,
        "// Python reference: closed net $112185.00, trades 443, PF 1.692, max DD 9.12%.",
        (
            f"// Python reference: closed net ${metrics['closed']['net']:.2f}, "
            f"trades {metrics['closed']['trades']}, PF {metrics['closed']['profit_factor']:.3f}, "
            f"max DD {metrics['max_drawdown']:.2f}%."
        ),
    )
    source = replace_once(
        source,
        "// Engine: ES 15m TV-parity C9 candidate with C8 cap/participation and refined core-long filters.",
        "// Engine: archived C10 high-net carry/participation variant. Not promoted: DD and forward gates failed.",
    )

    line_map = {
        "h4FastLen = input.int": f'h4FastLen = input.int({int(params["h4_fast"])}, "4H fast EMA", minval=1)',
        "h4SlowLen = input.int": f'h4SlowLen = input.int({int(params["h4_slow"])}, "4H slow EMA", minval=1)',
        "dFastLen = input.int": f'dFastLen = input.int({int(params["d_fast"])}, "Daily fast EMA", minval=1)',
        "dSlowLen = input.int": f'dSlowLen = input.int({int(params["d_slow"])}, "Daily slow EMA", minval=1)',
        "regimeMode = input.string": f'regimeMode = input.string("{params["regime_mode"]}", "Core regime mode", options=["both", "h4", "h4_daily_veto"])',
        "localFilter = input.string": f'localFilter = input.string("{params["local_filter"]}", "Core local filter", options=["none", "ema21", "ema55", "stack", "ema144"])',
        "coreStopAtr = input.float": f'coreStopAtr = input.float({f(params["stop_atr"])}, "Core hard stop ATR", step=0.1)',
        "coreTrailAtr = input.float": f'coreTrailAtr = input.float({f(params["trail_atr"])}, "Core trail stop ATR", step=0.1)',
        "coreCooldown = input.int": f'coreCooldown = input.int({int(params["cooldown"])}, "Core cooldown bars", minval=0)',
        "coreLongRsiMin = input.float": f'coreLongRsiMin = input.float({f(params["long_rsi_min"])}, "Core long RSI min", step=0.1)',
        "coreShortRsiMax = input.float": f'coreShortRsiMax = input.float({f(params["short_rsi_max"])}, "Core short RSI max", step=0.1)',
        "coreLongRsiMax = input.float": f'coreLongRsiMax = input.float({f(params["core_long_rsi_max"])}, "Core long RSI max", step=0.1)',
        "coreAdxMin = input.float": f'coreAdxMin = input.float({f(params["core_adx_min"])}, "Core ADX min", step=0.1)',
        "coreLongMaxExtensionAtr = input.float": f'coreLongMaxExtensionAtr = input.float({f(params["core_long_max_extension_atr"])}, "Core long max EMA21 extension ATR", step=0.1)',
        "coreLongMaxVwapDistAtr = input.float": f'coreLongMaxVwapDistAtr = input.float({f(params["core_long_max_vwap_dist_atr"])}, "Core long max VWAP distance ATR", step=0.1)',
        "coreMacdFloor = input.float": f'coreMacdFloor = input.float({f(params["macd_floor"])}, "Core MACD floor", step=0.1)',
        "coreVolMult = input.float": f'coreVolMult = input.float({f(params["vol_mult"])}, "Core volume multiplier", step=0.01)',
        "useMomentumExit = input.bool": f'useMomentumExit = input.bool({b(params["use_momentum_exit"])}, "Use core momentum exit")',
        "coreLongExitRsi = input.float": f'coreLongExitRsi = input.float({f(params["long_exit_rsi"])}, "Core long exit RSI", step=0.1)',
        "coreShortExitRsi = input.float": f'coreShortExitRsi = input.float({f(params["short_exit_rsi"])}, "Core short exit RSI", step=0.1)',
        "longExitRegime = input.int": f'longExitRegime = input.int({int(params["long_exit_regime"])}, "Core long exit regime", minval=-1, maxval=0)',
        "shortExitRegime = input.int": f'shortExitRegime = input.int({int(params["short_exit_regime"])}, "Core short exit regime", minval=0, maxval=1)',
        "allowShorts = input.bool": f'allowShorts = input.bool({b(params["allow_short"])}, "Allow shorts")',
        "shortGate = input.string": f'shortGate = input.string("{params["short_gate"]}", "Core short gate", options=["any", "daily_bear", "not_daily_bull", "h4_and_daily_bear"])',
        "useCarryLong = input.bool": f'useCarryLong = input.bool({b(params["use_carry_long"])}, "Use carry long extension")',
        "carryRegime = input.string": f'carryRegime = input.string("{params["carry_regime"]}", "Carry regime", options=["both_up", "h4_up", "daily_up", "either_up"])',
        "carryFilter = input.string": f'carryFilter = input.string("{params["carry_filter"]}", "Carry local filter", options=["none", "ema21", "ema55", "ema144", "stack"])',
        "carryRsiMin = input.float": f'carryRsiMin = input.float({f(params["carry_rsi_min"])}, "Carry RSI min", step=0.1)',
        "carryMacdFloor = input.float": f'carryMacdFloor = input.float({f(params["carry_macd_floor"])}, "Carry MACD floor", step=0.1)',
        "carryVolMult = input.float": f'carryVolMult = input.float({f(params["carry_vol_mult"])}, "Carry volume multiplier", step=0.01)',
        "useCap = input.bool": f'useCap = input.bool({b(params["use_cap"])}, "Use capitulation sleeve")',
        "capPriority = input.bool": f'capPriority = input.bool({b(params["cap_priority"])}, "Cap sleeve priority")',
        "capRegime = input.string": f'capRegime = input.string("{params["cap_regime"]}", "Cap regime", options=["any", "daily_not_bear", "h4_up", "either_up"])',
        "capAdxMin = input.float": f'capAdxMin = input.float({f(params["cap_adx_min"])}, "Cap ADX min", step=0.1)',
        "capAdxMax = input.float": f'capAdxMax = input.float({f(params["cap_adx_max"])}, "Cap ADX max", step=0.1)',
        "capAtrRelMin = input.float": f'capAtrRelMin = input.float({f(params["cap_atr_rel_min"])}, "Cap ATR relative min", step=0.01)',
        "capAtrRelMax = input.float": f'capAtrRelMax = input.float({f(params["cap_atr_rel_max"])}, "Cap ATR relative max", step=0.01)',
        "capVwapDistAtr = input.float": f'capVwapDistAtr = input.float({f(params["cap_vwap_dist_atr"])}, "Cap VWAP distance ATR", step=0.1)',
        "capBbAtr = input.float": f'capBbAtr = input.float({f(params["cap_bb_atr"])}, "Cap Bollinger ATR offset", step=0.1)',
        "capPrevLowAtr = input.float": f'capPrevLowAtr = input.float({f(params["cap_prev_low_atr"])}, "Cap prior low ATR", step=0.1)',
        "capLowBreakAtr = input.float": f'capLowBreakAtr = input.float({f(params["cap_low_break_atr"])}, "Cap 24-bar low break ATR", step=0.1)',
        "capLow96Atr = input.float": f'capLow96Atr = input.float({f(params["cap_low96_atr"])}, "Cap 96-bar low ATR", step=0.1)',
        "capRsiMax = input.float": f'capRsiMax = input.float({f(params["cap_rsi_max"])}, "Cap RSI max", step=0.1)',
        "capStochMax = input.float": f'capStochMax = input.float({f(params["cap_stoch_max"])}, "Cap stochastic max", step=0.1)',
        "capRetZ = input.float": f'capRetZ = input.float({f(params["cap_ret_z"])}, "Cap negative return Z", step=0.1)',
        "capReclaimPos = input.float": f'capReclaimPos = input.float({f(params["cap_reclaim_pos"])}, "Cap candle reclaim position", step=0.01)',
        "capVolumeMult = input.float": f'capVolumeMult = input.float({f(params["cap_volume_mult"])}, "Cap volume climax multiplier", step=0.01)',
        "capPvZMax = input.float": f'capPvZMax = input.float({f(params["cap_pv_z_max"])}, "Cap price-volume Z max", step=0.1)',
        "capRequireReversal = input.bool": f'capRequireReversal = input.bool({b(params["cap_require_reversal"])}, "Cap requires reversal confirmation")',
        "capStopAtr = input.float": f'capStopAtr = input.float({f(params["cap_stop_atr"])}, "Cap hard stop ATR", step=0.1)',
        "capTargetAtr = input.float": f'capTargetAtr = input.float({f(params["cap_target_atr"])}, "Cap target ATR", step=0.1)',
        "capTrailAtr = input.float": f'capTrailAtr = input.float({f(params["cap_trail_atr"])}, "Cap trailing ATR", step=0.1)',
        "capTrailRelaxPct = input.float": f'capTrailRelaxPct = input.float({f(params.get("cap_trail_relax_pct", 0.0))}, "Cap trail down-bar relax pct", minval=0.0, maxval=1.0, step=0.01)',
        "capExitVwapAtr = input.float": f'capExitVwapAtr = input.float({f(params["cap_exit_vwap_atr"])}, "Cap VWAP exit ATR", step=0.1)',
        "capExitRsi = input.float": f'capExitRsi = input.float({f(params["cap_exit_rsi"])}, "Cap exit RSI", step=0.1)',
        "capExitRangePos = input.float": f'capExitRangePos = input.float({f(params["cap_exit_range_pos"])}, "Cap peak-exit candle position", step=0.01)',
        "capExitOnPeak = input.bool": f'capExitOnPeak = input.bool({b(params["cap_exit_on_peak"])}, "Cap SciPy peak exit marker")',
        "capExitOnMomentumPeak = input.bool": f'capExitOnMomentumPeak = input.bool({b(params["cap_exit_on_momentum_peak"])}, "Cap momentum peak exit")',
        "capCooldown = input.int": f'capCooldown = input.int({int(params["cap_cooldown"])}, "Cap cooldown bars", minval=0)',
        "capMinHold = input.int": f'capMinHold = input.int({int(params["cap_min_hold"])}, "Cap minimum hold bars", minval=0)',
        "capMaxHold = input.int": f'capMaxHold = input.int({int(params["cap_max_hold"])}, "Cap maximum hold bars", minval=1)',
        "useParticipation = input.bool": f'useParticipation = input.bool({b(params["use_participation"])}, "Use participation sleeve")',
        "participationPriority = input.bool": f'participationPriority = input.bool({b(params["participation_priority"])}, "Participation sleeve priority")',
        "participationRegime = input.string": f'participationRegime = input.string("{params["participation_regime"]}", "Participation regime", options=["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"])',
        "participationFilter = input.string": f'participationFilter = input.string("{params["participation_filter"]}", "Participation local filter", options=["ema21", "ema55", "ema144", "stack", "vwap"])',
        "participationRsiMin = input.float": f'participationRsiMin = input.float({f(params["participation_rsi_min"])}, "Participation RSI min", step=0.1)',
        "participationRsiMax = input.float": f'participationRsiMax = input.float({f(params["participation_rsi_max"])}, "Participation RSI max", step=0.1)',
        "participationMacdFloor = input.float": f'participationMacdFloor = input.float({f(params["participation_macd_floor"])}, "Participation MACD floor", step=0.1)',
        "participationVolMult = input.float": f'participationVolMult = input.float({f(params["participation_vol_mult"])}, "Participation volume multiplier", step=0.01)',
        "participationAdxMin = input.float": f'participationAdxMin = input.float({f(params["participation_adx_min"])}, "Participation ADX min", step=0.1)',
        "participationMaxExtensionAtr = input.float": f'participationMaxExtensionAtr = input.float({f(params["participation_max_extension_atr"])}, "Participation max extension ATR", step=0.1)',
        "participationStopAtr = input.float": f'participationStopAtr = input.float({f(params["participation_stop_atr"])}, "Participation hard stop ATR", step=0.1)',
        "participationTrailAtr = input.float": f'participationTrailAtr = input.float({f(params["participation_trail_atr"])}, "Participation trail ATR", step=0.1)',
        "participationCooldown = input.int": f'participationCooldown = input.int({int(params["participation_cooldown"])}, "Participation cooldown bars", minval=0)',
        "participationMinHold = input.int": f'participationMinHold = input.int({int(params["participation_min_hold"])}, "Participation minimum hold bars", minval=0)',
        "participationMaxHold = input.int": f'participationMaxHold = input.int({int(params["participation_max_hold"])}, "Participation maximum hold bars", minval=1)',
        "participationExitFilter = input.string": f'participationExitFilter = input.string("{params["participation_exit_filter"]}", "Participation exit filter", options=["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"])',
        "participationExitRsi = input.float": f'participationExitRsi = input.float({f(params["participation_exit_rsi"])}, "Participation exit RSI", step=0.1)',
        "participationExitOnMacdRoll = input.bool": f'participationExitOnMacdRoll = input.bool({b(params["participation_exit_on_macd_roll"])}, "Participation MACD-roll exit")',
        "useDateRange = input.bool": f'useDateRange = input.bool({b(params["use_date_range"])}, "Use optimization date range")',
        "startTime = input.time": f'startTime = input.time({timestamp_ms(params["start_time"])}, "Start")',
    }
    for prefix, line in line_map.items():
        source = replace_line(source, prefix, line)

    Path(args.out).write_text(source)
    print(
        json.dumps(
            {
                "pine": args.out,
                "title": title,
                "rank": rank,
                "worker": item["worker_id"],
                "net": metrics["closed"]["net"],
                "profit_factor": metrics["closed"]["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "forward": metrics["forward"]["net"],
                "promotion_gate_pass": item["promotion_gate_pass"],
                "failed_gates": [key for key, value in item["gates"].items() if not value],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
