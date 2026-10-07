"""Paper-trading signal for recurring BTC 15-minute Up/Down markets."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LateFavoriteConfig:
    decision_second: int = 600
    timing_tolerance_seconds: int = 15
    max_quote_age_seconds: int = 15
    min_favorite_price: float = .55
    max_limit_price: float = .98
    max_order_cost_usd: float = 10.0


@dataclass(frozen=True)
class Signal:
    side: Literal["Up", "Down"]
    limit_price: float
    shares: float
    reason: str


def decide(
    *,
    elapsed_seconds: int,
    up_ask: float,
    down_ask: float,
    quote_age_seconds: int,
    config: LateFavoriteConfig = LateFavoriteConfig(),
) -> Signal | None:
    if abs(elapsed_seconds - config.decision_second) > config.timing_tolerance_seconds:
        return None
    if quote_age_seconds > config.max_quote_age_seconds:
        return None
    side, ask = ("Up", up_ask) if up_ask >= down_ask else ("Down", down_ask)
    if ask < config.min_favorite_price or ask > config.max_limit_price:
        return None
    shares = config.max_order_cost_usd / ask
    return Signal(side=side, limit_price=ask, shares=shares,
                  reason="10-minute BTC late favorite with fresh executable ask")
