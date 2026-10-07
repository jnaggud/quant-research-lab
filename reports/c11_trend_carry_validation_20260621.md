# C11 Trend-Carry Validation - 2026-06-21

Selected candidate: `JD ES 15m C11 Trend Carry 200k C1 20260621`

Source report: `reports/c11_trend_carry_sleeve_200k_20260621.json`
Pine: `pine_strategies/JD_ES_15m_C11_Trend_Carry_200k_C1.pine`
TradingView export: `reports/tv_c11_trend_carry_c1_robust_20260621.json`
Exact compare: `reports/tv_c11_trend_carry_c1_exact_compare_20260621.json`

## Result

The selected C11 candidate is worker `143`. It preserves C9 core/cap/participation settings and adds a regime-aware trend-carry sleeve.

TradingView completed-trade parity is exact:

| Check | Local | TradingView | Delta |
|---|---:|---:|---:|
| Completed trades | 435 | 435 | 0 |
| Completed net PnL | $128,862.50 | $128,862.50 | $0.00 |
| Profit factor | 1.8253803042 | 1.8253803042 | 0 |
| Reported mismatches | 0 | 0 | 0 |

There is one open TradingView mark at the export tail:

| Kind | Entry bar | Exit/eval bar | TV open PnL | Local end-of-data PnL |
|---|---:|---:|---:|---:|
| trend_carry | 20830 | 20867 | $257.50 | $245.00 |

The completed-trade comparison excludes that open mark, matching the existing C9 validation method.

## Promotion Passers

All eight promotion passers cleared every gate: minimum trades, trend-carry usage, C9-or-better net/excess/PF/DD/month, better forward than C9, nonnegative forward, C8 C5 net floor, and max-winner-share guard.

| Rank | Worker | Net | PF | Max DD | Trades | June Net | Forward | Core/Cap/Part/Trend |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 143 | $128,862.50 | 1.8254 | 8.83% | 435 | $11,940.00 | $282.50 | 192/156/49/38 |
| 2 | 106 | $121,330.00 | 1.7614 | 8.78% | 439 | $15,240.00 | $577.50 | 194/158/57/30 |
| 3 | 61 | $123,355.00 | 1.7804 | 9.12% | 439 | $11,760.00 | $102.50 | 214/162/56/7 |
| 4 | 229 | $117,055.00 | 1.7290 | 8.34% | 439 | $14,190.00 | $227.50 | 205/160/55/19 |
| 5 | 66 | $119,010.00 | 1.7245 | 8.00% | 443 | $13,427.50 | $40.00 | 178/162/56/47 |
| 6 | 306 | $118,582.50 | 1.7410 | 9.12% | 441 | $12,047.50 | $52.50 | 216/161/58/6 |
| 7 | 366 | $116,360.00 | 1.7199 | 9.12% | 443 | $10,640.00 | $282.50 | 207/162/59/15 |
| 8 | 176 | $112,475.00 | 1.6956 | 9.08% | 435 | $11,482.50 | $232.50 | 205/159/56/15 |

Notable near-misses:

| Worker | Net | PF | Max DD | Trades | June Net | Forward | Failed Gate |
|---:|---:|---:|---:|---:|---:|---:|---|
| 331 | $125,442.50 | 1.7904 | 8.45% | 434 | $15,312.50 | $670.00 | minimum trades |
| 249 | $123,952.50 | 1.7906 | 9.23% | 437 | $13,097.50 | $540.00 | drawdown |

## Baseline Comparison

| Candidate | Net | PF | Max DD | Trades | June Net | Forward |
|---|---:|---:|---:|---:|---:|---:|
| C9 champion | $112,185.00 | 1.6921 | 9.12% | 443 | $10,517.50 | -$2,040.00 |
| C11 selected | $128,862.50 | 1.8254 | 8.83% | 435 | $11,940.00 | $282.50 |

C11 improves net by `$16,677.50`, improves PF by `0.1332`, lowers max drawdown by about `0.29` percentage points, and turns the forward gate from negative to positive while keeping the completed-trade count above the 435 minimum.
