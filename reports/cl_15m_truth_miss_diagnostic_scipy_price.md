# CL 15m Truth/Missed-Signal Diagnostic

This report compares hindsight local extrema and legacy velocity reversal marks against the current CL hybrid sleeve gates.

## Summary

- data_start: 2025-06-30T22:00:00+00:00
- data_end: 2026-05-08T20:00:00+00:00
- truth_method: scipy_price
- truth_prominence_threshold: 0.6941085869834199
- bars: 20205
- truth_valleys: 385
- truth_peaks: 346
- strategy_long_entries: 161
- strategy_short_entries: 127
- strategy_exits: 288
- missed_truth_valleys: 352
- matched_truth_valleys: 33
- missed_truth_peak_exits: 312

## Top Long Entry Blockers

- core_rsi_low: 336
- sleeve_allowed_false: 324
- core_price_below_ema55: 270
- core_trend_state_false: 183
- sleeve_stoch_false: 125
- sleeve_vwap_not_deep: 119
- sleeve_rsi_too_high: 118
- sleeve_location_false: 114
- already_in_position: 112
- core_volume_low: 91
- sleeve_daily_bearish: 73
- core_direction_false: 51
- core_macd_low: 4
- core_pullback_false: 2

## Context Window

- start: None
- end: None
- truth_valleys: 385
- truth_peaks: 346
- long_entries: 161
- exits: 288

## Recent Missed Truth Valleys

- 2026-05-04T05:15:00+00:00 low=100.12; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-04T09:00:00+00:00 low=102.61; blockers=core_trend_state_false, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-04T14:15:00+00:00 low=101.49; blockers=already_in_position, core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-04T18:00:00+00:00 low=104.75; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-05T07:30:00+00:00 low=103.15; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-05T08:45:00+00:00 low=103.08; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-05T14:00:00+00:00 low=101.08; blockers=already_in_position, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-05T22:45:00+00:00 low=99.12; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-06T01:30:00+00:00 low=100.11; blockers=core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_stoch_false
- 2026-05-06T06:00:00+00:00 low=99.74; blockers=core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_location_false
- 2026-05-06T08:00:00+00:00 low=97.59; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-06T11:00:00+00:00 low=88.66; blockers=core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-06T14:30:00+00:00 low=94.48; blockers=already_in_position, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-06T18:15:00+00:00 low=94.33; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-07T02:00:00+00:00 low=94.83; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_location_false
- 2026-05-07T07:15:00+00:00 low=91.92; blockers=core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-07T12:45:00+00:00 low=89.85; blockers=already_in_position, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-07T14:15:00+00:00 low=90.30; blockers=already_in_position, core_price_below_ema55, core_rsi_low, sleeve_allowed_false, sleeve_location_false, sleeve_stoch_false
- 2026-05-07T17:45:00+00:00 low=94.56; blockers=already_in_position, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-07T20:00:00+00:00 low=94.72; blockers=already_in_position, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-07T22:15:00+00:00 low=96.12; blockers=already_in_position, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-08T02:45:00+00:00 low=95.08; blockers=core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-08T06:15:00+00:00 low=94.15; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false
- 2026-05-08T09:15:00+00:00 low=93.82; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-08T18:00:00+00:00 low=94.59; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false

## Recent Trades

- long core 2026-04-21T18:30:00+00:00 -> 2026-04-22T00:00:00+00:00 reason=core_momentum entry=89.67 exit=89.40
- short core 2026-04-22T07:15:00+00:00 -> 2026-04-22T09:45:00+00:00 reason=core_momentum entry=89.04 exit=90.86
- long core 2026-04-22T16:15:00+00:00 -> 2026-04-23T06:00:00+00:00 reason=time entry=93.22 exit=93.87
- long core 2026-04-23T08:30:00+00:00 -> 2026-04-23T11:00:00+00:00 reason=core_momentum entry=95.00 exit=94.01
- long sleeve 2026-04-23T12:15:00+00:00 -> 2026-04-23T13:45:00+00:00 reason=target entry=92.92 exit=94.42
- long core 2026-04-23T18:30:00+00:00 -> 2026-04-24T02:30:00+00:00 reason=core_momentum entry=96.04 exit=96.44
- long core 2026-04-27T08:00:00+00:00 -> 2026-04-27T10:30:00+00:00 reason=core_momentum entry=96.81 exit=95.44
- long core 2026-04-27T12:30:00+00:00 -> 2026-04-27T19:15:00+00:00 reason=core_momentum entry=96.37 exit=96.10
- long core 2026-04-28T06:30:00+00:00 -> 2026-04-28T11:45:00+00:00 reason=target entry=98.23 exit=101.52
- long core 2026-04-28T13:00:00+00:00 -> 2026-04-28T16:45:00+00:00 reason=core_momentum entry=100.33 exit=99.21
- long core 2026-04-29T11:00:00+00:00 -> 2026-04-29T16:45:00+00:00 reason=target entry=103.15 exit=107.16
- long core 2026-04-29T17:30:00+00:00 -> 2026-04-30T00:00:00+00:00 reason=core_momentum entry=107.15 exit=107.03
- long core 2026-04-30T04:30:00+00:00 -> 2026-04-30T07:00:00+00:00 reason=core_momentum entry=109.88 exit=108.04
- long core 2026-05-04T11:15:00+00:00 -> 2026-05-05T01:00:00+00:00 reason=time entry=105.14 exit=104.97
- long sleeve 2026-05-05T12:00:00+00:00 -> 2026-05-05T22:45:00+00:00 reason=risk_stop entry=103.20 exit=100.69
- short core 2026-05-06T08:15:00+00:00 -> 2026-05-06T10:15:00+00:00 reason=target entry=99.02 exit=92.22
- short core 2026-05-06T11:45:00+00:00 -> 2026-05-06T16:45:00+00:00 reason=core_momentum entry=92.56 exit=95.87
- short core 2026-05-07T07:45:00+00:00 -> 2026-05-07T15:00:00+00:00 reason=core_momentum entry=93.33 exit=91.69
- long core 2026-05-07T15:45:00+00:00 -> 2026-05-08T01:15:00+00:00 reason=core_momentum entry=93.31 exit=95.78
- long sleeve 2026-05-08T13:15:00+00:00 -> 2026-05-08T14:30:00+00:00 reason=target entry=94.16 exit=95.70
