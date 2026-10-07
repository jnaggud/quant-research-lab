# CL1! 15m Consistency Router TradingView Validation - 2026-05-18

TradingView symbol/range: `NYMEX_DL:CL1!`, 15m, June 30 2025 through May 18 2026.

## Protected fallback

`pine_strategies/JD_CL_15m_Active_Router_64k.pine` was left intact and archived at `archives/cl_strategy_iterations_20260518/c3_active_router_best/JD_CL_15m_Active_Router_64k.pine`.

| Strategy | Net P&L | Return | Max DD | Trades | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|
| JD CL 15m Active Router 64k Best 20260518 | $66,340.00 | 132.68% | $5,527.50 / 8.95% | 250 | 44.80% | 2.051 |

## Consistency-focused candidates

| Candidate | Net P&L | Return | Max DD | Trades | Win rate | Profit factor | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| Consistency C1 | $42,290.00 | 84.58% | $17,092.50 / 23.23% | 314 | 40.13% | 1.478 | Reject |
| Consistency C2 | $47,410.00 | 94.82% | $10,577.50 / 15.20% | 324 | 40.43% | 1.576 | Reject |
| Consistency C3 | $48,570.00 | 97.14% | $11,262.50 / 15.56% | 248 | 47.18% | 1.575 | Best in branch, still reject |
| Consistency C4 | $38,025.00 | 76.05% | $10,597.50 / 13.31% | 275 | 36.00% | 1.478 | Reject |
| Consistency C5 | -$6,835.00 | -13.67% | $17,607.50 / 34.44% | 483 | 37.27% | 0.871 | Reject |
| Consistency C6 | -$19,010.00 | -38.02% | $22,767.50 / 45.38% | 248 | 35.08% | 0.412 | Reject |

## Conclusion

The consistency objective improved distribution pressure in Python, but did not survive TradingView translation well enough. None of the new candidates beat the existing active-router C3. The correct action is to keep `JD CL 15m Active Router 64k Best 20260518` as the current CL best and treat the consistency branch as a failed promotion candidate.
