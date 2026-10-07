# Regime-Aware Adaptation Research + C12 Verdict (2026-07-07)

Question (user): before porting to Pine, is there merit in regime-aware REAL-TIME
retraining / parameter adaptation? Four experiments + the C12 promotion attempt.
All on the rolling-origin C11+ML harness (quarterly tests, 18mo train) unless noted.

**Headline: real-time adaptation is refuted four ways. Regime information is valuable
but already captured implicitly by the ML meta-label. The optimal configuration is
LESS adaptive than the current one: refresh the meta-label every ~6 months, keep
everything else fixed. The GEX short-gate improves the local C11+ML system robustly,
but does NOT transfer to the Pine C11 champion — C12 Pine promotion: REJECTED.**

## A. Retrain-frequency sweep (`quant/es_c11_retrain_freq.py`)

42 monthly test windows, RF meta-label refit every k months, 18mo trailing train:

| refit | ml total | ml Sharpe | +veto total | +veto Sharpe |
|---|---|---|---|---|
| 1mo | +93.4% | 0.74 | +109.2% | 0.83 |
| 3mo (current) | +110.0% | 0.78 | +127.3% | 0.86 |
| **6mo** | **+130.0%** | **0.89** | **+149.0%** | **0.99** |
| never | +48.8% | 0.50 | +60.6% | 0.57 |

Inverted-U with the peak at 6 months: periodic retraining earns its keep (never is
worst), but FASTER retraining monotonically hurts — monthly refits chase noise.
The veto helps at every frequency (a free robustness replication).

## B. Regime source: HMM vs EMA (`quant/es_c11_regime_source.py`)

| arm | total | pos quarters | Sharpe | maxDD |
|---|---|---|---|---|
| ema (control) | +178.0% | 71% | 0.92 | −32.4% |
| hmm_static (fit once, causal decode) | +133.7% | **93%** | **1.13** | −27.4% |
| hmm_feat (HMM as ML features) | +137.6% | 71% | 0.85 | −31.8% |
| hmm_refit (refit quarterly) | **−18.4%** | 50% | −0.07 | **−58.3%** |

Refitting the regime detector — the literal "regime-aware retraining in real time" —
is catastrophic (state definitions shift every refit). A static, fit-once HMM is a
legitimate alternative profile: less total, far steadier (93% positive quarters,
best Sharpe). NOTE: HMM regime is a 15m-level series — NOT portable to Pine via the
daily-series mechanism; it is a local-engine fork only.

## C. Per-regime parameter banks (`quant/es_c11_regime_params.py`)

ML probability threshold tuned train-only by inner 4-fold CV:

| arm | total | pos% | Sharpe |
|---|---|---|---|
| fixed global 0.5 (control) | +178.0% | 71% | 0.92 |
| one tuned threshold | −5.3% | 29% | −0.11 |
| per-regime thresholds | −10.4% | 21% | −0.13 |

Even ONE inner-CV-tuned threshold collapses the system (CV keeps choosing 0.60,
which looks better in-sample and starves it OOS). Per-regime banks are worse still.
Echoes the Pattern_FindR v10–v15 failure exactly.

## D. Regime-feature ablation

RF without (regime, h4_sig, daily_sig): +144.2% vs +178.0% control. Regime
information IS worth ~34 points — and the meta-label already extracts it
implicitly. Explicit adaptation on top is double-dipping that only adds overfit
surface.

## Veto robustness (`quant/es_c11_veto_robust.py`)

- Seed-MC: veto > plain ML for ALL 5 RF seeds (median +177.9% vs +142.7% control);
  100% of seeds positive.
- Threshold grid: the `gex_z < 0` short-gate row dominates at every pain setting;
  0 is the economic sign boundary (positive vs negative dealer gamma). Neighbors
  ±0.5z are worse — acceptable for a sign rule, but worth a finer scan later.
- **The pain veto costs return at every level and adds NO drawdown benefit**
  (gex-only: +233.3%, Sharpe 1.12, maxDD −18.9% vs gex+pain +205.0%, 1.11, −18.9%).
  → **Final overlay spec: single rule — core shorts only when prior-session
  gex_z < 0.** (Supersedes the two-rule veto in es_options_v2_research.)

## C12 promotion attempt (`scripts/c12_gex_veto_parity.py`) — REJECTED

C11 champion (worker 143) vs champion+gex-gate through the TV-parity engine:

| dataset | C11 net / PF / maxDD | C12 net / PF / maxDD |
|---|---|---|
| TV fixture 2025-07→2026-06 | $129,108 / 1.827 / −$7,383 | $111,573 / 1.695 / −$10,155 |
| local bars 2021-06→2026-06 | $116,338 / 1.701 / −$9,263 | $102,788 / 1.608 / −$10,155 |

Fails net, PF, and maxDD gates on both windows. Root cause: the gate was validated
on the PYTHON C11+ML system, whose stringent short logic fires almost only in
negative-gamma tape (gate removed 4.6% of its shorts); the Pine champion's tuned
short filters already avoid toxic shorts, and the gate blocks 37% of its short
bars — mostly profitable ones. **The GEX gate is an ML-stack improvement, not a
champion improvement. Do not port. C11 remains the Pine champion.**

## Where this leaves the system

1. **Local research stack (best known config): C11 sleeves + RF meta-label
   (13 original features, fixed 0.5 threshold, 6-monthly refresh) + GEX short-gate.**
   Rolling-origin: ~+233% total, Sharpe 1.12, maxDD −18.9% vs control +178%/0.92/−32.4%.
2. **Pine/TV: C11 champion unchanged.**
3. No real-time adaptation of any component. Slower is better; static regime
   detectors only.
4. hmm_static fork available if steadier equity is ever preferred over total.

## Addendum: weekly-complete GEX check (same day, post-download)

The scoped statistics download for the ~25 weekly ES option roots landed
(`data/databento/statistics-weekly/`, 35 GB, 6 jobs) and
the frame was re-staged with the full option complex feeding GEX
(`quant/cache/es_options_weekly_daily_v2.parquet`; per-day net GEX moves from
~−$0.2B to ~−$10B as near-dated weekly gamma dominates; flip coverage 93%→97%).

One-shot pre-registered comparison of the gate input (rolling-origin, seed 0):

| GEX input | gex_only total | Sharpe | maxDD |
|---|---|---|---|
| quarterly OI (validated spec) | **+233.3%** | **1.12** | **−18.9%** |
| weekly-complete OI (v2) | +199.6% | 1.00 | −27.1% |

The weekly-complete input DEGRADES the gate (though both beat no-gate +178%).
Interpretation: quarterly OI is the slow institutional-positioning signal; the
weekly complex injects expiry-cycle gamma that dominates the z-score with calendar
noise. **Gate input stays quarterly-OI. The v2 frame is kept for future research
(walls/IV unchanged; only the GEX columns differ).**
