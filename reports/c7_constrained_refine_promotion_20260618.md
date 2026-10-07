# C7 Constrained Refine Promotion - 2026-06-18

## Promoted Strategy

`JD ES 15m C7 Constrained Refine C1 20260519`

This is the rank 1 candidate from `reports/c6_constrained_refine_32k_20260618.json`.

## Intent

The goal was to preserve C6's net/PF improvement while borrowing the lower drawdown and stronger June behavior seen in refined rank 4/rank 9.

The search froze C6 entry logic and optimized only participation-sleeve management:

- `participation_stop_atr`
- `participation_trail_atr`
- `participation_cooldown`
- `participation_min_hold`
- `participation_max_hold`
- `participation_exit_filter`
- `participation_exit_rsi`
- `participation_exit_on_macd_roll`

The newest live bar was excluded from local scoring.

## Promotion Gates

The candidate cleared all promotion gates on closed-bar local scoring:

| Gate | Result |
| --- | --- |
| Trades >= 435 | pass |
| Net >= C6 | pass |
| PF >= C6 | pass |
| Drawdown <= rank4/rank9 risk target | pass |
| June net >= trusted C2 | pass |

## Local Closed-Bar Results

| Candidate | Net | PF | Local DD | June | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| trusted C2 reference | $90,245.00 | 1.509 | 18.38% | $8,265.00 | 481 |
| C6 reference | $92,605.00 | 1.523 | 18.95% | $6,552.50 | 479 |
| C7 constrained C1 | $95,497.50 | 1.546 | 18.50% | $8,870.00 | 478 |

## TradingView Verification

Active chart study verified as `JD ES 15m C7 Constrained Refine C1 20260519` on `CME_MINI_DL:ES1!`, 15m.

Server-side Pine compile passed with zero errors/warnings.

Closed historical trade parity:

- Compared closed trades: 477
- Mismatches: 0

The newest live trade is intentionally excluded from parity because ES moved between exports. TradingView's full snapshot can differ on the last trade while historical closed trades still match exactly.

## Artifacts

- Pine: `pine_strategies/JD_ES_15m_C7_Constrained_Refine_C1.pine`
- Search report: `reports/c6_constrained_refine_32k_20260618.json`
- TV report: `reports/tv_c7_constrained_refine_c1_report_orders.json`
- TV parity: `reports/tv_c7_constrained_refine_c1_parity_compare.json`

## Decision

C7 constrained rank 1 supersedes C6 for the next forward-test candidate because it improves total net, PF, drawdown, and June behavior under the closed-bar gate set.

C6 remains the benchmark reference. Trusted C2 remains the conservative baseline.
