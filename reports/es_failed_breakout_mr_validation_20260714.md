# ES Failed-Breakout Mean-Reversion Validation

## Scope

This research created a new standalone ES strategy. No C11 source, parameter,
signal, or Pine file was changed.

The setup is a causal mechanical translation of the supplied reversal framework:

- A one- or two-minute ATR-normalized spike breaches resistance or support.
- Pre-spike volume is flat and the spike has a volume climax.
- Price frequently crosses its 30-period mean, whose slope is constrained.
- The preceding four hours have low directional efficiency.
- A completed bar closes back inside the breached level.
- Entry occurs at the next one-minute open with one tick of slippage per side.
- The stop is beyond the rejection extreme with ATR bounds; target is fixed R.

Levels tested: rolling 8-hour extremes, prior RTH high/low, overnight high/low,
and the union of prior-RTH and overnight levels. Both same-bar and one-bar-later
reclaims were tested.

## Validation Design

- Data: 1,796,982 back-adjusted ES one-minute bars, June 2021 through June 2026.
- Candidate grid: 72 round, interpretable signal configurations.
- Direction choice: both, long-only, or short-only.
- Exit choice: 0.5R, 1R, or 1.5R.
- Selection: four temporal folds inside the first 60% only.
- Minimum activity: at least 30 train-fold trades; no-trade candidates rejected.
- Final evaluation: selected diverse finalists evaluated once on the final 40%.
- Compute: 32 forked workers, preserving a shared read-only source frame.

## Literal Strategy Result

The full checklist with session levels lost money. Neither delayed confirmation,
volume-climax confirmation, session-level selection, nor reward/risk changes from
0.5R to 2R rescued it. Raw forward returns were generally negative in the intended
reversal direction from 5 through 120 minutes.

## Best Train-Selected Candidate

- Direction: long-only.
- Level: rolling 480-minute high/low.
- Trigger: same-bar breach and reclaim.
- Spike: at least 2 ATR over two bars.
- Volume: 30/120 pre-spike volume ratio at most 1.15; spike volume at least 1.25x.
- Chop: at least six MA crossings; normalized MA slope at most 1.0; efficiency at
  most 0.30.
- Exit: 1R.

Train temporal CV:

- Mean fold return: +0.13%.
- Worst fold: -0.06%.
- Positive folds: 50%.
- Trades: 47.

Untouched holdout:

- Return: +0.15%.
- Trades: 35.
- Win rate: 54.3%.
- Profit factor: 1.04.
- Maximum drawdown: 1.39%.
- Positive half-year blocks: 55.6%.

Transaction-cost sensitivity:

| Slippage per side | Return | Profit factor |
|---:|---:|---:|
| 0 ticks | +1.10% | 1.33 |
| 1 tick | +0.15% | 1.04 |
| 2 ticks | -0.44% | 0.90 |
| 4 ticks | -2.09% | 0.62 |

The result is therefore cost-fragile and statistically sparse. It fails the
required 75% temporal-stability gate and does not provide a defensible live edge.

## Portfolio Test Against Unchanged C11

Across eight untouched quarters:

- C11/MR return correlation: -0.50.
- C11 alone: +15.8%, Sharpe 0.39, max drawdown -23.8%.
- C11 plus a 25% MR overlay: +16.0%, Sharpe 0.39, max drawdown -23.6%.
- Equal weight: +16.0%, Sharpe 0.40, max drawdown -11.5%.

The equal-weight drawdown reduction mostly reflects halving C11 exposure. The
25% overlay improvement is too small relative to sampling and execution error to
claim portfolio value.

## Verdict

**REJECT FOR PROMOTION.** Keep the implementation as a research prototype. Do not
port it to Pine, allocate capital, or modify C11 based on these results.

The only potentially useful lead is the long-only, two-ATR exhaustion pattern,
but it needs substantially more trades or independent-market confirmation before
further tuning. Optimizing it further on this ES holdout would contaminate the
evidence.
