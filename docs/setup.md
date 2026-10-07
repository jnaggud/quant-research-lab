# Setup and optional integrations

## Supported entry points

The README quickstart runs the self-contained Flask studio with synthetic inputs. Python 3.10 and 3.12 are the CI targets. Activate the virtual environment before running commands.

For the broader research code:

```bash
python -m pip install -e '.[research,dev]'
python -m pytest -q
```

`requirements-tested.txt` records the direct package versions tested for publication. Optional animations use `.[animation]` and ManimGL's platform dependencies; they are not required for tests or the dashboard.

## TradingView Desktop

The live adapters import a separate [tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) checkout at `tradingview-mcp/`. That project has its own MIT license and setup instructions; its implementation is not copied into this repository.

Install Node.js and set up that bridge according to its upstream documentation. Open your own TradingView chart with the bridge's CDP connection available, then:

```bash
export TRADINGVIEW_CDP_PORT=9223
export TRADINGVIEW_STRATEGY_NAME='JD ES 15m C11'
python -m dashboard.visual_server --live
```

The demo requires neither this bridge nor a TradingView account. Live export relies on application-internal interfaces and is not covered by offline CI. Configure `QUANT_TV_BARS_FILE` and `QUANT_TV_REPORT_FILE` for optional local snapshot fallback. Failed live access does not silently become a synthetic result.

## Historical research commands

Run research modules from the repository root, for example `python -m quant.es_portfolio_simulation`, only after preparing their required inputs. Read the module and corresponding dated report first: some jobs perform large searches or million-path simulations. Older scripts use relative filenames under `reports/`, `tmp/`, or `quant/cache/`. Raw historical inputs are intentionally absent.

The `scripts/diagnose_cl_truth_misses.py` diagnostic also needs a separate Pattern_FindR checkout, configurable with `PATTERN_FINDR_ROOT`. That optional historical comparison is outside the standalone demo.

The prediction-market dashboard runs with `python -m dashboard.polymarket_dashboard` and expects local paper-strategy outputs. It is a separate integration workflow, not a second prepopulated demo.

## Download utilities

Set `DATABENTO_ROOT` and `DATABENTO_API_KEY` explicitly. Download scripts reflect historical dataset plans and entitlement assumptions. Inspect their preflight output and your current account entitlements before intentionally submitting requests. No download utility is invoked by installation, tests, or the demo.

## Optional macOS monitoring

`python scripts/configure_launchd.py` generates local templates under ignored `launchd/generated/`. It installs nothing by default. Review the historical C8/C9 monitor's strategy title and export settings before using it.

On macOS, `python scripts/configure_launchd.py --install` installs weekday schedules at 4:30 PM and 7:30 AM in the machine's local timezone. It requires the configured TradingView bridge and an active desktop session. Those historical schedules are separate from the C11 research studio.
