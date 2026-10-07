from polymarket.btc_15m_strategy import decide


def test_selects_favorite_at_ten_minutes():
    signal = decide(elapsed_seconds=600, up_ask=.71, down_ask=.31, quote_age_seconds=2)
    assert signal is not None
    assert signal.side == "Up"
    assert signal.limit_price == .71


def test_rejects_stale_or_mistimed_quote():
    assert decide(elapsed_seconds=500, up_ask=.7, down_ask=.32, quote_age_seconds=2) is None
    assert decide(elapsed_seconds=600, up_ask=.7, down_ask=.32, quote_age_seconds=20) is None
