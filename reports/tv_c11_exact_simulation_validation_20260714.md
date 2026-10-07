# C11 Exact TradingView Simulation Audit

## Scope

This audit uses the frozen TradingView Strategy Tester export for `JD ES 15m C11 Trend Carry 200k C1 20260621` and the exact 20,494 ES1! bars loaded by that chart. It does not use the separate local C11 approximation, ML/GEX overlay, or mean-reversion strategy.

The original Pine source was not edited. Its SHA-256 matches the read-only frozen copy:

`f78e404927533c2f37e3b391f3d0e82f98eadeafdb8a90edf637ef90de8611d6`

## Reconstruction

- 469 of 469 entry and exit timestamps matched exact TradingView bars.
- Reconstructed realized P&L is exactly `$126,905`, or `+253.81%` on `$50,000`.
- The report spans September 30, 2025 through July 14, 2026: 247 trading days.
- Daily mark-to-market drawdown is 8.46%. TradingView's intratrade figure is 9.25%; the daily series is expected to be slightly lower because it cannot see every intraday adverse excursion.
- Daily annualized Sharpe is 4.16, measured on this one historical sample.

## Simulation Results

The main run used regime-aware contiguous block resampling, fixed `$50,000` notional, a 756-trading-day horizon, and one million paths.

- Median three-year return: `+761.29%`.
- 5th to 95th percentile return: `+629.87%` to `+897.57%`.
- Median maximum drawdown: `10.08%`.
- Probability of a drawdown above 20%: `1.60%`.
- Probability of a drawdown above 30%: `0.067%`.
- Probability of crossing 50% equity: approximately `0.0001%`.

The 41-case sweep remained strongly profitable across block lengths, bootstrap methods, regime counts, missed-trade assumptions, and up to four extra ticks of round-trip slippage. Four extra ticks reduced the median three-year return from about `+761%` to `+476%`.

The deliberately severe combined stress assumed two extra ticks, 10% missed exposure, large-loss synchronization on 50% of losing days, and recurring doubled gap losses. Under that constructed scenario:

- Median three-year return: `+100.55%`.
- Probability of finishing profitable: `86.31%`.
- Probability of a drawdown above 30%: `84.05%`.
- Probability of crossing 50% equity: `25.43%`.

This scenario is a robustness boundary, not an estimate of likely market behavior.

## Interpretation

The exact Pine strategy is a strong backtest and is materially better than the earlier local approximation. The earlier warning based on that approximation should not be applied to this C11.

It is still not independently validated as a live strategy. The source name dates to June 21, 2026, so most of the 247-day tester history predates deployment. Resampling one strong year into three years preserves its measured edge and repeatedly reuses the same market episodes; it tests sensitivity to ordering and execution assumptions, but cannot prove that the edge will persist.

The practical conclusion is: preserve and continue forward-testing this exact version, do not replace it with the local approximation, and treat the simulation as evidence of internal robustness rather than proof of future returns.
