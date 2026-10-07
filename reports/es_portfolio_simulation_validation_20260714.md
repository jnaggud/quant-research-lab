# ES Portfolio Simulation and Assumption Validation

## Scope

This is a separate risk laboratory. It does not change C11, optimize C11, or
create a new trading signal. It evaluates the local rolling-OOS C11+ML+GEX
research stack; it is not a forecast for the exact live Pine C11 champion.

## Input and Accounting

- 613 synchronized OOS days, June 14, 2024 through May 31, 2026.
- C11 ML models use rolling 18-month training windows and next-quarter tests.
- The MR sleeve is included only after its original 60% train boundary.
- One ES contract per $100,000 reference capital.
- Daily mark-to-market equity includes conservative liquidation value for open
  positions, one tick of exit slippage, and both commissions.
- Open positions are explicitly liquidated at walk-forward quarter boundaries.
- Fixed-notional equity is the default because the historical engine traded a
  fixed contract rather than continuously scaling with equity.

The synchronized panel contains 132 C11+ML+GEX trades. Its fixed-notional P&L is
+118.3% of reference capital. Open-position marks create nonzero daily P&L on 523
of 613 days, replacing the earlier exit-day-only representation.

## Simulation Model

- Joint strategy rows are sampled together, preserving dependence.
- Geometric blocks preserve local autocorrelation and volatility clustering.
- Causal regimes use prior 20-day volatility and prior 63-day trend.
- Five bootstrap methods are available: regime-aware stationary, ordinary
  stationary, fixed moving-block, circular, and crisis-weighted.
- Explicit stresses cover slippage, missed exposure, synchronized losses, and
  gap frequency/severity.
- All production runs use 32 workers and deterministic child seeds.

## Predeclared Assumption Sweep

Forty-one one-factor cases were run at 20,000 paths each. The sweep was declared
before inspecting results and no assumption was selected for favorable returns.

For the half-risk C11 book over a three-year simulated horizon:

| Assumption family | Median-return envelope | P(drawdown >30%) envelope |
|---|---:|---:|
| Mean block length, 5-60 days | +69.7% to +84.2% | 2.2% to 3.2% |
| Regime states, 2/4/6 | +74.0% to +74.9% | 3.3% to 3.8% |
| Ordinary bootstrap methods | +72.8% to +76.9% | 2.9% to 3.6% |
| Extra slippage, 0-4 ticks | +65.5% to +73.9% | 3.3% to 5.3% |
| Gap probability, 0-1% daily | +42.8% to +73.5% | 3.3% to 17.5% |
| Gap multiplier, 1x-3x | +50.7% to +65.7% | 5.4% to 14.7% |
| C11 risk, 25%-100% | +36.8% to +146.0% | 0.03% to 28.3% |

The crisis-weighted bootstrap produced +102.0% median and 2.0% drawdown risk
because the research strategy historically performed well in the sampled high-
volatility/downtrend regime. This should not be interpreted as proof that future
crises are favorable; the crisis sample is small.

Missed exposure is modeled as a whole-path exposure haircut because selectively
removing exit days would leave prior mark-to-market P&L behind. As expected, 0%-20%
missed exposure reduces median return from +73.4% to +59.1%; it also reduces risk.

## Million-Path Precision Runs

After the assumption sweep, two specifications fixed in advance were run for one
million paths each.

### Half-Risk Baseline

- Median three-year return: +73.5%.
- 5th-percentile return: +19.9%.
- 1st-percentile return: -2.7%.
- Modeled probability of profit: 98.765%.
- Monte Carlo 95% interval for P(profit): 98.744%-98.787%.
- Median maximum drawdown: -13.8%.
- Modeled P(drawdown >30%): 3.455%.
- Monte Carlo 95% interval: 3.419%-3.491%.
- Modeled P(drawdown >50%): 0.133%.
- Modeled probability equity falls below 50%: 0.089%.
- Median maximum recovery period: 169 trading days.

The narrow Monte Carlo intervals measure only random simulation error. They do
not measure model-specification or historical-sample uncertainty.

### Half-Risk Dependence Stress

This stress forces 25% of historical losing days to become synchronized losses at
least as large as the active sleeve's historical 90th-percentile loss.

- Median three-year return: -12.0%.
- Modeled probability of profit: 37.0%.
- P(drawdown >30%): 68.8%.
- P(drawdown >50%): 30.4%.
- Probability equity falls below 50%: 24.7%.
- Median recovery period: 543 trading days.

This is a reverse stress, not an estimated real-world probability. Its result says
that repeated clustered large losses break the system; it does not say that the
specified 25% clustering rate is likely.

## Position Sizing and MR Overlay

At full risk, the baseline P(drawdown >30%) is 28.3%; at half risk it is 3.5%; at
quarter risk it is effectively zero within 20,000 simulated paths. Sizing remains
the strongest available drawdown control.

The 25% MR overlay remains immaterial in baseline simulation and worsens dependence
stress. It is not promoted.

## What More Paths Did and Did Not Solve

One million paths reduced Monte Carlo error to a few hundredths of a percentage
point. It did not solve the dominant uncertainty: only 613 synchronized OOS days
exist, one four-state regime has only 19 observations, and the three-year simulated
horizon exceeds the historical panel.

Another year of OOS data cannot be manufactured now. The daily-panel builder is
rerunnable as new staged data arrives, so future observations can be appended and
the entire sweep repeated without changing the methodology.

## Verdict

Retain the simulation lab. Use the ordinary-assumption envelope, not a single
precise probability, for risk planning. Half-risk C11 is materially more robust
than full-risk C11, while the MR overlay does not help. Do not widen the MR strategy
search against its already-viewed holdout.
