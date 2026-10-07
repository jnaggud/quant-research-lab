# Contributing

Use Python 3.10 or 3.12, create a virtual environment, and install `.[research,dev]`.
Run `python -m pytest -q` before submitting a change. Keep new tests deterministic and independent of paid services where possible; mark original-data checks with `local_data`.

For strategy or backtest changes, state the signal timing, fill assumptions, costs, input period, and selection/holdout boundaries. Include a regression case for corrected behavior. Do not silently overwrite frozen strategy checkpoints or reinterpret historical results.

Keep credentials, raw licensed market data, caches, and generated runtime files out of commits. Demo data must remain clearly labeled as synthetic. Preserve source provenance and dependency notices.
