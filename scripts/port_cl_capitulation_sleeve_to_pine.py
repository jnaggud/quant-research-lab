#!/usr/bin/env python3
import json
from pathlib import Path

REPORT_PATH = Path("reports/cl_15m_capitulation_sleeve_64k.json")
MARKER_PATH = Path("pine_strategies/JD_CL_15m_SciPy_Truth_Markers_20260519.pine")
OUT_DIR = Path("pine_strategies")


def b(value):
    return "true" if value else "false"


def f(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def marker_block():
    text = MARKER_PATH.read_text()
    start = text.index("showPeaks =")
    body = text[start:]
    return (
        "\n// SciPy truth markers are hindsight diagnostic labels generated from exported TradingView data.\n"
        "// They are plotted for analysis only and are not used by the strategy logic.\n"
        + body
    )


def render(rank, item, core, sleeve):
    cap = item["params"]
    metrics = item["metrics"]["full"]
    title = f"JD CL 15m Capitulation Sleeve 64k C{rank} 20260519"
    return f'''//@version=6
strategy("{title}", overlay=true, initial_capital=50000, default_qty_type=strategy.fixed, default_qty_value=1, pyramiding=0, margin_long=5, margin_short=5, commission_type=strategy.commission.cash_per_contract, commission_value=2.50, slippage=1, process_orders_on_close=true)

// Source: reports/cl_15m_capitulation_sleeve_64k.json candidate C{rank}, worker {item["worker_id"]}.
// Python reference: net ${metrics["net_profit"]:.2f}, trades {metrics["n_trades"]}, PF {metrics["profit_factor"]:.3f}, max DD {metrics["max_drawdown"]:.2f}%.
// Engine: fixed CL 15m trend core + fixed consistency sleeve + optimized long-only capitulation sleeve trained against SciPy valley labels.
h4FastLen = input.int({core["h4_fast"]}, "4H fast EMA", minval=1)
h4SlowLen = input.int({core["h4_slow"]}, "4H slow EMA", minval=1)
dFastLen = input.int({core["d_fast"]}, "Daily fast EMA", minval=1)
dSlowLen = input.int({core["d_slow"]}, "Daily slow EMA", minval=1)
trendMode = input.string("{core["trend_mode"]}", "Core trend regime", options=["h4", "either", "not_against_daily", "both"])
coreTrendAdx = input.float({f(core["trend_adx"])}, "Core trend ADX min", step=0.1)
corePullbackAtr = input.float({f(core["pullback_atr"])}, "Core pullback ATR", step=0.1)
coreLongRsi = input.float({f(core["trend_long_rsi"])}, "Core long RSI min", step=0.1)
coreShortRsi = input.float({f(core["trend_short_rsi"])}, "Core short RSI max", step=0.1)
coreMacdFloor = input.float({f(core["trend_macd_floor"])}, "Core MACD floor", step=0.1)
coreVolMult = input.float({f(core["vol_mult"])}, "Core volume multiplier", step=0.01)
coreStopAtr = input.float({f(core["stop_atr"])}, "Core hard stop ATR", step=0.1)
coreTargetAtr = input.float({f(core["target_atr"])}, "Core target ATR", step=0.1)
coreTrailAtr = input.float({f(core["trail_atr"])}, "Core trailing ATR", step=0.1)
coreCooldown = input.int({core["cooldown"]}, "Core cooldown bars", minval=0)
coreMinHold = input.int({core["min_hold"]}, "Core minimum hold bars", minval=0)
coreMaxHold = input.int({core["max_hold"]}, "Core maximum hold bars", minval=1)
coreLongExitRsi = input.float({f(core["long_exit_rsi"])}, "Core long exit RSI", step=0.1)
coreShortExitRsi = input.float({f(core["short_exit_rsi"])}, "Core short exit RSI", step=0.1)

useSleeve = input.bool({b(sleeve["use_sleeve"])}, "Use consistency sleeve")
allowSleeveLongs = input.bool({b(sleeve["allow_sleeve_longs"])}, "Sleeve longs")
allowSleeveShorts = input.bool({b(sleeve["allow_sleeve_shorts"])}, "Sleeve shorts")
sleeveAdxMax = input.float({f(sleeve["sleeve_adx_max"])}, "Sleeve ADX max", step=0.1)
sleeveAdxSlopeMax = input.float({f(sleeve["sleeve_adx_slope_max"])}, "Sleeve ADX slope max", step=0.1)
atrRelMin = input.float({f(sleeve["atr_rel_min"])}, "Sleeve ATR relative min", step=0.01)
atrRelMax = input.float({f(sleeve["atr_rel_max"])}, "Sleeve ATR relative max", step=0.01)
volRankMin = input.float({f(sleeve["vol_rank_min"])}, "Sleeve volume rank min", step=0.01)
volRankMax = input.float({f(sleeve["vol_rank_max"])}, "Sleeve volume rank max", step=0.01)
vwapDistAtr = input.float({f(sleeve["vwap_dist_atr"])}, "Sleeve VWAP distance ATR", step=0.1)
prevLevelAtr = input.float({f(sleeve["prev_level_atr"])}, "Prior-day level ATR proximity", step=0.1)
bbAtr = input.float({f(sleeve["bb_atr"])}, "Sleeve Bollinger ATR offset", step=0.1)
sleeveLongRsi = input.float({f(sleeve["sleeve_long_rsi"])}, "Sleeve long RSI max", step=0.1)
sleeveShortRsi = input.float({f(sleeve["sleeve_short_rsi"])}, "Sleeve short RSI min", step=0.1)
sleeveStoch = input.float({f(sleeve["sleeve_stoch"])}, "Sleeve stochastic edge", step=0.1)
sleeveStopAtr = input.float({f(sleeve["sleeve_stop_atr"])}, "Sleeve hard stop ATR", step=0.1)
sleeveTargetAtr = input.float({f(sleeve["sleeve_target_atr"])}, "Sleeve target ATR", step=0.1)
sleeveTrailAtr = input.float({f(sleeve["sleeve_trail_atr"])}, "Sleeve trailing ATR", step=0.1)
sleeveExitVwapAtr = input.float({f(sleeve["sleeve_exit_vwap_atr"])}, "Sleeve VWAP exit ATR", step=0.1)
sleeveCooldown = input.int({sleeve["sleeve_cooldown"]}, "Sleeve cooldown bars", minval=0)
sleeveMinHold = input.int({sleeve["sleeve_min_hold"]}, "Sleeve minimum hold bars", minval=0)
sleeveMaxHold = input.int({sleeve["sleeve_max_hold"]}, "Sleeve maximum hold bars", minval=1)
nyStartHour = input.int({sleeve["ny_start_hour"]}, "Sleeve NY start hour", minval=0, maxval=23)
nyEndHour = input.int({sleeve["ny_end_hour"]}, "Sleeve NY end hour", minval=0, maxval=23)

useCap = input.bool({b(cap["use_cap"])}, "Use capitulation sleeve")
capRegime = input.string("{cap["cap_regime"]}", "Cap regime", options=["any", "daily_not_bear", "h4_up", "either_up"])
capAdxMin = input.float({f(cap["cap_adx_min"])}, "Cap ADX min", step=0.1)
capAdxMax = input.float({f(cap["cap_adx_max"])}, "Cap ADX max", step=0.1)
capAtrRelMin = input.float({f(cap["cap_atr_rel_min"])}, "Cap ATR relative min", step=0.01)
capAtrRelMax = input.float({f(cap["cap_atr_rel_max"])}, "Cap ATR relative max", step=0.01)
capVwapDistAtr = input.float({f(cap["cap_vwap_dist_atr"])}, "Cap VWAP distance ATR", step=0.1)
capBbAtr = input.float({f(cap["cap_bb_atr"])}, "Cap Bollinger ATR offset", step=0.1)
capPrevLowAtr = input.float({f(cap["cap_prev_low_atr"])}, "Cap prior low ATR", step=0.1)
capLowBreakAtr = input.float({f(cap["cap_low_break_atr"])}, "Cap 24-bar low break ATR", step=0.1)
capLow96Atr = input.float({f(cap["cap_low96_atr"])}, "Cap 96-bar low ATR", step=0.1)
capRsiMax = input.float({f(cap["cap_rsi_max"])}, "Cap RSI max", step=0.1)
capStochMax = input.float({f(cap["cap_stoch_max"])}, "Cap stochastic max", step=0.1)
capRetZ = input.float({f(cap["cap_ret_z"])}, "Cap negative return Z", step=0.1)
capReclaimPos = input.float({f(cap["cap_reclaim_pos"])}, "Cap candle reclaim position", step=0.01)
capVolumeMult = input.float({f(cap["cap_volume_mult"])}, "Cap volume climax multiplier", step=0.01)
capPvZMax = input.float({f(cap["cap_pv_z_max"])}, "Cap price-volume Z max", step=0.1)
capRequireReversal = input.bool({b(cap["cap_require_reversal"])}, "Cap requires reversal confirmation")
capStopAtr = input.float({f(cap["cap_stop_atr"])}, "Cap hard stop ATR", step=0.1)
capTargetAtr = input.float({f(cap["cap_target_atr"])}, "Cap target ATR", step=0.1)
capTrailAtr = input.float({f(cap["cap_trail_atr"])}, "Cap trailing ATR", step=0.1)
capExitVwapAtr = input.float({f(cap["cap_exit_vwap_atr"])}, "Cap VWAP exit ATR", step=0.1)
capExitRsi = input.float({f(cap["cap_exit_rsi"])}, "Cap exit RSI", step=0.1)
capExitRangePos = input.float({f(cap["cap_exit_range_pos"])}, "Cap peak-exit candle position", step=0.01)
capExitOnPeak = input.bool({b(cap["cap_exit_on_peak"])}, "Cap momentum peak exit")
capCooldown = input.int({cap["cap_cooldown"]}, "Cap cooldown bars", minval=0)
capMinHold = input.int({cap["cap_min_hold"]}, "Cap minimum hold bars", minval=0)
capMaxHold = input.int({cap["cap_max_hold"]}, "Cap maximum hold bars", minval=1)

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
prevDayHigh = request.security(syminfo.tickerid, "1D", high[1], barmerge.gaps_off, barmerge.lookahead_off)
prevDayLow = request.security(syminfo.tickerid, "1D", low[1], barmerge.gaps_off, barmerge.lookahead_off)

h4Signal = h4Fast > h4Slow ? 1 : -1
dailySignal = dFast > dSlow ? 1 : -1
inRange = not useDateRange or (time >= startTime and time <= endTime)

directionOk(mode, side) =>
    target = side == 1 ? 1 : -1
    mode == "h4" ? h4Signal == target : mode == "both" ? h4Signal == target and dailySignal == target : mode == "not_against_daily" ? h4Signal == target and dailySignal != -target : h4Signal == target or dailySignal == target

inSession(hourValue, startHour, endHour) =>
    startHour <= endHour ? hourValue >= startHour and hourValue <= endHour : hourValue >= startHour or hourValue <= endHour

rsiValue = ta.rsi(close, 14)
stochK = ta.stoch(close, high, low, 14)
stochD = ta.sma(stochK, 3)
[_, _, macdHist] = ta.macd(close, 12, 26, 9)
atrValue = ta.atr(14)
[_, _, adxValue] = ta.dmi(14, 14)
ema21 = ta.ema(close, 21)
ema55 = ta.ema(close, 55)
volSma = ta.sma(volume, 48)
bbBasis = ta.sma(close, 40)
bbDev = ta.stdev(close, 40)
bbUpper = bbBasis + 2.0 * bbDev
bbLower = bbBasis - 2.0 * bbDev
vwapValue = ta.vwap(hlc3)
atrRel = atrValue / ta.sma(atrValue, 192)
volRank = ta.percentrank(volume, 96) / 100.0
vwapDist = (close - vwapValue) / atrValue
adxSlope = adxValue - adxValue[8]
nyHour = hour(time, "America/New_York")
ret1 = ta.change(close) / close[1]
retMean = ta.sma(ret1, 96)
retStd = ta.stdev(ret1, 96)
retZ = retStd != 0.0 ? (ret1 - retMean) / retStd : 0.0
rangePos = (close - low) / math.max(high - low, syminfo.mintick)
low24 = ta.lowest(low, 24)[1]
low96 = ta.lowest(low, 96)[1]
priceVelocity = ta.change(close)
priceAcceleration = ta.change(priceVelocity)
priceJerk = ta.change(priceAcceleration)
pvMomentum = math.sum(priceVelocity * volume, 4)
pvStd = ta.stdev(pvMomentum, 96)
pvZ = pvStd != 0.0 ? pvMomentum / pvStd : 0.0
climaxVolume = volume / ta.sma(volume, 96)

coreVolOk = volume >= coreVolMult * volSma
coreTrendState = adxValue >= coreTrendAdx
coreLong = inRange and coreTrendState and directionOk(trendMode, 1) and close > ema55 and close <= ema21 + corePullbackAtr * atrValue and rsiValue >= coreLongRsi and macdHist >= coreMacdFloor and coreVolOk
coreShort = inRange and coreTrendState and directionOk(trendMode, -1) and close < ema55 and close >= ema21 - corePullbackAtr * atrValue and rsiValue <= coreShortRsi and macdHist <= -coreMacdFloor and coreVolOk

kCrossUp = stochK[1] <= stochD[1] and stochK > stochD
kCrossDown = stochK[1] >= stochD[1] and stochK < stochD
sleeveAllowed = inRange and useSleeve and not coreTrendState and adxValue <= sleeveAdxMax and adxSlope <= sleeveAdxSlopeMax and atrRel >= atrRelMin and atrRel <= atrRelMax and volRank >= volRankMin and volRank <= volRankMax and inSession(nyHour, nyStartHour, nyEndHour)
nearPrevLow = close <= prevDayLow + prevLevelAtr * atrValue
nearPrevHigh = close >= prevDayHigh - prevLevelAtr * atrValue
longLocation = close < bbLower + bbAtr * atrValue or nearPrevLow
shortLocation = close > bbUpper - bbAtr * atrValue or nearPrevHigh
sleeveLong = sleeveAllowed and allowSleeveLongs and vwapDist <= -vwapDistAtr and longLocation and rsiValue <= sleeveLongRsi and (kCrossUp or stochK <= sleeveStoch) and dailySignal != -1
sleeveShort = sleeveAllowed and allowSleeveShorts and vwapDist >= vwapDistAtr and shortLocation and rsiValue >= sleeveShortRsi and (kCrossDown or stochK >= 100.0 - sleeveStoch) and dailySignal != 1

capRegimeOk = capRegime == "any" or (capRegime == "daily_not_bear" and dailySignal != -1) or (capRegime == "h4_up" and h4Signal == 1) or (capRegime == "either_up" and (h4Signal == 1 or dailySignal == 1))
capDeep = vwapDist <= -capVwapDistAtr or close <= bbLower + capBbAtr * atrValue or close <= prevDayLow + capPrevLowAtr * atrValue or low <= low24 - capLowBreakAtr * atrValue or low <= low96 + capLow96Atr * atrValue
capExhaustion = rsiValue <= capRsiMax and stochK <= capStochMax and retZ <= -capRetZ and rangePos >= capReclaimPos and climaxVolume >= capVolumeMult and pvZ <= capPvZMax
capReversal = kCrossUp or close > close[1] or macdHist > macdHist[1]
capLong = inRange and useCap and capRegimeOk and atrRel >= capAtrRelMin and atrRel <= capAtrRelMax and adxValue >= capAdxMin and adxValue <= capAdxMax and capDeep and capExhaustion and (not capRequireReversal or capReversal)

var int lastExitBar = na
var int entryBar = na
var int activeKind = 0
var float entryHigh = na
var float entryLow = na
flatNow = strategy.position_size == 0 and strategy.position_size[1] != 0
if flatNow
    lastExitBar := bar_index
    entryBar := na
    activeKind := 0
    entryHigh := na
    entryLow := na

minCooldown = math.min(coreCooldown, math.min(sleeveCooldown, capCooldown))
cooldownOk = na(lastExitBar) or bar_index - lastExitBar >= minCooldown
cooldownOkSleeve = na(lastExitBar) or bar_index - lastExitBar >= sleeveCooldown
cooldownOkCap = na(lastExitBar) or bar_index - lastExitBar >= capCooldown
canEnter = strategy.position_size == 0 and cooldownOk

if canEnter and coreLong
    strategy.entry("Core Long", strategy.long)
    entryBar := bar_index
    activeKind := 1
    entryHigh := high
    entryLow := low
else if canEnter and coreShort
    strategy.entry("Core Short", strategy.short)
    entryBar := bar_index
    activeKind := 1
    entryHigh := high
    entryLow := low
else if canEnter and cooldownOkSleeve and sleeveLong
    strategy.entry("Sleeve Long", strategy.long)
    entryBar := bar_index
    activeKind := 2
    entryHigh := high
    entryLow := low
else if canEnter and cooldownOkSleeve and sleeveShort
    strategy.entry("Sleeve Short", strategy.short)
    entryBar := bar_index
    activeKind := 2
    entryHigh := high
    entryLow := low
else if canEnter and cooldownOkCap and capLong
    strategy.entry("Cap Long", strategy.long)
    entryBar := bar_index
    activeKind := 3
    entryHigh := high
    entryLow := low

if strategy.position_size != 0
    entryHigh := na(entryHigh) ? high : math.max(entryHigh, high)
    entryLow := na(entryLow) ? low : math.min(entryLow, low)

barsHeld = strategy.position_size != 0 and not na(entryBar) ? bar_index - entryBar : 0
coreHoldOk = barsHeld >= coreMinHold
sleeveHoldOk = barsHeld >= sleeveMinHold
capHoldOk = barsHeld >= capMinHold
coreLongStop = math.max(strategy.position_avg_price - coreStopAtr * atrValue, entryHigh - coreTrailAtr * atrValue)
coreLongTarget = strategy.position_avg_price + coreTargetAtr * atrValue
coreShortStop = math.min(strategy.position_avg_price + coreStopAtr * atrValue, entryLow + coreTrailAtr * atrValue)
coreShortTarget = strategy.position_avg_price - coreTargetAtr * atrValue
sleeveLongStop = math.max(strategy.position_avg_price - sleeveStopAtr * atrValue, entryHigh - sleeveTrailAtr * atrValue)
sleeveLongTarget = strategy.position_avg_price + sleeveTargetAtr * atrValue
sleeveShortStop = math.min(strategy.position_avg_price + sleeveStopAtr * atrValue, entryLow + sleeveTrailAtr * atrValue)
sleeveShortTarget = strategy.position_avg_price - sleeveTargetAtr * atrValue
capLongStop = math.max(strategy.position_avg_price - capStopAtr * atrValue, entryHigh - capTrailAtr * atrValue)
capLongTarget = strategy.position_avg_price + capTargetAtr * atrValue

if strategy.position_size > 0 and activeKind == 1
    strategy.exit("Core Long Risk", "Core Long", stop=coreLongStop, limit=coreLongTarget)
if strategy.position_size < 0 and activeKind == 1
    strategy.exit("Core Short Risk", "Core Short", stop=coreShortStop, limit=coreShortTarget)
if strategy.position_size > 0 and activeKind == 2
    strategy.exit("Sleeve Long Risk", "Sleeve Long", stop=sleeveLongStop, limit=sleeveLongTarget)
if strategy.position_size < 0 and activeKind == 2
    strategy.exit("Sleeve Short Risk", "Sleeve Short", stop=sleeveShortStop, limit=sleeveShortTarget)
if strategy.position_size > 0 and activeKind == 3
    strategy.exit("Cap Long Risk", "Cap Long", stop=capLongStop, limit=capLongTarget)

if strategy.position_size > 0 and activeKind == 1 and (not inRange or barsHeld >= coreMaxHold)
    strategy.close("Core Long", comment=not inRange ? "Range exit" : "Time exit")
if strategy.position_size < 0 and activeKind == 1 and (not inRange or barsHeld >= coreMaxHold)
    strategy.close("Core Short", comment=not inRange ? "Range exit" : "Time exit")
if strategy.position_size > 0 and activeKind == 1 and coreHoldOk and h4Signal == -1 and dailySignal != 1
    strategy.close("Core Long", comment="Regime exit")
if strategy.position_size < 0 and activeKind == 1 and coreHoldOk and h4Signal == 1 and dailySignal != -1
    strategy.close("Core Short", comment="Regime exit")
if strategy.position_size > 0 and activeKind == 1 and coreHoldOk and macdHist < macdHist[1] and rsiValue < coreLongExitRsi
    strategy.close("Core Long", comment="Momentum exit")
if strategy.position_size < 0 and activeKind == 1 and coreHoldOk and macdHist > macdHist[1] and rsiValue > coreShortExitRsi
    strategy.close("Core Short", comment="Momentum exit")
if strategy.position_size > 0 and activeKind == 2 and (not inRange or barsHeld >= sleeveMaxHold or (sleeveHoldOk and close >= vwapValue + sleeveExitVwapAtr * atrValue))
    strategy.close("Sleeve Long", comment="Sleeve exit")
if strategy.position_size < 0 and activeKind == 2 and (not inRange or barsHeld >= sleeveMaxHold or (sleeveHoldOk and close <= vwapValue - sleeveExitVwapAtr * atrValue))
    strategy.close("Sleeve Short", comment="Sleeve exit")
capMomentumPeakExit = capExitOnPeak and macdHist < macdHist[1] and rangePos <= capExitRangePos
if strategy.position_size > 0 and activeKind == 3 and (not inRange or barsHeld >= capMaxHold or (capHoldOk and (close >= vwapValue + capExitVwapAtr * atrValue or rsiValue >= capExitRsi or capMomentumPeakExit)))
    strategy.close("Cap Long", comment="Cap exit")

activeLongStop = strategy.position_size > 0 and activeKind == 1 ? coreLongStop : strategy.position_size > 0 and activeKind == 2 ? sleeveLongStop : strategy.position_size > 0 and activeKind == 3 ? capLongStop : na
activeShortStop = strategy.position_size < 0 and activeKind == 1 ? coreShortStop : strategy.position_size < 0 and activeKind == 2 ? sleeveShortStop : na
activeLongTarget = strategy.position_size > 0 and activeKind == 1 ? coreLongTarget : strategy.position_size > 0 and activeKind == 2 ? sleeveLongTarget : strategy.position_size > 0 and activeKind == 3 ? capLongTarget : na
activeShortTarget = strategy.position_size < 0 and activeKind == 1 ? coreShortTarget : strategy.position_size < 0 and activeKind == 2 ? sleeveShortTarget : na

plot(showBands ? h4Fast : na, "4H Fast EMA prev", color=color.new(color.aqua, 0))
plot(showBands ? h4Slow : na, "4H Slow EMA prev", color=color.new(color.orange, 0))
plot(showBands ? vwapValue : na, "Session VWAP", color=color.new(color.white, 55))
plot(showBands ? bbUpper : na, "Range upper", color=color.new(color.red, 85))
plot(showBands ? bbLower : na, "Range lower", color=color.new(color.green, 85))
plot(activeLongStop, "Long active stop", color=color.new(color.red, 0), style=plot.style_linebr)
plot(activeLongTarget, "Long active target", color=color.new(color.lime, 65), style=plot.style_linebr)
plot(activeShortStop, "Short active stop", color=color.new(color.lime, 0), style=plot.style_linebr)
plot(activeShortTarget, "Short active target", color=color.new(color.red, 65), style=plot.style_linebr)
plotshape(showSignals and canEnter and coreLong, "Core long", shape.triangleup, location.belowbar, color=color.new(color.lime, 0), size=size.small, text="CL")
plotshape(showSignals and canEnter and coreShort, "Core short", shape.triangledown, location.abovebar, color=color.new(color.fuchsia, 0), size=size.small, text="CS")
plotshape(showSignals and canEnter and cooldownOkSleeve and sleeveLong, "Sleeve long", shape.circle, location.belowbar, color=color.new(color.aqua, 0), size=size.tiny, text="SL")
plotshape(showSignals and canEnter and cooldownOkSleeve and sleeveShort, "Sleeve short", shape.circle, location.abovebar, color=color.new(color.orange, 0), size=size.tiny, text="SS")
plotshape(showSignals and canEnter and cooldownOkCap and capLong, "Cap long", shape.diamond, location.belowbar, color=color.new(color.yellow, 0), size=size.small, text="CAP")
plotshape(showRawSignals and capDeep, "Cap deep raw", shape.circle, location.belowbar, color=color.new(color.blue, 80), size=size.tiny, text="D")
plotshape(showRawSignals and capExhaustion, "Cap exhaustion raw", shape.circle, location.belowbar, color=color.new(color.yellow, 80), size=size.tiny, text="E")
bgcolor(h4Signal == 1 ? color.new(color.green, 93) : color.new(color.red, 94))
{marker_block()}
'''


def main():
    payload = json.loads(REPORT_PATH.read_text())
    OUT_DIR.mkdir(exist_ok=True)
    for rank, item in enumerate(payload["top10"][:6], start=1):
        path = OUT_DIR / f"JD_CL_15m_Capitulation_Sleeve_64k_C{rank}.pine"
        path.write_text(render(rank, item, payload["core_params"], payload["base_sleeve"]))
        print(path)


if __name__ == "__main__":
    main()
