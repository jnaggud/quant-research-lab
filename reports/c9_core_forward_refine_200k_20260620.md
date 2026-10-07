# C9 Core Forward Refine 200k - 2026-06-20

## Decision

Do not promote C9 yet.

The 200k / 32-worker search found stronger full-period candidates than C8 C5, but zero candidates passed the strict promotion gate because every top candidate still had a negative forward slice since `2026-06-18T00:00:00Z`.

## Baseline

| strategy | net | excess | PF | DD% | month | forward | trades |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C8 C5 | $99,910.00 | $57,660.00 | 1.544 | 12.99 | $9,247.50 | $-3,265.00 | 488 |

## Best C9 Candidate

| metric | C9 best | delta vs C8 C5 |
| --- | --- | --- |
| Net | $112,185.00 | +$12,275.00 |
| Excess vs buy-and-hold | $69,935.00 | +$12,275.00 |
| Profit factor | 1.692 | +0.148 |
| Max drawdown | 9.12% | -3.86 pts |
| Current month | $10,517.50 | +$1,270.00 |
| Forward since selection | $-2,040.00 | +$1,225.00 |
| Trades | 443 | -45 |

Failed gate: `forward_non_negative`.

## Top 10

| rank | net | excess | PF | DD% | month | forward | trades | failed gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | $112,185.00 | $69,935.00 | 1.692 | 9.12 | $10,517.50 | $-2,040.00 | 443 | forward_non_negative |
| 2 | $108,485.00 | $66,235.00 | 1.646 | 11.63 | $10,520.00 | $-1,765.00 | 468 | forward_non_negative |
| 3 | $109,292.50 | $67,042.50 | 1.620 | 12.80 | $11,585.00 | $-2,115.00 | 474 | forward_non_negative |
| 4 | $107,595.00 | $65,345.00 | 1.652 | 9.95 | $9,822.50 | $-1,427.50 | 466 | forward_non_negative |
| 5 | $107,972.50 | $65,722.50 | 1.661 | 10.07 | $9,507.50 | $-1,627.50 | 458 | forward_non_negative |
| 6 | $106,027.50 | $63,777.50 | 1.622 | 9.78 | $12,195.00 | $-1,750.00 | 582 | forward_non_negative |
| 7 | $107,335.00 | $65,085.00 | 1.644 | 10.58 | $10,015.00 | $-1,765.00 | 458 | forward_non_negative |
| 8 | $104,660.00 | $62,410.00 | 1.603 | 11.36 | $12,262.50 | $-1,122.50 | 443 | forward_non_negative |
| 9 | $104,975.00 | $62,725.00 | 1.613 | 10.71 | $10,802.50 | $-927.50 | 460 | forward_non_negative |
| 10 | $104,050.00 | $61,800.00 | 1.596 | 12.65 | $12,612.50 | $-1,122.50 | 450 | forward_non_negative |

## Best Candidate Core Params

| param | value |
| --- | --- |
| `stop_atr` | 5.080144212289923 |
| `trail_atr` | 4.85314757441612 |
| `vol_mult` | 0.7958586229883877 |
| `long_rsi_min` | 32.920393510081645 |
| `core_long_rsi_max` | 64.8035399674594 |
| `macd_floor` | -2.7104448466487994 |
| `long_exit_rsi` | 39.82942053658486 |
| `core_adx_min` | 22.492011003081227 |
| `core_long_max_extension_atr` | 3.1810563298588166 |
| `core_long_max_vwap_dist_atr` | 1.9488270468126774 |
| `cooldown` | 13 |
| `local_filter` | none |
| `long_exit_regime` | 0 |

## Read

- The forward loss attribution showed all C5-C8 variants took the same three losing core longs. Participation and cap did not cause the forward loss.
- C9 core filters improved long-run quality substantially: higher net, higher excess, higher PF, and lower max drawdown.
- The strict three-trade forward gate is probably too narrow to use as a hard promotion rule. It should remain a review trigger, but not the only forward validation.
- Next C9 pass should use broader rolling-forward gates, such as last 20/50/100 completed trades, monthly buckets, and recent excess over buy-and-hold, while still keeping exact Pine parity as a hard requirement.

## Validation

- Full optimization completed: `200000` trials, `32` workers.
- Promotion pass count: `0`.
- C8 exact parity after the opt-in C9 engine additions remained intact:
  - completed trade delta: `0`
  - completed net delta: `0.0`
  - completed PF delta: `0.0`
