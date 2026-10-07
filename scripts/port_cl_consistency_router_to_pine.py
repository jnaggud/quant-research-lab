#!/usr/bin/env python3
import json
from pathlib import Path


REPORT_PATH = Path("reports/cl_15m_consistency_router_32k.json")
OUT_DIR = Path("pine_strategies")


def pine_bool(value):
    return "true" if value else "false"


def pine_float(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def render_candidate(rank, item):
    params = item["params"]
    metrics = item["metrics"]["full"]
    title = f"JD CL 15m Consistency Router 32k C{rank} 20260518"
    return f"""//@version=6
strategy("{title}", overlay=true, initial_capital=50000, default_qty_type=strategy.fixed, default_qty_value=1, pyramiding=0, margin_long=5, margin_short=5, commission_type=strategy.commission.cash_per_contract, commission_value=2.50, slippage=1, process_orders_on_close=true)

// Source: reports/cl_15m_consistency_router_32k.json candidate C{rank}, worker {item["worker_id"]}
// Python reference: net ${metrics["net_profit"]:.2f}, trades {metrics["n_trades"]}, PF {metrics["profit_factor"]:.3f}, max DD {metrics["max_drawdown"]:.2f}%.
// Engine: 15m CL consistency router with trend pullback, range reversion, concentration-aware selection, H4/Daily filters, ATR risk, and long/short support.
h4FastLen = input.int({params["h4_fast"]}, "4H fast EMA", minval=1)
h4SlowLen = input.int({params["h4_slow"]}, "4H slow EMA", minval=1)
dFastLen = input.int({params["d_fast"]}, "Daily fast EMA", minval=1)
dSlowLen = input.int({params["d_slow"]}, "Daily slow EMA", minval=1)
trendMode = input.string("{params["trend_mode"]}", "Trend regime mode", options=["h4", "either", "not_against_daily", "both"])
breakoutMode = input.string("{params["breakout_mode"]}", "Breakout regime mode", options=["h4", "either", "not_against_daily", "both"])
useTrend = input.bool({pine_bool(params["use_trend"])}, "Use trend pullbacks")
useRange = input.bool({pine_bool(params["use_range"])}, "Use range reversions")
useBreakout = input.bool({pine_bool(params["use_breakout"])}, "Use breakouts")
trendAdx = input.float({pine_float(params["trend_adx"])}, "Trend ADX min", step=0.1)
rangeAdx = input.float({pine_float(params["range_adx"])}, "Range ADX max", step=0.1)
breakoutAdx = input.float({pine_float(params["breakout_adx"])}, "Breakout ADX min", step=0.1)
pullbackAtr = input.float({pine_float(params["pullback_atr"])}, "Pullback ATR distance", step=0.1)
rangeBandAtr = input.float({pine_float(params["range_band_atr"])}, "Range band ATR offset", step=0.1)
trendLongRsi = input.float({pine_float(params["trend_long_rsi"])}, "Trend long RSI min", step=0.1)
trendShortRsi = input.float({pine_float(params["trend_short_rsi"])}, "Trend short RSI max", step=0.1)
rangeLongRsi = input.float({pine_float(params["range_long_rsi"])}, "Range long RSI max", step=0.1)
rangeShortRsi = input.float({pine_float(params["range_short_rsi"])}, "Range short RSI min", step=0.1)
rangeStoch = input.float({pine_float(params["range_stoch"])}, "Range stochastic edge", step=0.1)
trendMacdFloor = input.float({pine_float(params["trend_macd_floor"])}, "Trend MACD floor", step=0.1)
breakoutMacdFloor = input.float({pine_float(params["breakout_macd_floor"])}, "Breakout MACD floor", step=0.1)
volMult = input.float({pine_float(params["vol_mult"])}, "Base volume multiplier", step=0.01)
breakoutVolMult = input.float({pine_float(params["breakout_vol_mult"])}, "Breakout volume multiplier", step=0.01)
stopAtr = input.float({pine_float(params["stop_atr"])}, "Hard stop ATR", step=0.1)
targetAtr = input.float({pine_float(params["target_atr"])}, "Target ATR", step=0.1)
trailAtr = input.float({pine_float(params["trail_atr"])}, "Trailing ATR", step=0.1)
cooldownBars = input.int({params["cooldown"]}, "Cooldown bars", minval=0)
minHoldBars = input.int({params["min_hold"]}, "Minimum hold bars", minval=0)
maxHoldBars = input.int({params["max_hold"]}, "Maximum hold bars", minval=1)
exitOnRegimeFlip = input.bool({pine_bool(params["exit_on_regime_flip"])}, "Exit on regime flip")
exitOnMomentum = input.bool({pine_bool(params["exit_on_momentum"])}, "Exit on momentum loss")
longExitRsi = input.float({pine_float(params["long_exit_rsi"])}, "Long momentum exit RSI", step=0.1)
shortExitRsi = input.float({pine_float(params["short_exit_rsi"])}, "Short momentum exit RSI", step=0.1)
allowShorts = input.bool({pine_bool(params["allow_short"])}, "Allow shorts")
useDateRange = input.bool(true, "Use optimization date range")
startTime = input.time(1751320800000, "Start")
endTime = input.time(1798761599000, "End")
showSignals = input.bool(true, "Show entry signals")
showRawSignals = input.bool(false, "Show raw setups")
showBands = input.bool(true, "Show router levels")

h4Fast = request.security(syminfo.tickerid, "240", ta.ema(close, h4FastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
h4Slow = request.security(syminfo.tickerid, "240", ta.ema(close, h4SlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dFast = request.security(syminfo.tickerid, "1D", ta.ema(close, dFastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dSlow = request.security(syminfo.tickerid, "1D", ta.ema(close, dSlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)

h4Signal = h4Fast > h4Slow ? 1 : -1
dailySignal = dFast > dSlow ? 1 : -1
inRange = not useDateRange or (time >= startTime and time <= endTime)

directionOk(mode, side) =>
    target = side == 1 ? 1 : -1
    mode == "h4" ? h4Signal == target : mode == "both" ? h4Signal == target and dailySignal == target : mode == "not_against_daily" ? h4Signal == target and dailySignal != -target : h4Signal == target or dailySignal == target

rsiValue = ta.rsi(close, 14)
stochK = ta.stoch(close, high, low, 14)
stochD = ta.sma(stochK, 3)
[_, _, macdHist] = ta.macd(close, 12, 26, 9)
atrValue = ta.atr(14)
[_, _, adxValue] = ta.dmi(14, 14)
ema8 = ta.ema(close, 8)
ema21 = ta.ema(close, 21)
ema55 = ta.ema(close, 55)
ema144 = ta.ema(close, 144)
volSma = ta.sma(volume, 48)
bbBasis = ta.sma(close, 40)
bbDev = ta.stdev(close, 40)
bbUpper = bbBasis + 2.0 * bbDev
bbLower = bbBasis - 2.0 * bbDev
donHigh = ta.highest(high, 32)[1]
donLow = ta.lowest(low, 32)[1]
vwapValue = ta.vwap(hlc3)

volOk = volume >= volMult * volSma
trendState = adxValue >= trendAdx
rangeState = adxValue <= rangeAdx
kCrossUp = stochK[1] <= stochD[1] and stochK > stochD
kCrossDown = stochK[1] >= stochD[1] and stochK < stochD

trendLong = useTrend and trendState and directionOk(trendMode, 1) and close > ema55 and close <= ema21 + pullbackAtr * atrValue and rsiValue >= trendLongRsi and macdHist >= trendMacdFloor and volOk
trendShort = useTrend and trendState and directionOk(trendMode, -1) and close < ema55 and close >= ema21 - pullbackAtr * atrValue and rsiValue <= trendShortRsi and macdHist <= -trendMacdFloor and volOk
rangeLong = useRange and rangeState and close < bbLower + rangeBandAtr * atrValue and close < vwapValue and rsiValue <= rangeLongRsi and (kCrossUp or stochK <= rangeStoch) and dailySignal != -1 and volOk
rangeShort = useRange and rangeState and close > bbUpper - rangeBandAtr * atrValue and close > vwapValue and rsiValue >= rangeShortRsi and (kCrossDown or stochK >= 100.0 - rangeStoch) and dailySignal != 1 and volOk
breakoutLong = useBreakout and close > donHigh and close > ema144 and directionOk(breakoutMode, 1) and adxValue >= breakoutAdx and macdHist >= breakoutMacdFloor and volume >= breakoutVolMult * volSma
breakoutShort = useBreakout and close < donLow and close < ema144 and directionOk(breakoutMode, -1) and adxValue >= breakoutAdx and macdHist <= -breakoutMacdFloor and volume >= breakoutVolMult * volSma

longSetup = inRange and (trendLong or rangeLong or breakoutLong)
shortSetup = inRange and allowShorts and (trendShort or rangeShort or breakoutShort)

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
longStop = math.max(strategy.position_avg_price - stopAtr * atrValue, entryHigh - trailAtr * atrValue)
longTarget = strategy.position_avg_price + targetAtr * atrValue
shortStop = math.min(strategy.position_avg_price + stopAtr * atrValue, entryLow + trailAtr * atrValue)
shortTarget = strategy.position_avg_price - targetAtr * atrValue

if strategy.position_size > 0
    strategy.exit("Long Risk", "Long", stop=longStop, limit=longTarget)
if strategy.position_size < 0
    strategy.exit("Short Risk", "Short", stop=shortStop, limit=shortTarget)
if strategy.position_size > 0 and (not inRange or barsHeld >= maxHoldBars)
    strategy.close("Long", comment=not inRange ? "Range exit" : "Time exit")
if strategy.position_size < 0 and (not inRange or barsHeld >= maxHoldBars)
    strategy.close("Short", comment=not inRange ? "Range exit" : "Time exit")
if strategy.position_size > 0 and holdOk and exitOnRegimeFlip and h4Signal == -1 and dailySignal != 1
    strategy.close("Long", comment="Regime exit")
if strategy.position_size < 0 and holdOk and exitOnRegimeFlip and h4Signal == 1 and dailySignal != -1
    strategy.close("Short", comment="Regime exit")
if strategy.position_size > 0 and holdOk and exitOnMomentum and macdHist < macdHist[1] and rsiValue < longExitRsi
    strategy.close("Long", comment="Momentum exit")
if strategy.position_size < 0 and holdOk and exitOnMomentum and macdHist > macdHist[1] and rsiValue > shortExitRsi
    strategy.close("Short", comment="Momentum exit")

plot(showBands ? h4Fast : na, "4H Fast EMA prev", color=color.new(color.aqua, 0))
plot(showBands ? h4Slow : na, "4H Slow EMA prev", color=color.new(color.orange, 0))
plot(showBands ? bbUpper : na, "Range upper", color=color.new(color.red, 80))
plot(showBands ? bbLower : na, "Range lower", color=color.new(color.green, 80))
plot(strategy.position_size > 0 ? longStop : na, "Long active stop", color=color.new(color.red, 0), style=plot.style_linebr)
plot(strategy.position_size > 0 ? longTarget : na, "Long active target", color=color.new(color.lime, 65), style=plot.style_linebr)
plot(strategy.position_size < 0 ? shortStop : na, "Short active stop", color=color.new(color.lime, 0), style=plot.style_linebr)
plot(strategy.position_size < 0 ? shortTarget : na, "Short active target", color=color.new(color.red, 65), style=plot.style_linebr)
plotshape(showSignals and canEnter and longSetup, "Long entry setup", shape.triangleup, location.belowbar, color=color.new(color.lime, 0), size=size.small, text="L")
plotshape(showSignals and canEnter and shortSetup, "Short entry setup", shape.triangledown, location.abovebar, color=color.new(color.fuchsia, 0), size=size.small, text="S")
plotshape(showRawSignals and trendLong, "Trend long raw", shape.circle, location.belowbar, color=color.new(color.green, 70), size=size.tiny, text="T")
plotshape(showRawSignals and rangeLong, "Range long raw", shape.circle, location.belowbar, color=color.new(color.aqua, 70), size=size.tiny, text="R")
plotshape(showRawSignals and breakoutLong, "Breakout long raw", shape.circle, location.belowbar, color=color.new(color.blue, 70), size=size.tiny, text="B")
plotshape(showRawSignals and trendShort, "Trend short raw", shape.circle, location.abovebar, color=color.new(color.red, 70), size=size.tiny, text="T")
plotshape(showRawSignals and rangeShort, "Range short raw", shape.circle, location.abovebar, color=color.new(color.orange, 70), size=size.tiny, text="R")
plotshape(showRawSignals and breakoutShort, "Breakout short raw", shape.circle, location.abovebar, color=color.new(color.purple, 70), size=size.tiny, text="B")
bgcolor(h4Signal == 1 ? color.new(color.green, 93) : color.new(color.red, 94))
"""


def main():
    payload = json.loads(REPORT_PATH.read_text())
    OUT_DIR.mkdir(exist_ok=True)
    for rank, item in enumerate(payload["top10"][:6], start=1):
        path = OUT_DIR / f"JD_CL_15m_Consistency_Router_32k_C{rank}.pine"
        path.write_text(render_candidate(rank, item))
        print(path)


if __name__ == "__main__":
    main()
