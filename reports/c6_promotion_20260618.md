# C6 Promotion - 2026-06-18

## Promoted Strategy

`JD ES 15m C6 Participation Refine 20260618`

This is promoted from `JD ES 15m Participation C2 Refine 32k C2 20260519`, which was the rank 2 result from `reports/c5_participation_overlay_c2_refine_32k_20260618.json`.

## Local Artifact

- Pine: `pine_strategies/JD_ES_15m_C6_Participation_Refine_20260618.pine`
- Robustness report: `reports/c5_refine_rank2_robustness_20260618.md`
- TradingView report export: `reports/tv_c6_participation_refine_report_orders.json`
- TradingView parity compare: `reports/tv_c6_participation_refine_parity_compare.json`

## Baseline Comparison

| Candidate | Net | vs trusted C2 | Trades | PF | Local DD | June |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| trusted C2 | $90,562.50 | $0.00 | 480 | 1.512 | 18.38% | $8,582.50 |
| C6 / refined rank 2 | $92,922.50 | +$2,360.00 | 478 | 1.526 | 18.95% | $6,870.00 |

## TradingView State

The active chart study was verified as `JD ES 15m C6 Participation Refine 20260618` on `CME_MINI_DL:ES1!`, 15m.

TradingView's saved script list still shows the library row name as `JD ES BEST`, but its title is `JD ES 15m C6 Participation Refine 20260618`, version 14. The MCP CLI supports save/open/list but not rename/save-as, so the title is the reliable identifier.

## Parity Status

Closed historical trades match TradingView exactly:

- Compared closed trades: 478
- Mismatches: 0

The newest live-bar trade can differ between local export and TradingView export because ES is moving while the snapshots are taken. That live-trade mismatch should not be treated as a model mismatch.

## Promotion Decision

C6 is the current best-net candidate and should be treated as the promoted successor to trusted C2 for total-performance testing.

Trusted C2 remains the baseline reference because it has slightly lower drawdown and stronger June performance. Refined rank 4 and rank 9 remain useful alternates if the next gate prioritizes drawdown or recent-month behavior over total net.
