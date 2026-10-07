# C11 Five-Year and X-Derived Improvement Research

## Correction

The prior 247-day resampling was not a many-year backtest. This research runs the fixed C11 parameters on 119,841 back-adjusted Databento ES 15-minute bars from June 2021 through June 2026. The Pine date gate was disabled for this transport test; no production Pine code was changed.

The Databento series is not byte-for-byte ES1!. On the overlapping period, the date-gated local parity engine produced `$116,337.50`, PF `1.70`, and drawdown `8.83%`, compared with TradingView's `$126,905`, PF `1.745`, and drawdown `9.25%`. Results below are comparative Databento research, not exact TradingView figures.

## Fixed C11

- Five-year net: `$142,472.50` on one ES contract and `$50,000` initial capital.
- Trades: `3,093`.
- Profit factor: `1.133`.
- Closed-equity maximum drawdown: `87.77%`.
- 2021: `-$2,680` from June onward.
- 2022: `-$25,377.50`.
- 2023: `+$23,207.50`.
- 2024: `+$18,867.50`.
- 2025: `+$56,965`.
- 2026 through June 28: `+$71,490`.

The strategy transports profitably across five years, but its edge and risk are unstable. Most profit comes from 2025-2026, and the 2021-2022 drawdown would be operationally difficult.

## X Checklist Tests

The four-filter article was translated into causal measurements: 30-MA crossing count, normalized MA slope, path efficiency, pre-spike volume slope, fast ATR-normalized approach, and failed-breakout rejection. A predeclared 433-candidate grid tested five uses: unchanged control, trend-sleeve veto during chop, all-momentum veto during chop, failed-breakout long overlay, and a hybrid.

Candidates were ranked using 2021-2024 only. The selected candidate vetoes C11 momentum entries when the prior context has at least six 30-MA crossings over 32 bars, normalized slope at most 1 ATR, and efficiency at most 0.30.

- Full net improved to `$165,747.50`.
- Profit factor improved to `1.166`.
- Drawdown improved to `59.80%`, still too high.
- 2021-2022 loss improved from roughly `-$28,058` to `-$10,200`.
- Reserved 2025-2026 net was `$125,875`, PF `1.355`, and drawdown `20.30%`.
- All 108 variants in the same veto family were profitable in the reserved period; median reserved PF was `1.356`.
- 84.2% of overlapping six-month windows were profitable; the worst lost `$16,532.50`.

The direct failed-breakout overlay did not beat the veto approach. The separately tested one-minute mean-reversion strategy also failed promotion: its best holdout made only `$150.23` on `$100,000` with PF `1.04`; five of six finalists lost money.

## Sleeve Ablation

- Removing shorts reduced pre-2025 drawdown from `87.77%` to `64.85%` and improved pre-2025 net, but reduced 2025-2026 net from `$128,455` to `$91,812.50`.
- Removing capitulation reduced total net to `$87,190`.
- Removing participation reduced total net to `$99,180`.
- Removing trend carry reduced total net to `$121,230`.
- Core-only produced only `$12,427.50`, PF `1.019`.

The complementary sleeves are responsible for most of the long-run edge. Shorts are the clearest historical risk source, but simply deleting them sacrifices substantial recent profit.

## Adaptation Tests

These adaptation tests use the existing rolling-origin local C11+ML harness, not the exact Pine engine.

- Monthly retraining: `+93.4%`, drawdown `39.9%`.
- Three-month retraining: `+110.0%`, drawdown `40.8%`.
- Six-month retraining: `+130.0%`, drawdown `38.9%`.
- Never retraining: `+48.8%`, drawdown `40.8%`.
- Per-regime probability thresholds: `-10.4%`.
- Static HMM regime: `+133.7%`, drawdown `27.4%`.
- Quarterly refitted HMM: `-18.4%`, drawdown `58.3%`.

Slow scheduled retraining has merit. Fast regime-dependent parameter changes and quarterly HMM refitting do not.

## Costs and Stress

The selected X-veto variant already includes one tick of TradingView-style slippage and `$5` round-trip commission.

- One additional tick per side-equivalent round trip: net `$92,797.50`, drawdown `98.84%`.
- Two additional ticks: net `$19,847.50`, PF `1.018`; the historical equity path becomes insolvent before later recovery.
- Four additional ticks: net `-$126,052.50`.
- Double commission: net `$151,157.50`, PF `1.150`.

One million regime-aware three-year bootstrap paths gave a median return of `+139.1%`, but a `37.95%` probability of drawdown above 30% and `5.62%` probability of crossing 50% equity. Under two extra ticks, 10% missed exposure, and gap stress, median return was `-16.9%` and the probability of crossing 50% equity was `52.71%`.

## Decision

Do not replace the preserved C11. The X-derived chop veto improved the Databento transport test, but it did not solve C11's older-regime drawdown or cost sensitivity. Do not add the direct mean-reversion overlay, per-regime thresholds, or rapidly refitted HMM.

## Exact TradingView Candidate Test

The separate Pine candidate `JD ES 15m C11-X Causal Chop Veto C1 20260714` compiled with zero errors and zero warnings. It was tested on the same ES1! chart, date range, capital, contract size, commission, and slippage as C11.

| Metric | C11 | C11-X | Change |
|---|---:|---:|---:|
| Net profit | `$126,905` | `$111,412.50` | `-$15,492.50` |
| Profit factor | `1.745` | `1.665` | `-0.080` |
| Maximum drawdown | `9.25%` | `11.30%` | `+2.05 points` |
| Trades | `469` | `445` | `-24` |
| Win rate | `47.55%` | `47.19%` | `-0.36 points` |

The candidate fails every promotion objective: lower profit, lower PF, higher drawdown, and fewer trades. The improvement on the long Databento feed did not transfer to exact TradingView ES1! behavior.

**Final decision: reject C11-X. Keep C11 unchanged.** The candidate remains as a local research artifact only and is explicitly marked rejected. The TradingView `JD ES BEST` saved script and active chart were restored from the frozen C11 source after testing.
