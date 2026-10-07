#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

MARKER_PATH = Path("pine_strategies/JD_ES_15m_SciPy_Truth_Markers_20260519.pine")
OUT_DIR = Path("pine_strategies")


def b(value):
    return "true" if value else "false"


def f(value):
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def marker_block():
    text = MARKER_PATH.read_text()
    start = text.index("showPeaks =")
    body = text[start:].replace("\\n", "\n")
    return (
        "\n// SciPy truth markers are hindsight diagnostic labels generated from exported TradingView data.\n"
        "// They are plotted for analysis only and are not used by the strategy logic.\n"
        + body
    )


def render(rank, item, core, report_path, title_base, date_suffix="20260519"):
    cap = item["params"]
    metrics = item.get("metrics", {}).get("full", item.get("metrics", {}))
    title = f"{title_base} C{rank} {date_suffix}"
    return f'''//@version=6
strategy("{title}", overlay=true, initial_capital=50000, default_qty_type=strategy.fixed, default_qty_value=1, pyramiding=0, margin_long=5, margin_short=5, commission_type=strategy.commission.cash_per_contract, commission_value=2.50, slippage=1, process_orders_on_close=true)

// Source: {report_path} candidate C{rank}, worker {item["worker_id"]}.
// Python reference: net ${metrics["net_profit"]:.2f}, trades {metrics["n_trades"]}, PF {metrics["profit_factor"]:.3f}, max DD {metrics["max_drawdown"]:.2f}%.
// Engine: ES 15m TV-parity successor with optimized core/carry/capitulation sleeves.
h4FastLen = input.int({core["h4_fast"]}, "4H fast EMA", minval=1)
h4SlowLen = input.int({core["h4_slow"]}, "4H slow EMA", minval=1)
dFastLen = input.int({core["d_fast"]}, "Daily fast EMA", minval=1)
dSlowLen = input.int({core["d_slow"]}, "Daily slow EMA", minval=1)
regimeMode = input.string("{core["regime_mode"]}", "Core regime mode", options=["both", "h4", "h4_daily_veto"])
localFilter = input.string("{core["local_filter"]}", "Core local filter", options=["none", "ema21", "ema55", "stack", "ema144"])
coreStopAtr = input.float({f(core["stop_atr"])}, "Core hard stop ATR", step=0.1)
coreTrailAtr = input.float({f(core["trail_atr"])}, "Core trail stop ATR", step=0.1)
coreCooldown = input.int({core["cooldown"]}, "Core cooldown bars", minval=0)
coreLongRsiMin = input.float({f(core["long_rsi_min"])}, "Core long RSI min", step=0.1)
coreShortRsiMax = input.float({f(core["short_rsi_max"])}, "Core short RSI max", step=0.1)
coreMacdFloor = input.float({f(core["macd_floor"])}, "Core MACD floor", step=0.1)
coreVolMult = input.float({f(core["vol_mult"])}, "Core volume multiplier", step=0.01)
useMomentumExit = input.bool({b(core["use_momentum_exit"])}, "Use core momentum exit")
coreLongExitRsi = input.float({f(core["long_exit_rsi"])}, "Core long exit RSI", step=0.1)
coreShortExitRsi = input.float({f(core["short_exit_rsi"])}, "Core short exit RSI", step=0.1)
longExitRegime = input.int({core["long_exit_regime"]}, "Core long exit regime", minval=-1, maxval=0)
shortExitRegime = input.int({core["short_exit_regime"]}, "Core short exit regime", minval=0, maxval=1)
allowShorts = input.bool({b(core["allow_short"])}, "Allow shorts")
shortGate = input.string("{core.get("short_gate", "any")}", "Core short gate", options=["any", "daily_bear", "not_daily_bull", "h4_and_daily_bear"])
useCarryLong = input.bool({b(core.get("use_carry_long", False))}, "Use carry long extension")
carryRegime = input.string("{core.get("carry_regime", "both_up")}", "Carry regime", options=["both_up", "h4_up", "daily_up", "either_up"])
carryFilter = input.string("{core.get("carry_filter", "ema55")}", "Carry local filter", options=["none", "ema21", "ema55", "ema144", "stack"])
carryRsiMin = input.float({f(core.get("carry_rsi_min", 45.0))}, "Carry RSI min", step=0.1)
carryMacdFloor = input.float({f(core.get("carry_macd_floor", -1.0))}, "Carry MACD floor", step=0.1)
carryVolMult = input.float({f(core.get("carry_vol_mult", 0.75))}, "Carry volume multiplier", step=0.01)

useCap = input.bool({b(cap["use_cap"])}, "Use capitulation sleeve")
capPriority = input.bool({b(cap["cap_priority"])}, "Cap sleeve priority")
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
capTrailRelaxPct = input.float({f(cap.get("cap_trail_relax_pct", 0.0))}, "Cap trail down-bar relax pct", minval=0.0, maxval=1.0, step=0.01)
capExitVwapAtr = input.float({f(cap["cap_exit_vwap_atr"])}, "Cap VWAP exit ATR", step=0.1)
capExitRsi = input.float({f(cap["cap_exit_rsi"])}, "Cap exit RSI", step=0.1)
capExitRangePos = input.float({f(cap["cap_exit_range_pos"])}, "Cap peak-exit candle position", step=0.01)
capExitOnPeak = input.bool({b(cap["cap_exit_on_peak"])}, "Cap SciPy peak exit marker")
capExitOnMomentumPeak = input.bool({b(cap["cap_exit_on_momentum_peak"])}, "Cap momentum peak exit")
capCooldown = input.int({cap["cap_cooldown"]}, "Cap cooldown bars", minval=0)
capMinHold = input.int({cap["cap_min_hold"]}, "Cap minimum hold bars", minval=0)
capMaxHold = input.int({cap["cap_max_hold"]}, "Cap maximum hold bars", minval=1)
useParticipation = input.bool({b(cap.get("use_participation", False))}, "Use participation sleeve")
participationPriority = input.bool({b(cap.get("participation_priority", False))}, "Participation sleeve priority")
participationRegime = input.string("{cap.get("participation_regime", "both_up")}", "Participation regime", options=["both_up", "h4_up_daily_not_bear", "h4_up", "daily_up", "either_up"])
participationFilter = input.string("{cap.get("participation_filter", "ema55")}", "Participation local filter", options=["ema21", "ema55", "ema144", "stack", "vwap"])
participationRsiMin = input.float({f(cap.get("participation_rsi_min", 50.0))}, "Participation RSI min", step=0.1)
participationRsiMax = input.float({f(cap.get("participation_rsi_max", 80.0))}, "Participation RSI max", step=0.1)
participationMacdFloor = input.float({f(cap.get("participation_macd_floor", -1.0))}, "Participation MACD floor", step=0.1)
participationVolMult = input.float({f(cap.get("participation_vol_mult", 0.5))}, "Participation volume multiplier", step=0.01)
participationAdxMin = input.float({f(cap.get("participation_adx_min", 10.0))}, "Participation ADX min", step=0.1)
participationMaxExtensionAtr = input.float({f(cap.get("participation_max_extension_atr", 3.0))}, "Participation max extension ATR", step=0.1)
participationStopAtr = input.float({f(cap.get("participation_stop_atr", 5.0))}, "Participation hard stop ATR", step=0.1)
participationTrailAtr = input.float({f(cap.get("participation_trail_atr", 6.0))}, "Participation trail ATR", step=0.1)
participationCooldown = input.int({cap.get("participation_cooldown", 0)}, "Participation cooldown bars", minval=0)
participationMinHold = input.int({cap.get("participation_min_hold", 0)}, "Participation minimum hold bars", minval=0)
participationMaxHold = input.int({cap.get("participation_max_hold", 10000)}, "Participation maximum hold bars", minval=1)
participationExitFilter = input.string("{cap.get("participation_exit_filter", "ema55")}", "Participation exit filter", options=["ema21", "ema55", "ema144", "vwap", "h4_down", "daily_bear"])
participationExitRsi = input.float({f(cap.get("participation_exit_rsi", 45.0))}, "Participation exit RSI", step=0.1)
participationExitOnMacdRoll = input.bool({b(cap.get("participation_exit_on_macd_roll", True))}, "Participation MACD-roll exit")

useDateRange = input.bool(true, "Use optimization date range")
startTime = input.time(1759190400000, "Start")
endTime = input.time(4102444799000, "End")
showSignals = input.bool(true, "Show entry signals")
showRawSignals = input.bool(false, "Show raw setups")
showMtfLines = input.bool(true, "Show MTF / router levels")

h4Fast = request.security(syminfo.tickerid, "240", ta.ema(close, h4FastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
h4Slow = request.security(syminfo.tickerid, "240", ta.ema(close, h4SlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dFast = request.security(syminfo.tickerid, "1D", ta.ema(close, dFastLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
dSlow = request.security(syminfo.tickerid, "1D", ta.ema(close, dSlowLen)[1], barmerge.gaps_off, barmerge.lookahead_off)
prevDayLow = request.security(syminfo.tickerid, "1D", low[1], barmerge.gaps_off, barmerge.lookahead_off)

h4Signal = h4Fast > h4Slow ? 1 : -1
dailySignal = dFast > dSlow ? 1 : -1
regime = regimeMode == "both" ? (h4Signal == dailySignal ? h4Signal : 0) : regimeMode == "h4" ? h4Signal : (dailySignal == -h4Signal ? 0 : h4Signal)
inRange = not useDateRange or (time >= startTime and time <= endTime)

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
bbLower = bbBasis - 2.0 * bbDev
vwapValue = ta.vwap(hlc3)
atrRel = atrValue / ta.sma(atrValue, 192)
vwapDist = (close - vwapValue) / atrValue
ret1 = ta.change(close) / close[1]
retMean = ta.sma(ret1, 96)
retStd = ta.stdev(ret1, 96)
retZ = retStd != 0.0 ? (ret1 - retMean) / retStd : 0.0
rangePos = (close - low) / math.max(high - low, syminfo.mintick)
low24 = ta.lowest(low, 24)[1]
low96 = ta.lowest(low, 96)[1]
priceVelocity = ta.change(close)
pvMomentum = math.sum(priceVelocity * volume, 4)
pvStd = ta.stdev(pvMomentum, 96)
pvZ = pvStd != 0.0 ? pvMomentum / pvStd : 0.0
climaxVolume = volume / ta.sma(volume, 96)

longFilter = localFilter == "none" ? true : localFilter == "ema21" ? close > ema21 : localFilter == "ema55" ? close > ema55 : localFilter == "stack" ? ema8 > ema21 and ema21 > ema55 and close > ema8 : close > ema144
shortFilter = localFilter == "none" ? true : localFilter == "ema21" ? close < ema21 : localFilter == "ema55" ? close < ema55 : localFilter == "stack" ? ema8 < ema21 and ema21 < ema55 and close < ema8 : close < ema144
coreVolOk = volume >= coreVolMult * volSma
shortGateOk = shortGate == "any" or (shortGate == "daily_bear" and dailySignal == -1) or (shortGate == "not_daily_bull" and dailySignal != 1) or (shortGate == "h4_and_daily_bear" and h4Signal == -1 and dailySignal == -1)
carryRegimeOk = (carryRegime == "h4_up" and h4Signal == 1) or (carryRegime == "daily_up" and dailySignal == 1) or (carryRegime == "both_up" and h4Signal == 1 and dailySignal == 1) or (carryRegime == "either_up" and (h4Signal == 1 or dailySignal == 1))
carryFilterOk = carryFilter == "none" ? true : carryFilter == "ema21" ? close > ema21 : carryFilter == "ema55" ? close > ema55 : carryFilter == "ema144" ? close > ema144 : ema8 > ema21 and ema21 > ema55 and close > ema8
coreBaseLong = regime == 1 and longFilter and rsiValue >= coreLongRsiMin and macdHist >= coreMacdFloor and coreVolOk
carryLong = useCarryLong and carryRegimeOk and carryFilterOk and rsiValue >= carryRsiMin and macdHist >= carryMacdFloor and volume >= carryVolMult * volSma
coreLong = inRange and (coreBaseLong or carryLong)
coreShort = inRange and allowShorts and shortGateOk and regime == -1 and shortFilter and rsiValue <= coreShortRsiMax and macdHist <= -coreMacdFloor and coreVolOk

kCrossUp = stochK[1] <= stochD[1] and stochK > stochD
capRegimeOk = capRegime == "any" or (capRegime == "daily_not_bear" and dailySignal != -1) or (capRegime == "h4_up" and h4Signal == 1) or (capRegime == "either_up" and (h4Signal == 1 or dailySignal == 1))
capDeep = vwapDist <= -capVwapDistAtr or close <= bbLower + capBbAtr * atrValue or close <= prevDayLow + capPrevLowAtr * atrValue or low <= low24 - capLowBreakAtr * atrValue or low <= low96 + capLow96Atr * atrValue
capExhaustion = rsiValue <= capRsiMax and stochK <= capStochMax and retZ <= -capRetZ and rangePos >= capReclaimPos and climaxVolume >= capVolumeMult and pvZ <= capPvZMax and atrRel >= capAtrRelMin and atrRel <= capAtrRelMax and adxValue >= capAdxMin and adxValue <= capAdxMax
capReversal = kCrossUp or close > close[1] or macdHist > macdHist[1]
capLong = inRange and useCap and capRegimeOk and capDeep and capExhaustion and (not capRequireReversal or capReversal)
participationRegimeOk = (participationRegime == "h4_up" and h4Signal == 1) or (participationRegime == "daily_up" and dailySignal == 1) or (participationRegime == "both_up" and h4Signal == 1 and dailySignal == 1) or (participationRegime == "h4_up_daily_not_bear" and h4Signal == 1 and dailySignal != -1) or (participationRegime == "either_up" and (h4Signal == 1 or dailySignal == 1))
participationFilterOk = participationFilter == "ema21" ? close > ema21 : participationFilter == "ema55" ? close > ema55 : participationFilter == "ema144" ? close > ema144 : participationFilter == "stack" ? ema8 > ema21 and ema21 > ema55 and close > ema8 : close > vwapValue
participationExtensionOk = close - ema21 <= participationMaxExtensionAtr * atrValue
participationLong = inRange and useParticipation and participationRegimeOk and participationFilterOk and participationExtensionOk and rsiValue >= participationRsiMin and rsiValue <= participationRsiMax and macdHist >= participationMacdFloor and volume >= participationVolMult * volSma and adxValue >= participationAdxMin
participationFilterExit = (participationExitFilter == "ema21" and close < ema21) or (participationExitFilter == "ema55" and close < ema55) or (participationExitFilter == "ema144" and close < ema144) or (participationExitFilter == "vwap" and close < vwapValue) or (participationExitFilter == "h4_down" and h4Signal != 1) or (participationExitFilter == "daily_bear" and dailySignal == -1)
participationCloseExit = h4Signal != 1 or participationFilterExit or rsiValue < participationExitRsi or (participationExitOnMacdRoll and macdHist < macdHist[1] and rsiValue < participationRsiMin)

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

coreReady = na(lastExitBar) or bar_index - lastExitBar >= coreCooldown
capReady = na(lastExitBar) or bar_index - lastExitBar >= capCooldown
participationReady = na(lastExitBar) or bar_index - lastExitBar >= participationCooldown
canEnter = strategy.position_size == 0 and not flatNow

if canEnter and capPriority and capReady and capLong
    strategy.entry("Cap Long", strategy.long)
    entryBar := bar_index
    activeKind := 2
    entryHigh := high
    entryLow := low
else if canEnter and participationPriority and participationReady and participationLong
    strategy.entry("Participation Long", strategy.long)
    entryBar := bar_index
    activeKind := 3
    entryHigh := high
    entryLow := low
else if canEnter and coreReady and coreLong
    strategy.entry("Core Long", strategy.long)
    entryBar := bar_index
    activeKind := 1
    entryHigh := high
    entryLow := low
else if canEnter and participationReady and participationLong
    strategy.entry("Participation Long", strategy.long)
    entryBar := bar_index
    activeKind := 3
    entryHigh := high
    entryLow := low
else if canEnter and coreReady and coreShort
    strategy.entry("Core Short", strategy.short)
    entryBar := bar_index
    activeKind := 1
    entryHigh := high
    entryLow := low
else if canEnter and capReady and capLong
    strategy.entry("Cap Long", strategy.long)
    entryBar := bar_index
    activeKind := 2
    entryHigh := high
    entryLow := low

barsHeld = strategy.position_size != 0 and not na(entryBar) ? bar_index - entryBar : 0
coreLongStop = math.max(strategy.position_avg_price - coreStopAtr * atrValue, entryHigh - coreTrailAtr * atrValue)
coreShortStop = math.min(strategy.position_avg_price + coreStopAtr * atrValue, entryLow + coreTrailAtr * atrValue)
capHardStop = strategy.position_avg_price - capStopAtr * atrValue
capTrailStop = entryHigh - capTrailAtr * atrValue
capTrailStop := close < close[1] ? capTrailStop - math.max(capTrailStop - capHardStop, 0.0) * capTrailRelaxPct : capTrailStop
capLongStop = math.max(capHardStop, capTrailStop)
capLongTarget = strategy.position_avg_price + capTargetAtr * atrValue
participationLongStop = math.max(strategy.position_avg_price - participationStopAtr * atrValue, entryHigh - participationTrailAtr * atrValue)

if strategy.position_size > 0 and activeKind == 1
    strategy.exit("Core Long Risk", "Core Long", stop=coreLongStop)
if strategy.position_size < 0 and activeKind == 1
    strategy.exit("Core Short Risk", "Core Short", stop=coreShortStop)
if strategy.position_size > 0 and activeKind == 2
    strategy.exit("Cap Long Risk", "Cap Long", stop=capLongStop, limit=capLongTarget)
if strategy.position_size > 0 and activeKind == 3
    strategy.exit("Participation Long Risk", "Participation Long", stop=participationLongStop)

if strategy.position_size > 0 and activeKind == 1 and (not inRange or regime <= longExitRegime)
    strategy.close("Core Long", comment="Regime exit")
if strategy.position_size < 0 and activeKind == 1 and (not inRange or regime >= shortExitRegime)
    strategy.close("Core Short", comment="Regime exit")
if strategy.position_size > 0 and activeKind == 1 and useMomentumExit and macdHist < macdHist[1] and rsiValue < coreLongExitRsi
    strategy.close("Core Long", comment="Momentum exit")
if strategy.position_size < 0 and activeKind == 1 and useMomentumExit and macdHist > macdHist[1] and rsiValue > coreShortExitRsi
    strategy.close("Core Short", comment="Momentum exit")
capMomentumPeakExit = capExitOnMomentumPeak and macdHist < macdHist[1] and rangePos <= capExitRangePos
if strategy.position_size > 0 and activeKind == 2 and (not inRange or barsHeld >= capMaxHold or (barsHeld >= capMinHold and (close >= vwapValue + capExitVwapAtr * atrValue or rsiValue >= capExitRsi or capMomentumPeakExit)))
    strategy.close("Cap Long", comment="Cap exit")
if strategy.position_size > 0 and activeKind == 3 and (not inRange or barsHeld >= participationMaxHold or (barsHeld >= participationMinHold and participationCloseExit))
    strategy.close("Participation Long", comment="Participation exit")

if strategy.position_size != 0
    entryHigh := na(entryHigh) ? high : math.max(entryHigh, high)
    entryLow := na(entryLow) ? low : math.min(entryLow, low)

activeLongStop = strategy.position_size > 0 and activeKind == 1 ? coreLongStop : strategy.position_size > 0 and activeKind == 2 ? capLongStop : strategy.position_size > 0 and activeKind == 3 ? participationLongStop : na
activeShortStop = strategy.position_size < 0 and activeKind == 1 ? coreShortStop : na
activeLongTarget = strategy.position_size > 0 and activeKind == 2 ? capLongTarget : na

plot(showMtfLines ? h4Fast : na, "4H Fast EMA prev", color=color.new(color.aqua, 0))
plot(showMtfLines ? h4Slow : na, "4H Slow EMA prev", color=color.new(color.orange, 0))
plot(showMtfLines ? dFast : na, "Daily Fast EMA prev", color=color.new(color.lime, 60), linewidth=2)
plot(showMtfLines ? dSlow : na, "Daily Slow EMA prev", color=color.new(color.red, 60), linewidth=2)
plot(showMtfLines ? vwapValue : na, "Session VWAP", color=color.new(color.white, 55))
plot(activeLongStop, "Long active stop", color=color.new(color.red, 0), style=plot.style_linebr)
plot(activeLongTarget, "Long active target", color=color.new(color.lime, 65), style=plot.style_linebr)
plot(activeShortStop, "Short active stop", color=color.new(color.lime, 0), style=plot.style_linebr)
plotshape(showSignals and canEnter and coreReady and coreLong, "Core long", shape.triangleup, location.belowbar, color=color.new(color.lime, 0), size=size.small, text="CL")
plotshape(showSignals and canEnter and coreReady and coreShort, "Core short", shape.triangledown, location.abovebar, color=color.new(color.fuchsia, 0), size=size.small, text="CS")
plotshape(showSignals and canEnter and capReady and capLong, "Cap long", shape.diamond, location.belowbar, color=color.new(color.yellow, 0), size=size.small, text="CAP")
plotshape(showSignals and canEnter and participationReady and participationLong, "Participation long", shape.triangleup, location.belowbar, color=color.new(color.aqua, 0), size=size.tiny, text="PL")
plotshape(showRawSignals and capDeep, "Cap deep raw", shape.circle, location.belowbar, color=color.new(color.blue, 80), size=size.tiny, text="D")
plotshape(showRawSignals and capExhaustion, "Cap exhaustion raw", shape.circle, location.belowbar, color=color.new(color.yellow, 80), size=size.tiny, text="E")
bgcolor(regime == 1 ? color.new(color.green, 92) : regime == -1 ? color.new(color.red, 94) : color.new(color.gray, 94))
{marker_block()}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="reports/es_15m_capitulation_sleeve_64k.json")
    parser.add_argument("--title-base", default="JD ES 15m Capitulation Sleeve 64k")
    parser.add_argument("--file-prefix", default="JD_ES_15m_Capitulation_Sleeve_64k")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--date-suffix", default="20260519")
    args = parser.parse_args()

    report_path = Path(args.report)
    payload = json.loads(report_path.read_text())
    OUT_DIR.mkdir(exist_ok=True)
    for rank, item in enumerate(payload["top10"][:args.top], start=1):
        path = OUT_DIR / f"{args.file_prefix}_C{rank}.pine"
        path.write_text(render(rank, item, payload.get("core_params", item["params"]), report_path, args.title_base, args.date_suffix))
        print(path)


if __name__ == "__main__":
    main()
