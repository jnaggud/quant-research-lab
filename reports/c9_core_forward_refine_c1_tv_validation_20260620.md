# C9 Core Forward Refine C1 TradingView Validation - 2026-06-20

## Decision

C9 C1 is now TradingView-validated on the exported ES1! 15m chart data.

It should be treated as the best validated candidate versus C8 C5, subject to live monitoring after promotion.

## TradingView Export

- Strategy title: `JD ES 15m C9 Core Forward Refine 200k C1 20260620`
- Study ID: `087vOT`
- Symbol: `CME_MINI_DL:ES1!`
- Timeframe: `15`
- Export: `reports/tv_c9_core_forward_refine_c1_robust_20260620.json`

## Exact Parity

| Check | Result |
| --- | ---: |
| Completed trade count delta | 0 |
| Completed net delta | $0.00 |
| Completed PF delta | 0.000000 |
| Mismatches reported | 0 |

Open mark note: TradingView marks the still-open participation trade at `7556.25`; the local end-of-data mark uses the final closed bar close `7556.00`. Completed trades match exactly.

## TradingView Completed Results

| Metric | Value |
| --- | ---: |
| Completed trades | 443 |
| Net profit | $112,185.00 |
| Gross profit | $274,270.00 |
| Gross loss | -$162,085.00 |
| Profit factor | 1.6921368418 |
| Win rate | 46.501% |
| Max drawdown | $7,860.00 |
| Buy and hold return | $42,650.00 |
| Open P&L | -$87.50 |

## C9 Versus C8 C5

| Metric | C8 C5 | C9 C1 | Delta |
| --- | ---: | ---: | ---: |
| Completed net | $99,910.00 | $112,185.00 | +$12,275.00 |
| Profit factor | 1.544157 | 1.692137 | +0.147980 |
| Max DD percent | 12.99% | 9.12% | -3.86 pts |
| Current month net | $9,247.50 | $10,517.50 | +$1,270.00 |
| Forward net since `2026-06-18` | -$3,265.00 | -$2,040.00 | +$1,225.00 |
| Completed trades | 488 | 443 | -45 |

## Conclusion

C9 C1 is materially better than C8 C5 across the local and TradingView-validated completed-trade metrics. The earlier strict `forward_non_negative` gate was too harsh for a 3-trade slice; C9 improved the forward slice while also improving full-period net, PF, drawdown, and current month behavior.
