#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from port_es_capitulation_sleeve_to_pine import OUT_DIR, render

CORE_KEYS = {
    "h1_fast",
    "h1_slow",
    "d_fast",
    "d_slow",
    "regime_mode",
    "local_filter",
    "stop_atr",
    "trail_atr",
    "cooldown",
    "long_rsi_min",
    "short_rsi_max",
    "macd_floor",
    "vol_mult",
    "use_momentum_exit",
    "long_exit_rsi",
    "short_exit_rsi",
    "long_exit_regime",
    "short_exit_regime",
    "allow_short",
}


def render_1h(rank, item, core, report_path, title_base):
    render_core = dict(core)
    render_core.update({key: item["params"][key] for key in CORE_KEYS if key in item["params"]})
    render_core["h4_fast"] = render_core["h1_fast"]
    render_core["h4_slow"] = render_core["h1_slow"]
    render_core["regime_mode"] = render_core["regime_mode"].replace("h1", "h4")

    render_item = dict(item)
    render_item["params"] = {key: value for key, value in item["params"].items() if key not in CORE_KEYS}
    render_item["params"]["cap_regime"] = render_item["params"]["cap_regime"].replace("h1", "h4")

    text = render(rank, render_item, render_core, report_path, title_base)
    text = text.replace("4H", "1H")
    text = text.replace("h4", "h1")
    text = text.replace('"240"', '"60"')
    text = text.replace("20260519", "20260520")
    text = text.replace("Use optimization date range", "Use optimization start date")
    text = text.replace('endTime = input.time(1778198399000, "End")\n', "")
    text = text.replace("inRange = not useDateRange or (time >= startTime and time <= endTime)", "inRange = not useDateRange or time >= startTime")
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/es_15m_capitulation_sleeve_1h_regime_64k.json")
    parser.add_argument("--title-base", default="JD ES 15m 1H Regime 64k")
    parser.add_argument("--file-prefix", default="JD_ES_15m_1H_Regime_64k")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    report_path = Path(args.report)
    payload = json.loads(report_path.read_text())
    OUT_DIR.mkdir(exist_ok=True)
    for rank, item in enumerate(payload["top10"][:args.top], start=1):
        path = OUT_DIR / f"{args.file_prefix}_C{rank}.pine"
        path.write_text(render_1h(rank, item, payload["core_params"], report_path, args.title_base))
        print(path)


if __name__ == "__main__":
    main()
