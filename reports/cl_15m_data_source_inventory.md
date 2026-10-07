# CL1! Data Source Inventory

This inventory separates data we can source from TradingView from external vendor data that can be joined into the Python optimizer.

## TradingView Candidates

| Symbol | Role | Candidate Features |
|---|---|---|
| `NYMEX:CL1!` | primary | 15m OHLCV, front-month crude trend, session behavior |
| `NYMEX:CL2!` | term_structure | front-second spread, roll/contango/backwardation |
| `NYMEX:CL3!` | term_structure | curve slope, inventory expectation proxy |
| `NYMEX:BZ1!` | cross_market | Brent confirmation, Brent/WTI spread |
| `NYMEX:RB1!` | energy_complex | gasoline demand impulse, refined product confirmation |
| `NYMEX:HO1!` | energy_complex | distillate confirmation, crack-spread proxy |
| `NYMEX:NG1!` | energy_complex | energy volatility/risk proxy |
| `TVC:DXY` | macro | USD pressure, commodity headwind/tailwind |
| `TVC:US10Y` | macro | rates regime, risk/liquidity proxy |
| `CME_MINI:ES1!` | risk | risk-on/off confirmation, equity volatility proxy |
| `CBOE:VIX` | risk | risk-off regime, volatility shock filter |
| `COMEX:GC1!` | macro | safe-haven pressure, USD sensitivity proxy |
| `AMEX:USO` | flow_proxy | ETF flow proxy, cash-session oil proxy |
| `TVC:SPX` | risk | broad risk trend |

## Vendor Candidates

| Source | Frequency | Candidate Features |
|---|---|---|
| EIA petroleum status | weekly | crude inventory surprise, gasoline/distillate surprise, Cushing stocks |
| API inventory | weekly | pre-EIA inventory expectation, event risk flag |
| CFTC COT | weekly | managed-money positioning, producer hedge pressure |
| News/sentiment API | intraday | OPEC/geopolitical shock flags, headline intensity |
| Options/skew API | intraday/daily | implied vol regime, put/call skew, tail-risk pricing |
| Order-flow/tick API | intraday | delta, cumulative delta, liquidity sweeps, absorption |
| Economic calendar API | scheduled | CPI/FOMC/NFP blackouts, EIA event windows |

## Integration Plan

1. Export/load each TradingView symbol on the same 15m timestamp grid.
2. Add lagged features only; never use data before it was published.
3. Add event blackout flags for EIA, FOMC, CPI, NFP, and major OPEC windows.
4. Optimize with walk-forward validation and compare against the current fixed CL baseline.
5. Promote external data only if it improves out-of-sample net PnL, drawdown, and fold consistency.

## Highest-Value First Tests

- CL term structure: `CL1! - CL2!`, `CL2! - CL3!`.
- Energy confirmation: Brent/WTI, RB, HO.
- Event controls: EIA/API inventory windows and scheduled macro blackout flags.
- Risk regime: DXY, ES1!, VIX.
