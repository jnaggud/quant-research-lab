import pytest

from polymarket.btc_15m_research import crypto_taker_fee


def test_crypto_taker_fee_peaks_at_half_probability():
    assert crypto_taker_fee(100, .5) == pytest.approx(1.75)
    assert crypto_taker_fee(100, .3) == pytest.approx(crypto_taker_fee(100, .7))
