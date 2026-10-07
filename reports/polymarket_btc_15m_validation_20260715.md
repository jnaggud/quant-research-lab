# Polymarket BTC 15-Minute Strategy Research

## Verdict

The current research candidate is a **paper-trading-only late-favorite strategy**:

- Observe the recurring BTC Up/Down contract at 10 minutes elapsed.
- Require a live, executable order-book quote no more than 15 seconds old.
- Buy the favorite only when its ask is at least 0.55 and no more than 0.98.
- Cap each paper order at $10 until forward execution is measured.

This is not yet approved for live capital. Historical trade prints do not reconstruct the
full bid/ask queue, fill probability, latency, or Chainlink/Binance basis at decision time.

## Data

- 4,000 resolved BTC 15-minute markets indexed from Polymarket.
- 3,999 market histories from CLOB price history plus public-trade reconstruction.
- 60,137 matching BTCUSDT one-minute bars.
- Historical range: 2026-06-03 through 2026-07-15.
- Chronological split: 60% train, 20% validation, 20% untouched holdout.

Only 2,038 markets had a fresh trade within 60 seconds of the 10-minute decision point.
This availability filter was applied before the chronological split.

## Untouched Holdout

Validation selected the 0.55 favorite threshold. On the newest 20%:

| Assumed adverse execution | Trades | Net per 1-share sequence | Average | Win rate | Max drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 cent | 352 | 24.63 | 0.0700 | 97.73% | -1.99 |
| 2 cents | 308 | 21.35 | 0.0693 | 97.40% | -2.06 |
| 3 cents | 272 | 18.48 | 0.0679 | 97.06% | -2.11 |
| 5 cents | 213 | 13.84 | 0.0650 | 96.24% | -2.21 |

Net results include the crypto taker-fee formula. Trades whose stressed execution price
would reach $1 were rejected.

## Model Comparison

The logistic model used Polymarket probability, BTC movement, 5/15/60-minute momentum,
and realized volatility. At 10 minutes it earned 15.96 on 244 holdout trades under the
1-cent assumption. The simpler late-favorite rule earned 24.63 on 352 trades, so the model
is not part of the candidate strategy.

Earlier entry delays were not robust: the 3-minute and 5-minute model variants lost money
on holdout. The 1-minute variant failed under 3-cent execution stress.

## Required Forward Gate

Run the candidate in paper mode against live CLOB best asks for at least 500 signals and
30 calendar days. Record quote age, spread, depth, submitted limit, simulated fill, BTC
reference prices, resolution, fee, and P&L. Do not promote it unless net expectancy remains
positive after actual observed spread/latency costs and across weekly subperiods.
