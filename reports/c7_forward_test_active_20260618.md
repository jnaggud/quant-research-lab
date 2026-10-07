# C7 Forward-Test Active - 2026-06-18

## Status

`JD ES 15m C7 Constrained Refine C1 20260519` is the active forward-test strategy.

TradingView active chart state was verified on `CME_MINI_DL:ES1!`, 15m.

## Closed-Bar Validation

Validation report: `reports/c7_forward_validation_20260618.md`

| Strategy | Net | Buy/Hold | Excess | Trades | PF | Local DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| trusted C2 | $90,245.00 | $60,050.00 | $30,195.00 | 481 | 1.509 | 18.38% |
| C6 | $92,605.00 | $60,050.00 | $32,555.00 | 479 | 1.523 | 18.95% |
| C7 | $95,497.50 | $60,050.00 | $35,447.50 | 478 | 1.546 | 18.50% |

June-only closed-bar validation:

| Strategy | June Net | June Buy/Hold | Excess | Trades | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| trusted C2 | $8,265.00 | -$2,237.50 | $10,502.50 | 37 | 1.412 |
| C6 | $6,552.50 | -$2,237.50 | $8,790.00 | 37 | 1.304 |
| C7 | $8,870.00 | -$2,237.50 | $11,107.50 | 36 | 1.443 |

## Stress Test

Random local perturbations around C7 participation management:

- Trials: 512
- All four stress gates passed: 111
- At least 3/4 stress gates passed: 163
- Net range: $73,737.50 to $96,385.00
- Median net: $89,375.00
- June net range: $3,170.00 to $9,795.00
- Median June net: $8,470.00

Interpretation: C7 is not a single exact-point artifact, but the neighborhood is mixed. The active candidate is valid for forward testing, not for additional unbounded optimization without new out-of-sample gates.

## TradingView Live Snapshot

Live report export: `reports/tv_c7_forward_active_report_orders.json`

- Active source: `JD ES 15m C7 Constrained Refine C1 20260519`
- Net: $95,812.50
- Trades: 477
- Profit factor: 1.548864
- Max drawdown: $14,370.00
- Buy/Hold return: $43,337.50

Latest listed trade snapshot:

- Entry: Core Long
- Entry bar: 20767
- Entry price: 7566.50
- Exit bar: 20779
- Exit price: 7569.75
- PnL: $157.50

Live-bar and latest-trade values can move between exports. Promotion and parity decisions should continue to use closed historical trades only.

## Execution Rule

Forward test C7 as active. Do not overwrite it during exploratory optimization.

For future validation/stress runs, use the 32-worker validator path:

`python3 scripts/validate_c7_forward_test.py --workers 32 --stress-trials <N> ...`

C6 remains the benchmark. Trusted C2 remains the conservative baseline.
