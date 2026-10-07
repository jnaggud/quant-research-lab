# C8 Successor 200k Summary - 2026-06-18

## Run

- Script: `scripts/optimize_c8_successor.py`
- Source data: `reports/c7_monitor/data/es1_15m_20260618_142818.json`
- Daily bars: `reports/c7_monitor/data/es1_1d_20260618_142818.json`
- 4h bars: `reports/c7_monitor/data/es1_240m_20260618_142818.json`
- Trials: 200,000 requested / 200,000 completed
- Workers: 32
- Minimum trades gate: 435
- Promotion gate pass count: 227
- Full result: `reports/c8_successor_200k_20260618.json`

## C7 Reference

| Net | PF | Max DD % | Trades | June PnL | Buy/Hold | Excess |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 95,085.00 | 1.542 | 18.50 | 478 | 8,457.50 | 59,637.50 | 35,447.50 |

## Top Local Candidates

| Rank | Pine file | Net | PF | Max DD % | Trades | June PnL | Buy/Hold Excess | Participation Trades |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `pine_strategies/JD_ES_15m_C8_Successor_200k_C1.pine` | 100,987.50 | 1.562 | 14.19 | 480 | 10,282.50 | 41,350.00 | 59 |
| 2 | `pine_strategies/JD_ES_15m_C8_Successor_200k_C2.pine` | 100,735.00 | 1.559 | 14.68 | 478 | 10,332.50 | 41,097.50 | 61 |
| 3 | `pine_strategies/JD_ES_15m_C8_Successor_200k_C3.pine` | 100,405.00 | 1.553 | 17.47 | 479 | 10,320.00 | 40,767.50 | 67 |

## Key C8 Changes Versus C7

C8 keeps the C7 core, capitulation, carry, and regime logic fixed. The search only retunes the participation sleeve that was added to keep exposure during strong uptrends:

- Participation stop ATR
- Participation trailing ATR
- Participation exit RSI
- Participation cooldown
- Participation minimum hold bars
- Participation maximum hold bars
- Participation exit filter
- Optional MACD-roll exit

## TradingView Check

TradingView Desktop was reachable on CDP port 9223. All three generated Pine strategies were injected into the Pine editor and compiled successfully with no editor errors:

- `JD ES 15m C8 Successor 200k C1 20260618`
- `JD ES 15m C8 Successor 200k C2 20260618`
- `JD ES 15m C8 Successor 200k C3 20260618`

Final chart state was `CME_MINI_DL:ES1!`, 15m, with study `087vOT` loaded as `JD ES 15m C8 Successor 200k C1 20260618`.

Structured Strategy Tester metric export could not be completed in this run: both the raw export script and the dedicated MCP Strategy Tester tools repeatedly hit CDP transport failures during heavy report extraction. Lightweight chart state calls continued to work, so the failure appears isolated to long Strategy Tester reads rather than Pine compile/load.

## Next Validation Gate

Before promoting C8, compare TradingView Strategy Tester metrics against the local result for C1. If TradingView agrees within the existing parity tolerance, C1 is the preferred C8 successor candidate. If it diverges, export the TradingView trade list first and diff against local trades before changing the strategy logic.
