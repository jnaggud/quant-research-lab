# C8 Successor Prep - 2026-06-18

## Immediate Validation

Manual full monitor run completed successfully:

- Snapshot: `reports/c7_monitor/20260618_142818.md`
- Status: `OK`
- Active TradingView source: `JD ES 15m C7 Constrained Refine C1 20260519`
- TradingView net: `$95,812.50`
- TradingView trades: `477`
- TradingView PF: `1.5488643198808467`
- TradingView max DD: `$14,370.00`

The local monitor excludes the newest live bar, but still includes an end-of-data mark for the latest open/local trade. That current latest local mark is:

- Entry: `2026-06-18T14:45:00+00:00`
- Mark/exit: `2026-06-18T19:00:00+00:00`
- PnL: `$-730.00`
- Reason: `end_of_data`

That explains why local closed-bar-style monitor net is lower than the TradingView closed-trade snapshot in this run.

## Current Reference Metrics

From the fresh monitor snapshot:

| strategy | net | buy_hold | excess | trades | PF | DD% | June |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| trusted C2 | `$89,832.50` | `$59,637.50` | `$30,195.00` | 481 | 1.506 | 18.38 | `$7,852.50` |
| C6 | `$92,192.50` | `$59,637.50` | `$32,555.00` | 479 | 1.520 | 18.95 | `$6,140.00` |
| C7 | `$95,085.00` | `$59,637.50` | `$35,447.50` | 478 | 1.542 | 18.50 | `$8,457.50` |

C7 still clears every monitor trigger:

- `c7_net_below_c6`: false
- `c7_pf_below_c6`: false
- `c7_june_below_c2`: false
- `c7_dd_above_c6`: false
- `c7_dd_above_threshold`: false
- `tv_active_source_not_c7`: false

## What Worked From C6 To C7

C7 froze C6 entry logic and refined only participation-sleeve management. The useful deltas were:

| parameter | trusted C2 | C6 | C7 |
| --- | ---: | ---: | ---: |
| `participation_stop_atr` | 2.8579 | 4.0194 | 4.7906 |
| `participation_trail_atr` | 10.9765 | 8.6828 | 6.9645 |
| `participation_exit_rsi` | 54.7450 | 51.6982 | 49.3580 |
| `participation_cooldown` | 24 | 20 | 19 |
| `participation_min_hold` | 22 | 23 | 24 |
| `participation_max_hold` | 40 | 24 | 47 |
| `participation_exit_filter` | `ema21` | `ema21` | `ema21` |
| `participation_exit_on_macd_roll` | true | true | true |

Interpretation:

- C7 let the participation sleeve breathe more at entry via a wider stop.
- C7 tightened trailing behavior versus C6.
- C7 allowed participation trades to stay open materially longer.
- C7 exited participation trades at a lower RSI threshold.
- C7 preserved the `daily_up` + `stack` participation regime rather than broadening regime entry.

## C8 Search Design

Do not start with a broad strategy search. C8 should be a constrained successor around C7.

Freeze:

- Core entry logic.
- Cap logic.
- Carry logic.
- `regime_mode`, `h4_fast`, `h4_slow`, `d_fast`, `d_slow`.
- `participation_regime = daily_up`.
- `participation_filter = stack`.

Search only:

| parameter | C7 value | proposed C8 bounds |
| --- | ---: | ---: |
| `participation_stop_atr` | 4.7906 | 3.5 to 6.5 |
| `participation_trail_atr` | 6.9645 | 4.5 to 9.5 |
| `participation_exit_rsi` | 49.3580 | 44.0 to 54.0 |
| `participation_cooldown` | 19 | 8 to 28 |
| `participation_min_hold` | 24 | 12 to 36 |
| `participation_max_hold` | 47 | 32 to 96 |
| `participation_exit_filter` | `ema21` | `ema21`, `ema55`, `vwap` |
| `participation_exit_on_macd_roll` | true | true, false |

Optional second-stage knobs only if stage 1 stalls:

| parameter | C7 value | proposed bounds |
| --- | ---: | ---: |
| `participation_rsi_min` | 47.3869 | 44.0 to 52.0 |
| `participation_rsi_max` | 62.0 | 58.0 to 66.0 |
| `participation_max_extension_atr` | 6.0 | 4.0 to 8.0 |
| `participation_vol_mult` | 0.9469 | 0.75 to 1.15 |

## C8 Promotion Gates

Minimum local gates:

- `n_trades >= 435`
- `net_profit >= C7 net_profit`
- `profit_factor >= C7 profit_factor`
- `max_drawdown <= C7 max_drawdown`
- `june_net >= C7 june_net`
- `excess_net >= C7 excess_net`
- `max_winner_share <= 0.18`

Secondary gates:

- Must beat trusted C2 June net.
- Must beat C6 full net and PF.
- Must preserve historical TradingView closed-trade parity.
- Must not increase cap-trade dependence.
- Must not use the newest live bar in optimization scoring.

## Execution Recommendation

Next optimizer should be a C7-centered variant of `scripts/optimize_c6_constrained_refine.py`.

Run plan:

1. Use latest monitor-exported data from `reports/c7_monitor/data/`.
2. Use 32 workers.
3. Run a single 200k-trial pass around the tighter C8 participation space.
4. Export only top promotion-gate passers to Pine.
5. Validate top 3 in TradingView.

Command shape for the optimization run:

```sh
env PYTHONDONTWRITEBYTECODE=1 python3 <c8_optimizer>.py \
  --workers 32 \
  --trials 200000 \
  --min-trades 435 \
  --exclude-tail-bars 1
```

Do not promote a C8 unless it beats C7 on local closed-bar scoring and TradingView closed-trade parity.
