# ES Microstructure Starter Scan (2026-07-07)

First pass at the tick-data assets (trades schema, 12-month entitlement window
2025-06-29 → 2026-06-26). Edge scan only — no backtest, no strategy claims.

## Infra

- `quant/stage_microstructure.py`: per-day front-ES aggressor-flow features on a
  15m grid (buy/sell aggressor volume, imbalance, large-print [≥10 lot] imbalance,
  trade count, avg size). 320 trade days staged in ~13 min (12 workers; ALL_SYMBOLS
  day frames are RAM-heavy). → `quant/cache/es_microstructure_15m.parquet` (23.5k rows).
- Bug found & fixed during validation: DBN `size` is unsigned — `buy − sell` on uint
  wrapped to huge positives (zero negative imbalances, a giveaway). Cast to float;
  parquet rebuilt from stored components.

## Findings (train 60% | holdout 40%)

- All flow features have noise-level 16-bar correlations; the only sign-consistent
  one is **big_imb (large-print imbalance): +0.012 | +0.024**, decile spread
  +2.1 | +4.1 bps — a weak MOMENTUM tilt (big prints lead price slightly).
- Best conditional (holdout): **big prints buying a −1σ dip → +14.4 bps fwd 4h**,
  but n = 76 in 9 months — thin.
- Large sellers into +1σ rips got run over (+6.1 bps forward) — consistent with the
  2025-26 bull tape; not a fade signal.

## Verdict

Nothing tradeable standalone at 15m granularity — bps-sized, cost-dominated, same
class as the options levels. `big_imb` is the one candidate worth carrying forward,
with two caveats: (1) options features as RF inputs *degraded* OOS performance
(es_options_v2_research §3), so "add it to the ML" is not automatic; (2) only 12
months of data exist (entitlement window), so any test has one regime.

Natural next steps for a future cycle: finer horizons (1m bars from ohlcv-1s or the
reconstructed L1 — flow edges usually live below 15m), signed volume-at-price from
mbp-10 (1 month), and queue-imbalance from bbo-1s.
