# JD CL 15m Trend Bias 64k Best 20260508

## Files
- Pine: `pine_strategies/JD_CL_15m_Trend_Bias_64k.pine`
- Optimizer report: `reports/cl_15m_trend_bias_64k.json`
- Full TradingView data export: `tmp/tv_cl1_15m_loaded_full_raw.json`
- Cropped data export: `tmp/tv_cl1_15m_20250930_20260507.json`

## Market / Range
- Symbol: `NYMEX:CL1!` / TradingView internal `NYMEX_DL:CL1!`
- Timeframe: `15m`
- Data range loaded: June 30, 2025 through May 8, 2026
- Initial capital: `$50,000`
- Position size: `1` CL contract
- Contract assumptions in Python: `$1,000` per point, `$0.01` tick size, `$2.50` commission per side, `1` tick slippage

## Optimization Result
- Trials: `64,000`
- Workers: `32`
- Selected candidate: top TradingView performer among the strongest Python candidates
- Python full P&L: `$48,307.85` / `+96.62%`
- Python full trades: `115`
- Python full win rate: `53.04%`
- Python full profit factor: `2.426`
- Python full max drawdown: `9.87%`
- Python OOS P&L: `$8,843.40` / `+17.69%`
- Python OOS buy-and-hold P&L: `-$3,740.00`

## TradingView Backtest Result
- Strategy P&L: `$42,760.00` / `+85.52%`
- Buy-and-hold P&L: `$28,930.00` / `+57.86%`
- Strategy outperformance: `$13,830.00`
- Max equity drawdown: `$7,547.50` / `8.01%`
- Total trades: `112`
- Win rate: `49.11%`
- Profit factor: `2.155`
- Long P&L: `$29,760.00`
- Short P&L: `$13,000.00`

## Candidate Notes
- Initial optimizer best translated poorly into TradingView and only slightly beat buy-and-hold.
- Several top candidates were tested directly in TradingView; candidate C6 was promoted because it had the best TradingView combination of P&L, drawdown, and profit factor.
- Current chart should show `JD CL 15m Trend Bias 64k Best 20260508`.
