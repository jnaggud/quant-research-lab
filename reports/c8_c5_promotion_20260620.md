# C8 C5 Promotion - 2026-06-20

## Decision

Promote `JD ES 15m C8 Successor 200k C5 20260618` as the current best validated C8 candidate.

C8 C1 remains a strong candidate and has slightly higher net/PF on the original optimizer dataset, but after correcting the buy-and-hold baseline and using a risk-aware composite rerank, C8 C5 is the better overall production candidate because it preserves nearly all of the return while materially reducing drawdown.

## Corrected Rerank

Corrected rerank report: `reports/c8_family_corrected_rerank_20260620.md`

| Candidate | Net | PF | Max DD % | Trades | Corrected Excess | June | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C8 C5 | 100,715.00 | 1.550957 | 12.989114 | 487 | 58,665.00 | 10,052.50 | 157,293.8971 |
| C8 C1 | 100,987.50 | 1.561814 | 14.193972 | 480 | 58,937.50 | 10,282.50 | 155,334.1752 |
| C7 C1 | 95,085.00 | 1.542436 | 18.501439 | 478 | 53,035.00 | 8,457.50 | 131,899.5578 |

## TradingView Exact Parity

TradingView export: `reports/tv_c8_successor_200k_c5_robust_20260620.json`

Exact comparison: `reports/c8_c5_tv_exact_compare_20260620.json`

Screenshot: `reports/c8_c5_strategy_tester_20260620.png`

| Metric | Local Completed | TradingView Completed | Delta |
| --- | ---: | ---: | ---: |
| Trades | 488 | 488 | 0 |
| Net PnL | 99,910.00 | 99,910.00 | 0.00 |
| Win rate | 43.442623% | 43.442623% | 0.000000% |
| Gross profit | 283,515.00 | 283,515.00 | 0.00 |
| Gross loss | -183,605.00 | -183,605.00 | 0.00 |
| Profit factor | 1.544157 | 1.544157 | 0.000000 |

Trade-by-trade mismatches: `0`.

## Open Position

TradingView had one open marked row at export:

- Entry: `Participation Long`
- Entry bar: `20854`
- Mark bar: `20867`
- TV open mark PnL: `-92.50`

The local engine has the same open position represented as an `end_of_data` row. Completed-trade parity excludes both open marks.

## Promotion State

TradingView chart state after validation:

- Symbol: `ES1!`
- Timeframe: `15m`
- Study ID: `087vOT`
- Loaded strategy: `JD ES 15m C8 Successor 200k C5 20260618`

## Follow-Up

Use C8 C5 as the current production candidate. Future C9 optimization should start from C8 C5, keep the corrected date-filtered buy-and-hold baseline, and retain the exact TradingView parity gate before promotion.
