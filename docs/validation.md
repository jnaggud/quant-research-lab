# Publication validation

The public snapshot was checked on October 7, 2026.

- Fresh Python 3.10 virtual environment: installation of `.[research,dev]` succeeded; dependency consistency check passed.
- Public suite: **26 passed, 2 skipped**. The two skips require original TradingView exports, described in `data.md`.
- Original-data integration checks: **2 passed** when run locally against the original July 2026 exports. Those exports were removed from the public staging directory after verification and are not distributed.
- Independent wheel install: the home page, JavaScript asset, synthetic inference API, and synthetic report API passed outside the source checkout with only base dependencies installed.
- Python source compilation and studio JavaScript syntax checks passed.
- Browser review: the synthetic-data labels, observe-only posture, chart rendering, slider controls, and report rendering were inspected. No browser console warnings or errors were observed.
- The current and frozen C11 Pine files both retain SHA-256 `f78e404927533c2f37e3b391f3d0e82f98eadeafdb8a90edf637ef90de8611d6`.
- The publication guard checks tracked paths, raw export formats, and common credential patterns. It is not a full security audit.

GitHub Actions provides the ongoing Python 3.10/3.12 and packaged-demo checks. Live TradingView connectivity, paid data downloads, long research searches, and optional ManimGL rendering are not covered by offline CI.
