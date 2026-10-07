# C8 Forward Attribution - 20260620

Forward start: `2026-06-18T00:00:00Z`
Data window: `2025-07-31T22:00:00+00:00` to `2026-06-19T16:45:00+00:00`

## Summary
| strategy | closed_net | closed_excess | closed_pf | forward_net | forward_bh | forward_excess | forward_trades | forward_pf |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trusted_c2 | $89,027.50 | $46,777.50 | 1.499 | $-3,265.00 | $737.50 | $-4,002.50 | 3 | 0.0 |
| c6 | $91,387.50 | $49,137.50 | 1.513 | $-3,265.00 | $737.50 | $-4,002.50 | 3 | 0.0 |
| c7 | $94,280.00 | $52,030.00 | 1.535 | $-3,265.00 | $737.50 | $-4,002.50 | 3 | 0.0 |
| c8_c1 | $100,182.50 | $57,932.50 | 1.555 | $-3,265.00 | $737.50 | $-4,002.50 | 3 | 0.0 |
| c8_c5 | $99,910.00 | $57,660.00 | 1.544 | $-3,265.00 | $737.50 | $-4,002.50 | 3 | 0.0 |

## Forward By Sleeve
| strategy | kind | trades | net | pf | wins | losses |
| --- | --- | --- | --- | --- | --- | --- |
| trusted_c2 | core | 3 | $-3,265.00 | 0.0 | 0 | 3 |
| trusted_c2 | cap | 0 | $0.00 | 0.0 | 0 | 0 |
| trusted_c2 | participation | 0 | $0.00 | 0.0 | 0 | 0 |
| c6 | core | 3 | $-3,265.00 | 0.0 | 0 | 3 |
| c6 | cap | 0 | $0.00 | 0.0 | 0 | 0 |
| c6 | participation | 0 | $0.00 | 0.0 | 0 | 0 |
| c7 | core | 3 | $-3,265.00 | 0.0 | 0 | 3 |
| c7 | cap | 0 | $0.00 | 0.0 | 0 | 0 |
| c7 | participation | 0 | $0.00 | 0.0 | 0 | 0 |
| c8_c1 | core | 3 | $-3,265.00 | 0.0 | 0 | 3 |
| c8_c1 | cap | 0 | $0.00 | 0.0 | 0 | 0 |
| c8_c1 | participation | 0 | $0.00 | 0.0 | 0 | 0 |
| c8_c5 | core | 3 | $-3,265.00 | 0.0 | 0 | 3 |
| c8_c5 | cap | 0 | $0.00 | 0.0 | 0 | 0 |
| c8_c5 | participation | 0 | $0.00 | 0.0 | 0 | 0 |

## Champion Forward Trades
| entry_time | exit_time | side | kind | bars | entry | exit | pnl | reason | mfe | mae | h4 | daily | rsi | macdh | adx | above_ema21 | above_ema55 | above_vwap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-18T08:00:00+00:00 | 2026-06-18T11:30:00+00:00 | long | core | 14 | 7565.5 | 7531.0 | $-1,730.00 | stop | $137.50 | $-1,737.50 | 1 | 1 | 61.32 | 1.5563 | 14.61 | True | True | True |
| 2026-06-18T14:45:00+00:00 | 2026-06-19T01:45:00+00:00 | long | core | 40 | 7566.5 | 7548.5 | $-905.00 | stop | $825.00 | $-1,275.00 | 1 | 1 | 57.11 | 0.851 | 12.78 | True | True | True |
| 2026-06-19T07:30:00+00:00 | 2026-06-19T11:15:00+00:00 | long | core | 15 | 7551.0 | 7538.5 | $-630.00 | core_close | $575.00 | $-700.00 | 1 | 1 | 60.48 | 3.2437 | 31.38 | True | True | True |

## Read
- C8 C5 forward loss is concentrated in `core`: $-3,265.00 across 3 trades.
- Do not promote a C9 variant unless it improves this forward slice without breaking exact completed-trade parity against Pine after export.
