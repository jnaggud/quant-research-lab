# CL1! 15m Active Router TradingView Validation - 2026-05-18

TradingView symbol/range: `NYMEX_DL:CL1!`, 15m, June 30 2025 through May 18 2026.

## Existing benchmark

| Strategy | Net P&L | Return | Max DD | Trades | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|
| JD CL 15m Trend Bias 64k Best 20260508 | $42,760.00 | 85.52% | $7,547.50 / 8.01% | 112 | 49.11% | 2.155 |

## New active-router candidates

| Candidate | Net P&L | Return | Max DD | Trades | Win rate | Profit factor | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| C1 | $53,747.50 | 107.50% | $12,212.50 / 22.16% | 398 | 41.21% | 1.445 | Most active, too much drawdown |
| C2 | $49,495.00 | 98.99% | $8,737.50 / 16.69% | 337 | 34.72% | 1.555 | Robust in Python, weaker TV equity quality |
| C3 | $66,340.00 | 132.68% | $5,527.50 / 8.95% | 250 | 44.80% | 2.051 | Best TV balance of return, DD, PF, and activity |
| C4 | $41,985.00 | 83.97% | $13,742.50 / 17.40% | 309 | 37.54% | 1.497 | More trades but worse than benchmark |
| C5 | $57,690.00 | 115.38% | $7,192.50 / 14.26% | 266 | 39.85% | 1.860 | Good but worse DD/PF than C3 |
| C6 | $55,710.00 | 111.42% | $6,542.50 / 11.01% | 250 | 42.40% | 1.823 | Cleaner than C1/C2 but lower return than C3 |

## Decision

Promoted `pine_strategies/JD_CL_15m_Active_Router_64k_C3.pine` to `pine_strategies/JD_CL_15m_Active_Router_64k.pine`.

C3 is the current active-router winner because it improves the existing CL benchmark from $42,760 to $66,340, raises trade count from 112 to 250, keeps drawdown near the existing benchmark, and still has a profit factor above 2.0. It is not simply the highest Python result; it is the best TradingView-confirmed candidate from this batch.
