# C5 Refined Rank 2 Robustness - 2026-06-18

Data window: `2025-07-31T22:00:00+00:00` to `2026-06-18T13:15:00+00:00`.

## TradingView Parity
Exact match: `True`; trade mismatches: `0`. Local/TV net `$92,922.50` / `$92,922.50`, trades `478` / `478`, PF `1.525810` / `1.525810`.

## Candidate Comparison
| name | net | vs_c2 | trades | PF | DD% | June | June trades | 30d bars | Part |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| trusted_c2 | $90,562.50 | $0.00 | 480 | 1.512 | 18.38 | $8,582.50 | 36 | $22,127.50 | 22 |
| refine_rank2 | $92,922.50 | $2,360.00 | 478 | 1.526 | 18.95 | $6,870.00 | 36 | $23,365.00 | 20 |
| refine_rank4 | $92,540.00 | $1,977.50 | 477 | 1.523 | 18.50 | $7,770.00 | 36 | $24,052.50 | 20 |
| refine_rank9 | $91,932.50 | $1,370.00 | 476 | 1.516 | 18.50 | $9,212.50 | 35 | $25,495.00 | 21 |

## Rank 2 Sleeve Breakdown
| group | trades | net | win_rate | pf | avg |
| --- | --- | --- | --- | --- | --- |
| cap | 163 | $38,847.50 | 54.6 | 1.701 | $238.33 |
| core | 295 | $31,787.50 | 31.53 | 1.282 | $107.75 |
| participation | 20 | $22,287.50 | 70.0 | 3.531 | $1,114.38 |

## Rank 2 Monthly PnL
| month | pnl | trades | win_rate |
| --- | --- | --- | --- |
| 2025-09 | $70.00 | 1 | 100.0 |
| 2025-10 | $11,452.50 | 62 | 35.48 |
| 2025-11 | $10,102.50 | 47 | 38.3 |
| 2025-12 | $122.50 | 58 | 43.1 |
| 2026-01 | $-7,062.50 | 60 | 28.33 |
| 2026-02 | $12,935.00 | 63 | 47.62 |
| 2026-03 | $12,712.50 | 55 | 32.73 |
| 2026-04 | $30,050.00 | 50 | 54.0 |
| 2026-05 | $15,670.00 | 46 | 54.35 |
| 2026-06 | $6,870.00 | 36 | 36.11 |

## Worst Trades
| entry_time | exit_time | side | kind | entry | exit | pnl | reason |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-09T11:30:00+00:00 | 2026-06-09T14:45:00+00:00 | long | participation | 7448.75 | 7389.75 | $-2,955.00 | stop |
| 2026-01-23T16:45:00+00:00 | 2026-01-25T23:00:00+00:00 | long | core | 6952.0 | 6903.75 | $-2,417.50 | stop |
| 2026-04-01T17:00:00+00:00 | 2026-04-01T18:15:00+00:00 | long | core | 6652.25 | 6609.5 | $-2,142.50 | core_close |
| 2026-06-10T18:45:00+00:00 | 2026-06-10T22:00:00+00:00 | long | cap | 7295.5 | 7253.0 | $-2,130.00 | stop |
| 2026-02-11T14:15:00+00:00 | 2026-02-11T15:00:00+00:00 | long | core | 7004.25 | 6965.5 | $-1,942.50 | stop |
| 2026-04-02T01:00:00+00:00 | 2026-04-02T01:15:00+00:00 | long | core | 6607.75 | 6570.25 | $-1,880.00 | core_close |
| 2025-10-10T19:00:00+00:00 | 2025-10-10T19:45:00+00:00 | long | cap | 6629.25 | 6592.75 | $-1,830.00 | stop |
| 2026-06-18T08:00:00+00:00 | 2026-06-18T11:30:00+00:00 | long | core | 7565.5 | 7531.0 | $-1,730.00 | stop |
| 2026-03-31T14:45:00+00:00 | 2026-03-31T15:00:00+00:00 | short | core | 6453.75 | 6487.5 | $-1,692.50 | core_close |
| 2026-03-04T20:30:00+00:00 | 2026-03-05T03:15:00+00:00 | long | participation | 6888.0 | 6855.25 | $-1,642.50 | participation_close |

## Sensitivity: Best One-At-A-Time Perturbations
| param | variant | net | delta_net | trades | pf | dd_pct |
| --- | --- | --- | --- | --- | --- | --- |
| participation_stop_atr | 3.51937456576717 | $93,622.50 | $700.00 | 478 | 1.532 | 18.95 |
| participation_stop_atr | 4.51937456576717 | $93,082.50 | $160.00 | 476 | 1.533 | 18.95 |
| participation_rsi_min | 45.38694783071283 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_rsi_min | 49.38694783071283 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_rsi_max | 62 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_macd_floor | -4 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_macd_floor | -3.5 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_adx_min | 2.6676362093380535 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_adx_min | 6.6676362093380535 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_max_extension_atr | 5.5 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_max_extension_atr | 6 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |
| participation_trail_atr | 7.682829246438372 | $92,922.50 | $0.00 | 478 | 1.526 | 18.95 |

## Sensitivity: Worst One-At-A-Time Perturbations
| param | variant | net | delta_net | trades | pf | dd_pct |
| --- | --- | --- | --- | --- | --- | --- |
| participation_regime | h4_up | $60,397.50 | $-32,525.00 | 473 | 1.339 | 29.19 |
| participation_regime | both_up | $60,397.50 | $-32,525.00 | 473 | 1.339 | 29.19 |
| participation_regime | h4_up_daily_not_bear | $60,397.50 | $-32,525.00 | 473 | 1.339 | 29.19 |
| participation_filter | ema144 | $60,477.50 | $-32,445.00 | 487 | 1.309 | 32.91 |
| participation_filter | ema55 | $68,332.50 | $-24,590.00 | 486 | 1.349 | 30.95 |
| participation_filter | ema21 | $70,227.50 | $-22,695.00 | 487 | 1.359 | 31.55 |
| participation_cooldown | 16 | $79,315.00 | $-13,607.50 | 482 | 1.430 | 26.15 |
| participation_filter | vwap | $81,585.00 | $-11,337.50 | 483 | 1.431 | 21.40 |
| participation_min_hold | 20 | $82,922.50 | $-10,000.00 | 478 | 1.460 | 19.34 |
| participation_rsi_max | 64.0 | $84,770.00 | $-8,152.50 | 481 | 1.461 | 17.66 |
| participation_vol_mult | 1.0469466673052394 | $89,682.50 | $-3,240.00 | 476 | 1.502 | 19.14 |
| participation_cooldown | 24 | $90,397.50 | $-2,525.00 | 478 | 1.512 | 19.16 |

## Initial Read
- Refined rank 2 is the best net candidate and is exactly reproducible in TradingView.
- It improves net and PF versus trusted C2, but does not improve drawdown. Rank 4/rank 9 are better risk-control references if drawdown becomes the promotion gate.
- Sensitivity rows that improve rank 2 are not automatically promoted; they need a new combined search and TradingView parity export before replacing the current candidate.
