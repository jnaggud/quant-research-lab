# CL 15m Truth/Missed-Signal Diagnostic

This report compares hindsight local extrema and legacy velocity reversal marks against the current CL hybrid sleeve gates.

## Summary

- data_start: 2026-05-11T22:00:00+00:00
- data_end: 2026-05-19T07:45:00+00:00
- truth_method: scipy_oscillator
- truth_prominence_threshold: 0.15
- bars: 500
- truth_valleys: 179
- truth_peaks: 166
- strategy_long_entries: 3
- strategy_short_entries: 0
- strategy_exits: 2
- missed_truth_valleys: 174
- matched_truth_valleys: 5
- missed_truth_peak_exits: 164

## Top Long Entry Blockers

- sleeve_allowed_false: 157
- sleeve_rsi_too_high: 133
- sleeve_vwap_not_deep: 127
- sleeve_location_false: 113
- core_rsi_low: 110
- sleeve_stoch_false: 102
- core_trend_state_false: 91
- core_volume_low: 85
- core_price_below_ema55: 65
- sleeve_daily_bearish: 32
- already_in_position: 21
- core_pullback_false: 12
- core_direction_false: 6

## Context Window

- start: 2026-05-18T00:00:00Z
- end: 2026-05-19T00:00:00Z
- truth_valleys: 39
- truth_peaks: 36
- long_entries: 2
- exits: 1

## Recent Missed Truth Valleys

- 2026-05-18T11:00:00+00:00 low=102.32; blockers=core_trend_state_false, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T11:15:00+00:00 low=102.26; blockers=core_trend_state_false, core_rsi_low, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T11:30:00+00:00 low=100.16; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T11:45:00+00:00 low=100.34; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T12:00:00+00:00 low=100.75; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T12:15:00+00:00 low=101.03; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T12:30:00+00:00 low=99.24; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T12:45:00+00:00 low=98.60; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T13:00:00+00:00 low=98.95; blockers=core_trend_state_false, core_price_below_ema55, core_rsi_low, sleeve_allowed_false
- 2026-05-18T16:30:00+00:00 low=102.89; blockers=core_trend_state_false, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T16:45:00+00:00 low=102.71; blockers=core_trend_state_false, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T17:00:00+00:00 low=102.24; blockers=core_trend_state_false, core_rsi_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T17:15:00+00:00 low=102.19; blockers=core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T20:00:00+00:00 low=101.37; blockers=already_in_position, core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false
- 2026-05-18T20:15:00+00:00 low=101.10; blockers=already_in_position, core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-18T20:30:00+00:00 low=101.68; blockers=already_in_position, core_trend_state_false, core_price_below_ema55, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-18T20:45:00+00:00 low=101.87; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T22:00:00+00:00 low=102.12; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-18T22:15:00+00:00 low=102.30; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_rsi_too_high
- 2026-05-19T03:30:00+00:00 low=102.67; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-19T03:45:00+00:00 low=102.74; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-19T04:00:00+00:00 low=102.64; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-19T04:15:00+00:00 low=102.70; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false
- 2026-05-19T04:30:00+00:00 low=102.69; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high
- 2026-05-19T04:45:00+00:00 low=102.59; blockers=already_in_position, core_trend_state_false, core_rsi_low, core_volume_low, sleeve_allowed_false, sleeve_vwap_not_deep, sleeve_location_false, sleeve_rsi_too_high, sleeve_stoch_false

## Recent Trades

- long core 2026-05-15T10:00:00+00:00 -> 2026-05-15T13:00:00+00:00 reason=core_momentum entry=100.19 exit=99.49
- long sleeve 2026-05-18T07:15:00+00:00 -> 2026-05-18T11:00:00+00:00 reason=target entry=102.12 exit=103.06
