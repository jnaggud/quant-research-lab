# Data and reproducibility

The public repository includes source, strategy parameters, historical narrative reports, and derived experiment summaries. It excludes raw OHLCV exports, complete TradingView report/order exports, DBN files, Parquet caches, runtime logs, and local credentials. A report mentioning an excluded file is describing the input used in the historical experiment; the file is not implied to be publicly available.

## Included demo

```bash
python -m dashboard.demo --output data/demo
```

This produces artificial bars and a synthetic trade-report fixture with a fixed seed. No third-party market data is embedded. The same generator powers the default dashboard.

## Local data roots

Set `DATABENTO_ROOT` to an existing directory containing schema/job folders, for example `data/databento/ohlcv-1m/<job-id>/*.dbn.zst`. Export `DATABENTO_API_KEY` only if intentionally running a download utility. Provider credentials and data entitlements are supplied by the user; the code license grants no data redistribution rights.

Live-mode snapshot fallback accepts `QUANT_TV_BARS_FILE` and `QUANT_TV_REPORT_FILE`. See `.env.example` for configuration names. Keep private inputs under ignored `data/`.

## Historical integration tests

Two tests depend on original exports under `archives/c11_frozen_20260714/`:

| Test | Local input |
| --- | --- |
| `test_trader_metrics.py` | `tv_c11_current_report_20260714.json` |
| `test_tv_c11_exact_simulation.py` | The same report plus `tv_es1_full_15m_bars_20260714.json` |

These exact July 2026 exports are not redistributable fixtures in this repository. If you already have them, restore them at those paths and run `python -m pytest -q -m local_data`. The checks reconcile the reported 469 trades and $126,905 net result to the historical source. A later export or synthetic substitute is not equivalent. Without the originals, these tests skip explicitly; the remaining suite uses source files or generated data.

## Publication snapshot

This is a fresh public history of a longer local research project. Workstation paths in retained documentation and report metadata have been made relative. The current and frozen C11 Pine files retain their original contents and integrity hashes. Historical parameter searches, datasets, and upstream software are not automatically rerun by installation or CI.
