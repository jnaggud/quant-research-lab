# CL 15m Walk-Forward Validation

- Data: `tmp/tv_cl1_15m_loaded_full_raw.json`
- Train window: `120` days
- Test window: `30` days
- Step: `30` days
- Trials per fold: `16384`
- Workers: `32`

## Summary

- Adaptive OOS net: `$67,203.34` across `179` trades; positive folds `3/6`.
- Fixed baseline OOS net: `$78,902.66` across `166` trades; positive folds `5/6`.
- Buy-and-hold OOS net over same fold windows: `$40,010.00`.

## Fold Results

| Fold | Test Window | Adaptive Net | Baseline Net | Buy/Hold | Adaptive Trades | Baseline Trades |
|---:|---|---:|---:|---:|---:|---:|
| 1 | 2025-11-02 23:00:00+00:00 → 2025-12-01 03:45:00+00:00 | $-1,431.31 | $-882.66 | $-1,860.00 | 27 | 23 |
| 2 | 2025-12-01 04:00:00+00:00 → 2025-12-31 03:45:00+00:00 | $-486.15 | $398.12 | $-1,650.00 | 32 | 24 |
| 3 | 2025-12-31 04:00:00+00:00 → 2026-01-30 03:45:00+00:00 | $-886.50 | $677.95 | $6,350.00 | 36 | 30 |
| 4 | 2026-01-30 04:00:00+00:00 → 2026-02-27 21:45:00+00:00 | $1,324.84 | $3,468.23 | $3,050.00 | 23 | 30 |
| 5 | 2026-03-01 23:00:00+00:00 → 2026-03-31 03:45:00+00:00 | $38,262.40 | $42,852.39 | $27,990.00 | 27 | 24 |
| 6 | 2026-03-31 04:00:00+00:00 → 2026-04-30 03:45:00+00:00 | $30,420.07 | $32,388.63 | $6,130.00 | 34 | 35 |

## Decision Rule

Promote adaptive retraining only if out-of-sample net improves versus the fixed baseline, positive folds do not deteriorate, max drawdown remains comparable, and improvement is not concentrated in one test fold.
