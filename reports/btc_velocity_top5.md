# BTC Velocity Pine Strategy Top 5

Ranking uses available source validation metrics from the Pattern_FindR configs because TradingView Strategy Tester metric extraction returned an empty internal API payload after the first script was added to chart.

| Rank | Pine file | TF | Oscillator | Signal | Return % | Win % | PF | Max DD % | Trades |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | `pine_strategies/velocity_BTCUSD_5y_v2.pine` | 1d | composite_smooth | velocity_crossover_or_zone | 291.86 | 84.62 | 36.75 | 1.87 | 39 |
| 2 | `pine_strategies/velocity_BTCUSD_15m_v15_algo.pine` | 15m | ewaf | any_reversal | 68.54 | 81.90 | 11.73 | 2.00 | 171 |
| 3 | `pine_strategies/velocity_BTCUSD_15m_v15_manual.pine` | 15m | ewaf | any_reversal | 68.54 | 81.90 | 11.73 | 2.00 | 171 |
| 4 | `pine_strategies/velocity_BTCUSD_15m_v2.pine` | 15m | arwo | any_reversal | 68.54 | 81.90 | 11.73 | 2.00 | 171 |
| 5 | `pine_strategies/velocity_BTC_2y_v4.pine` | 1d | composite | zone_only | 26.82 | 77.78 | 3.08 | 4.36 | 18 |

Compile validation: all 24 generated Pine files compile successfully through TradingView server-side Pine check.

TradingView chart state: `pine_strategies/velocity_BTCUSD_15m_v15_algo.pine` was added to the active BTC chart; Strategy Tester metrics were not exposed through the MCP internal API in this session.
