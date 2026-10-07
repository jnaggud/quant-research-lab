# TV C8 Successor 200k C1 Parity - 2026-06-19

## TradingView Export

- Strategy: `JD ES 15m C8 Successor 200k C1 20260618`
- Symbol/timeframe: `ES1!`, 15m
- Study ID: `087vOT`
- Export: `reports/tv_c8_successor_200k_c1_robust_20260619.json`
- Screenshot: `reports/c8_strategy_tester_20260619.png`

## Key Result

TradingView export now works after restarting TradingView with a clean CDP socket and running the checkpointed exporter outside the sandbox.

TV reports 481 trade rows because the final row is the currently open long marked to market. Excluding that open row leaves 480 completed trades, matching the local C8 C1 result.

| Metric | Local C8 C1 | TV Completed | TV Including Open Mark |
| --- | ---: | ---: | ---: |
| Net PnL | 100,987.50 | 100,812.50 | 101,030.00 |
| Trades | 480 | 480 | 481 rows |
| Win rate | 43.125% | 43.125% | 43.243% |
| Profit factor | 1.562 | 1.560 | 1.562 |
| Buy/Hold | 59,637.50 | 42,625.00 | 42,625.00 |

## TV Risk/State

- Max strategy drawdown: 13,885.00
- Open P&L from Strategy Tester performance block: 225.00
- Open-like final row P&L at export: 220.00
- Gross profit, completed trades: 280,740.00
- Gross loss, completed trades: -179,927.50
- Completed wins/losses: 207 / 273

## Interpretation

The C8 Pine strategy is loaded and materially matches the local result on the core parity metrics. The small net difference is consistent with live-data drift and the current open position mark:

- Local C8 C1 net: 100,987.50
- TV completed net: 100,812.50
- Difference: -175.00
- TV including open mark: 101,030.00
- Difference versus local: +42.50

The one larger mismatch is Buy/Hold. TV is respecting the Pine date range visible in the strategy title (`2025-09-30` start), while the local C8 report's buy/hold baseline was computed over the loaded local feature window. This affects the baseline comparison, not the strategy trade parity.

## Next Gate

Use C8 C1 as the current promoted successor candidate, but fix the local buy/hold baseline calculation to respect the strategy date filter before using buy/hold excess as an optimizer objective again.
