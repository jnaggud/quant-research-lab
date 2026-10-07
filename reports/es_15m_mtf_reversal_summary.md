# ES 15m MTF Reversal Summary

## Dataset

- Source: TradingView MCP loaded chart bars
- Symbol: `CME_MINI_DL:ES1!`
- Timeframe: `15m`
- Optimization range: Sep 30, 2025 – May 7, 2026
- Exported file: `tmp/tv_es1_15m_20250930_20260507.json`
- Bars used: `14,200`

## Baseline Result

This is the BTC 15m MTF reversal logic retuned for ES.

- Report: `reports/es_15m_mtf_reversal_tv_64k_min60.json`
- Trials: `64,000`
- Minimum trades: `60`
- Best Python-modeled return: `+4.27%`
- Trades: `63`
- Win rate: `74.60%`
- Profit factor: `1.89`
- Max drawdown: `1.37%`
- Direction: long-only was selected by the optimizer

## Best Parameters

- 4H EMA: `11 / 37`
- Daily EMA: `19 / 52`
- Entry score: `4`
- Exit score: `4`
- Stoch valley max: `33.8656`
- Stoch peak min: `62.8195`
- RSI valley max: `32.4064`
- RSI peak min: `56.6820`
- Williams valley max: `-80.2733`
- Williams peak min: `-10.7991`
- Bollinger multiplier: `2.7376`
- ATR displacement: `1.3291`
- Stop ATR: `4.8149`
- Target ATR: `6.9662`
- Cooldown bars: `15`
- Shorts: disabled

## Pine Strategy

- File: `pine_strategies/JD_ES_15m_MTF_Reversal_64k.pine`
- Compile status: passed
- TradingView title: `JD ES 15m MTF Reversal 64k 20260508`

## Caveat

The first ES baseline is stable but not aggressive. It is not yet comparable to the BTC flagship strategy. The same logic appears to work modestly on ES, but the next improvement pass should test ES-specific session filters, RTH-only logic, opening-range filters, volatility regime filters, and futures-specific position sizing.

## TradingView Backtest

Applied on `CME_MINI_DL:ES1!` 15m after enabling futures margin in Pine.

- Strategy Tester displayed data window: Jun 30, 2025 – May 8, 2026
- Pine optimization window enforced by inputs: Sep 30, 2025 – May 7, 2026
- Net P&L: `+12,347.50 USD` / `+24.70%`
- Max equity drawdown: `8,210.00 USD` / `14.83%`
- Total trades: `78`
- Profitable trades: `69.23%` / `54 of 78`
- Profit factor: `1.436`
- Commission paid: `390.00 USD`

## TradingView Backtest: Trend/Reversal + Shorts

Applied on `CME_MINI_DL:ES1!` 15m using `pine_strategies/JD_ES_15m_Trend_Reversal_Short_64k.pine`.

- Source report: `reports/es_15m_trend_reversal_short_force_trend_64k_min150_max1500.json`
- Strategy Tester displayed data window: Jun 30, 2025 – May 8, 2026
- Pine optimization window enforced by inputs: Sep 30, 2025 – May 7, 2026
- Net P&L: `+22,545.00 USD` / `+45.09%`
- Max equity drawdown: `5,550.00 USD` / `8.57%`
- Total trades: `141`
- Profitable trades: `43.97%` / `62 of 141`
- Profit factor: `1.662`
- Long P&L: `+16,012.50 USD`
- Short P&L: `+6,532.50 USD`
- Commission paid: `705.00 USD`

## TradingView Backtest: Regime Carry Beats Buy-and-Hold

Applied on `CME_MINI_DL:ES1!` 15m using `pine_strategies/JD_ES_15m_Regime_Carry_64k.pine`.

- Source report: `reports/es_15m_regime_carry_64k.json`
- Strategy Tester displayed data window: Jun 30, 2025 – May 8, 2026
- Pine optimization window enforced by inputs: Sep 30, 2025 – May 7, 2026
- Net P&L: `+41,717.50 USD` / `+83.44%`
- Buy & hold return: `+35,525.00 USD` / `+71.05%`
- Strategy outperformance: `+6,192.50 USD`
- Max equity drawdown: `11,415.00 USD` / `19.08%`
- Total trades: `239`
- Profit factor: `1.463`
- Long P&L: `+19,860.00 USD`
- Short P&L: `+21,857.50 USD`
- Commission paid: `1,195.00 USD`
