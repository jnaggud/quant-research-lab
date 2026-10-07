# ES 15m TradingView Candidate Shortlist - 2026-05-19

TradingView is the source of truth for this list. Python optimizer rank is only used to decide which Pine variants to test.

## Benchmark

- Strategy: `JD ES 15m Regime Carry 64k 20260508`
- Status: fallback benchmark until a tested Pine candidate is clearly better.

## Rejected Candidates

| Candidate | Total P&L | Return | Max DD | Trades | Win Rate | Profit Factor | Reason |
|---|---:|---:|---:|---:|---:|---:|---|
| C1 | n/a | n/a | n/a | n/a | n/a | n/a | Worse than Regime Carry in TradingView sanity check |
| C2 | $26,035.00 | 52.07% | $22,102.50 / 32.67% | 388 | 41.49% | 1.230 | Did not beat buy-and-hold; high drawdown |
| C3 | $28,240.00 | 56.48% | $13,662.50 / 25.47% | 342 | 40.06% | 1.261 | Did not beat buy-and-hold; high drawdown |
| C4 | $29,152.50 | 58.30% | $16,360.00 / 22.33% | 412 | 40.05% | 1.262 | Did not beat buy-and-hold |
| C6 | $24,010.00 | 48.02% | $16,305.00 / 23.58% | 378 | 41.53% | 1.216 | Did not beat buy-and-hold |
| RiskAdj128k C1 | n/a | n/a | n/a | n/a | n/a | n/a | Rejected in TradingView manual test |
| RiskAdj128k C2 | n/a | n/a | n/a | n/a | n/a | n/a | Rejected in TradingView manual test |
| RiskAdj128k C3 | n/a | n/a | n/a | n/a | n/a | n/a | Rejected in TradingView manual test |
| RiskAdj128k C4 | n/a | n/a | n/a | n/a | n/a | n/a | Rejected in TradingView manual test |

## Active Candidate Shortlist

| Candidate | Pine File | Total P&L | Return | Max DD | Trades | Win Rate | Profit Factor | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---|
| C5 | `pine_strategies/JD_ES_15m_Capitulation_Sleeve_64k_C5.pine` | $48,192.50 | 96.39% | $15,905.00 / 21.24% | 419 | 41.77% | 1.431 | First candidate to beat buy-and-hold; drawdown still high |
