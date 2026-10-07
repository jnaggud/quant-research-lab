# C8 TV Exact Parity - 2026-06-20

## Result

C8 C1 now matches TradingView exactly for completed trades over the exported TradingView window.

- Strategy: `JD ES 15m C8 Successor 200k C1 20260618`
- Symbol/timeframe: `ES1!`, 15m
- TV export: `reports/tv_c8_successor_200k_c1_robust_20260619.json`
- 15m bars: `reports/tv_es1_15m_bars_20260620.json`
- 240m bars: `reports/tv_es1_240m_bars_20260620.json`
- 1D bars: `reports/tv_es1_1d_bars_20260620.json`
- Exact compare: `reports/c8_tv_exact_compare_20260620.json`

## Completed-Trade Parity

| Metric | Local Completed | TradingView Completed | Delta |
| --- | ---: | ---: | ---: |
| Trades | 480 | 480 | 0 |
| Net PnL | 100,812.50 | 100,812.50 | 0.00 |
| Win rate | 43.125% | 43.125% | 0.000% |
| Gross profit | 280,740.00 | 280,740.00 | 0.00 |
| Gross loss | -179,927.50 | -179,927.50 | 0.00 |
| Profit factor | 1.560295 | 1.560295 | 0.000000 |

Trade-by-trade mismatch count: `0`.

## Open Position Handling

TradingView includes one final open mark-to-market row in the Strategy Tester trade list. The local engine creates an `end_of_data` mark for that same still-open position, but this is not counted as completed-trade parity.

The completed trade list is exact after excluding:

- TradingView row where `x.c == ""`
- Local row where `exit_reason == "end_of_data"`

## Important Correction

The earlier apparent mismatch came from comparing:

- local results run through newer bars, and
- TradingView results exported earlier with one open position still active.

After truncating local bars to the TradingView export window and separating open marks from completed trades, the completed trade results match exactly.

## Remaining Baseline Issue

Buy/Hold is still not a parity metric until the local optimizer computes it over the same Pine date-filtered range. This does not affect C8 trade parity, but it should be fixed before using buy/hold excess as an optimization objective again.
