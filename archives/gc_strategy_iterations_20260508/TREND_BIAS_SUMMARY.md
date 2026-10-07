# JD GC 15m Trend Bias 64k 20260508

## Fallback
- Saved current fallback before changes: `archives/gc_strategy_iterations_20260508/fallback_current/`
- Fallback Pine: `archives/gc_strategy_iterations_20260508/fallback_current/JD_GC_15m_Regime_Carry_64k.pine`

## Files
- Pine: `pine_strategies/JD_GC_15m_Trend_Bias_64k.pine`
- OOS Pine: `pine_strategies/JD_GC_15m_Trend_Bias_64k_OOS_PreTrain.pine`
- Optimizer: `scripts/optimize_gc_15m_trend_bias_mp.py`
- Optimizer report: `reports/gc_15m_trend_bias_64k.json`
- Source data: `tmp/tv_gc1_15m_loaded_full_raw.json`

## Optimization Result
- Trials: `64,000`
- Workers: `32`
- Full raw-data P&L: `$299,647.01` / `+599.29%`
- Full buy-and-hold P&L: `$137,530.00`
- Full trades: `154`
- Full win rate: `53.25%`
- Full profit factor: `3.605`
- Full max drawdown: `9.60%`
- Pre-training OOS P&L: `$45,495.01` / `+90.99%`
- Pre-training OOS buy-and-hold P&L: `$51,790.00`

## TradingView Full Backtest
- Symbol: `COMEX_DL:GC1!`
- Timeframe: `15m`
- Strategy P&L: `$327,525.00` / `+655.05%`
- Buy-and-hold P&L: `$138,100.00` / `+276.20%`
- Strategy outperformance: `$189,425.00`
- Max equity drawdown: `$17,432.50` / `21.12%`
- Total trades: `137`
- Win rate: `57.66%`
- Profit factor: `4.139`

## TradingView Pre-Training OOS Check
- Strategy P&L: `$31,065.00` / `+62.13%`
- Max equity drawdown: `$17,982.50` / `35.45%`
- Total trades: `45`
- Win rate: `37.78%`
- Profit factor: `2.056`
- TradingView's displayed buy-and-hold benchmark is not valid for this date-gated OOS script because it uses the full tester span, not only the script's active trade window.

## Conclusion
- The trend-biased variant is materially better than the prior GC regime-carry version on the full TradingView range.
- It beats buy-and-hold on the full TradingView backtest.
- It remains profitable in the pre-training OOS window, but it does not cleanly beat raw buy-and-hold over that OOS window. Treat it as the current best candidate, not a final publishable paid strategy.
