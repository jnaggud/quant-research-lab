# CL 15m Truth/Missed-Signal Diagnostic

This report compares hindsight local extrema and legacy velocity reversal marks against the current CL hybrid sleeve gates.

## Summary

- data_start: 2026-05-11T22:00:00+00:00
- data_end: 2026-05-19T07:45:00+00:00
- truth_method: scipy_price
- truth_prominence_threshold: 0.5058803999999999
- bars: 500
- truth_valleys: 24
- truth_peaks: 23
- strategy_long_entries: 3
- strategy_short_entries: 0
- strategy_exits: 2
- missed_truth_valleys: 23
- matched_truth_valleys: 1
- missed_truth_peak_exits: 22

## Top Long Entry Blockers

- sleeve_allowed_false: 23
- core_rsi_low: 22
- core_price_below_ema55: 15
- sleeve_rsi_too_high: 14
- core_trend_state_false: 13
- sleeve_vwap_not_deep: 11
- core_volume_low: 10
- sleeve_location_false: 8
- sleeve_stoch_false: 6
- sleeve_daily_bearish: 2
- already_in_position: 2

## Context Window

- start: 2026-05-18T00:00:00Z
- end: 2026-05-19T00:00:00Z
- truth_valleys: 7
- truth_peaks: 6
- long_entries: 2
- exits: 1

## Recent Missed Truth Valleys

- 2026-05-12T12:45:00+00:00 low=100.60; blockers=core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_daily_bearish
- 2026-05-12T15:45:00+00:00 low=101.16; blockers=core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false, sleeve_daily_bearish
- 2026-05-13T00:30:00+00:00 low=100.93; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false
- 2026-05-13T05:45:00+00:00 low=100.56; blockers=core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false
- 2026-05-13T16:15:00+00:00 low=100.85; blockers=core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_location_false
- 2026-05-13T18:45:00+00:00 low=100.69; blockers=core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-13T20:45:00+00:00 low=100.70; blockers=core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_location_false
- 2026-05-14T06:45:00+00:00 low=99.60; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-14T08:30:00+00:00 low=101.00; blockers=core_trend_state_false, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-14T10:00:00+00:00 low=100.11; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-14T12:15:00+00:00 low=99.39; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_rsi_too_high
- 2026-05-14T16:15:00+00:00 low=100.25; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-14T18:30:00+00:00 low=101.07; blockers=core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-14T22:15:00+00:00 low=97.23; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false
- 2026-05-15T02:45:00+00:00 low=97.83; blockers=core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-15T10:45:00+00:00 low=98.65; blockers=already_in_position, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-15T13:30:00+00:00 low=99.18; blockers=core_trend_state_false, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-18T00:00:00+00:00 low=102.00; blockers=core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T05:45:00+00:00 low=102.56; blockers=core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-18T11:30:00+00:00 low=100.16; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T12:45:00+00:00 low=98.60; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T17:15:00+00:00 low=102.19; blockers=core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T20:15:00+00:00 low=101.10; blockers=already_in_position, core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high

## Recent Trades

- long core 2026-05-15T10:00:00+00:00 -> 2026-05-15T13:00:00+00:00 reason=core_momentum entry=100.19 exit=99.49
- long sleeve 2026-05-18T07:15:00+00:00 -> 2026-05-18T11:00:00+00:00 reason=target entry=102.12 exit=103.06
