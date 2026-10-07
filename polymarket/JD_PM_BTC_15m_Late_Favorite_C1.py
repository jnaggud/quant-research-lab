"""Named release artifact for JD PM BTC 15m Late Favorite C1.

This release is paper-trading only. The implementation is re-exported from the tested
strategy module so research and forward verification use exactly the same decision code.
"""
from polymarket.btc_15m_strategy import LateFavoriteConfig, Signal, decide

STRATEGY_NAME = "JD PM BTC 15m Late Favorite C1"
STRATEGY_VERSION = "C1"
LIVE_CAPITAL_APPROVED = False

__all__ = ["LateFavoriteConfig", "Signal", "decide", "STRATEGY_NAME",
           "STRATEGY_VERSION", "LIVE_CAPITAL_APPROVED"]
