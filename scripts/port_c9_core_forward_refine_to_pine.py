#!/usr/bin/env python3
"""Render the best C9 core-forward-refine candidate from the C8 Pine template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def f(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def replace_once(source: str, old: str, new: str) -> str:
    if old not in source:
        raise ValueError(f"template text not found: {old}")
    return source.replace(old, new, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/c9_core_forward_refine_200k_20260620.json")
    parser.add_argument("--template", default="pine_strategies/JD_ES_15m_C8_Successor_200k_C5.pine")
    parser.add_argument("--out", default="pine_strategies/JD_ES_15m_C9_Core_Forward_Refine_200k_C1.pine")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text())
    item = report["best"]
    params = item["params"]
    metrics = item["metrics"]
    source = Path(args.template).read_text()
    title = "JD ES 15m C9 Core Forward Refine 200k C1 20260620"

    source = replace_once(
        source,
        'strategy("JD ES 15m C8 Successor 200k C5 20260618"',
        f'strategy("{title}"',
    )
    source = replace_once(
        source,
        "// Source: reports/c8_successor_200k_20260618.json candidate C5, worker 375.",
        f"// Source: {args.report} best candidate, worker {item['worker_id']}.",
    )
    source = replace_once(
        source,
        "// Python reference: net $100715.00, trades 487, PF 1.551, max DD 12.99%.",
        (
            f"// Python reference: closed net ${metrics['closed']['net']:.2f}, "
            f"trades {metrics['closed']['trades']}, PF {metrics['closed']['profit_factor']:.3f}, "
            f"max DD {metrics['max_drawdown']:.2f}%."
        ),
    )
    source = replace_once(
        source,
        "// Engine: ES 15m TV-parity successor with optimized core/carry/capitulation sleeves.",
        "// Engine: ES 15m TV-parity C9 candidate with C8 cap/participation and refined core-long filters.",
    )

    replacements = {
        "localFilter = input.string": f'localFilter = input.string("{params["local_filter"]}", "Core local filter", options=["none", "ema21", "ema55", "stack", "ema144"])',
        "coreStopAtr = input.float": f'coreStopAtr = input.float({f(params["stop_atr"])}, "Core hard stop ATR", step=0.1)',
        "coreTrailAtr = input.float": f'coreTrailAtr = input.float({f(params["trail_atr"])}, "Core trail stop ATR", step=0.1)',
        "coreCooldown = input.int": f'coreCooldown = input.int({int(params["cooldown"])}, "Core cooldown bars", minval=0)',
        "coreLongRsiMin = input.float": f'coreLongRsiMin = input.float({f(params["long_rsi_min"])}, "Core long RSI min", step=0.1)',
        "coreMacdFloor = input.float": f'coreMacdFloor = input.float({f(params["macd_floor"])}, "Core MACD floor", step=0.1)',
        "coreVolMult = input.float": f'coreVolMult = input.float({f(params["vol_mult"])}, "Core volume multiplier", step=0.01)',
        "coreLongExitRsi = input.float": f'coreLongExitRsi = input.float({f(params["long_exit_rsi"])}, "Core long exit RSI", step=0.1)',
        "longExitRegime = input.int": f'longExitRegime = input.int({int(params["long_exit_regime"])}, "Core long exit regime", minval=-1, maxval=0)',
    }
    for prefix, new_line in replacements.items():
        lines = source.splitlines()
        for idx, line in enumerate(lines):
            if line.startswith(prefix):
                lines[idx] = new_line
                source = "\n".join(lines) + "\n"
                break
        else:
            raise ValueError(f"line prefix not found: {prefix}")

    source = replace_once(
        source,
        'coreShortRsiMax = input.float(49.205005, "Core short RSI max", step=0.1)',
        (
            f'coreShortRsiMax = input.float({f(params["short_rsi_max"])}, "Core short RSI max", step=0.1)\n'
            f'coreLongRsiMax = input.float({f(params["core_long_rsi_max"])}, "Core long RSI max", step=0.1)\n'
            f'coreAdxMin = input.float({f(params["core_adx_min"])}, "Core ADX min", step=0.1)\n'
            f'coreLongMaxExtensionAtr = input.float({f(params["core_long_max_extension_atr"])}, "Core long max EMA21 extension ATR", step=0.1)\n'
            f'coreLongMaxVwapDistAtr = input.float({f(params["core_long_max_vwap_dist_atr"])}, "Core long max VWAP distance ATR", step=0.1)'
        ),
    )
    source = replace_once(
        source,
        "coreBaseLong = regime == 1 and longFilter and rsiValue >= coreLongRsiMin and macdHist >= coreMacdFloor and coreVolOk",
        (
            "coreLongExtensionOk = close - ema21 <= coreLongMaxExtensionAtr * atrValue\n"
            "coreLongVwapOk = close - vwapValue <= coreLongMaxVwapDistAtr * atrValue\n"
            "coreBaseLong = regime == 1 and longFilter and rsiValue >= coreLongRsiMin and rsiValue <= coreLongRsiMax and macdHist >= coreMacdFloor and adxValue >= coreAdxMin and coreLongExtensionOk and coreLongVwapOk and coreVolOk"
        ),
    )

    Path(args.out).write_text(source)
    print(json.dumps({"pine": args.out, "title": title, "worker": item["worker_id"], "net": metrics["closed"]["net"]}, indent=2))


if __name__ == "__main__":
    main()
