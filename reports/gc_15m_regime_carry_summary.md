# JD GC 15m Regime Carry 64k 20260508

## Files
- Pine: `pine_strategies/JD_GC_15m_Regime_Carry_64k.pine`
- Optimizer report: `reports/gc_15m_regime_carry_64k.json`
- TradingView data export: `tmp/tv_gc1_15m_20250930_20260507.json`

## Market / Range
- Symbol: `COMEX:GC1!` / TradingView internal `COMEX_DL:GC1!`
- Timeframe: 15 minutes
- Optimization date range: September 30, 2025 through May 7, 2026
- Initial capital: `$50,000`
- Position size: `1` GC contract
- Commission: `$2.50` per side
- Slippage: `1` tick

## Optimizer Result
- Net P&L: `$259,977.99`
- Return: `+519.96%`
- Max drawdown: `14.17%`
- Total trades: `344`
- Win rate: `39.83%`
- Profit factor: `1.979`
- Buy-and-hold P&L: `$85,200.00`

## TradingView Backtest Result
- Net P&L: `$251,785.00`
- Return: `+503.57%`
- Max equity drawdown: `$19,397.50` / `16.68%`
- Total trades: `325`
- Win rate: `38.77%`
- Profit factor: `2.01`
- Buy-and-hold return: `$85,210.00` / `+170.42%`
- Strategy outperformance: `$166,575.00`

## Out-of-Sample Pre-Training Test
- Pine: `pine_strategies/JD_GC_15m_Regime_Carry_64k_OOS_PreTrain.pine`
- Test window: June 30, 2025 through September 29, 2025, before the optimized window
- Available exported bars begin: July 11, 2025 05:15 UTC
- TradingView strategy P&L: `$23,330.00` / `+46.66%`
- Max equity drawdown: `$11,807.50` / `19.48%`
- Total trades: `136`
- Win rate: `34.56%`
- Profit factor: `1.489`
- Raw 1-contract GC buy-and-hold over available OOS bars: `$50,730.00` / `+101.46%`
- OOS conclusion: positive standalone performance, but it did not beat buy-and-hold during this strong gold uptrend.

## Notes
- This is a GC-specific 15m futures strategy using the same regime-carry architecture as the ES version.
- It uses H4 trend state, local EMA filtering, RSI/MACD/volume confirmation, ATR stop logic, ATR trailing risk, and both long and short entries.
- The TradingView result is close to the Python result but not identical because TradingView's historical feed, order processing, futures point value handling, session model, and bar availability differ from the exported optimizer dataset.
- TradingView's benchmark comparison can be misleading when a script date filter is used, because the built-in buy-and-hold benchmark may still use the full chart/tester span rather than only the strategy's gated trade window.
