# ES Options v2 — Weekly Complex, GEX Regime, ML Features (2026-07-07)

Follow-up to `es_options_levels_validation_20260707.md` (quarterly-wall signal rejected).
Three threads run on the completed 4.8 TB dataset, all compute on 32 cores.

**Headline: the options overlay that works is the HARD VETO on C11+ML** — shorts only in
negative-gamma tape, no longs stretched above weekly max-pain. On the rolling-origin
harness it lifts total from +178% to +205%, Sharpe 0.92 → 1.11, and cuts max drawdown
from −32.4% to −18.9%. Options as raw trade signals: rejected again. Options as ML
features: rejected (the RF loves them in-sample — 73% importance share — and degrades OOS).

## 0. Data discoveries

- The definitions carry the **full ES weekly complex** (E1A–E5D Mon–Thu, EW1–EW4 Fri,
  EW month-end) with expiries 0–6 DTE. The v1 `asset == "ES"` filter saw only 44–84 DTE
  quarterlies. Selecting options by `underlying_id` ∈ ES futures gets everything.
- **The statistics schema is scoped to the 43 major roots by parent symbology**, and
  `ES.OPT` covers only the quarterly root → **weekly-root open interest is NOT on disk**
  (verified: 0 of 11,772 weekly contracts have OI records; exactly 43 roots present).
  Adaptation: weekly walls/max-pain are VOLUME-weighted (ohlcv-1d is ALL_SYMBOLS);
  GEX/gamma-flip use real OI from the quarterly chain (dte ≤ 120). A tiny scoped
  statistics batch job for the ~25 weekly roots would upgrade GEX later.
- Around quarterly rolls the near-dated weeklies sit on the OLD front future while
  listings pile onto the next — the chain pools all ES underlyings and picks the front
  future by daily volume (`quant/options_weekly.py`).

## 1. Staged frame — `quant/cache/es_options_weekly_daily.parquet`

`quant/stage_options_weekly.py`, mp.Pool over all cores, 1,709 days (2021-01→2026-06)
staged in ~4 min. Coverage 100% (walls/IV), 98% net GEX, 93% gamma flip. Wall distance
median 1.4–2.3% of spot (was 2.2–4.8%); **weekly max-pain 0.20% from spot** (was 1–2.5%).
New columns: `call/put_wall(_wk)` (volume), `max_pain(_wk)`, `net_gex`, `gamma_flip`,
`atm_iv`, `iv_skew`, `pcr_vol`, `pcr_oi` (quarterly).

Lookahead fix: `quant/options_join.py` stamps day-d features available at d 22:00 UTC and
merge_asofs backward — bars only ever see the PRIOR session's chain (v1 tests leaked
same-day settlement volume).

## 2. Weekly levels signal — standalone: REJECTED again

`quant/es_options_weekly_signal.py`. Raw 16-bar edges are now **sign-stable across
train | holdout** (they were not with quarterly walls):

| condition | n (tr\|ho) | fwd bps (tr\|ho) |
|---|---|---|
| near call wall (<0.3%) | 569 \| 149 | −12.6 \| −4.6 |
| near put wall (<0.3%) | 5,964 \| 3,185 | +2.4 \| +1.6 |
| >0.4% above weekly pain | 1,079 \| 712 | −7.7 \| −4.7 |

But bps-sized edges don't clear the cost hurdle as trade triggers: best holdout variant
+68.3% vs buy-and-hold +128%; rolling-origin 55% of 56 blocks positive (gate: 75%),
+131% vs market +268%. Wall-only variants are negative outright. Same verdict as v1 —
levels are **conditioning information, not signals**.

## 3. Options on C11+ML — the decisive test

Context: the raw C11 python port (round defaults, no ML) is **negative** over 2021–2026
(−33% across 56 quarterly windows) — the system's edge lives in the ML meta-label, so
overlays must be tested on C11+ML. Preliminary raw-signal filters agreed directionally:
gex-shorts recovered ~14pts removing only 98 bars; pain-veto cut maxDD 69%→42%
(`quant/es_c11_gex_filter.py`).

Main experiment `quant/es_c11_options_ml.py`: rolling-origin (train 1.5y → test next
quarter, 14 quarters 2022-12→2026-03), RF meta-label n_jobs=-1, options joined
next-session, embargo = label window. Three arms:

| series | total% | mean%/q | pos% | Sharpe | maxDD% | down-mkt q+ |
|---|---|---|---|---|---|---|
| ml (control) | +178.0 | +9.29 | 71% | 0.92 | −32.4 | 2/3 |
| ml+opt (RF features) | +137.4 | +7.90 | 57% | 0.83 | −31.9 | 1/3 |
| **ml+veto (hard gates)** | **+205.0** | **+9.49** | 71% | **1.11** | **−18.9** | 2/3 |

- **ml+opt REJECTED**: the RF assigns the 9 options features 73.4% of importance
  (atm_iv, gex_z, iv_skew top the list) yet performs worse on every metric — classic
  in-sample seduction; also collapses trade counts in some quarters.
- **ml+veto ACCEPTED on this harness**: two pre-registered rules taken from the
  sign-stable §2 edges (not tuned on the quarters): (1) core shorts only when
  `gex_z < 0`; (2) cancel longs when >0.4% above weekly max-pain. Biggest effect is
  taming the worst quarter (2024-06: −26.1% → −11.4%). Passes the es_c11_robust gate
  (median>0, ≥60% windows positive, holds in down-market quarters).

Caveat to carry into promotion: the veto's gains concentrate in a few quarters (that is
what a tail-risk veto should look like, but it means fewer effective observations), and
the GEX input is quarterly-OI only until the weekly-OI statistics job is run.

## 4. Recommended next steps

1. **Promote the veto overlay toward a C12 candidate**: port the two veto rules to the
   Pine/TV parity pipeline (they need only daily levels — computable from the staged
   frame and exportable as a daily series for Pine) and run the standard promotion gates
   vs C11 (`docs/strategy_next_steps.md` discipline).
2. Submit the scoped **statistics job for the ~25 weekly ES option roots** (tiny; would
   make GEX/gamma-flip weekly-complete and likely sharpen the gex_z veto).
3. Optional: retest the veto with OI-weighted weekly walls once (2) lands.

## Compute notes

Staging mp.Pool(32) ≈ 4 min for 1,709 days; window backtests parallelized across
(variant × quarter) with mp.Pool; RF fits n_jobs=-1. Modules added: `quant/options_weekly.py`,
`quant/stage_options_weekly.py`, `quant/options_join.py`, `quant/es_options_weekly_signal.py`,
`quant/es_c11_gex_filter.py`, `quant/es_c11_options_ml.py`.
