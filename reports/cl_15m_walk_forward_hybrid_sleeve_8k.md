# CL 15m Walk-Forward Validation

- Data: `tmp/tv_cl1_15m_loaded_full_raw.json`
- Train window: `120` days
- Test window: `30` days
- Step: `30` days
- Trials per fold: `8192`
- Workers: `32`

## Summary

- Adaptive OOS net: `$71,903.73` across `195` trades; positive folds `3/6`.
- Fixed baseline OOS net: `$78,902.66` across `166` trades; positive folds `5/6`.
- Buy-and-hold OOS net over same fold windows: `$40,010.00`.

## Fold Results

| Fold | Test Window | Adaptive Net | Baseline Net | Buy/Hold | Adaptive Trades | Baseline Trades |
|---:|---|---:|---:|---:|---:|---:|
| 1 | 2025-11-02 23:00:00+00:00 → 2025-12-01 03:45:00+00:00 | $-587.26 | $-882.66 | $-1,860.00 | 26 | 23 |
| 2 | 2025-12-01 04:00:00+00:00 → 2025-12-31 03:45:00+00:00 | $-1,931.39 | $398.12 | $-1,650.00 | 40 | 24 |
| 3 | 2025-12-31 04:00:00+00:00 → 2026-01-30 03:45:00+00:00 | $-740.33 | $677.95 | $6,350.00 | 34 | 30 |
| 4 | 2026-01-30 04:00:00+00:00 → 2026-02-27 21:45:00+00:00 | $2,296.29 | $3,468.23 | $3,050.00 | 26 | 30 |
| 5 | 2026-03-01 23:00:00+00:00 → 2026-03-31 03:45:00+00:00 | $37,002.30 | $42,852.39 | $27,990.00 | 26 | 24 |
| 6 | 2026-03-31 04:00:00+00:00 → 2026-04-30 03:45:00+00:00 | $35,864.12 | $32,388.63 | $6,130.00 | 43 | 35 |

## Decision Rule

Promote adaptive retraining only if out-of-sample net improves versus the fixed baseline, positive folds do not deteriorate, max drawdown remains comparable, and improvement is not concentrated in one test fold.
