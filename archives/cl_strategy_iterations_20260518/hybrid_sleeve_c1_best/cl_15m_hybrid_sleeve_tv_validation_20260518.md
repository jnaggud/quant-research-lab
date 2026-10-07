# CL1! 15m Hybrid Sleeve TradingView Validation - 2026-05-18

TradingView symbol/range: `NYMEX_DL:CL1!`, 15m, June 30 2025 through May 18 2026.

## Baseline

| Strategy | Net P&L | Return | Max DD | Trades | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|
| JD CL 15m Active Router 64k Best 20260518 | $66,340.00 | 132.68% | $5,527.50 / 8.95% | 250 | 44.80% | 2.051 |

## Hybrid sleeve candidates

| Candidate | Net P&L | Return | Max DD | Trades | Win rate | Profit factor | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| Hybrid C1 | $90,955.00 | 181.91% | $5,527.50 / 8.72% | 293 | 50.17% | 2.327 | Promote |
| Hybrid C2 | $76,370.00 | 152.74% | $8,462.50 / 6.78% | 284 | 49.65% | 2.131 | Good lower-DD alternative |
| Hybrid C3 | $63,600.00 | 127.20% | $6,327.50 / 9.29% | 338 | 42.90% | 1.845 | Reject |
| Hybrid C4 | $64,740.00 | 129.48% | $7,582.50 / 14.26% | 356 | 44.38% | 1.873 | Reject |
| Hybrid C5 | $78,030.00 | 156.06% | $11,022.50 / 13.79% | 290 | 48.97% | 2.057 | Reject due DD |
| Hybrid C6 | $65,655.00 | 131.31% | $7,177.50 / 13.31% | 387 | 43.93% | 1.845 | Reject |

## Decision

Promoted `pine_strategies/JD_CL_15m_Hybrid_Sleeve_32k_C1.pine` to `pine_strategies/JD_CL_15m_Hybrid_Sleeve_32k.pine`. The active-router C3 fallback remains archived and untouched.
