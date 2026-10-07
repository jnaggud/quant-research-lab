# Architecture and research assumptions

Quant Research Lab brings together several research workflows. It is a source-first toolkit; historical experiments are scripts with explicit data requirements, rather than a single production trading service.

## Components

1. **Inputs.** `dashboard/demo.py` creates synthetic OHLCV bars and an artificial report with a fixed seed. Optional adapters read local Databento DBN files or export the user's TradingView chart through a separate CDP bridge.
2. **Features.** `quant/features.py`, `quant/strategy_c11.py`, and `dashboard/realtime_inference.py` calculate trailing indicators and state scores. Completed-bar handling and causality checks matter more than visual smoothness.
3. **Execution.** `quant/backtest.py` models next-bar entries, gap-through stops, costs, and position exits. `scripts/tv_c5_parity_engine.py` models TradingView-specific execution behavior. These engines have different scopes; parity should be established for a particular strategy and dataset.
4. **Validation.** Walk-forward, holdout, ablation, and execution-cost experiments live in `quant/` and `scripts/`. Reports retain the original experiment dates and assumptions.
5. **Risk.** Portfolio simulation and mark-to-market reconciliation sit alongside probability calibration and tail-loss utilities. A stress model measures conditional outcomes; it does not demonstrate an entry signal's predictive value.
6. **Presentation.** The Flask studio serves JSON and static JavaScript/canvas assets. Demo mode has no external process or data-service dependency. Live mode is explicitly selected and uses local integrations.

## Public demo contract

The generated bars are artificial and continuous, including times when an actual exchange could be closed. The ledger is a deterministic fixture, not an execution of C11. Its run-up and drawdown entries are illustrative. The demo never places orders, and the interface shows observe-only status. Sample files can be generated under ignored `data/demo/`.

The trend, chop, and stress values are independent logistic heuristic scores. They need not sum to one. The triangle normalizes them only for display; neither that visualization nor the confidence label establishes a calibrated posterior. The browser's simulated paths are a scenario visualization, separate from the offline portfolio bootstrap.

## Research boundaries

- Historical Pine strategies are preserved for inspection, including variants that were rejected.
- Original report reproduction needs original licensed inputs. Synthetic fixtures do not recreate the reported investment results.
- Some data adapters make simplifying choices, including daily volume-based contract selection. Full-day roll choices require care before using them in an intraday causal evaluation.
- Chart exports rely on TradingView internals and may need maintenance when the application changes.
- The development dashboard binds to loopback. Authentication, multi-user hosting, and brokerage execution are outside the public demo's scope.
- Some historical diagnostics refer to the separate Pattern_FindR research project. Their provenance remains in source comments; that checkout is optional and not bundled.
