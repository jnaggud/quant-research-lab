# ES Options-Levels Signal — Validation Verdict (2026-07-07)

**Verdict: REJECTED — do not promote.** The walls + max-pain signal fails the temporal-stability gate and underperforms buy-and-hold on every variant. This closes the research thread opened 2026-07-01 (`quant/options_bands.py`, `quant/es_options_levels_signal.py`).

## Setup

- Data: `quant/cache/es_options_daily.parquet` (1,696 days, 2021-01 → 2026-06-28; staged 2026-07-02 from definition + ohlcv-1d + statistics, so open interest is real) merged onto the ES 15m continuous grid → 119,586 bars.
- Engine: `quant/backtest.py`, ES contract model, `next_bar_open` entries, 1-tick slippage + commission, 40pt SL/TP, `min_bars_between=2`.
- Splits: chronological 60/40 holdout, plus rolling-origin walk-forward in 2,000-bar (~quarterly) blocks — 56 blocks.
- Note on seed-MC: not applicable — the signal has fixed parameters (no optimizer), so optimizer-seed stability is moot; rolling-origin is the operative robustness test, and it fails (below).

## Results

Holdout buy-and-hold: **+125.2%**.

| Variant | Holdout | Trades | Win | PF |
|---|---|---|---|---|
| walls + pain (no gate) | +87.2% | 929 | 52% | 1.10 |
| walls + pain, stretch gate 1.0 | +53.0% | 541 | 52% | 1.10 |
| walls + pain, stretch gate 1.5 | +27.8% | 463 | 51% | 1.06 |
| put-wall LONG only | −9.4% | 98 | 47% | 0.91 |
| pain-pin long only (< −0.4%) | +76.2% | 800 | 52% | 1.10 |
| pain-pin long only (< −1.0%) | +98.7% | 740 | 53% | 1.14 |

Rolling-origin walk-forward:

- walls+pain gate 1.0: **52% of blocks positive**, total **−12.0%** vs market +274.8%.
- pain-pin long only: **52% of blocks positive**, total +83.3% vs market +274.8%.

## Gate check (per BUILD_PLAN §Three-gate acceptance)

1. Positive OOS return — nominally passes, but every variant loses to buy-and-hold (required by the promotion rules). **Fail.**
2. ≥75% stability — 52% of walk-forward blocks positive. **Fail (decisive).**
3. ≥20 holdout trades — 740–929 trades. Pass.

## What we learned (keep)

1. **The wall legs are dead weight.** "walls + pain (no gate)" is numerically identical to "pain-pin long+short" (+87.2%, 929 trades, PF 1.10) — the wall terms almost never fire. Reason: the chain uses the nearest expiry of the front-month quarterly (`asset == "ES"`, median DTE 44), so the volume-weighted call wall sits a median 2.2–4.8% above spot and the put wall ~5% below. In the 2024–2026 uptrend holdout, price came within 0.3% of the call wall on **1 bar** out of ~47k. Near-wall touches are vol-spike events, not daily S/R.
2. **Max-pain pinning is real but tiny.** corr(fwd 16-bar return, signed distance above pain) = −0.022 train / −0.042 holdout — the only effect stable across both splits. Below-pain bars average +2.7 bps fwd vs −1.8 at pain (holdout). Sign-stable, but at 44-DTE granularity it is not tradeable after costs as a standalone signal (PF ≤ 1.14, loses to B&H).
3. The stretch (z-score) gate only removes trades without improving PF — the stretch × wall interaction from `options_bands.py` test 3 did not replicate as conviction.

## Possible follow-ups (not commitments)

- **Weekly options walls**: ES weeklies (E1A–E5A/EW roots) would put walls at tradeable distances and are in the downloaded definitions — the current `asset == "ES"` filter excludes them. This is the most direct fix to the structural problem above.
- **OI-weighted GEX / gamma flip level** from the now-complete statistics schema, as a *regime filter* on the promoted C11 champion rather than a standalone signal.
- Max-pain distance as a weak *bias feature* inside a larger model, not a trade trigger.
