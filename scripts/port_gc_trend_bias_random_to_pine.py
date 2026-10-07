#!/usr/bin/env python3
"""Render a GC 15m trend-bias random-search candidate to Pine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def f(value: float) -> str:
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def b(value: object) -> str:
    return "true" if bool(value) else "false"


def find_item(report: dict, worker: int | None, rank: int) -> tuple[int, dict]:
    items = report.get("top10") or []
    for idx, item in enumerate(items, 1):
        if worker is not None and item["worker_id"] == worker:
            return idx, item
        if worker is None and idx == rank:
            return idx, item
    raise SystemExit(f"candidate not found: worker={worker} rank={rank}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default="reports/gc_15m_trend_bias_random_64k_20260626.json")
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--out", default="pine_strategies/JD_GC_15m_Trend_Bias_Random_64k_C1_20260626.pine")
    args = parser.parse_args()

    report = json.loads(Path(args.report).read_text())
    rank, item = find_item(report, args.worker, args.rank)
    params = item["params"]
    metrics = item["metrics"]["full"]
    title = f"JD GC 15m Trend Bias Random 64k C{rank} 20260626"
    source = f"""//@version=6
strategy("{title}", overlay=true, initial_capital=50000, default_qty_type=strategy.fixed, default_qty_value=1, pyramiding=0, margin_long=5, margin_short=5, commission_type=strategy.commission.cash_per_contract, commission_value=2.50, slippage=1, process_orders_on_close=true)

// Source: {args.report} rank {rank}, worker {item["worker_id"]}.
// Python reference: net ${metrics["net_profit"]:.2f}, trades {metrics["n_trades"]}, PF {metrics["profit_factor"]:.3f}, max DD {metrics["max_drawdown"]:.2f}%.
// Engine: GC 15m H4/daily trend bias with asymmetric long/short trailing risk, min-hold gate, and optional momentum exits.
h4FastLen = input.int({int(params["h4_fast"])}, "4H fast EMA", minval=1)
h4SlowLen = input.int({int(params["h4_slow"])}, "4H slow EMA", minval=1)
dFastLen = input.int({int(params["d_fast"])}, "Daily fast EMA", minval=1)
dSlowLen = input.int({int(params["d_slow"])}, "Daily slow EMA", minval=1)
longMode = input.string("{params["long_mode"]}", "Long regime mode", options=["h4_up", "daily_up", "both_up", "either_up"])
shortMode = input.string("{params["short_mode"]}", "Short regime mode", options=["h4_down", "both_down", "daily_down", "h4_down_daily_not_up"])
localFilter = input.string("{params["local_filter"]}", "Local filter", options=["none", "ema21", "ema55", "stack", "ema144"])
stopAtr = input.float({f(params["stop_atr"])}, "Hard stop ATR", step=0.1)
trailAtr = input.float({f(params["trail_atr"])}, "Long trail ATR", step=0.1)
shortTrailAtr = input.float({f(params["short_trail_atr"])}, "Short trail ATR", step=0.1)
cooldownBars = input.int({int(params["cooldown"])}, "Cooldown bars", minval=0)
minHoldBars = input.int({int(params["min_hold"])}, "Minimum hold bars", minval=0)
longRsiMin = input.float({f(params["long_rsi_min"])}, "Long RSI min", step=0.1)
shortRsiMax = input.float({f(params["short_rsi_max"])}, "Short RSI max", step=0.1)
longMacdFloor = input.float({f(params["long_macd_floor"])}, "Long MACD floor", step=0.1)
shortMacdCeiling = input.float({f(params["short_macd_ceiling"])}, "Short MACD ceiling", step=0.1)
volMult = input.float({f(params["vol_mult"])}, "Volume multiplier", step=0.01)
useMomentumExit = input.bool({b(params["use_momentum_exit"])}, "Use momentum exit")
longExitRsi = input.float({f(params["long_exit_rsi"])}, "Long momentum exit RSI", step=0.1)
shortExitRsi = input.float({f(params["short_exit_rsi"])}, "Short momentum exit RSI", step=0.1)
longExitMode = input.string("{params["long_exit_mode"]}", "Long regime exit", options=["h4_down", "daily_down", "both_down", "none"])
shortExitMode = input.string("{params["short_exit_mode"]}", "Short regime exit", options=["h4_up", "daily_up", "either_up", "none"])
allowShorts = input.bool({b(params["allow_short"])}, "Allow shorts")
useDateRange = input.bool(true, "Use test date range")
startTime = input.time(1754452800000, "Start")
endTime = input.time(4102444799000, "End")
showSignals = input.bool(true, "Show signals")
showMtfLines = input.bool(true, "Show MTF EMAs")

h4Fast = request.security(syminfo.tickerid, "240", ta.ema(close, h4FastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
h4Slow = request.security(syminfo.tickerid, "240", ta.ema(close, h4SlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dFast = request.security(syminfo.tickerid, "1D", ta.ema(close, dFastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dSlow = request.security(syminfo.tickerid, "1D", ta.ema(close, dSlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)

h4Signal = h4Fast > h4Slow ? 1 : -1
dailySignal = dFast > dSlow ? 1 : -1
inRange = not useDateRange or (time >= startTime and time <= endTime)

rsi = ta.rsi(close, 14)
[_, _, macdHist] = ta.macd(close, 12, 26, 9)
atr = ta.atr(14)
ema8 = ta.ema(close, 8)
ema21 = ta.ema(close, 21)
ema55 = ta.ema(close, 55)
ema144 = ta.ema(close, 144)
volSma = ta.sma(volume, 48)

longFilter = localFilter == "none" ? true : localFilter == "ema21" ? close > ema21 : localFilter == "ema55" ? close > ema55 : localFilter == "stack" ? ema8 > ema21 and ema21 > ema55 and close > ema8 : close > ema144
shortFilter = localFilter == "none" ? true : localFilter == "ema21" ? close < ema21 : localFilter == "ema55" ? close < ema55 : localFilter == "stack" ? ema8 < ema21 and ema21 < ema55 and close < ema8 : close < ema144
longRegime = longMode == "daily_up" ? dailySignal == 1 : longMode == "both_up" ? h4Signal == 1 and dailySignal == 1 : longMode == "either_up" ? h4Signal == 1 or dailySignal == 1 : h4Signal == 1
shortRegime = shortMode == "both_down" ? h4Signal == -1 and dailySignal == -1 : shortMode == "daily_down" ? dailySignal == -1 : shortMode == "h4_down_daily_not_up" ? h4Signal == -1 and dailySignal != 1 : h4Signal == -1
volOk = volume >= volMult * volSma
longSetup = inRange and longRegime and longFilter and rsi >= longRsiMin and macdHist >= longMacdFloor and volOk
shortSetup = inRange and allowShorts and shortRegime and shortFilter and rsi <= shortRsiMax and macdHist <= shortMacdCeiling and volOk

var int lastExitBar = na
var int entryBar = na
var float entryHigh = na
var float entryLow = na
flatNow = strategy.position_size == 0 and strategy.position_size[1] != 0
if flatNow
    lastExitBar := bar_index
    entryBar := na
    entryHigh := na
    entryLow := na
cooldownOk = na(lastExitBar) or bar_index - lastExitBar >= cooldownBars
canEnter = strategy.position_size == 0 and cooldownOk

if canEnter and longSetup
    strategy.entry("Long", strategy.long)
    entryBar := bar_index
    entryHigh := high
    entryLow := low
else if canEnter and shortSetup
    strategy.entry("Short", strategy.short)
    entryBar := bar_index
    entryHigh := high
    entryLow := low

if strategy.position_size != 0
    entryHigh := na(entryHigh) ? high : math.max(entryHigh, high)
    entryLow := na(entryLow) ? low : math.min(entryLow, low)

barsHeld = strategy.position_size != 0 and not na(entryBar) ? bar_index - entryBar : 0
holdOk = barsHeld >= minHoldBars
longStop = math.max(strategy.position_avg_price - stopAtr * atr, entryHigh - trailAtr * atr)
shortStop = math.min(strategy.position_avg_price + stopAtr * atr, entryLow + shortTrailAtr * atr)

longRegimeExit = longExitMode == "h4_down" ? h4Signal == -1 : longExitMode == "daily_down" ? dailySignal == -1 : longExitMode == "both_down" ? h4Signal == -1 and dailySignal == -1 : false
shortRegimeExit = shortExitMode == "h4_up" ? h4Signal == 1 : shortExitMode == "daily_up" ? dailySignal == 1 : shortExitMode == "either_up" ? h4Signal == 1 or dailySignal == 1 : false

if strategy.position_size > 0
    strategy.exit("Long Risk", "Long", stop=longStop)
if strategy.position_size < 0
    strategy.exit("Short Risk", "Short", stop=shortStop)
if strategy.position_size > 0 and (not inRange or (holdOk and longRegimeExit))
    strategy.close("Long", comment="Regime exit")
if strategy.position_size < 0 and (not inRange or (holdOk and shortRegimeExit))
    strategy.close("Short", comment="Regime exit")
if strategy.position_size > 0 and holdOk and useMomentumExit and dailySignal != 1 and macdHist < macdHist[1] and rsi < longExitRsi
    strategy.close("Long", comment="Momentum exit")
if strategy.position_size < 0 and holdOk and useMomentumExit and macdHist > macdHist[1] and rsi > shortExitRsi
    strategy.close("Short", comment="Momentum exit")

plot(showMtfLines ? h4Fast : na, "4H Fast EMA prev", color=color.new(color.aqua, 0))
plot(showMtfLines ? h4Slow : na, "4H Slow EMA prev", color=color.new(color.orange, 0))
plot(showMtfLines ? dFast : na, "Daily Fast EMA prev", color=color.new(color.lime, 60), linewidth=2)
plot(showMtfLines ? dSlow : na, "Daily Slow EMA prev", color=color.new(color.red, 60), linewidth=2)
plot(strategy.position_size > 0 ? longStop : na, "Long active stop", color=color.new(color.red, 0), style=plot.style_linebr)
plot(strategy.position_size < 0 ? shortStop : na, "Short active stop", color=color.new(color.lime, 0), style=plot.style_linebr)
plotshape(showSignals and longSetup, "Long setup", shape.circle, location.belowbar, color=color.new(color.lime, 0), size=size.tiny, text="L")
plotshape(showSignals and shortSetup, "Short setup", shape.circle, location.abovebar, color=color.new(color.fuchsia, 0), size=size.tiny, text="S")
bgcolor(h4Signal == 1 ? color.new(color.green, 92) : color.new(color.red, 94))
"""
    Path(args.out).write_text(source)
    print(
        json.dumps(
            {
                "pine": args.out,
                "title": title,
                "rank": rank,
                "worker": item["worker_id"],
                "net": metrics["net_profit"],
                "profit_factor": metrics["profit_factor"],
                "max_drawdown": metrics["max_drawdown"],
                "trades": metrics["n_trades"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
